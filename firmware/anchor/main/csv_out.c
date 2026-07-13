/* Record queue + writer task.
 *
 * Line formats (documented in firmware/README.md — the gateway parser
 * depends on these exactly):
 *
 *   CSI,<anchor>,<seq>,<mac>,<rssi>,<sig_mode>,<channel>,<timestamp_us>,<n_sub>,<v1>,...,<vN>
 *   STAT,<anchor>,<uptime_ms>,<pkts_seen>,<csi_cb_count>,<queued>,<dropped>,<free_heap>
 *
 * Amplitude mode (default): n_sub = 64, v_i = round(sqrt(I^2+Q^2)) of the
 * i-th subcarrier in hardware buffer order. Raw I/Q mode: n_sub = 128,
 * values alternate imag,real as int8. Subcarrier reordering and null
 * removal happen on the gateway.
 */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"

#include "anchor_config.h"
#include "csv_out.h"
#include "udp_out.h"

#define WRITER_TASK_STACK 4096
#define WRITER_TASK_PRIO  5
#define UART_TX_RING      8192

/* Worst case: raw I/Q line = header (~64) + 128 * "-128," (~640). */
#define LINE_MAX 800

static QueueHandle_t s_queue;

bool csv_out_submit(const csi_record_t *rec)
{
    return xQueueSend(s_queue, rec, 0) == pdTRUE;
}

static int format_record(const csi_record_t *rec, char *line, size_t cap)
{
    int n = snprintf(line, cap,
                     "CSI,%s,%u,%02x:%02x:%02x:%02x:%02x:%02x,%d,%u,%u,%u,",
                     ANCHOR_ID, (unsigned)rec->seq,
                     rec->mac[0], rec->mac[1], rec->mac[2],
                     rec->mac[3], rec->mac[4], rec->mac[5],
                     (int)rec->rssi, (unsigned)rec->sig_mode,
                     (unsigned)rec->channel, (unsigned)rec->timestamp_us);

#if ANCHOR_OUTPUT_RAW_IQ
    n += snprintf(line + n, cap - n, "%u", (unsigned)rec->len);
    for (int i = 0; i < rec->len; i++) {
        n += snprintf(line + n, cap - n, ",%d", (int)rec->buf[i]);
    }
#else
    int pairs = rec->len / 2; /* buf holds [imag, real] int8 pairs */
    n += snprintf(line + n, cap - n, "%u", (unsigned)pairs);
    for (int i = 0; i < pairs; i++) {
        float im  = (float)rec->buf[2 * i];
        float re  = (float)rec->buf[2 * i + 1];
        int   amp = (int)lroundf(sqrtf(im * im + re * re));
        n += snprintf(line + n, cap - n, ",%d", amp);
    }
#endif
    n += snprintf(line + n, cap - n, "\n");
    return n;
}

static int format_stats(char *line, size_t cap)
{
    return snprintf(line, cap,
                    "STAT,%s,%llu,%u,%u,%u,%u,%u\n",
                    ANCHOR_ID,
                    (unsigned long long)(esp_timer_get_time() / 1000),
                    (unsigned)g_sniffer_stats.pkts_seen,
                    (unsigned)g_sniffer_stats.csi_count,
                    (unsigned)g_sniffer_stats.queued,
                    (unsigned)g_sniffer_stats.dropped,
                    (unsigned)heap_caps_get_free_size(MALLOC_CAP_DEFAULT));
}

static void emit(const char *line, int len)
{
    uart_write_bytes(UART_NUM_0, line, len);
#if ANCHOR_UDP_ENABLE
    udp_out_send(line, len);
#endif
}

static void writer_task(void *arg)
{
    (void)arg;
    static char line[LINE_MAX];
    csi_record_t rec;
    int64_t last_stat = 0;

    for (;;) {
        if (xQueueReceive(s_queue, &rec, pdMS_TO_TICKS(200)) == pdTRUE) {
            emit(line, format_record(&rec, line, sizeof(line)));
        }
        int64_t now = esp_timer_get_time();
        if (now - last_stat >= (int64_t)ANCHOR_STATS_MS * 1000) {
            last_stat = now;
            emit(line, format_stats(line, sizeof(line)));
        }
    }
}

void csv_out_init(void)
{
    /* Install the UART0 driver with a TX ring buffer so writes don't
     * block the writer task under packet bursts. */
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 1024, UART_TX_RING, 0, NULL, 0));
    uart_config_t cfg = {
        .baud_rate  = ANCHOR_UART_BAUD,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0, &cfg));

    s_queue = xQueueCreate(ANCHOR_QUEUE_DEPTH, sizeof(csi_record_t));
    configASSERT(s_queue);

    xTaskCreate(writer_task, "csv_writer", WRITER_TASK_STACK, NULL,
                WRITER_TASK_PRIO, NULL);
}
