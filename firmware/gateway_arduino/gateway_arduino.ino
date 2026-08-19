#include <esp_now.h>
#include <WiFi.h>

// Updated callback function for ESP32 Core v3.x+
void OnDataRecv(const esp_now_recv_info *info, const uint8_t *incomingData, int len) {
  // Extract the sender's MAC address from the info struct
  Serial.print("Received from MAC [");
  for (int i = 0; i < 6; i++) {
    Serial.printf("%02X", info->src_addr[i]);
    if (i < 5) Serial.print(":");
  }
  Serial.print("] -> Payload: ");
  
  // Print the incoming data as text
  for (int i = 0; i < len; i++) {
    Serial.print((char)incomingData[i]);
  }
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  
  // ESP-NOW requires the ESP32 to be in Wi-Fi Station mode
  WiFi.mode(WIFI_STA);
  
  if (esp_now_init() != ESP_OK) {
    Serial.println("Error initializing ESP-NOW");
    return;
  }
  
  // Register the callback function
  esp_now_register_recv_cb(OnDataRecv);
  Serial.println("Gateway initialized. Waiting for ESP-NOW packets...");
}

void loop() {
  // Background task handles reception
}
