#!/usr/bin/env python3
"""Poll the modem's side of the esoc handshake.

tlmm 1 = mdm2ap_errfatal, tlmm 3 = mdm2ap_status (names from the stock
qcom,mdm0 node).  Read only - the lines are inputs and unclaimed.
"""
import subprocess, time

CHIP = "gpiochip3"
LINES = {"1": "mdm2ap_errfatal", "3": "mdm2ap_status"}
TICK = 0.1


TAG = "GPIOWATCH"
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


def read():
    try:
        out = subprocess.run(["gpioget", "-c", CHIP] + list(LINES),
                             capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "read failed: %s" % e
    return out.stdout.strip() or ("error: " + out.stderr.strip())


def main():
    prev = None
    while True:
        cur = read()
        if cur != prev:
            log(cur)
            prev = cur
        time.sleep(TICK)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
