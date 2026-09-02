#!/bin/bash
# ath11k finds no board data with the real address here, so it invents one with
# the Atheros prefix (00:03:7f:...) on every boot and the router sees a new
# client each time.  The address the phone was made with lives in the persist
# partition, as "wlan0=<12 hex digits>".
set -u
IF=${1:-wlp1s0}
P=$(readlink -f /dev/disk/by-partlabel/persist) || exit 0
M=$(dd if="$P" bs=1M count=8 2>/dev/null | strings | grep -m1 -oE "wlan0=[0-9a-fA-F]{12}" | cut -d= -f2)
[ -n "$M" ] || { echo "no wlan mac in persist"; exit 0; }
MAC=$(echo "$M" | sed "s/../&:/g;s/:$//")
for i in $(seq 1 30); do ip link show "$IF" >/dev/null 2>&1 && break; sleep 1; done
ip link set dev "$IF" down 2>/dev/null
ip link set dev "$IF" address "$MAC" && echo "$IF set to $MAC"
ip link set dev "$IF" up 2>/dev/null
