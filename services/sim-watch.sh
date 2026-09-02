#!/bin/bash
# Notice cards being put in or taken out.
#
# The bring-up service provisions the cards once, at boot.  Nothing else would
# ever look again, so a card put in later stays invisible - the modem reports it
# as 'present' and its application sits in 'detected' for ever.  The modem does
# announce the change, so listen for that rather than polling.
set -u

DEV=qrtr://3
LOG=${MODEM_LOG:-/var/log/modem-up.log}
log () { echo "[$(date +%T)] sim-watch: $*" | tee -a "$LOG"; }

log "listening for slot status indications"
# Any indication is reason enough to look: provisioning is idempotent and says
# so in its exit status, and only then is ModemManager worth restarting - it
# does not pick up a card that appeared while it was already running.
qmicli -d $DEV --uim-monitor-slot-status 2>&1 | while read -r line; do
    case "$line" in
        ""|*"Monitoring"*|*"monitoring"*) continue ;;
    esac
    log "$line"
    sleep 2
    if alioth-sim-provision; then
        log "restarting ModemManager"
        systemctl restart ModemManager
    fi
done
