#!/bin/bash
# Put the postmarketOS rootfs we built onto the phone's sda35 - the partition
# that currently holds Arch's /home (287 MB, already backed up to
# ~/work/alioth-backup/home-backup.tar.gz).
#
# Arch itself stays untouched on sda37, and its boot entries stay in the menu,
# so a bad first boot is one reboot away from the old system.
set -eu

# The phone as it is reachable now, still running the system being replaced.
PHONE=${PHONE:-root@172.16.42.1}
# Where the rootfs pmbootstrap built lives.  ORB is for the case where
# pmbootstrap runs inside an OrbStack machine on a Mac; leave it empty to run
# the commands locally.
ORB=${ORB:-}
R=${ROOTFS:-$HOME/.local/var/pmbootstrap/chroot_rootfs_xiaomi-alioth}
# The partition that gets the rootfs.  sda35 is "userdata" - on a phone set up
# the way ours was, that is the 80 GB partition Arch used for /home.
PART=${PART:-/dev/sda35}
# How to become root where pmbootstrap lives - Alpine uses doas, others sudo.
SU=${SU:-doas}
KEY=$(cat "${SSH_KEY:-$HOME/.ssh/id_rsa.pub}")

# run a command where pmbootstrap lives
pmb_host () { if [ -n "$ORB" ]; then orb -m "$ORB" "$@"; else "$@"; fi; }

say () { printf '\n== %s\n' "$*"; }

say "checking the phone"
ssh -o ConnectTimeout=8 "$PHONE" "test -b $PART && blkid -o value -s PARTLABEL $PART"

say "freeing sda35"
# A plain umount fails here with EBUSY, and not because something is using the
# filesystem: nothing has a file open on it, nothing has its cwd there.  It is
# the systemd services running with ProtectHome= - each of them carries its own
# copy of the /home mount inside a private mount namespace, and that keeps the
# mount referenced.  A lazy umount detaches it from our namespace, which is all
# mkfs needs; the data is 287 MB of idle files, already backed up, and synced
# just below.
ssh "$PHONE" 'systemctl stop sddm 2>/dev/null || true
              sleep 2
              sync
              if mountpoint -q /home; then
                  umount /home 2>/dev/null || umount -l /home
              fi
              mountpoint -q /home && { echo "still mounted"; exit 1; }
              echo "sda35 is free"'

say "making the filesystem"
ssh "$PHONE" "mkfs.ext4 -F -L pmOS_root $PART >/dev/null 2>&1
              mkdir -p /mnt/pmos
              mount $PART /mnt/pmos
              df -h /mnt/pmos | tail -1"

say "unmounting the build chroot"
# pmbootstrap leaves /proc, /sys and a dozen other mounts live inside the
# chroot.  tar walks into them, and files under /proc change size while being
# read, so the archive comes out with headers that do not match their data -
# the receiving tar then reports "Skipping to next header" and gives up.
pmb_host pmbootstrap shutdown >/dev/null 2>&1 || true
left=$(pmb_host sh -c 'mount | grep -c chroot_rootfs_xiaomi-alioth' || true)
[ "$left" = "0" ] || { echo "chroot still has $left mounts, not safe to tar"; exit 1; }

say "streaming the rootfs (about 5.8 GB, takes a few minutes)"
pmb_host "$SU" tar --numeric-owner \
    --exclude=./proc/* --exclude=./sys/* --exclude=./dev/pts/* \
    -C "$R" -cf - . \
    | ssh "$PHONE" 'tar -xf - -C /mnt/pmos && echo "unpacked"'

say "ssh key and fstab"
ssh "$PHONE" "mkdir -p /mnt/pmos/root/.ssh /mnt/pmos/home/user/.ssh
              printf '%s\n' '$KEY' > /mnt/pmos/root/.ssh/authorized_keys
              printf '%s\n' '$KEY' > /mnt/pmos/home/user/.ssh/authorized_keys
              chmod 700 /mnt/pmos/root/.ssh /mnt/pmos/home/user/.ssh
              chmod 600 /mnt/pmos/root/.ssh/authorized_keys /mnt/pmos/home/user/.ssh/authorized_keys
              chown -R 10000:10000 /mnt/pmos/home/user/.ssh
              mkdir -p /mnt/pmos/efi
              grep -q 'PARTLABEL=esp' /mnt/pmos/etc/fstab ||
                  printf 'PARTLABEL=esp\t/efi\tvfat\tdefaults,nofail\t0 2\n' >> /mnt/pmos/etc/fstab"

say "apk signing keys"
# pmbootstrap wipes /etc/apk/keys when it finishes the rootfs - it removes its
# own temporary build key and takes the distribution keys with it.  Without them
# every repository reads as UNTRUSTED and apk refuses to install anything.
ssh "$PHONE" 'mkdir -p /mnt/pmos/etc/apk/keys
              cp /mnt/pmos/usr/share/apk/keys/*.rsa.pub /mnt/pmos/etc/apk/keys/ 2>/dev/null
              cp /mnt/pmos/usr/share/apk/keys/aarch64/*.rsa.pub /mnt/pmos/etc/apk/keys/ 2>/dev/null
              ls /mnt/pmos/etc/apk/keys | wc -l'

say "kernel and boot entry"
# Note the absence of cpuidle.off=1, which the Arch entries carry: it was a
# leftover from a diagnosis that came to nothing, and with cpuidle disabled the
# machine enters s2idle and never comes back out.  Without it suspend and
# resume work, modem included.
ssh "$PHONE" 'cp /mnt/pmos/boot/vmlinuz /efi/Image-pmos
              cp /mnt/pmos/boot/sm8250-xiaomi-alioth.dtb /efi/sm8250-xiaomi-alioth-pmos.dtb
              cat > /efi/loader/entries/03-pmos.conf <<EOF
title      postmarketOS (Plasma Mobile)
sort-key   03-pmos
linux      /Image-pmos
devicetree /sm8250-xiaomi-alioth-pmos.dtb
options    root=PARTLABEL=userdata rw rootwait console=tty0 console=ttyMSM0,115200 loglevel=4
EOF
              sync
              ls -la /efi/Image-pmos /efi/loader/entries/'

say "done - reboot and pick \"postmarketOS\" in the boot menu"
echo "user: user / password: alioth   (root login by key)"
