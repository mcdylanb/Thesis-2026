/*
 * ESP32 Beacon firmware — steady OFDM transmitter for Calibration sessions
 * and test Trials (ADR-0003, #30).
 *
 * Board:  "ESP32 Dev Module" (same settings as the Anchor sketch)
 * Core:   arduino-esp32 3.x (2.x also works)
 * Serial: 115200 baud (optional — the Beacon runs the same on a power bank)
 *
 * Broadcasts one small ESP-NOW frame every 1000 / RATE_HZ ms on
 * WIFI_CHANNEL, from the STA MAC. The rate is forced to HT MCS0: the
 * default ESP-NOW rate is 1 Mbps DSSS, which carries no OFDM training
 * field, so the Anchors' CSI callback would never fire and they would emit
 * no Records at all. Broadcast frames are never acked or retried, which
 * keeps the transmit rate steady.
 *
 * Line format (every INFO_INTERVAL_MS, USB serial only):
 *   INFO,beacon,mac=<mac>,channel=<ch>,rate_hz=<hz>,sent=<n>,fail=<n>
 * mac is the Beacon's identity in every Anchor Record; put it in the
 * authorized-device list. sent climbing and fail at 0 means the Beacon is
 * transmitting; whether the Anchors hear it is checked on their STATUS line.
 */

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

// ==================== CONFIG ====================
#define WIFI_CHANNEL     11     // must equal the Anchors' WIFI_CHANNEL
#define RATE_HZ          20     // frames per second (ADR-0003 default)
#define SERIAL_BAUD      115200
#define INFO_INTERVAL_MS 5000   // INFO line period
#define STATUS_LED       2      // on-board LED on most DevKit boards; blinks once per second
// ================================================

static uint8_t bcast[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static uint32_t s_sent = 0;
static uint32_t s_fail = 0; // esp_now_send() refused the frame

void setup() {
  Serial.begin(SERIAL_BAUD);
  pinMode(STATUS_LED, OUTPUT);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_ps(WIFI_PS_NONE);
  if (esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE) != ESP_OK) {
    Serial.printf("ERROR,beacon,set_channel_failed,channel=%d\n", WIFI_CHANNEL);
  }

  // OFDM rate so every frame carries an L-LTF (see header).
  if (esp_wifi_config_espnow_rate(WIFI_IF_STA, WIFI_PHY_RATE_MCS0_LGI) != ESP_OK) {
    Serial.println("ERROR,beacon,set_rate_failed");
  }

  if (esp_now_init() != ESP_OK) {
    Serial.println("ERROR,beacon,esp_now_init_failed");
    return;
  }

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, bcast, 6);
  peer.channel = WIFI_CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) {
    Serial.println("ERROR,beacon,add_peer_failed");
  }
}

void loop() {
  static uint32_t next = millis();
  static uint32_t last_info = 0;

  if (esp_now_send(bcast, (uint8_t *)&s_sent, sizeof(s_sent)) == ESP_OK) s_sent++;
  else s_fail++;

  // Heartbeat LED: alive check when running on a power bank with no serial.
  digitalWrite(STATUS_LED, (millis() / 500) % 2);

  if (millis() - last_info >= INFO_INTERVAL_MS) {
    last_info = millis();
    uint8_t ch = 0;
    wifi_second_chan_t second;
    esp_wifi_get_channel(&ch, &second);
    Serial.printf("INFO,beacon,mac=%s,channel=%u,rate_hz=%d,sent=%lu,fail=%lu\n",
                  WiFi.macAddress().c_str(), (unsigned)ch, RATE_HZ,
                  (unsigned long)s_sent, (unsigned long)s_fail);
  }

  // Fixed schedule: send time doesn't accumulate as drift.
  next += 1000 / RATE_HZ;
  int32_t wait = (int32_t)(next - millis());
  if (wait > 0) delay(wait);
}
