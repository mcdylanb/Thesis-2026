#include <esp_now.h>
#include <WiFi.h>
#include <math.h>

#define CSI_BUF_MAX 128
#define LINE_MAX 800

// --- LED Config ---
#define LED_PIN 2
const int LED_TIMEOUT_MS = 50; // How long the LED stays on per packet

// --- Timing Variables ---
unsigned long last_packet_time = 0;
unsigned long last_heartbeat = 0;

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
  
  Serial.println(line);
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
}

