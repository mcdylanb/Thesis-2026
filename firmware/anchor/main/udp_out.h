#pragma once

#include <stddef.h>

/* Open the UDP socket to the gateway. No-ops when UDP mode is disabled. */
void udp_out_init(void);

/* Mirror one CSV line (including trailing newline) as a single datagram.
 * Best-effort: send failures are silently ignored so serial output is
 * never disturbed. */
void udp_out_send(const char *line, size_t len);
