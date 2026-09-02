#!/usr/bin/env python3
"""Watch the modem's voice audio channel during a call.

The SDX55 has an MHI channel pair for call audio - 80 and 81, named
AUDIO_VOICE_0.  Downstream hands it straight to the ADSP through mhi_satellite
and the call is then run by q6voice, neither of which exists in mainline.  The
question this answers is whether the channel carries anything the host can use
on its own: raw PCM would mean in-call audio needs no DSP work at all, just a
bridge to ALSA.

Run it, place or answer a call, and watch.  It prints how much arrives and what
the first bytes look like, so the shape of the data is visible even if the
meaning is not.

    voiceprobe.py [/dev/wwan0mbim0] [seconds]
"""
import os
import sys
import time

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/wwan0mbim0"
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 120


def main():
    try:
        fd = os.open(PORT, os.O_RDWR | os.O_NONBLOCK)
    except OSError as e:
        print("cannot open %s: %s" % (PORT, e))
        return 1

    print("listening on %s for %d s - place a call now" % (PORT, SECONDS))
    start = time.time()
    total = 0
    chunks = 0
    first = None

    while time.time() - start < SECONDS:
        try:
            buf = os.read(fd, 4096)
        except BlockingIOError:
            time.sleep(0.02)
            continue
        except OSError as e:
            print("read failed: %s" % e)
            break
        if not buf:
            time.sleep(0.02)
            continue

        total += len(buf)
        chunks += 1
        if first is None:
            first = buf
            print("first %d bytes at %+.2f s:" % (len(buf), time.time() - start))
            print("  " + buf[:64].hex(" "))
        if chunks % 50 == 0:
            print("  %d chunks, %d bytes, %.1f kB/s"
                  % (chunks, total, total / 1024 / (time.time() - start)))

    os.close(fd)
    if total:
        # 8 kHz 16-bit mono is 16 kB/s, 16 kHz is 32 kB/s - the rate alone says
        # a lot about whether this is PCM.
        print("done: %d chunks, %d bytes, %.1f kB/s average"
              % (chunks, total, total / 1024 / SECONDS))
    else:
        print("done: nothing arrived - the channel is open but silent, which "
              "means the modem is not putting the call on it by itself")
    return 0


if __name__ == "__main__":
    sys.exit(main())
