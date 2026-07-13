/* ESP32 anchor firmware — passive RSSI+CSI sniffer.
 *
 * Built against ESP-IDF v5.4, target: esp32 (classic, NodeMCU boards).
 * One binary for all anchors; only CONFIG_ANCHOR_ID differs per board.
 *
 * Bring-up order matters:
 *   serial mode: NULL mode -> start -> promiscuous -> set_channel -> CSI
 *   UDP mode:    STA mode  -> start -> associate  -> promiscuous -> CSI
 *                (no set_channel: the AP dictates the channel)
 */
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_wifi.h"

#include "anchor_config.h"
#include "sniffer.h"
#include "csv_out.h"
#include "wifi_conn.h"
#include "udp_out.h"

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    wifi_init_config_t wifi_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

    /* Output path first so sniffed records always have somewhere to go. */
    csv_out_init();

#if ANCHOR_UDP_ENABLE
    wifi_conn_join();   /* sets STA mode, starts WiFi, blocks until IP */
    udp_out_init();
#else
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL));
    ESP_ERROR_CHECK(esp_wifi_start());
#endif

    sniffer_start();
}
