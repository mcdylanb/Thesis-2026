/* STA association for UDP forwarding mode.
 *
 * Joining an AP locks the radio to the AP's channel, so in this mode the
 * sniff channel == backhaul channel == the AP's channel. Deployment
 * recipe: pin the laptop/phone hotspot to a known 2.4 GHz channel and put
 * the target device on that same hotspot.
 */
#include "anchor_config.h"

#if ANCHOR_UDP_ENABLE

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"

#include "wifi_conn.h"

static const char *TAG = "wifi_conn";

static EventGroupHandle_t s_events;
#define GOT_IP_BIT BIT0

static void on_wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "disconnected, retrying");
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(s_events, GOT_IP_BIT);
    }
}

void wifi_conn_join(void)
{
    s_events = xEventGroupCreate();

    esp_netif_create_default_wifi_sta();
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi_event, NULL, NULL));

    wifi_config_t sta_cfg = { 0 };
    strlcpy((char *)sta_cfg.sta.ssid, ANCHOR_UDP_SSID, sizeof(sta_cfg.sta.ssid));
    strlcpy((char *)sta_cfg.sta.password, ANCHOR_UDP_PASSWORD, sizeof(sta_cfg.sta.password));

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGW(TAG, "joining %s ...", ANCHOR_UDP_SSID);
    xEventGroupWaitBits(s_events, GOT_IP_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
    ESP_LOGW(TAG, "connected");
}

#else /* !ANCHOR_UDP_ENABLE */

void wifi_conn_join(void) { }

#endif
