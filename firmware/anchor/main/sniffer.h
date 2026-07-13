#pragma once

#include <stdint.h>

/* Max CSI payload with LLTF-only @ HT20: 128 bytes = 64 int8 [imag, real]
 * pairs. If htltf_en is ever turned on this grows to 256/384 and the
 * record buffer must be resized. */
#define CSI_BUF_MAX 128

/* Fixed-size record copied out of the CSI callback (WiFi task context)
 * into the writer queue. One record == one sniffed packet == one CSV line. */
typedef struct {
    uint32_t seq;          /* per-boot monotonic sequence number        */
    uint8_t  mac[6];       /* transmitter (source) MAC of the packet    */
    int8_t   rssi;         /* dBm, from rx_ctrl                         */
    uint8_t  channel;      /* primary channel the packet was seen on    */
    uint8_t  sig_mode;     /* 0 = non-HT (11g), 1 = HT (11n)            */
    uint8_t  len;          /* valid bytes in buf (<= CSI_BUF_MAX)       */
    uint32_t timestamp_us; /* rx_ctrl.timestamp, local MAC clock, wraps ~71.6 min */
    int8_t   buf[CSI_BUF_MAX];
} csi_record_t;

/* Counters read by the STAT reporter (single writer per counter, aligned
 * 32-bit — atomic enough on ESP32 for statistics). */
typedef struct {
    volatile uint32_t pkts_seen;    /* promiscuous cb invocations        */
    volatile uint32_t csi_count;    /* CSI cb invocations                */
    volatile uint32_t queued;       /* records accepted into the queue   */
    volatile uint32_t dropped;      /* records lost to a full queue      */
} sniffer_stats_t;

extern sniffer_stats_t g_sniffer_stats;

/* Configure promiscuous mode + CSI capture and start delivering records
 * into the queue owned by csv_out. Call after esp_wifi_start() (and after
 * STA association when UDP mode is enabled). */
void sniffer_start(void);
