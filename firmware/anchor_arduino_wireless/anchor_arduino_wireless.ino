#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_timer.h>

// ==================== CONFIG (edit per sniffer) ====================
#define ANCHOR_ID        "A1"   // replace with sniffer id num
#define WIFI_CHANNEL     11     // sniff channel
#define SERIAL_BAUD      921600 

// Esp-Now = 3c:8a:1f:9a:66:8c
// a1 = 3c:8a:1f:5e:ae:e4
uint8_t gateway_mac[] = {0x3c, 0x8a, 0x1f, 0x9a, 0x66, 0x8c}; // replace with esp-now's mac address

#define FILTER_MASK      (WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA)
#define QUEUE_DEPTH      64
#define CSI_BUF_MAX      128
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

// ---------------- Callbacks ----------------
static void promisc_rx_cb(void *buf, wifi_promiscuous_pkt_type_t type) {
  // keeping promiscuous active to satisfy radio requirements
}

static void csi_rx_cb(void *ctx, wifi_csi_info_t *info) {
  if (!info || !info->buf || info->len == 0) return;
  
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

  xQueueSendFromISR(s_queue, &rec, NULL);
}

// ---------- ESP-NOW Writer Task ----------
static void writer_task(void *arg) {
  esp_now_csi_t rec;

  for (;;) {
    if (xQueueReceive(s_queue, &rec, pdMS_TO_TICKS(200)) == pdTRUE) {
      // Blast the binary struct over ESP-NOW
      esp_now_send(gateway_mac, (uint8_t *) &rec, sizeof(esp_now_csi_t));
    }
  }
}

// ---------------- Setup ----------------
void setup() {
  Serial.begin(SERIAL_BAUD);
  s_queue = xQueueCreate(QUEUE_DEPTH, sizeof(esp_now_csi_t));

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW Init Failed");
    return;
  }

  // Register Gateway Peer
  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, gateway_mac, 6);
  peerInfo.channel = WIFI_CHANNEL;  
  peerInfo.encrypt = false;
  esp_now_add_peer(&peerInfo);

  esp_wifi_set_ps(WIFI_PS_NONE);
  
  wifi_promiscuous_filter_t filter;
  memset(&filter, 0, sizeof(filter));
  filter.filter_mask = FILTER_MASK;
  esp_wifi_set_promiscuous_filter(&filter);
  esp_wifi_set_promiscuous_rx_cb(promisc_rx_cb);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

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

  Serial.printf("INFO,%s,channel=%d,esp_now_mode=ready\n", ANCHOR_ID, WIFI_CHANNEL);
}

void loop() {
  vTaskDelay(pdMS_TO_TICKS(1000));
}

