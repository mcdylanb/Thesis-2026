#include <esp_now.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <math.h>

// ==================== CONFIG ====================
#define WIFI_SSID        "TP-Link_40F1"
#define WIFI_PASSWORD    "90061962"
#define GATEWAY_IP       "192.168.0.197"
#define GATEWAY_PORT     5555
#define WIFI_RECONNECT_INTERVAL_MS 5000
// =================================================

#define CSI_BUF_MAX 128
#define LINE_MAX 800

// --- LED Config ---
#define LED_PIN 2
const int LED_TIMEOUT_MS = 50;

// --- Timing ---
unsigned long last_packet_time = 0;
unsigned long last_heartbeat = 0;
unsigned long last_wifi_attempt = 0;

// --- Counters ---
volatile uint32_t total_rx_packets = 0;
volatile uint32_t valid_csi_packets = 0;
volatile uint32_t invalid_packets = 0;
volatile uint32_t udp_sent_packets = 0;

// --- UDP ---
static WiFiUDP s_udp;
static IPAddress s_gateway_ip;

// ============================================================
// CSI PACKET STRUCTURE
// MUST MATCH TRANSMITTER EXACTLY
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
// FORMAT CSI FOR UDP + SERIAL
// ============================================================

void format_and_print(const esp_now_csi_t *rec) {

  char line[LINE_MAX];

  // ------------------------------------------
  // Safely terminate anchor ID
  // ------------------------------------------

  char anchor_id[4];

  memcpy(
    anchor_id,
    rec->anchor_id,
    3
  );

  anchor_id[3] = '\0';


  // ------------------------------------------
  // Build CSV line
  // ------------------------------------------

  int n = snprintf(
    line,
    sizeof(line),

    "CSI,%s,%u,%02x:%02x:%02x:%02x:%02x:%02x,%d,%u,%u,%u,",

    anchor_id,

    (unsigned)rec->seq,

    rec->mac[0],
    rec->mac[1],
    rec->mac[2],
    rec->mac[3],
    rec->mac[4],
    rec->mac[5],

    (int)rec->rssi,

    (unsigned)rec->sig_mode,

    (unsigned)rec->channel,

    (unsigned)rec->timestamp_us
  );


  if (n < 0 || n >= sizeof(line)) {

    Serial.println(
      "ERROR,CSI_line_too_long"
    );

    return;
  }


  // ------------------------------------------
  // Number of I/Q pairs
  // ------------------------------------------

  int pairs = rec->len / 2;


  n += snprintf(
    line + n,
    sizeof(line) - n,
    "%u",
    (unsigned)pairs
  );


  // ------------------------------------------
  // Calculate amplitude
  // ------------------------------------------

  for (
    int i = 0;
    i < pairs && n < sizeof(line);
    i++
  ) {

    float im =
      (float)rec->buf[2 * i];

    float re =
      (float)rec->buf[2 * i + 1];

    int amp =
      (int)lroundf(
        sqrtf(
          im * im +
          re * re
        )
      );

    n += snprintf(
      line + n,
      sizeof(line) - n,
      ",%d",
      amp
    );
  }


  // ========================================================
  // PRINT COMPLETE CSI DATA
  // ========================================================

  Serial.println();
  Serial.println(
    "================ RECEIVED CSI ================"
  );

  Serial.printf(
    "ANCHOR_ID      : %s\n",
    anchor_id
  );

  Serial.printf(
    "SEQUENCE       : %u\n",
    (unsigned)rec->seq
  );

  Serial.print(
    "ESP-NOW SENDER : "
  );

  // Actual ESP-NOW sender is not stored inside the struct.
  // This is printed by OnDataRecv().
  Serial.println(
    "(printed above in RX_ANY)"
  );

  Serial.print(
    "CSI SOURCE MAC : "
  );

  printMac(rec->mac);

  Serial.println();

  Serial.printf(
    "RSSI           : %d dBm\n",
    (int)rec->rssi
  );

  Serial.printf(
    "CHANNEL        : %u\n",
    (unsigned)rec->channel
  );

  Serial.printf(
    "SIG MODE       : %u\n",
    (unsigned)rec->sig_mode
  );

  Serial.printf(
    "CSI LENGTH     : %u bytes\n",
    (unsigned)rec->len
  );

  Serial.printf(
    "CSI PAIRS      : %d\n",
    pairs
  );

  Serial.printf(
    "TIMESTAMP      : %u us\n",
    (unsigned)rec->timestamp_us
  );

  Serial.println(
    "CSI AMPLITUDES:"
  );

  // Print amplitudes in rows
  for (int i = 0; i < pairs; i++) {

    float im =
      (float)rec->buf[2 * i];

    float re =
      (float)rec->buf[2 * i + 1];

    int amp =
      (int)lroundf(
        sqrtf(
          im * im +
          re * re
        )
      );

    Serial.printf(
      "%d:%d ",
      i,
      amp
    );

    // New line every 16 values
    if ((i + 1) % 16 == 0) {
      Serial.println();
    }
  }

  Serial.println();

  Serial.println(
    "CSV:"
  );

  Serial.println(line);

  Serial.println(
    "================================================"
  );


  // ========================================================
  // SEND TO GATEWAY VIA UDP
  // ========================================================

  s_udp.beginPacket(
    s_gateway_ip,
    GATEWAY_PORT
  );

  s_udp.write(
    (const uint8_t *)line,
    n
  );

  int result =
    s_udp.endPacket();

  if (result == 1) {

    udp_sent_packets++;

    Serial.printf(
      "UDP_FORWARD,SUCCESS,bytes=%d,destination=%s:%d\n",

      n,

      s_gateway_ip.toString().c_str(),

      GATEWAY_PORT
    );

  } else {

    Serial.println(
      "UDP_FORWARD,FAILED"
    );
  }
}


// ============================================================
// ESP-NOW RECEIVE CALLBACK
// ============================================================

void OnDataRecv(
  const esp_now_recv_info *info,
  const uint8_t *incomingData,
  int len
) {

  total_rx_packets++;

  // ========================================================
  // ANY ESP-NOW PACKET RECEIVED
  // ========================================================

  Serial.println();
  Serial.println(
    "******** ESP-NOW PACKET RECEIVED ********"
  );

  Serial.printf(
    "PACKET LENGTH : %d bytes\n",
    len
  );

  Serial.printf(
    "EXPECTED       : %u bytes\n",
    (unsigned)sizeof(esp_now_csi_t)
  );

  Serial.print(
    "ESP-NOW FROM   : "
  );

  printMac(
    info->src_addr
  );

  Serial.println();


  // LED
  digitalWrite(
    LED_PIN,
    HIGH
  );

  last_packet_time =
    millis();


  // ========================================================
  // CHECK PACKET LENGTH
  // ========================================================

  if (len != sizeof(esp_now_csi_t)) {

    invalid_packets++;

    Serial.println(
      "TYPE           : UNKNOWN / TEST PACKET"
    );

    Serial.printf(
      "WARNING        : size mismatch (%d != %u)\n",

      len,

      (unsigned)sizeof(esp_now_csi_t)
    );


    // ------------------------------------------
    // Print raw data
    // ------------------------------------------

    Serial.print(
      "RAW DATA       : "
    );

    int dump_len =
      min(len, 64);

    for (int i = 0; i < dump_len; i++) {

      Serial.printf(
        "%02X ",
        incomingData[i]
      );
    }

    Serial.println();

    Serial.println(
      "****************************************"
    );

    return;
  }


  // ========================================================
  // VALID CSI PACKET
  // ========================================================

  valid_csi_packets++;

  const esp_now_csi_t *rec =
    (const esp_now_csi_t *)incomingData;


  Serial.println(
    "TYPE           : CSI PACKET"
  );

  Serial.printf(
    "ANCHOR         : %.3s\n",
    rec->anchor_id
  );

  Serial.printf(
    "SEQUENCE       : %u\n",
    (unsigned)rec->seq
  );

  Serial.printf(
    "RSSI           : %d dBm\n",
    (int)rec->rssi
  );

  Serial.printf(
    "CHANNEL        : %u\n",
    (unsigned)rec->channel
  );

  Serial.printf(
    "CSI LENGTH     : %u bytes\n",
    (unsigned)rec->len
  );

  Serial.printf(
    "TIMESTAMP      : %u us\n",
    (unsigned)rec->timestamp_us
  );

  Serial.print(
    "CSI SOURCE     : "
  );

  printMac(
    rec->mac
  );

  Serial.println();


  // ========================================================
  // FORMAT + FORWARD
  // ========================================================

  format_and_print(
    rec
  );
}


// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial.begin(
    115200
  );

  delay(1000);


  Serial.println();
  Serial.println(
    "============================================"
  );
  Serial.println(
    "ESP-NOW CSI RELAY / RECEIVER"
  );
  Serial.println(
    "============================================"
  );


  // ========================================================
  // LED
  // ========================================================

  pinMode(
    LED_PIN,
    OUTPUT
  );

  digitalWrite(
    LED_PIN,
    LOW
  );


  // ========================================================
  // WIFI
  // ========================================================

  WiFi.mode(
    WIFI_STA
  );

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

    delay(200);

    Serial.print(".");
  }

  Serial.println();


  // ========================================================
  // UDP
  // ========================================================

  s_gateway_ip.fromString(
    GATEWAY_IP
  );

  s_udp.begin(0);


  // ========================================================
  // WIFI INFO
  // ========================================================

  Serial.printf(
    "INFO,wifi_connected,ip=%s\n",
    WiFi.localIP().toString().c_str()
  );

  Serial.printf(
    "INFO,receiver_mac=%s\n",
    WiFi.macAddress().c_str()
  );

  Serial.printf(
    "INFO,wifi_channel=%d\n",
    WiFi.channel()
  );

  Serial.printf(
    "INFO,expected_csi_struct_size=%u\n",
    (unsigned)sizeof(esp_now_csi_t)
  );


  // ========================================================
  // ESP-NOW
  // ========================================================

  if (
    esp_now_init() != ESP_OK
  ) {

    Serial.println(
      "ERROR,esp_now_init_failed"
    );

    return;
  }

  Serial.println(
    "INFO,esp_now_initialized"
  );


  esp_now_register_recv_cb(
    OnDataRecv
  );

  Serial.println(
    "INFO,receive_callback_registered"
  );


  Serial.println(
    "INFO,relay_ready"
  );

  Serial.println(
    "============================================"
  );
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  // ========================================================
  // LED TIMEOUT
  // ========================================================

  if (
    millis() - last_packet_time >
    LED_TIMEOUT_MS
  ) {

    digitalWrite(
      LED_PIN,
      LOW
    );
  }


  // ========================================================
  // HEARTBEAT
  // ========================================================

  if (
    millis() - last_heartbeat >= 2000
  ) {

    last_heartbeat =
      millis();


    Serial.printf(
      "HEARTBEAT,%lu,"
      "wifi_status=%d,"
      "channel=%d,"
      "rx_total=%lu,"
      "csi_valid=%lu,"
      "invalid=%lu,"
      "udp_sent=%lu\n",

      last_heartbeat,

      WiFi.status(),

      WiFi.channel(),

      total_rx_packets,

      valid_csi_packets,

      invalid_packets,

      udp_sent_packets
    );
  }


  // ========================================================
  // WIFI RECONNECT
  // ========================================================

  if (
    WiFi.status() != WL_CONNECTED &&
    millis() - last_wifi_attempt >=
      WIFI_RECONNECT_INTERVAL_MS
  ) {

    last_wifi_attempt =
      millis();

    Serial.println(
      "INFO,wifi_reconnecting"
    );

    WiFi.reconnect();
  }
}