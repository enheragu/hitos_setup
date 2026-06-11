#!/usr/bin/env bash
# One-time system configuration for HITOS.
# Run once as root (or with sudo) after first deployment:
#   sudo bash setup_system_limits.sh
#
# Configures:
#   - journald: hard cap on log size and rate limiting
#   - rsyslog: daily rotation with max file size
#   - Sudoers: passwordless rules for HITOS services

set -e
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

echo "=== HITOS system limits setup ==="

# ---- journald limits ----
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/hitos-limits.conf << 'EOF'
[Journal]
# Total journal size cap
SystemMaxUse=500M
SystemMaxFileSize=50M
# Delete entries older than 2 weeks
MaxRetentionSec=2weeks
# Rate limiting: max 300 messages per 30s per service (~10/s average)
# Prevents any one crashed/spamming node from filling disk
RateLimitIntervalSec=30s
RateLimitBurst=300
EOF
systemctl restart systemd-journald
echo "  [OK] journald limits configured (500 MB max, 2 weeks retention)"

# ---- rsyslog rotation ----
cat > /etc/logrotate.d/rsyslog << 'EOF'
/var/log/syslog
/var/log/mail.log
/var/log/kern.log
/var/log/auth.log
/var/log/user.log
/var/log/cron.log
{
    daily
    rotate 7
    maxsize 100M
    missingok
    notifempty
    compress
    delaycompress
    sharedscripts
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate
    endscript
}
EOF
echo "  [OK] rsyslog rotation configured (daily, 7 days, max 100 MB per file)"

# ---- Sudoers ----
cp "$SCRIPT_DIR/hitos-manager-sudoers" /etc/sudoers.d/hitos-manager
chmod 440 /etc/sudoers.d/hitos-manager
echo "  [OK] sudoers rules installed"

echo ""
echo "Done. Reboot or restart affected services to apply all changes."
