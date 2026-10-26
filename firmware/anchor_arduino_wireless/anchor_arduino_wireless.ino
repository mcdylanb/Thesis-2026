#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_timer.h>

// ============================================================
// CONFIGURATION
// ============================================================

#define ANCHOR_ID           "A4"

#define WIFI_SSID           "TP-Link_40F1"
#define WIFI_PASSWORD       "90061962"

#define WIFI_CHANNEL        11

// ESP-NOW receiver / Gateway ESP32 MAC
// From your receiver output:
// 3C:8A:1F:9A:66:C8
uint8_t GATEWAY_MAC[] = {
  0x3c, 0x8a, 0x1f, 0x9a, 0x66, 0xc8
};

// CSI buffer size expected by your receiver
#define CSI_BUF_MAX         128

// Number of CSI packets that can wait in the queue
#define CSI_QUEUE_LENGTH    8

// Send a simple HELLO packet every few seconds for testing.
// Set to false after ESP-NOW communication is confirmed.
#define DEBUG_TEST_ESPNOW   true
#define TEST_INTERVAL_MS    3000

// ============================================================
// CSI + ESP-NOW PACKET STRUCTURE
// MUST MATCH RECEIVER EXACTLY
// ============================================================

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

// ============================================================
// GLOBAL VARIABLES
// ============================================================

QueueHandle_t csiQueue;

uint32_t csiSequence = 0;

volatile uint32_t csiReceivedCount = 0;
volatile uint32_t csiDroppedCount = 0;
volatile uint32_t espNowSendCount = 0;
volatile uint32_t espNowFailCount = 0;

unsigned long lastHeartbeat = 0;
unsigned long lastTestPacket = 0;

// ============================================================
// PRINT MAC
// ============================================================

void printMac(const uint8_t *mac) {

  Serial.printf(
    "%02X:%02X:%02X:%02X:%02X:%02X",
    mac[0],
    mac[1],
    mac[2],
    mac[3],
    mac[4],
    mac[5]
  );
}

// ============================================================
// ESP-NOW TEST PACKET
// ============================================================

void sendTestPacket() {

  const char *msg = "HELLO";

  Serial.print("TEST_TX,to=");

  printMac(GATEWAY_MAC);

  Serial.println();

  esp_err_t result = esp_now_send(
    GATEWAY_MAC,
    (const uint8_t *)msg,
    strlen(msg)
  );

  Serial.printf(
    "TEST_TX_RESULT,%s\n",
    esp_err_to_name(result)
  );
}

// ============================================================
// CSI CALLBACK
// ============================================================
//
// This is called whenever the ESP32 receives a CSI frame.
// Keep this callback lightweight.
// ============================================================

void wifi_csi_rx_cb(
  void *ctx,
  wifi_csi_info_t *data
) {

  if (data == nullptr) {
    return;
  }

  if (data->buf == nullptr) {
    return;
  }

  if (data->len == 0) {
    return;
  }

  esp_now_csi_t packet = {};

  // ----------------------------------------------------------
  // Anchor ID
  // ----------------------------------------------------------

  strncpy(
    packet.anchor_id,
    ANCHOR_ID,
    sizeof(packet.anchor_id)
  );

  // ----------------------------------------------------------
  // Sequence number
  // ----------------------------------------------------------

  packet.seq = csiSequence++;

  // ----------------------------------------------------------
  // Source MAC of Wi-Fi frame
  // ----------------------------------------------------------

  memcpy(
    packet.mac,
    data->mac,
    6
  );

  // ----------------------------------------------------------
  // RSSI
  // ----------------------------------------------------------

  packet.rssi =
    data->rx_ctrl.rssi;

  // ----------------------------------------------------------
  // Channel
  // ----------------------------------------------------------

  packet.channel =
    data->rx_ctrl.channel;

  // ----------------------------------------------------------
  // Signal mode
  // ----------------------------------------------------------

  packet.sig_mode =
    data->rx_ctrl.sig_mode;

  // ----------------------------------------------------------
  // Timestamp
  // ----------------------------------------------------------

  packet.timestamp_us =
    data->rx_ctrl.timestamp;

  // ----------------------------------------------------------
  // CSI length
  // ----------------------------------------------------------

  uint16_t copyLen = data->len;

  if (copyLen > CSI_BUF_MAX) {
    copyLen = CSI_BUF_MAX;
  }

  packet.len = (uint8_t)copyLen;

  // ----------------------------------------------------------
  // CSI BUFFER
  // ----------------------------------------------------------

  memcpy(
    packet.buf,
    data->buf,
    copyLen
  );

  // ----------------------------------------------------------
  // Put packet into queue
  // ----------------------------------------------------------

  csiReceivedCount++;

  if (xQueueSend(csiQueue, &packet, 0) != pdTRUE) {
    csiDroppedCount++;
  }
}

// ============================================================
// ESP-NOW SETUP
// ============================================================

bool setupEspNow() {

  Serial.println("INFO,esp_now_initializing");

  if (esp_now_init() != ESP_OK) {

    Serial.println(
      "ERROR,esp_now_init_failed"
    );

    return false;
  }

  Serial.println(
    "INFO,esp_now_initialized"
  );

  // ----------------------------------------------------------
  // Add Gateway as peer
  // ----------------------------------------------------------

  esp_now_peer_info_t peerInfo = {};

  memcpy(
    peerInfo.peer_addr,
    GATEWAY_MAC,
    6
  );

  peerInfo.channel = WIFI_CHANNEL;

  peerInfo.ifidx = WIFI_IF_STA;

  peerInfo.encrypt = false;

  esp_err_t peerResult =
    esp_now_add_peer(&peerInfo);

  if (peerResult != ESP_OK) {

    Serial.printf(
      "ERROR,peer_add_failed,%s\n",
      esp_err_to_name(peerResult)
    );

    return false;
  }

  Serial.print(
    "INFO,peer_added,mac="
  );

  printMac(GATEWAY_MAC);

  Serial.println();

  return true;
}

// ============================================================
// CSI SETUP
// ============================================================

bool setupCSI() {

  Serial.println(
    "INFO,csi_initializing"
  );

  // ----------------------------------------------------------
  // CSI Configuration
  // ----------------------------------------------------------

  wifi_csi_config_t csi_config = {};

  csi_config.lltf_en = true;

  csi_config.htltf_en = true;

  csi_config.stbc_htltf2_en = true;

  csi_config.ltf_merge_en = true;

  csi_config.channel_filter_en = true;

  csi_config.manu_scale = false;

  csi_config.shift = 0;

  // ----------------------------------------------------------
  // Apply CSI configuration
  // ----------------------------------------------------------

  esp_err_t result =
    esp_wifi_set_csi_config(
      &csi_config
    );

  if (result != ESP_OK) {

    Serial.printf(
      "ERROR,csi_config_failed,%s\n",
      esp_err_to_name(result)
    );

    return false;
  }

  Serial.println(
    "INFO,csi_config_ok"
  );

  // ----------------------------------------------------------
  // Register CSI callback
  // ----------------------------------------------------------

  result =
    esp_wifi_set_csi_rx_cb(
      wifi_csi_rx_cb,
      nullptr
    );

  if (result != ESP_OK) {

    Serial.printf(
      "ERROR,csi_callback_failed,%s\n",
      esp_err_to_name(result)
    );

    return false;
  }

  Serial.println(
    "INFO,csi_callback_registered"
  );

  // ----------------------------------------------------------
  // Enable CSI
  // ----------------------------------------------------------

  result =
    esp_wifi_set_csi(true);

  if (result != ESP_OK) {

    Serial.printf(
      "ERROR,csi_enable_failed,%s\n",
      esp_err_to_name(result)
    );

    return false;
  }

  Serial.println(
    "INFO,csi_enabled"
  );

  return true;
}

// ============================================================
// SEND ONE CSI PACKET THROUGH ESP-NOW
// ============================================================

void sendCsiPacket(
  const esp_now_csi_t *packet
) {

  Serial.print(
    "CSI_TX,seq="
  );

  Serial.print(
    packet->seq
  );

  Serial.print(
    ",len="
  );

  Serial.print(
    packet->len
  );

  Serial.print(
    ",rssi="
  );

  Serial.print(
    packet->rssi
  );

  Serial.print(
    ",channel="
  );

  Serial.print(
    packet->channel
  );

  Serial.print(
    ",source="
  );

  printMac(packet->mac);

  Serial.println();

  // ----------------------------------------------------------
  // Send packet
  // ----------------------------------------------------------

  esp_err_t result =
    esp_now_send(
      GATEWAY_MAC,
      (const uint8_t *)packet,
      sizeof(esp_now_csi_t)
    );

  if (result == ESP_OK) {

    espNowSendCount++;

    Serial.printf(
      "ESP_NOW_SEND_CALL,SUCCESS,len=%u\n",
      (unsigned)sizeof(esp_now_csi_t)
    );

  } else {

    espNowFailCount++;

    Serial.printf(
      "ESP_NOW_SEND_CALL,FAIL,%s\n",
      esp_err_to_name(result)
    );
  }
}

// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial.begin(115200);

  delay(1000);

  Serial.println();
  Serial.println(
    "========================================"
  );
  Serial.println(
    "ESP32 CSI + ESP-NOW TRANSMITTER"
  );
  Serial.println(
    "========================================"
  );

  // ----------------------------------------------------------
  // Create CSI queue
  // ----------------------------------------------------------

  csiQueue =
    xQueueCreate(
      CSI_QUEUE_LENGTH,
      sizeof(esp_now_csi_t)
    );

  if (csiQueue == nullptr) {

    Serial.println(
      "ERROR,csi_queue_creation_failed"
    );

    while (true) {
      delay(1000);
    }
  }

  Serial.println(
    "INFO,csi_queue_created"
  );

  // ----------------------------------------------------------
  // Wi-Fi Station
  // ----------------------------------------------------------

  WiFi.mode(WIFI_STA);

  Serial.println(
    "INFO,wifi_connecting"
  );

  WiFi.begin(
    WIFI_SSID,
    WIFI_PASSWORD
  );

  while (
    WiFi.status() != WL_CONNECTED
  ) {

    delay(250);

    Serial.print(".");
  }

  Serial.println();

  // ----------------------------------------------------------
  // Verify Wi-Fi
  // ----------------------------------------------------------

  Serial.printf(
    "INFO,wifi_connected,ip=%s\n",
    WiFi.localIP().toString().c_str()
  );

  Serial.printf(
    "INFO,anchor_mac=%s\n",
    WiFi.macAddress().c_str()
  );

  Serial.printf(
    "INFO,wifi_channel=%d\n",
    WiFi.channel()
  );

  Serial.printf(
    "INFO,expected_packet_size=%u\n",
    (unsigned)sizeof(esp_now_csi_t)
  );

  // ----------------------------------------------------------
  // Make sure we're on expected channel
  // ----------------------------------------------------------

  if (WiFi.channel() != WIFI_CHANNEL) {

    Serial.printf(
      "WARNING,CHANNEL_MISMATCH,expected=%d,actual=%d\n",
      WIFI_CHANNEL,
      WiFi.channel()
    );
  }

  // ----------------------------------------------------------
  // ESP-NOW
  // ----------------------------------------------------------

  if (!setupEspNow()) {

    Serial.println(
      "ERROR,esp_now_setup_failed"
    );

    return;
  }

  // ----------------------------------------------------------
  // Promiscuous/sniffer mode
  // ----------------------------------------------------------
  //
  // Espressif recommends promiscuous mode when you want
  // broader CSI reception rather than only packets received
  // through the station connection.
  // ----------------------------------------------------------

  esp_err_t promiscResult =
    esp_wifi_set_promiscuous(true);

  if (promiscResult != ESP_OK) {

    Serial.printf(
      "WARNING,promiscuous_enable_failed,%s\n",
      esp_err_to_name(promiscResult)
    );

  } else {

    Serial.println(
      "INFO,promiscuous_enabled"
    );
  }

  // ----------------------------------------------------------
  // CSI
  // ----------------------------------------------------------

  if (!setupCSI()) {

    Serial.println(
      "ERROR,csi_setup_failed"
    );

    return;
  }

  Serial.println(
    "INFO,transmitter_ready"
  );
}

// ============================================================
// LOOP
// ============================================================

void loop() {

  // ----------------------------------------------------------
  // Handle queued CSI packets
  // ----------------------------------------------------------

  esp_now_csi_t packet;

  while (
    xQueueReceive(
      csiQueue,
      &packet,
      0
    ) == pdTRUE
  ) {

    sendCsiPacket(&packet);
  }

  // ----------------------------------------------------------
  // Debug ESP-NOW test packet
  // ----------------------------------------------------------

  if (
    DEBUG_TEST_ESPNOW &&
    millis() - lastTestPacket >= TEST_INTERVAL_MS
  ) {

    lastTestPacket = millis();

    sendTestPacket();
  }

  // ----------------------------------------------------------
  // Heartbeat
  // ----------------------------------------------------------

  if (
    millis() - lastHeartbeat >= 2000
  ) {

    lastHeartbeat = millis();

    Serial.printf(
      "HEARTBEAT,%lu,"
      "wifi=%d,"
      "channel=%d,"
      "csi_received=%lu,"
      "csi_dropped=%lu,"
      "espnow_sent=%lu,"
      "espnow_failed=%lu\n",

      lastHeartbeat,

      WiFi.status(),

      WiFi.channel(),

      csiReceivedCount,

      csiDroppedCount,

      espNowSendCount,

      espNowFailCount
    );
  }

  delay(1);
}