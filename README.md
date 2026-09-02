# Modem support for the Poco F3 on a mainline kernel

Xiaomi Poco F3 / Redmi K40 / Mi 11X — codename **alioth** — on a mainline 6.15
kernel. This repository is what it took to make the modem work. It was written
against Arch Linux ARM and now also carries a full postmarketOS port: device,
kernel and firmware packages, so the phone can be installed rather than
assembled by hand.

What works now:

| | |
|---|---|
| Registration on the operator's network | LTE, tested on MTS and MegaFon |
| SMS | sending and receiving, including Cyrillic |
| Mobile data | ~34 Mbit/s, through NetworkManager and the shell |
| Voice calls | signalling only: the call connects, **there is no audio** |
| Everything above from the desktop | ModemManager sees the modem as an ordinary one |
| Suspend and resume | s2idle, modem still connected after waking |

The phone starts up with all of this by itself.

## Why this is not just "enable the driver"

The Snapdragon 870 has **no modem inside it**. The phone carries a separate
**Qualcomm SDX55** chip on PCIe, talking MHI, with no flash of its own: the
application processor feeds it the entire boot chain and hosts its filesystem.
Mainline knows how to talk to standalone SDX55 modem cards, but not to one wired
next to a SoC like this one.

Three things were missing, and none of them are documented anywhere:

1. **The EFS channel.** MHI channels 10/11 carry the modem's remote filesystem.
   Without them it reaches mission mode, answers nothing, and drops the PCIe
   link after exactly 16 seconds. Stock device trees declare the channels;
   mainline does not.

2. **The real NV.** The `efs*.bin` shipped next to the firmware images are
   placeholders — they literally say `IMGEFS- DUMMY-1` inside. A modem fed those
   comes up in factory-test mode with no IMEI. The real thing lives in the
   phone's `mdm1m9kefs1..3` partitions.

3. **TFTP over QRTR.** While starting, the modem fetches files from the host and
   says so plainly in its own log: `could not resolve remote host`. `tqftpserv`
   provides that service, but publishes it with an instance value the modem
   never looks for.

Each of those alone leaves the modem in `DeviceNotReady` forever, with no clue
as to why. The way out was to read the modem's own F3 log over DIAG — the modem
says what it is missing in plain words, but only while it is starting up. The
tool for that is in `tools/diagprobe.py`.

## Layout

```
kernel/patches/     six patches against 6.15 (device tree, MHI core,
                    mhi_pci_generic, wwan, pcie-qcom, and the platform bits
                    the phone needs at all)
userspace/          patches for ModemManager, tqftpserv and gmobile
services/           systemd units, the bring-up script, udev rules
tools/              the servers and probes: Sahara, EFS, data, SMS, DIAG,
                    a filesystem browser for the modem
pmaports/           the postmarketOS packages: kernel, device, firmware and
                    the modem userspace.  The files in them are symlinks into
                    services/ and tools/, so nothing is maintained twice
pmos-deploy.sh      puts a built postmarketOS rootfs onto the phone
install.sh          puts the userspace side in place on other distributions
```

## Installing

### postmarketOS

The packages build with an ordinary pmbootstrap checkout:

```sh
pmaports/install-into-pmaports.sh              # copies the aports in
pmbootstrap config device xiaomi-alioth
pmbootstrap config ui plasma-mobile
pmbootstrap config kernel alioth
```

The firmware package needs a tarball of the blobs, which are not in this
repository — they are Xiaomi's and every handset already carries its own copy.
Take them off the phone:

```sh
device/testing/firmware-xiaomi-alioth/make-tarball.sh root@<phone>
pmbootstrap checksum linux-postmarketos-alioth device-xiaomi-alioth \
                     firmware-xiaomi-alioth alioth-modem
pmbootstrap install --no-image --filesystem ext4
```

Two Alpine packages need patching as well, and are not vendored here:

```sh
pmbootstrap aportgen --fork-alpine tqftpserv modemmanager
# drop userspace/tqftpserv/*.patch and userspace/modemmanager/*.patch into the
# two forked aports, add them to source=, and raise pkgrel.
# ModemManager also needs, in its APKBUILD:
#   options="!check"          three of its tests abort inside the build chroot
#   makedepends without $depends_dev - that is libmm-glib at the pkgrel this
#   build is about to produce, so with a raised pkgrel it does not exist yet
```

The stock bootloader rejects mainline boot images, so the phone boots through
Mu-Silicium UEFI in the `boot` partition and systemd-boot on an ESP; there is
nothing to flash. `pmos-deploy.sh` writes the rootfs onto a partition, drops in
a boot entry and copies the kernel across:

```sh
PHONE=root@<phone> PART=/dev/sda35 ./pmos-deploy.sh
```

### Other distributions

Build a kernel with `kernel/patches` applied, then:

```sh
sudo ./install.sh
```

The firmware and the modem's NV are copied out of the phone's own partitions on
the first boot — nothing proprietary is redistributed here. Then build the
userspace projects with the patches from `userspace/`, and reboot.

## What the patches do

**Kernel**

* `0001` — device tree: the `global` interrupt for `pcie2` that the mainline
  driver needs to notice the link coming up, plus the esoc handshake pins.
* `0002` — MHI core: bandwidth scaling (the modem refuses to leave the
  bootloader without it), a forced M3 suspend, and letting a device that is
  already in SBL be powered up again.
* `0003` — `mhi_pci_generic`: the SDX55-next-to-SM8250 device entry, the EFS,
  BL, DIAG, QMI, IPCR and data channels, ring polling for a board whose MSIs
  never arrive, the mission-mode suspend/resume cycle downstream performs, and
  the esoc and PMIC handling.
* `0004` — `mhi_wwan_ctrl`: expose the EFS channel.
* `0005` — `pcie-qcom`: link-down recovery, and the debugging that found it.
* `0006` — the rest of what the phone needs to boot at all: GPU, audio, PDR.

**Userspace**

* ModemManager — four fixes, all of general interest, not specific to this
  phone:
  * a dual-SIM modem reports **both** slots active, and the code picking the
    primary slot takes the last one it sees, so it settles on whichever slot
    happens to come last — including an empty one. It now prefers a slot that
    holds a card, judged by the ICCID being there at all, and only among equals
    the lowest logical slot;
  * a modem that reports a card status change while the SIM object is still
    being filled in has nothing cached to compare against, and ModemManager
    reads that as a SIM swap and reprobes for ever;
  * the `qcom-soc` plugin only accepts `ipa` and `bam-dmux` data interfaces and
    rejects anything on MHI;
  * without multiplexing ModemManager never binds the WDS client, and starting
    the session then fails — so on MHI multiplexing has to be the default, as it
    already is for IPA.
* tqftpserv — publish the service where this modem looks for it. `libqrtr`
  encodes the field as `instance << 8 | version`, so the upstream call yields 1
  on the wire while the modem asks for 3.
* gmobile — a display panel entry for this device, so Phosh knows the screen.
  Not needed on Plasma Mobile, which is what the postmarketOS port ships.

## Things that cost time

Each of these looked like a hardware problem and was not.

**The phone would not wake from sleep.** The boot entry carried
`cpuidle.off=1`, inherited from a diagnosis that had come to nothing. With
cpuidle disabled the machine enters s2idle and never returns — the journal
simply ends at "PM: suspend entry". Remove it and suspend works, modem
included: it comes back still registered and connected.

**The SIM application sat in `detected` for ever** and ModemManager gave up
with `sim-missing`, even though the card status said `present` and the PIN was
disabled. The card initialises only when the slot is power cycled, and only
once a provisioning session is bound to it. Power cycling before provisioning
changes nothing, which is why the order in `modem-up.sh` matters.

**ModemManager picked the empty slot.** A dual SIM modem powers both slots and
reports both as `active`, so the original code — which keeps the last one it
saw — chose at random, and our first patch, which preferred the lowest logical
slot, chose the dead card as soon as slot 1 was the broken one. It now prefers
a slot that actually holds a card, and only among equals the lowest slot.

**Every repository read as UNTRUSTED** after installing postmarketOS by hand:
pmbootstrap clears `/etc/apk/keys` when it finishes the rootfs, taking the
distribution keys with its own temporary build key. Copy them back from
`/usr/share/apk/keys`.

**`mount` guessed fuseblk** on the stock `modem_a` partition and failed. It is
vfat, and saying so with `-t vfat` is enough.

**qmicli is not in `libqmi`** on Alpine — the tools are in `qmi-utils`, and
without them the bring-up script dies halfway with `command not found`.

**The GPU firmware never arrived** because the device package depended on the
empty `firmware-xiaomi-alioth` metapackage rather than its subpackages, and
`linux-firmware-qcom` fails to install from the mirror. Plasma then renders on
the CPU and the phone feels broken. `a650_sqe.fw` and `a650_gmu.bin` are in the
firmware package now.

## Voice audio

The call connects; nobody can hear anything. Voice audio travels on MHI channel
80, and that channel is meant to be handed to the **ADSP**, not to the CPU:
frames go straight between the modem and the DSP. Creating that session needs
the q6voice stack (MVM, CVS, CVP over APR), which does not exist in mainline at
all. This is not specific to this phone — in-call audio works on no mainline
Qualcomm phone. Doing it means porting `mhi_satellite` and writing q6voice.

## Status of the patches

None of this has been sent upstream yet. The ModemManager fixes and the gmobile
device entry are ready to be; the kernel side still needs splitting into a
proper series with a changelog per patch. The MHI patches belong upstream rather
than in any fork — they are not about this phone. The device tree has nowhere to
go upstream yet: `sm8250-xiaomi-alioth.dts` exists only in the `nikroks/alioth`
branch of the mainlining fork, which is where the kernel package takes it from.

The patches carry no debugging: the tracing that found all of this, the dead-end
module knobs and the passive channel listener have been taken out, and what is
left has been built and run on the phone.

## Licence

GPL-2.0, the same as the kernel the patches are against. The scripts and the
servers under `tools/` are covered by it too.
