#!/bin/bash
# ath11k finds no board data with the real address here, so it invents one on
# every boot and the router sees a new client each time.  The address the phone
# was made with lives in the persist partition, as "wlan0=<12 hex digits>".
#
# Reading it needs no network interface, which matters: this runs before
# NetworkManager, and at that point ath11k has not probed yet and there is no
# wlan device to talk to.  So the address goes into a NetworkManager drop-in
# that matches the interface by name pattern, and NetworkManager applies it to
# whatever wireless interface turns up later.
set -u

# This runs early, before NetworkManager, and udev has not necessarily created
# the by-partlabel links yet - without waiting the script simply finds nothing
# and exits, leaving the invented address in place.
P=""
for i in $(seq 1 20); do
    P=$(readlink -f /dev/disk/by-partlabel/persist 2>/dev/null || true)
    [ -n "$P" ] && [ -b "$P" ] && break
    sleep 1
done
[ -n "$P" ] && [ -b "$P" ] || { echo "no persist partition"; exit 0; }
M=$(dd if="$P" bs=1M count=8 2>/dev/null | strings | grep -m1 -oE "wlan0=[0-9a-fA-F]{12}" | cut -d= -f2)
[ -n "$M" ] || { echo "no wlan mac in persist"; exit 0; }
MAC=$(echo "$M" | sed "s/../&:/g;s/:$//")

# Setting the address with "ip link" alone does not hold: NetworkManager puts
# back what the driver calls the permanent address, and on ath11k that is the
# invented one.  Only an explicit cloned-mac-address sticks.  This lives in
# /run rather than /etc because it is read out of the hardware every boot and
# differs on every handset.
CONF=/run/NetworkManager/conf.d/00-alioth-wifi-mac.conf
mkdir -p "$(dirname "$CONF")"
cat > "$CONF" <<CONFEOF
[device-alioth-wifi]
match-device=interface-name:wlan*
wifi.scan-rand-mac-address=no

[connection-alioth-wifi]
match-device=interface-name:wlan*
wifi.cloned-mac-address=$MAC
CONFEOF
echo "wifi mac $MAC written to $CONF"

# If the interface happens to exist already, set it directly as well - harmless
# when it does not, and it makes the address right even without NetworkManager.
IF=${1:-}
[ -n "$IF" ] || IF=$(for d in /sys/class/net/*/wireless; do
        [ -e "$d" ] && basename "$(dirname "$d")" && break
    done)
[ -n "$IF" ] || exit 0
ip link set dev "$IF" down 2>/dev/null
ip link set dev "$IF" address "$MAC" 2>/dev/null && echo "$IF set to $MAC"
ip link set dev "$IF" up 2>/dev/null
