#pragma once

#include <stdbool.h>

#include "sniffer.h"

/* Create the record queue and start the UART writer task. Call before
 * sniffer_start() so records always have somewhere to go. */
void csv_out_init(void);

/* Enqueue one record for formatting/output. Non-blocking; returns false
 * when the queue is full (caller counts the drop). Safe from the WiFi
 * task context. */
bool csv_out_submit(const csi_record_t *rec);
