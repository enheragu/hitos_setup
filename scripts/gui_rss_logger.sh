#!/bin/bash
# Persistent RSS/PSS sampler for the multiespectral camera GUI
# (multiespectral_control). Characterizes its slow memory growth — the
# ~1 GB-over-long-uptime climb seen 2026-06-17. The idle baseline is flat
# (~180 MB); growth only appears with image flow + a connected browser client,
# so this must run across normal operation (and reboots) to catch the slope.
#
# Launch from cron @reboot (survives reboots, no sudo):
#   ( crontab -l 2>/dev/null; \
#     echo "@reboot /bin/bash /home/arvc/ros2_ws/src/hitos_setup/scripts/gui_rss_logger.sh >/dev/null 2>&1" ) | crontab -
#
# Analyze later: column 4 (rss_kB) vs column 3 (etimes_s) — monotonic climb = leak;
# correlate jumps with when the preview was open.
LOG="${GUI_RSS_LOG:-/home/arvc/gui_rss.log}"
INTERVAL="${GUI_RSS_INTERVAL:-60}"

# Single-instance guard (flock): a second @reboot or manual launch is a no-op.
exec 9>"/tmp/gui_rss_logger.lock"
flock -n 9 || exit 0

[ -f "$LOG" ] || echo "ts,pid,etimes_s,rss_kB,pss_kB,memavail_kB" > "$LOG"

while true; do
    ma=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null)
    p=$(pgrep -f multiespectral_control | head -1)
    if [ -n "$p" ] && [ -r "/proc/$p/status" ]; then
        rss=$(awk '/^VmRSS/{print $2}' "/proc/$p/status" 2>/dev/null)
        pss=$(awk '/^Pss:/{s+=$2} END{print s+0}' "/proc/$p/smaps_rollup" 2>/dev/null)
        et=$(ps -o etimes= -p "$p" 2>/dev/null | tr -d ' ')
        echo "$(date +%FT%T),$p,$et,$rss,$pss,$ma" >> "$LOG"
    else
        echo "$(date +%FT%T),,,,,$ma" >> "$LOG"
    fi
    sleep "$INTERVAL"
done
