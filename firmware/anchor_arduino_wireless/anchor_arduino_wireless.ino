#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_timer.h>

// ==================== CONFIG (edit per Anchor) ====================
#define ANCHOR_ID        "A1"   // replace with this Anchor's id (A1..A4)
#define WIFI_CHANNEL     11     // sniff channel
#define SERIAL_BAUD      115200 // CH340 clones garble 921600

// Relay = 20:e7:c8:ad:96:68 (from its upload log, "MAC: ...")
uint8_t relay_mac[] = {0x20, 0xe7, 0xc8, 0xad, 0x96, 0x68}; // replace with the Relay's ESP-NOW MAC address

// Source MACs dropped in csi_rx_cb before they reach ESP-NOW (see
// firmware/README.md "Anchor CONFIG block"). relay_mac is always dropped;
// list other never-a-target radios here, e.g. the trial network AP.
const uint8_t ignore_macs[][6] = {
  {0x8c, 0x90, 0x2d, 0x19, 0x40, 0xf1}, // MP700 trial network AP (beacons)
};
#define IGNORE_MACS_N (sizeof(ignore_macs) / sizeof(ignore_macs[0]))

#define FILTER_MASK      (WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA)
#define QUEUE_DEPTH      64
#define CSI_BUF_MAX      128
#define STATUS_INTERVAL_MS 5000 // serial-only STATUS line period
// ======================================================================

// The lightweight binary struct sent over to ESP-NOW (250 byte limit)
typedef struct __attribute__((packed)) {
  char     anchor_id[3]; 
  uint32_t seq;
  uint8_t  mac[6];
  int8_t   rssi;
  uint8_t  channel;
  uint8_t  sig_mode;
  uint8_t  len;
  uint32_t timestamp_us;
  int8_t   buf[CSI_BUF_MAX];
} esp_now_csi_t;

static QueueHandle_t s_queue;
static volatile uint32_t s_csi_count = 0;
// Serial-only diagnostics (STATUS line); never sent to the Relay.
static volatile uint32_t s_queue_drops = 0; // queue full in csi_rx_cb
static volatile uint32_t s_send_ok     = 0; // Relay MAC-acked the frame
static volatile uint32_t s_send_fail   = 0; // no ack, or esp_now_send() error

static inline bool is_ignored_mac(const uint8_t *mac) {
  // relay_mac is kept separate from ignore_macs: it is non-const and doubles
  // as the ESP-NOW peer address, so it must always be dropped regardless of
  // what the ignore list holds.
  if (memcmp(mac, relay_mac, 6) == 0) return true;
  for (size_t i = 0; i < IGNORE_MACS_N; i++) {
    if (memcmp(mac, ignore_macs[i], 6) == 0) return true;
  }
  return false;
}

// ---------------- Callbacks ----------------
static void promisc_rx_cb(void *buf, wifi_promiscuous_pkt_type_t type) {
  // keeping promiscuous active to satisfy radio requirements
}

static void csi_rx_cb(void *ctx, wifi_csi_info_t *info) {
  if (!info || !info->buf || info->len == 0) return;
  if (is_ignored_mac(info->mac)) return;

  s_csi_count++;

  esp_now_csi_t rec;
  strcpy(rec.anchor_id, ANCHOR_ID);
  rec.seq          = s_csi_count;
  memcpy(rec.mac, info->mac, 6);
  rec.rssi         = info->rx_ctrl.rssi;
  rec.channel      = info->rx_ctrl.channel;
  rec.sig_mode     = info->rx_ctrl.sig_mode;
  rec.timestamp_us = info->rx_ctrl.timestamp;
  rec.len          = (info->len > CSI_BUF_MAX) ? CSI_BUF_MAX : info->len;
  memcpy(rec.buf, info->buf, rec.len);

  if (xQueueSendFromISR(s_queue, &rec, NULL) != pdTRUE) s_queue_drops++;
}

// ESP-NOW delivery result. FAIL means the Relay did not ack: wrong relay_mac,
// Relay on another channel, or Relay out of range/off.
#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3, 3, 0)
static void on_send(const wifi_tx_info_t *info, esp_now_send_status_t status) {
#else
static void on_send(const uint8_t *mac, esp_now_send_status_t status) {
#endif
  if (status == ESP_NOW_SEND_SUCCESS) s_send_ok++;
  else s_send_fail++;
}

// ---------- ESP-NOW Writer Task ----------
static void writer_task(void *arg) {
  esp_now_csi_t rec;

  for (;;) {
    if (xQueueReceive(s_queue, &rec, pdMS_TO_TICKS(200)) == pdTRUE) {
      // Blast the binary struct over ESP-NOW
      if (esp_now_send(relay_mac, (uint8_t *) &rec, sizeof(esp_now_csi_t)) != ESP_OK) {
        s_send_fail++;
      }
    }
  }
}

// ---------------- Setup ----------------
void setup() {
  Serial.begin(SERIAL_BAUD);
  s_queue = xQueueCreate(QUEUE_DEPTH, sizeof(esp_now_csi_t));

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  esp_wifi_set_ps(WIFI_PS_NONE);

  wifi_promiscuous_filter_t filter;
  memset(&filter, 0, sizeof(filter));
  filter.filter_mask = FILTER_MASK;
  esp_wifi_set_promiscuous_filter(&filter);
  esp_wifi_set_promiscuous_rx_cb(promisc_rx_cb);
  esp_wifi_set_promiscuous(true);
  // Tune before adding the peer: ESP-NOW requires the peer's channel to be
  // the radio's current channel.
  if (esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE) != ESP_OK) {
    Serial.printf("ERROR,%s,set_channel_failed,channel=%d\n", ANCHOR_ID, WIFI_CHANNEL);
  }

  if (esp_now_init() != ESP_OK) {
    Serial.printf("ERROR,%s,esp_now_init_failed\n", ANCHOR_ID);
    return;
  }
  esp_now_register_send_cb(on_send);

  // Register Relay Peer
  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, relay_mac, 6);
  peerInfo.channel = WIFI_CHANNEL;
  peerInfo.encrypt = false;
  esp_err_t peer_err = esp_now_add_peer(&peerInfo);
  if (peer_err != ESP_OK) {
    Serial.printf("ERROR,%s,add_peer_failed,err=0x%x\n", ANCHOR_ID, (unsigned)peer_err);
  }

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

  xTaskCreate(writer_task, "espnow_writer", 4096, NULL, 5, NULL);

  Serial.printf("INFO,%s,channel=%d,esp_now_mode=ready,anchor_mac=%s,"
                "relay_mac=%02x:%02x:%02x:%02x:%02x:%02x\n",
                ANCHOR_ID, WIFI_CHANNEL, WiFi.macAddress().c_str(),
                relay_mac[0], relay_mac[1], relay_mac[2],
                relay_mac[3], relay_mac[4], relay_mac[5]);
}

// Serial-only health line. csi = frames sniffed (after the ignore list);
// csi=0 means nothing is transmitting on the channel, sent_fail>0 means the
// Relay is not acking (wrong relay_mac or channel).
void loop() {
  vTaskDelay(pdMS_TO_TICKS(STATUS_INTERVAL_MS));
  uint8_t ch = 0;
  wifi_second_chan_t second;
  esp_wifi_get_channel(&ch, &second);
  Serial.printf("STATUS,%s,csi=%lu,sent_ok=%lu,sent_fail=%lu,dropped=%lu,ch=%u\n",
                ANCHOR_ID, (unsigned long)s_csi_count, (unsigned long)s_send_ok,
                (unsigned long)s_send_fail, (unsigned long)s_queue_drops, (unsigned)ch);
}

