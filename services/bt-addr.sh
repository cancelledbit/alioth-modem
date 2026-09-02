#!/bin/bash
# Give the Bluetooth controller a stable address.
#
# This phone has no Bluetooth address of its own to find: the NVM on its own
# bluetooth partition leaves the field empty, persist holds only the Wi-Fi
# address, and no other partition carries one.  Left alone the driver falls back
# to whatever the generic NVM from linux-firmware says, which is the same on
# every handset - so two of these phones in one room would answer to the same
# address, and pairings are keyed on it.
#
# So derive one from the Wi-Fi address, which *is* per handset: set the
# locally-administered bit, so it cannot collide with any address a
# manufacturer handed out, and step the last byte to keep the two apart.
#
#   8c:7a:3d:c0:df:17  ->  8e:7a:3d:c0:df:18
set -u

P=""
for i in $(seq 1 20); do
    P=$(readlink -f /dev/disk/by-partlabel/persist 2>/dev/null || true)
    [ -n "$P" ] && [ -b "$P" ] && break
    sleep 1
done
[ -n "$P" ] && [ -b "$P" ] || { echo "no persist partition"; exit 0; }

M=$(dd if="$P" bs=1M count=8 2>/dev/null | strings 2>/dev/null | grep -m1 -oE "wlan0=[0-9a-fA-F]{12}" | cut -d= -f2)
[ -n "$M" ] || { echo "no wlan mac in persist"; exit 0; }
M=$(echo "$M" | tr "a-f" "A-F")

first=$(( 0x${M:0:2} | 0x02 ))
last=$(( (0x${M:10:2} + 1) & 0xff ))
BT=$(printf '%02X:%s:%s:%s:%s:%02X' "$first" "${M:2:2}" "${M:4:2}" "${M:6:2}" "${M:8:2}" "$last")

for i in $(seq 1 30); do
    [ -e /sys/class/bluetooth/hci0 ] && break
    sleep 1
done
[ -e /sys/class/bluetooth/hci0 ] || { echo "no bluetooth controller"; exit 0; }

# The controller takes the address once and rejects it afterwards, so check
# before setting - otherwise a restart of this unit reports a failure for
# something that is already right.
now=$(btmgmt info 2>/dev/null | grep -m1 -oE "addr [0-9A-Fa-f:]{17}" | cut -d" " -f2 | tr "a-f" "A-F")
if [ "$now" = "$BT" ]; then
    echo "hci0 already $BT"
    exit 0
fi

if btmgmt --index 0 public-addr "$BT" >/dev/null 2>&1; then
    echo "hci0 set to $BT"
else
    # Not worth failing the boot over: Bluetooth still works, it just answers
    # to whatever generic address the firmware came with.
    echo "could not set the address, hci0 stays $now"
fi
exit 0
