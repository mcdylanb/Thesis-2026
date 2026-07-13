#include "anchor_config.h"
#include "udp_out.h"

#if ANCHOR_UDP_ENABLE

#include <string.h>

#include "lwip/sockets.h"
#include "esp_log.h"

static const char *TAG = "udp_out";

static int s_sock = -1;
static struct sockaddr_in s_dest;

void udp_out_init(void)
{
    memset(&s_dest, 0, sizeof(s_dest));
    s_dest.sin_family = AF_INET;
    s_dest.sin_port   = htons(ANCHOR_UDP_GW_PORT);
    s_dest.sin_addr.s_addr = inet_addr(ANCHOR_UDP_GW_IP);

    s_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (s_sock < 0) {
        ESP_LOGE(TAG, "socket() failed, UDP forwarding disabled");
    } else {
        ESP_LOGW(TAG, "forwarding to %s:%d", ANCHOR_UDP_GW_IP, ANCHOR_UDP_GW_PORT);
    }
}

void udp_out_send(const char *line, size_t len)
{
    if (s_sock >= 0) {
        sendto(s_sock, line, len, 0, (struct sockaddr *)&s_dest, sizeof(s_dest));
    }
}

#else /* !ANCHOR_UDP_ENABLE */

void udp_out_init(void) { }
void udp_out_send(const char *line, size_t len) { (void)line; (void)len; }

#endif
