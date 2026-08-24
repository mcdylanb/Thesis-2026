#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_idf_version.h>

// ==================== CONFIG ====================
#define ESPNOW_WIFI_CHANNEL 11  // Must match the Sniffer's channel
#define SERIAL_BAUD      921600 // High baud rate to prevent serial bottleneck
#define CSI_BUF_MAX      128
// ================================================

// Must match the Sniffer's struct exactly
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

// Process and output the binary CSI payload
void process_csi_payload(const uint8_t *data, int len) {
  if (len != sizeof(esp_now_csi_t)) return;

  esp_now_csi_t *csi = (esp_now_csi_t *)data;

  // Print metadata row: CSI, Anchor, Seq, Target_MAC, RSSI, Channel, Length
  Serial.printf("CSI,%s,%lu,%02X:%02X:%02X:%02X:%02X:%02X,%d,%d,%d,",
                csi->anchor_id,
                csi->seq,
                csi->mac[0], csi->mac[1], csi->mac[2],
                csi->mac[3], csi->mac[4], csi->mac[5],
                csi->rssi,
                csi->channel,
                csi->len);

  // Print raw CSI matrix values as comma-separated integers
  for (int i = 0; i < csi->len; i++) {
    Serial.printf("%d", csi->buf[i]);

    if (i < csi->len - 1) {
      Serial.print(",");
    }
  }
  Serial.println();
}

// Version-agnostic ESP-NOW receive callback
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 0, 0)
void on_data_receive(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  process_csi_payload(data, len);
}
#else
void on_data_receive(const uint8_t *mac_addr, const uint8_t *data, int len) {
  process_csi_payload(data, len);
}
#endif

void setup() {
  Serial.begin(SERIAL_BAUD);

  WiFi.mode(WIFI_STA);
  WiFi.setChannel(ESPNOW_WIFI_CHANNEL);
  WiFi.disconnect();

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW Init Failed. Rebooting...");
    delay(3000);
    ESP.restart();
  }

  // Register native ESP-NOW callback
  esp_now_register_recv_cb(on_data_receive);

  Serial.println("==========================================================");
  Serial.println("Gateway Ready.");
  Serial.println("Listening for CSI data on Channel " + String(ESPNOW_WIFI_CHANNEL));
  Serial.println("CSV Format: CSI, Anchor, Seq, Target_MAC, RSSI, Channel, Array_Length, [Raw CSI Data...]");
  Serial.println("==========================================================");
}

void loop() {
  vTaskDelay(pdMS_TO_TICKS(1000));
}