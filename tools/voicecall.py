#!/usr/bin/env python3
"""Place a voice call through the QMI Voice service.

qmicli has no dial command, but the modem lists 0x0020 (dial), 0x0021 (end) and
0x0022 (answer) among its supported messages, so we send them ourselves.

Signalling only: audio for this modem travels on a separate MHI channel
(mhi_chan@80 "AUDIO_VOICE_0" in the stock device tree) and then through the SoC's
audio path, none of which is wired up here.  The far end will ring; nobody will
be able to hear anything.
"""
import ctypes, struct, subprocess, sys, time

VOICE_SERVICE = 9
VOICE_DIAL_CALL = 0x0020
VOICE_END_CALL = 0x0021

libqrtr = ctypes.CDLL("libqrtr.so.1")


def find_service(service):
    out = subprocess.run(["qrtr-lookup"], capture_output=True, text=True, timeout=15).stdout
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 5 and f[0].isdigit() and int(f[0]) == service:
            return int(f[3]), int(f[4])
    return None, None


class Qmi:
    def __init__(self, node, port):
        self.sock = libqrtr.qrtr_open(0)
        self.node, self.port = node, port
        self.txn = 0

    def send(self, msg_id, tlvs):
        self.txn = (self.txn + 1) & 0xFFFF
        body = b"".join(struct.pack("<BH", t, len(v)) + v for t, v in tlvs)
        req = struct.pack("<BHHH", 0, self.txn, msg_id, len(body)) + body
        libqrtr.qrtr_sendto(self.sock, self.node, self.port, req, len(req))

    def pump(self, seconds):
        buf = ctypes.create_string_buffer(4096)
        nn, np = ctypes.c_uint32(), ctypes.c_uint32()
        end = time.monotonic() + seconds
        seen = []
        while time.monotonic() < end:
            if libqrtr.qrtr_poll(self.sock, 500) <= 0:
                continue
            n = libqrtr.qrtr_recvfrom(self.sock, buf, 4096, ctypes.byref(nn), ctypes.byref(np))
            if n <= 0:
                continue
            r = buf.raw[:n]
            typ, txn, mid, ln = struct.unpack_from("<BHHH", r, 0)
            tlvs, off = {}, 7
            while off + 3 <= len(r):
                t, l = struct.unpack_from("<BH", r, off)
                tlvs[t] = r[off + 3:off + 3 + l]
                off += 3 + l
            print("  << type=%d msg=0x%04x %s" %
                  (typ, mid, {k: v.hex() for k, v in tlvs.items()}), flush=True)
            seen.append((typ, mid, tlvs))
        return seen


def main():
    number = sys.argv[1]
    hold = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    node, port = find_service(VOICE_SERVICE)
    if node is None:
        print("voice service not found")
        return 1
    print("Voice at node %d port %d" % (node, port), flush=True)
    q = Qmi(node, port)

    print("dialling %s" % number, flush=True)
    q.send(VOICE_DIAL_CALL, [(0x01, number.encode()), (0x10, bytes([0x00]))])
    seen = q.pump(6)

    call_id = None
    for typ, mid, tlvs in seen:
        if typ == 2 and mid == VOICE_DIAL_CALL:
            if 0x02 in tlvs and struct.unpack("<HH", tlvs[0x02][:4])[0] != 0:
                print("dial rejected: %r" % (struct.unpack("<HH", tlvs[0x02][:4]),))
            if 0x10 in tlvs:
                call_id = tlvs[0x10][0]
                print("call id %d" % call_id, flush=True)

    if call_id is None:
        print("no call id, nothing to hang up")
        return 1

    print("ringing for %d s" % hold, flush=True)
    q.pump(hold)
    print("hanging up", flush=True)
    q.send(VOICE_END_CALL, [(0x01, bytes([call_id]))])
    q.pump(4)
    return 0


if __name__ == "__main__":
    sys.exit(main())
