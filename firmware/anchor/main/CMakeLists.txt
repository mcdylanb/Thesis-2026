idf_component_register(
    SRCS
        "main.c"
        "sniffer.c"
        "csv_out.c"
        "wifi_conn.c"
        "udp_out.c"
    INCLUDE_DIRS "."
    REQUIRES esp_wifi nvs_flash esp_netif esp_event driver lwip
)
