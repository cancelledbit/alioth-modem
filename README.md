# Modem support for the Poco F3 on a mainline kernel

Xiaomi Poco F3 / Redmi K40 / Mi 11X — codename **alioth** — running Arch Linux
ARM on a mainline 6.15 kernel. This repository is what it took to make the
modem work.

What works now:

| | |
|---|---|
| Registration on the operator's network | LTE, tested on MTS and MegaFon |
| SMS | sending and receiving, including Cyrillic |
| Mobile data | ~34 Mbit/s, through NetworkManager and the shell |
| Voice calls | signalling only: the call connects, **there is no audio** |
| Everything above from the desktop | ModemManager sees the modem as an ordinary one |

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
as to why. The way out was to read the modem's own F3 log — see
[docs/HANDOFF.md](docs/HANDOFF.md), sections 12.16 and 12.17.

## Layout

```
kernel/patches/     six patches against 6.15 (device tree, MHI core,
                    mhi_pci_generic, wwan, pcie-qcom, and the platform bits
                    the phone needs at all)
userspace/          patches for ModemManager, tqftpserv and gmobile
services/           systemd units, the bring-up script, udev rules
tools/              the servers and probes: Sahara, EFS, data, SMS, DIAG,
                    a filesystem browser for the modem
docs/HANDOFF.md     the full log of how this was worked out, including every
                    wrong turn - read this before changing anything
install.sh          puts the userspace side in place
```

## Installing

Build a kernel with `kernel/patches` applied, then:

```sh
sudo ./install.sh
```

It pulls the firmware and the modem's NV out of the phone's own partitions —
nothing proprietary is redistributed here. Then build the three userspace
projects with the patches from `userspace/`, and reboot.

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

* ModemManager — three fixes, all of general interest, not specific to this
  phone:
  * a dual-SIM modem reports **both** slots active, and the code picking the
    primary slot takes the last one it sees, so it settles on the second card,
    then decides the SIM was swapped and reprobes the modem forever;
  * the `qcom-soc` plugin only accepts `ipa` and `bam-dmux` data interfaces and
    rejects anything on MHI;
  * without multiplexing ModemManager never binds the WDS client, and starting
    the session then fails — so on MHI multiplexing has to be the default, as it
    already is for IPA.
* tqftpserv — publish the service where this modem looks for it. `libqrtr`
  encodes the field as `instance << 8 | version`, so the upstream call yields 1
  on the wire while the modem asks for 3.
* gmobile — a display panel entry for this device, so Phosh knows the screen.

## Voice audio

The call connects; nobody can hear anything. Voice audio travels on MHI channel
80, and that channel is meant to be handed to the **ADSP**, not to the CPU:
frames go straight between the modem and the DSP. Creating that session needs
the q6voice stack (MVM, CVS, CVP over APR), which does not exist in mainline at
all. This is not specific to this phone — in-call audio works on no mainline
Qualcomm phone. Doing it means porting `mhi_satellite` and writing q6voice.

## Status of the patches

None of this has been sent upstream yet. The ModemManager fixes and the gmobile
device entry are ready to be. The kernel side needs the debugging stripped out
first: `MHIDBG` prints, the `sdx_*` module knobs and the channel tap are a
workbench, not a patch series.
