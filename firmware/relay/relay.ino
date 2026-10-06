#include <esp_now.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <math.h>

// ==================== CONFIG (edit per trial) ====================
// NOTE: associating locks this radio to the trial network's channel — every
// anchor's WIFI_CHANNEL (see anchor_arduino_wireless.ino) must match it for
// ESP-NOW to keep working.
#define WIFI_SSID        "TP-Link_40F1"     // trial network: the team MP700 pocket WiFi, 2.4 GHz ch 11
#define WIFI_PASSWORD    "90061962"
#define GATEWAY_IP       "192.168.0.197"    // static IP reserved for the Gateway on the MP700
#define GATEWAY_PORT     5555
#define WIFI_RECONNECT_INTERVAL_MS 5000     // how often to retry a dropped association
// ======================================================================

#define CSI_BUF_MAX 128
#define LINE_MAX 800

// --- LED Config ---
#define LED_PIN 2
const int LED_TIMEOUT_MS = 50; // How long the LED stays on per packet

// --- Timing Variables ---
unsigned long last_packet_time = 0;
unsigned long last_heartbeat = 0;
unsigned long last_wifi_attempt = 0;

static WiFiUDP s_udp;
static WiFiUDP s_hb_udp;  // loop() only; s_udp is used from the ESP-NOW callback
static IPAddress s_gateway_ip;
static volatile uint32_t s_rx_count = 0; // ESP-NOW records received since boot

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

void format_and_print(const esp_now_csi_t *rec) {
  char line[LINE_MAX];

  int n = snprintf(line, sizeof(line),
                   "CSI,%s,%u,%02x:%02x:%02x:%02x:%02x:%02x,%d,%u,%u,%u,",
                   rec->anchor_id, (unsigned)rec->seq,
                   rec->mac[0], rec->mac[1], rec->mac[2],
                   rec->mac[3], rec->mac[4], rec->mac[5],
                   (int)rec->rssi, (unsigned)rec->sig_mode,
                   (unsigned)rec->channel, (unsigned)rec->timestamp_us);

  int pairs = rec->len / 2;
  n += snprintf(line + n, sizeof(line) - n, "%u", (unsigned)pairs);

  for (int i = 0; i < pairs; i++) {
    float im  = (float)rec->buf[2 * i];
    float re  = (float)rec->buf[2 * i + 1];
    int   amp = (int)lroundf(sqrtf(im * im + re * re));
    n += snprintf(line + n, sizeof(line) - n, ",%d", amp);
  }

  Serial.println(line); // debug tee for bring-up

  // Uplink: same line, unicast UDP to the Gateway on the trial network.
  s_udp.beginPacket(s_gateway_ip, GATEWAY_PORT);
  s_udp.write((const uint8_t *)line, n);
  s_udp.endPacket();
}

// Callback for incoming ESP-NOW data
void OnDataRecv(const esp_now_recv_info *info, const uint8_t *incomingData, int len) {
  if (len == sizeof(esp_now_csi_t)) {
    s_rx_count++;
    // 1. Turn the LED ON and record the exact timestamp it happened
    digitalWrite(LED_PIN, HIGH);
    last_packet_time = millis();
    
    // 2. Process the incoming packet
    esp_now_csi_t *rec = (esp_now_csi_t *)incomingData;
    format_and_print(rec);
  }
}

void setup() {
  Serial.begin(115200);
  
  // Initialize the LED pin as an output and ensure it is OFF to start
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  WiFi.mode(WIFI_STA);
  // The Anchors' relay_mac must equal this (the STA MAC).
  Serial.printf("INFO,relay_mac=%s\n", WiFi.macAddress().c_str());

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long last_report = 0;
  while (WiFi.status() != WL_CONNECTED) {
    // Report once a second so a wrong SSID/password or a powered-off trial
    // network shows up on the Serial Monitor instead of a silent hang.
    if (millis() - last_report >= 1000) {
      last_report = millis();
      Serial.printf("INFO,wifi_connecting,ssid=%s,status=%d\n", WIFI_SSID, (int)WiFi.status());
    }
    delay(200);
  }
  // Modem sleep can drop ESP-NOW frames on an associated station.
  WiFi.setSleep(false);
  s_gateway_ip.fromString(GATEWAY_IP);
  s_udp.begin(0);
  s_hb_udp.begin(0);
  // channel must equal every Anchor's WIFI_CHANNEL.
  Serial.printf("INFO,wifi_connected,ip=%s,channel=%d,gateway=%s:%d\n",
                WiFi.localIP().toString().c_str(), (int)WiFi.channel(),
                GATEWAY_IP, GATEWAY_PORT);

  if (esp_now_init() != ESP_OK) {
    Serial.println("Error initializing ESP-NOW");
    return;
  }

  esp_now_register_recv_cb(OnDataRecv);
}

void loop() {
  // 1. LED Auto-Turnoff mechanism (Non-blocking)
  // If 50 milliseconds have passed since the last packet arrived, turn the LED off.
  if (millis() - last_packet_time > LED_TIMEOUT_MS) {
    digitalWrite(LED_PIN, LOW);
  }

  // 2. Heartbeat every 2 seconds, on serial and over UDP, so the Gateway can
  // tell "Relay reachable, no Anchor data" from "Relay unreachable".
  // rx = ESP-NOW records received since boot.
  if (millis() - last_heartbeat >= 2000) {
    last_heartbeat = millis();
    char hb[96];
    int n = snprintf(hb, sizeof(hb), "HEARTBEAT,%lu,rx=%lu,ch=%d,wifi=%d",
                     last_heartbeat, (unsigned long)s_rx_count,
                     (int)WiFi.channel(), WiFi.status() == WL_CONNECTED ? 1 : 0);
    Serial.println(hb);
    s_hb_udp.beginPacket(s_gateway_ip, GATEWAY_PORT);
    s_hb_udp.write((const uint8_t *)hb, n);
    s_hb_udp.endPacket();
  }

  // 3. If the trial network association drops, retry in the background
  // rather than requiring a manual power-cycle.
  if (WiFi.status() != WL_CONNECTED &&
      millis() - last_wifi_attempt >= WIFI_RECONNECT_INTERVAL_MS) {
    last_wifi_attempt = millis();
    WiFi.reconnect();
  }
}

