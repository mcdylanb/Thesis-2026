/* Passive RSSI+CSI capture.
 *
 * The CSI callback is the single source of the output tuple: wifi_csi_info_t
 * carries the source MAC, RSSI, local timestamp and the CSI buffer for the
 * same packet, so RSSI and CSI never need to be joined across callbacks.
 * The promiscuous callback only counts frames seen by the radio; comparing
 * pkts_seen vs csi_count in STAT lines shows how many frames carried no
 * usable OFDM training field (e.g. 11b/DSSS frames yield no CSI).
 *
 * Both callbacks run in the WiFi task: no blocking, no float math, no
 * logging here — copy into the queue and return.
 */
#include <string.h>

#include "esp_wifi.h"
#include "esp_log.h"

#include "anchor_config.h"
#include "sniffer.h"
#include "csv_out.h"

static const char *TAG = "sniffer";

sniffer_stats_t g_sniffer_stats;

static void promisc_rx_cb(void *buf, wifi_promiscuous_pkt_type_t type)
{
    (void)buf;
    (void)type;
    g_sniffer_stats.pkts_seen++;
}

static void csi_rx_cb(void *ctx, wifi_csi_info_t *info)
{
    (void)ctx;

    if (!info || !info->buf || info->len == 0) {
        return;
    }
    g_sniffer_stats.csi_count++;

    csi_record_t rec;
    rec.seq          = g_sniffer_stats.csi_count;
    memcpy(rec.mac, info->mac, 6);
    rec.rssi         = info->rx_ctrl.rssi;
    rec.channel      = info->rx_ctrl.channel;
    rec.sig_mode     = info->rx_ctrl.sig_mode;
    rec.timestamp_us = info->rx_ctrl.timestamp;
    rec.len          = (info->len > CSI_BUF_MAX) ? CSI_BUF_MAX : info->len;
    memcpy(rec.buf, info->buf, rec.len);

    if (csv_out_submit(&rec)) {
        g_sniffer_stats.queued++;
    } else {
        g_sniffer_stats.dropped++;
    }
}

void sniffer_start(void)
{
    /* Modem power save silently throttles receive throughput. */
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));

    const wifi_promiscuous_filter_t filter = {
        .filter_mask = ANCHOR_PROMISC_FILTER,
    };
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&filter));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(promisc_rx_cb));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));

#if !ANCHOR_UDP_ENABLE
    /* Must come after promiscuous enable or it may be reset. Never call
     * in UDP/STA mode: association locks the radio to the AP's channel. */
    ESP_ERROR_CHECK(esp_wifi_set_channel(ANCHOR_CHANNEL, WIFI_SECOND_CHAN_NONE));
#endif

    /* LLTF-only keeps the buffer a constant 128 bytes across 11g/11n
     * frames; the legacy training field is present in every OFDM frame. */
    wifi_csi_config_t csi_cfg = {
        .lltf_en           = true,
        .htltf_en          = false,
        .stbc_htltf2_en    = false,
        .ltf_merge_en      = true,
        .channel_filter_en = false,
        .manu_scale        = false,
        .shift             = 0,
        .dump_ack_en       = false,
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_cfg));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_rx_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));

#if ANCHOR_UDP_ENABLE
    int channel = -1; /* dictated by the AP */
#else
    int channel = ANCHOR_CHANNEL;
#endif
    ESP_LOGW(TAG, "sniffing: anchor=%s channel=%d filter=0x%08x udp=%d",
             ANCHOR_ID, channel, (unsigned)ANCHOR_PROMISC_FILTER, ANCHOR_UDP_ENABLE);
}
