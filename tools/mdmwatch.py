#!/usr/bin/env python3
"""Watch the SDX55's boot state registers while mhi_pci_generic drives it.

Reads only.  BAR0 is unassigned until mhi_pci_claim() runs and reads back as
all-ones, so wait for a plausible BHI offset rather than for the mmap to
succeed.  Polls every 2 ms - the modem settles its execution environment within
milliseconds of the last Sahara image, so a coarser tick would step over it.
"""
import mmap, os, struct, sys, time

DEV = "/sys/bus/pci/devices/0002:01:00.0"
EE = {0: "PBL", 1: "SBL", 2: "AMSS", 3: "RDDM", 4: "WFW", 5: "PTHRU",
      6: "EDL", 7: "FP", 8: "MAX_SUPPORTED", 9: "DISABLE_TRANS",
      10: "NOT_SUPPORTED"}
TICK = 0.002
HEARTBEAT = 5.0
PWR_TICK = 0.02


TAG = "MDMWATCH"
try:
    _kmsg = open("/dev/kmsg", "w")
except OSError:
    _kmsg = None


def log(msg):
    line = "[%.4f] %s" % (time.monotonic(), msg)
    print(line, flush=True)
    # ramoops keeps the kernel console across a hang; a file on ext4 does not
    if _kmsg is not None:
        try:
            _kmsg.write("%s: %s\n" % (TAG, line))
            _kmsg.flush()
        except OSError:
            pass


def link():
    try:
        with open(DEV + "/current_link_speed") as f:
            speed = f.read().strip()
        with open(DEV + "/current_link_width") as f:
            width = f.read().strip()
        return "%s x%s" % (speed, width)
    except OSError as e:
        return "unreadable (%d)" % (e.errno or 0)


def power():
    """Runtime-PM view of the device.  The pci_generic probe tail arms a 2 s
    autosuspend and a 2 s health-check timer; if either of them is what takes
    the link down, the transition shows up here before the link goes."""
    out = []
    for name in ("runtime_status", "runtime_enabled", "runtime_suspended_time"):
        try:
            with open(DEV + "/power/" + name) as f:
                out.append(f.read().strip())
        except OSError as e:
            out.append("err%d" % (e.errno or 0))
    return "runtime %s/%s suspended_ms=%s" % tuple(out)


def wait_for_bhi():
    """Return (mmap, bhi_offset) once the BAR carries something believable."""
    while True:
        m = fd = None
        try:
            fd = os.open(DEV + "/resource0", os.O_RDWR | os.O_SYNC)
            m = mmap.mmap(fd, 0x1000, offset=0)
            bhi = struct.unpack_from("<I", m, 0x28)[0]
            if bhi != 0xffffffff and 0 < bhi < 0x1000 - 0x30:
                os.close(fd)
                return m, bhi
        except (OSError, ValueError, struct.error):
            pass
        if m is not None:
            m.close()
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        time.sleep(0.005)


def main():
    log("waiting for BAR0 to carry a BHI pointer")
    m, bhi = wait_for_bhi()
    log("BHI base 0x%x, link %s" % (bhi, link()))

    prev = None
    last_link = link()
    last_power = power()
    last_pwr_poll = 0.0
    log("power at start: %s" % last_power)
    last_beat = 0.0
    while True:
        try:
            ee = struct.unpack_from("<I", m, bhi + 0x28)[0]
            bhi_status = struct.unpack_from("<I", m, bhi + 0x2c)[0]
            mhistatus = struct.unpack_from("<I", m, 0x48)[0]
        except (ValueError, struct.error):
            time.sleep(TICK)
            continue

        cur = (ee, bhi_status, mhistatus)
        now = time.monotonic()
        if cur != prev:
            log("EE=%d (%s)  BHI_STATUS=0x%08x  MHISTATUS=0x%08x"
                % (ee, EE.get(ee, "?"), bhi_status, mhistatus))
            prev = cur
            last_beat = now
        elif now - last_beat >= HEARTBEAT:
            log("still EE=%d (%s)  MHISTATUS=0x%08x  link %s"
                % (ee, EE.get(ee, "?"), mhistatus, link()))
            last_beat = now

        cur_link = link()
        if cur_link != last_link:
            log("link: %s -> %s" % (last_link, cur_link))
            last_link = cur_link

        # sysfs is far more expensive than the mmap reads, so poll it coarser
        if now - last_pwr_poll >= PWR_TICK:
            last_pwr_poll = now
            cur_power = power()
            if cur_power != last_power:
                log("power: %s -> %s" % (last_power, cur_power))
                last_power = cur_power

        time.sleep(TICK)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
