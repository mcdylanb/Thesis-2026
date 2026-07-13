#pragma once

/* Join the configured AP as a station and block until an IP is obtained.
 * Only compiled to a real implementation when UDP mode is enabled;
 * otherwise a no-op. */
void wifi_conn_join(void);
