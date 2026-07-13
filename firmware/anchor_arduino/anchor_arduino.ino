/*
 * ESP32 anchor firmware — passive RSSI+CSI sniffer (Arduino IDE version).
 *
 * Direct port of firmware/anchor (ESP-IDF v5.4). Same architecture, same
 * output line format — firmware/tools/gateway_logger.py works with either.
 *
 * Board:  "ESP32 Dev Module" (classic ESP32 NodeMCU)
 * Core:   arduino-esp32 3.x (2.x also works — same legacy CSI struct)
 * Serial: 921600 baud (set the Serial Monitor to match)
 *
 * The CSI callback is the single source of the output tuple: wifi_csi_info_t
 * carries the source MAC, RSSI, local timestamp and CSI buffer of the SAME
 * packet, so RSSI and CSI never need joining across callbacks. The
 * promiscuous callback only counts frames (pkts_seen vs csi_cb_count in
 * STAT lines shows frames with no OFDM training field, e.g. 802.11b).
 *
 * Line formats:
 *   CSI,<anchor>,<seq>,<mac>,<rssi>,<sig_mode>,<channel>,<timestamp_us>,<n_sub>,<v1>,...,<vN>
 *   STAT,<anchor>,<uptime_ms>,<pkts_seen>,<csi_cb_count>,<queued>,<dropped>,<free_heap>
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <math.h>
#include <string.h>

#include "esp_wifi.h"
#include "esp_timer.h"

// ==================== CONFIG (edit per deployment) ====================

#define ANCHOR_ID        "A1"   // A1..A4 — the ONLY per-board difference
#define WIFI_CHANNEL     6      // sniff channel, 1..13 (serial mode only)
#define SERIAL_BAUD      921600 // fallback 460800 if a CH340 clone misbehaves

// Frame classes passed up by the radio.
#define FILTER_MASK      (WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA)

#define OUTPUT_RAW_IQ    0      // 0 = 64 amplitudes (default), 1 = 128 raw int8 I/Q (debug)
#define QUEUE_DEPTH      64     // records buffered between CSI callback and writer task
#define STATS_INTERVAL_S 5      // STAT line period

// Optional UDP mirroring. CONSTRAINT: joining an AP locks the radio to the
// AP's channel — the target must transmit on that same channel. Recipe: pin
// the laptop/phone hotspot to a known channel, put the target on it too.
#define UDP_ENABLE       0
#define UDP_SSID         "thesis-hotspot"
#define UDP_PASSWORD     ""
#define UDP_GATEWAY_IP   "192.168.1.100"
#define UDP_GATEWAY_PORT 5555

// ======================================================================

// Max CSI payload with LLTF-only @ HT20: 128 bytes = 64 int8 [imag, real]
// pairs, constant across 11g/11n frames.
#define CSI_BUF_MAX 128

// Worst case line: raw I/Q = header (~64) + 128 * "-128," (~640).
#define LINE_MAX 800

typedef struct {
  uint32_t seq;
  uint8_t  mac[6];
  int8_t   rssi;
  uint8_t  channel;
  uint8_t  sig_mode;      // 0 = non-HT (11g), 1 = HT (11n)
  uint8_t  len;
  uint32_t timestamp_us;  // local MAC clock, wraps ~71.6 min; sync is gateway-side
  int8_t   buf[CSI_BUF_MAX];
} csi_record_t;

static QueueHandle_t s_queue;

// Single writer per counter; aligned 32-bit is atomic enough for statistics.
static volatile uint32_t s_pkts_seen = 0;
static volatile uint32_t s_csi_count = 0;
static volatile uint32_t s_queued    = 0;
static volatile uint32_t s_dropped   = 0;

#if UDP_ENABLE
static WiFiUDP s_udp;
static IPAddress s_gateway_ip;
#endif

// ---------------- callbacks (WiFi task context: no blocking, ------------
// ---------------- no float math, no printing — copy and return) ---------

static void promisc_rx_cb(void *buf, wifi_promiscuous_pkt_type_t type) {
  (void)buf;
  (void)type;
  s_pkts_seen++;
}

static void csi_rx_cb(void *ctx, wifi_csi_info_t *info) {
  (void)ctx;
  if (!info || !info->buf || info->len == 0) {
    return;
  }
  s_csi_count++;

  csi_record_t rec;
  rec.seq          = s_csi_count;
  memcpy(rec.mac, info->mac, 6);
  rec.rssi         = info->rx_ctrl.rssi;
  rec.channel      = info->rx_ctrl.channel;
  rec.sig_mode     = info->rx_ctrl.sig_mode;
  rec.timestamp_us = info->rx_ctrl.timestamp;
  rec.len          = (info->len > CSI_BUF_MAX) ? CSI_BUF_MAX : info->len;
  memcpy(rec.buf, info->buf, rec.len);

  if (xQueueSend(s_queue, &rec, 0) == pdTRUE) {
    s_queued++;
  } else {
    s_dropped++;
  }
}

// ---------------------------- writer task -------------------------------

static int format_record(const csi_record_t *rec, char *line, size_t cap) {
  int n = snprintf(line, cap,
                   "CSI,%s,%u,%02x:%02x:%02x:%02x:%02x:%02x,%d,%u,%u,%u,",
                   ANCHOR_ID, (unsigned)rec->seq,
                   rec->mac[0], rec->mac[1], rec->mac[2],
                   rec->mac[3], rec->mac[4], rec->mac[5],
                   (int)rec->rssi, (unsigned)rec->sig_mode,
                   (unsigned)rec->channel, (unsigned)rec->timestamp_us);

#if OUTPUT_RAW_IQ
  n += snprintf(line + n, cap - n, "%u", (unsigned)rec->len);
  for (int i = 0; i < rec->len; i++) {
    n += snprintf(line + n, cap - n, ",%d", (int)rec->buf[i]);
  }
#else
  int pairs = rec->len / 2;  // buf holds [imag, real] int8 pairs
  n += snprintf(line + n, cap - n, "%u", (unsigned)pairs);
  for (int i = 0; i < pairs; i++) {
    float im  = (float)rec->buf[2 * i];
    float re  = (float)rec->buf[2 * i + 1];
    int   amp = (int)lroundf(sqrtf(im * im + re * re));
    n += snprintf(line + n, cap - n, ",%d", amp);
  }
#endif
  n += snprintf(line + n, cap - n, "\n");
  return n;
}

static int format_stats(char *line, size_t cap) {
  return snprintf(line, cap,
                  "STAT,%s,%llu,%u,%u,%u,%u,%u\n",
                  ANCHOR_ID,
                  (unsigned long long)(esp_timer_get_time() / 1000),
                  (unsigned)s_pkts_seen, (unsigned)s_csi_count,
                  (unsigned)s_queued, (unsigned)s_dropped,
                  (unsigned)ESP.getFreeHeap());
}

static void emit(const char *line, int len) {
  Serial.write((const uint8_t *)line, len);
#if UDP_ENABLE
  s_udp.beginPacket(s_gateway_ip, UDP_GATEWAY_PORT);
  s_udp.write((const uint8_t *)line, len);
  s_udp.endPacket();
#endif
}

static void writer_task(void *arg) {
  (void)arg;
  static char line[LINE_MAX];
  csi_record_t rec;
  int64_t last_stat = 0;

  for (;;) {
    if (xQueueReceive(s_queue, &rec, pdMS_TO_TICKS(200)) == pdTRUE) {
      emit(line, format_record(&rec, line, sizeof(line)));
    }
    int64_t now = esp_timer_get_time();
    if (now - last_stat >= (int64_t)STATS_INTERVAL_S * 1000000) {
      last_stat = now;
      emit(line, format_stats(line, sizeof(line)));
    }
  }
}

// ------------------------------- setup ----------------------------------

void setup() {
  // Large TX buffer so Serial.write never blocks the writer task under
  // packet bursts. Must be set before Serial.begin().
  Serial.setTxBufferSize(8192);
  Serial.begin(SERIAL_BAUD);

  s_queue = xQueueCreate(QUEUE_DEPTH, sizeof(csi_record_t));

#if UDP_ENABLE
  // STA join: the AP now dictates the sniff channel.
  WiFi.mode(WIFI_STA);
  WiFi.begin(UDP_SSID, UDP_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(200);
  }
  s_gateway_ip.fromString(UDP_GATEWAY_IP);
  s_udp.begin(0);
#else
  // Bring the WiFi driver up without associating to anything.
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
#endif

  // Modem power save silently throttles receive throughput.
  esp_wifi_set_ps(WIFI_PS_NONE);

  wifi_promiscuous_filter_t filter;
  memset(&filter, 0, sizeof(filter));
  filter.filter_mask = FILTER_MASK;
  esp_wifi_set_promiscuous_filter(&filter);
  esp_wifi_set_promiscuous_rx_cb(promisc_rx_cb);
  esp_wifi_set_promiscuous(true);

#if !UDP_ENABLE
  // Must come after promiscuous enable or it may be reset. Never call in
  // UDP mode: association locks the radio to the AP's channel.
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
#endif

  // LLTF-only keeps the buffer a constant 128 bytes; the legacy training
  // field is present in every OFDM frame. (Legacy wifi_csi_config_t —
  // classic ESP32 keeps this struct in IDF 5.x / core 3.x.)
  wifi_csi_config_t csi_cfg;
  memset(&csi_cfg, 0, sizeof(csi_cfg));
  csi_cfg.lltf_en           = true;
  csi_cfg.htltf_en          = false;
  csi_cfg.stbc_htltf2_en    = false;
  csi_cfg.ltf_merge_en      = true;
  csi_cfg.channel_filter_en = false;
  csi_cfg.manu_scale        = false;
  csi_cfg.shift             = 0;
  csi_cfg.dump_ack_en       = false;
  esp_wifi_set_csi_config(&csi_cfg);
  esp_wifi_set_csi_rx_cb(csi_rx_cb, NULL);
  esp_wifi_set_csi(true);

  xTaskCreate(writer_task, "csv_writer", 4096, NULL, 5, NULL);

#if UDP_ENABLE
  int channel = -1;  // dictated by the AP
#else
  int channel = WIFI_CHANNEL;
#endif
  Serial.printf("INFO,%s,channel=%d,udp=%d,raw_iq=%d\n",
                ANCHOR_ID, channel, UDP_ENABLE, OUTPUT_RAW_IQ);
}

void loop() {
  // All work happens in the callbacks and the writer task.
  vTaskDelay(pdMS_TO_TICKS(1000));
}
