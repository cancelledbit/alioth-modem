#!/bin/bash
# Install the userspace side of modem support on a Poco F3 (alioth) running a
# mainline kernel with the patches from kernel/patches applied.
#
# This is the path for distributions other than postmarketOS - on postmarketOS
# the same files are packaged, see pmaports/ and the README.
#
# The kernel is not touched here - build it yourself and put the Image in place.
set -eu

PREFIX=/usr/share/alioth-modem

say () { printf '\n== %s\n' "$*"; }

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
grep -q alioth /sys/firmware/devicetree/base/compatible 2>/dev/null || \
    echo "warning: this does not look like an alioth, continuing anyway"

say "tools"
mkdir -p "$PREFIX"
install -m 755 tools/*.py "$PREFIX"/

say "services"
install -m 755 services/modem-up.sh              /usr/bin/alioth-modem-up
install -m 755 services/wlan-mac.sh              /usr/bin/alioth-wlan-mac
install -m 755 services/sim-provision.sh         /usr/bin/alioth-sim-provision
install -m 755 services/sim-watch.sh             /usr/bin/alioth-sim-watch
install -m 755 services/bt-addr.sh               /usr/bin/alioth-bt-addr
install -m 755 services/alioth-modem-firmware.sh /usr/bin/alioth-modem-firmware
install -m 644 services/alioth-modem.service          /etc/systemd/system/
install -m 644 services/alioth-modem-firmware.service /etc/systemd/system/
install -m 644 services/alioth-wlan-mac.service       /etc/systemd/system/
install -m 644 services/alioth-sim-watch.service      /etc/systemd/system/
install -m 644 services/alioth-bt-addr.service        /etc/systemd/system/
install -m 644 services/udev/77-mm-sdx55-qrtr.rules   /etc/udev/rules.d/
install -Dm644 services/pd-mapper.service.d/10-alioth-retry.conf \
    /etc/systemd/system/pd-mapper.service.d/10-alioth-retry.conf
mkdir -p /var/lib/alioth-modem

say "keeping the modem driver out of autoload"
# The service loads it in the right order, after the firmware servers exist.
printf 'blacklist mhi_pci_generic\n' > /etc/modprobe.d/mhi-manual.conf

say "enabling"
udevadm control --reload
systemctl daemon-reload
systemctl enable ModemManager alioth-modem-firmware.service alioth-modem.service \
    alioth-wlan-mac.service alioth-sim-watch.service \
    alioth-bt-addr.service

cat <<'MSG'

Done.  The firmware and the modem's own NV are copied out of the phone's
partitions by alioth-modem-firmware.service on the first boot, so nothing else
has to be fetched.

Still to do by hand, because they are separate projects:

  * qrtr userspace   - https://github.com/andersson/qrtr
                       meson setup build --prefix=/usr && ninja -C build install
  * tqftpserv        - https://github.com/linux-msm/tqftpserv
                       apply userspace/tqftpserv/*.patch first, or the modem
                       will never find it and will sit in DeviceNotReady
  * ModemManager     - apply userspace/modemmanager/*.patch and rebuild;
                       replacing /usr/bin/ModemManager and
                       /usr/lib/ModemManager/libmm-plugin-qcom-soc.so is enough
  * qmicli           - from libqmi; the bring-up script drives the modem with it

Then reboot.  "journalctl -u alioth-modem" shows the bring-up.
MSG
