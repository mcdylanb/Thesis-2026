#include <esp_now.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <math.h>

// ==================== CONFIG (edit per trial) ====================
// NOTE: associating locks this radio to the trial network's channel — every
// anchor's WIFI_CHANNEL (see anchor_arduino_wireless.ino) must match it for
// ESP-NOW to keep working.
#define WIFI_SSID        "trial-network"    // trial network the Relay joins
#define WIFI_PASSWORD    "trial-password"
#define GATEWAY_IP       "192.168.1.100"    // static IP reserved for the Gateway
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
static IPAddress s_gateway_ip;

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
    // 1. Turn the LED ON and record the exact timestamp it happened
    digitalWrite(LED_PIN, HIGH);
    last_packet_time = millis();
    
    // 2. Process the incoming packet
    esp_now_csi_t *rec = (esp_now_csi_t *)incomingData;
    format_and_print(rec);
  }
}

void setup() {
  Serial.begin(921600);
  
  // Initialize the LED pin as an output and ensure it is OFF to start
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(200);
  }
  s_gateway_ip.fromString(GATEWAY_IP);
  s_udp.begin(0);
  Serial.printf("INFO,wifi_connected,ip=%s\n", WiFi.localIP().toString().c_str());

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

  // 2. Emit a heartbeat pulse every 2 seconds to signal active serial connection
  if (millis() - last_heartbeat >= 2000) {
    last_heartbeat = millis();
    Serial.printf("HEARTBEAT,%lu\n", last_heartbeat);
  }

  // 3. If the trial network association drops, retry in the background
  // rather than requiring a manual power-cycle.
  if (WiFi.status() != WL_CONNECTED &&
      millis() - last_wifi_attempt >= WIFI_RECONNECT_INTERVAL_MS) {
    last_wifi_attempt = millis();
    WiFi.reconnect();
  }
}

