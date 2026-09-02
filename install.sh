#!/bin/bash
# Install the userspace side of modem support on a Poco F3 (alioth) running a
# mainline kernel with the patches from kernel/patches applied.
#
# The kernel is not touched here - build it yourself and put the Image in place.
set -eu

PREFIX=${PREFIX:-/usr/local/lib/alioth-modem}
FW=/lib/firmware/qcom/sdx55m
RPROC_FW=/lib/firmware/qcom/sm8250/xiaomi/alioth

say () { printf '\n== %s\n' "$*"; }
part () { readlink -f "/dev/disk/by-partlabel/$1"; }

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
grep -q alioth /sys/firmware/devicetree/base/compatible 2>/dev/null || \
    echo "warning: this does not look like an alioth, continuing anyway"

say "firmware from the stock modem partition"
mkdir -p /mnt/modem "$FW" "$RPROC_FW"
mountpoint -q /mnt/modem || mount -o ro "$(part modem_a)" /mnt/modem
cp -f /mnt/modem/image/sdx55m/* "$FW"/
# The modem asks for these over TFTP while it starts; tqftpserv resolves
# /readonly/firmware/image/... next to the remoteproc firmware.
cp -rf /mnt/modem/image/modem_pr "$RPROC_FW"/
umount /mnt/modem

say "the modem's own NV out of the phone's flash"
# The efs*.bin shipped next to the images are placeholders - they say
# "IMGEFS- DUMMY-1" inside - and a modem fed those comes up in factory test mode
# with no IMEI.  The real thing lives in these partitions.
for n in 1 2 3; do
    dd if="$(part "mdm1m9kefs$n")" of="$FW/efs${n}_real.bin" bs=1M status=none
done
ls -la "$FW"/efs*_real.bin

say "tools"
mkdir -p "$PREFIX"
install -m 755 tools/*.py "$PREFIX"/
# The services look for them in /root by default, keep that working
for f in "$PREFIX"/*.py; do ln -sf "$f" "/root/$(basename "$f")"; done

say "services"
install -m 755 services/modem-up.sh /usr/local/bin/modem-up.sh
install -m 755 services/wlan-mac.sh /usr/local/bin/wlan-mac.sh
install -m 644 services/modem.service /etc/systemd/system/modem.service
install -m 644 services/wlan-mac.service /etc/systemd/system/wlan-mac.service
install -m 644 services/udev/77-mm-sdx55-qrtr.rules /etc/udev/rules.d/
mkdir -p /etc/NetworkManager/conf.d
install -m 644 services/NetworkManager-00-mac.conf /etc/NetworkManager/conf.d/00-mac.conf
echo "note: put your own Wi-Fi MAC into /etc/NetworkManager/conf.d/00-mac.conf"

say "keeping the modem driver out of autoload"
# The service loads it in the right order, after the firmware servers exist.
printf 'blacklist mhi_pci_generic\n' > /etc/modprobe.d/mhi-manual.conf

say "enabling"
udevadm control --reload
systemctl daemon-reload
systemctl enable ModemManager wlan-mac.service modem.service

cat <<'MSG'

Done.  Still to do by hand, because they are separate projects:

  * qrtr userspace   - https://github.com/andersson/qrtr
                       meson setup build --prefix=/usr && ninja -C build install
  * tqftpserv        - https://github.com/linux-msm/tqftpserv
                       apply userspace/tqftpserv/*.patch first, or the modem
                       will never find it and will sit in DeviceNotReady
  * ModemManager     - apply userspace/modemmanager/*.patch and rebuild;
                       replacing /usr/bin/ModemManager and
                       /usr/lib/ModemManager/libmm-plugin-qcom-soc.so is enough

Then reboot.  "journalctl -u modem" shows the bring-up.
MSG
