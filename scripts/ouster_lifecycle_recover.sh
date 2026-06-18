#!/bin/bash
# Recover the Ouster os_driver lifecycle after a boot-timing race.
#
# If hitos_sensors.service starts while the Ouster is still booting, the launch
# lifecycle manager's single TRANSITION_CONFIGURE fails and is NEVER retried:
# the driver sits "unconfigured" forever while the service shows active
# (observed 2026-06-12: 30+ min without lidar data). This script runs in the
# background from ExecStartPost and:
#   1. waits for the sensor HTTP API (cold boot takes 60-90 s),
#   2. drives the driver to "active" with retries,
#   3. saves the applied config to flash so the next restart finds
#      staging==active and skips reinitialise (which would break PTP lock).
#
# Always exits 0 — diagnostics go to the journal, never fail the service.

source /home/arvc/ros2_ws/install/setup.bash

OUSTER=${HITOS_LIDAR_IP:-192.168.4.4}
NODE=/ouster/os_driver

log() { echo "ouster-recover: $*"; }

get_state() {
    timeout 20 ros2 lifecycle get "$NODE" 2>/dev/null | awk '{print $1}'
}

# ---- 1. Wait for the sensor HTTP API ----
log "waiting for Ouster HTTP API at $OUSTER..."
http_up=0
for i in $(seq 60); do
    if curl -sf --max-time 2 "http://$OUSTER/api/v1/sensor/metadata/sensor_info" >/dev/null 2>&1; then
        http_up=1
        log "sensor HTTP API up (iteration $i)"
        break
    fi
    sleep 3
done
if [ "$http_up" -ne 1 ]; then
    log "WARNING: sensor HTTP API unreachable after 180 s — skipping lifecycle recovery."
    exit 0
fi

# ---- 2. Drive the driver lifecycle to 'active' ----
# The launch's own configure may have succeeded (normal case) or be in
# progress; check state between attempts. After an external CONFIGURE the
# launch OnStateTransition handler usually emits ACTIVATE by itself; the
# 'inactive' branch covers the case where it does not.
for attempt in $(seq 6); do
    state=$(get_state)
    log "driver state: '${state:-unknown}' (attempt $attempt/6)"
    case "$state" in
        active)
            break
            ;;
        unconfigured)
            log "sending CONFIGURE (may reinitialise the sensor, ~30-60 s)..."
            timeout 90 ros2 lifecycle set "$NODE" configure
            ;;
        inactive)
            log "sending ACTIVATE..."
            timeout 60 ros2 lifecycle set "$NODE" activate
            ;;
        *)
            # node not discoverable yet or mid-transition — just wait
            ;;
    esac
    sleep 5
done

state=$(get_state)
if [ "$state" = "active" ]; then
    log "driver active."
else
    log "WARNING: driver not active after recovery (state='${state:-unknown}'). Manual 'systemctl restart hitos_sensors' may be needed."
fi

# ---- 3. Save active config to flash ----
# The sensor HTTP API is briefly offline during reinitialisation, so poll: the
# first success necessarily captures the freshly-applied config.
log "saving Ouster config to flash..."
for i in $(seq 40); do
    if curl -sf --max-time 2 -X POST "http://$OUSTER/api/v1/sensor/cmd/save_config_params" >/dev/null 2>&1; then
        log "config saved to flash (iteration $i). Next restart will not reinitialise."
        exit 0
    fi
    sleep 3
done
log "WARNING: could not save Ouster config to flash after 120 s. A manual save_config_params or power-cycle may be needed to avoid PTP disruption on next restart."
exit 0
