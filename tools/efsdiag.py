#!/usr/bin/env python3
"""Browse the modem's EFS over DIAG.

The modem refuses to enable RF with DeviceNotReady and reports an empty radio
interface list, which points at its RF driver finding no configuration.  Its
configuration lives in EFS, and DIAG's file system subsystem can read it, so
this walks the tree and prints what is actually there.

Transport is the same HDLC framing as diagprobe.py.  Packets are
DIAG_SUBSYS_CMD_F (0x4b) with subsystem 0x13 (FS) and an EFS2 opcode.
"""
import binascii, os, struct, sys, time

PORT = "/dev/wwan0qcdm0"
SUBSYS_FS = 0x13
EFS2_HELLO, EFS2_OPEN, EFS2_CLOSE, EFS2_READ = 0, 2, 3, 4
EFS2_OPENDIR, EFS2_READDIR, EFS2_CLOSEDIR = 11, 12, 13
EFS2_WRITE = 5
EFS2_STAT = 15

# Qualcomm's own open flags, not the libc ones
O_RDONLY, O_WRONLY, O_RDWR, O_CREAT, O_TRUNC = 0, 1, 2, 0x100, 0x200


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def frame(payload):
    body = payload + struct.pack("<H", crc16(payload))
    out = bytearray()
    for b in body:
        if b in (0x7E, 0x7D):
            out += bytes([0x7D, b ^ 0x20])
        else:
            out.append(b)
    out.append(0x7E)
    return bytes(out)


def unframe(buf):
    packets, rest = [], b""
    for chunk in buf.split(b"\x7e"):
        rest = chunk
        if not chunk:
            continue
        out, esc = bytearray(), False
        for b in chunk:
            if esc:
                out.append(b ^ 0x20)
                esc = False
            elif b == 0x7D:
                esc = True
            else:
                out.append(b)
        if len(out) > 2:
            packets.append(bytes(out[:-2]))
    if buf.endswith(b"\x7e"):
        rest = b""
    return packets, rest


class Efs:
    def __init__(self, path=PORT):
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        self.buf = b""

    def call(self, opcode, payload=b"", timeout=3.0):
        os.write(self.fd, frame(struct.pack("<BBH", 0x4B, SUBSYS_FS, opcode) + payload))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data = os.read(self.fd, 0x4000)
            except BlockingIOError:
                time.sleep(0.004)
                continue
            except OSError:
                return None
            self.buf += data
            pkts, self.buf = unframe(self.buf)
            for p in pkts:
                if len(p) >= 4 and p[0] == 0x4B and p[1] == SUBSYS_FS:
                    got = struct.unpack_from("<H", p, 2)[0]
                    if got == opcode:
                        return p[4:]
        return None

    def hello(self):
        return self.call(EFS2_HELLO, struct.pack("<4I", 0x100, 0x100, 1024, 1024) + b"\0" * 16)

    def listdir(self, path):
        r = self.call(EFS2_OPENDIR, path.encode() + b"\0")
        if not r or len(r) < 8:
            return None, "no answer to opendir"
        dirp, err = struct.unpack_from("<2i", r, 0)
        if err != 0 or dirp == 0:
            return None, "opendir errno %d" % err
        out, seq = [], 1
        while True:
            r = self.call(EFS2_READDIR, struct.pack("<2I", dirp, seq))
            if not r or len(r) < 12:
                break
            _dirp, _seq, err = struct.unpack_from("<3i", r, 0)
            if err != 0:
                break
            # dirp, seqno, errno, entry_type, mode, size, atime, mtime, ctime,
            # then the name - so the name starts at 36, not right after size
            etype, mode, size = struct.unpack_from("<3i", r, 12)
            name = r[36:].split(b"\0")[0].decode("ascii", "replace")
            if not name:
                break
            out.append((etype, mode, size, name))
            seq += 1
            if seq > 4096:
                break
        self.call(EFS2_CLOSEDIR, struct.pack("<I", dirp))
        return out, None


    def write(self, path, data):
        """Careful, but not dangerous here: the modem gets a fresh EFS from the
        snapshot on every boot, so anything written is undone by a reboot."""
        r = self.call(EFS2_OPEN, struct.pack("<2I", O_RDWR, 0) + path.encode() + b"\0")
        if not r or len(r) < 8:
            return "no answer to open"
        fd, err = struct.unpack_from("<2i", r, 0)
        if err != 0 or fd < 0:
            return "open errno %d" % err
        off = 0
        while off < len(data):
            piece = data[off:off + 256]
            r = self.call(EFS2_WRITE, struct.pack("<iI", fd, off) + piece)
            if not r or len(r) < 16:
                self.call(EFS2_CLOSE, struct.pack("<i", fd))
                return "no answer to write at %d" % off
            _fd, _off, nwrote, err = struct.unpack_from("<2i2i", r, 0)
            if err != 0 or nwrote <= 0:
                self.call(EFS2_CLOSE, struct.pack("<i", fd))
                return "write errno %d after %d bytes" % (err, off)
            off += nwrote
        self.call(EFS2_CLOSE, struct.pack("<i", fd))
        return None

    def cat(self, path, limit=8192):
        r = self.call(EFS2_OPEN, struct.pack("<2I", 0, 0) + path.encode() + b"\0")
        if not r or len(r) < 8:
            return None, "no answer to open"
        fd, err = struct.unpack_from("<2i", r, 0)
        if err != 0 or fd < 0:
            return None, "open errno %d" % err
        data, off = b"", 0
        while off < limit:
            r = self.call(EFS2_READ, struct.pack("<iII", fd, 512, off))
            if not r or len(r) < 16:
                break
            _fd, _off, nread, err = struct.unpack_from("<2i2i", r, 0)
            if err != 0 or nread <= 0:
                break
            data += r[16:16 + nread]
            off += nread
            if nread < 512:
                break
        self.call(EFS2_CLOSE, struct.pack("<i", fd))
        return data, None


def walk(efs, path, depth, maxdepth):
    entries, err = efs.listdir(path)
    if err:
        print("%s  <%s>" % (path, err), flush=True)
        return
    for etype, mode, size, name in entries:
        kind = "dir " if etype == 1 else ("file" if etype == 0 else "t%-2d " % etype)
        full = (path.rstrip("/") + "/" + name)
        print("%s%s %8d  %s" % ("  " * depth, kind, size, full), flush=True)
        if etype == 1 and depth < maxdepth:
            walk(efs, full, depth + 1, maxdepth)


if __name__ == "__main__":
    efs = Efs()
    h = efs.hello()
    print("HELLO: %s" % (binascii.hexlify(h[:32]).decode() if h else "no answer"), flush=True)
    if len(sys.argv) > 3 and sys.argv[2] == "write":
        blob = binascii.unhexlify(sys.argv[3])
        err = efs.write(sys.argv[1], blob)
        print("write %s: %s" % (sys.argv[1], err or "ok, %d bytes" % len(blob)), flush=True)
        back, err = efs.cat(sys.argv[1])
        print("readback: %s" % (err or binascii.hexlify(back).decode()), flush=True)
        sys.exit(0)
    if len(sys.argv) > 2 and sys.argv[2] == "cat":
        for path in sys.argv[1].split(","):
            data, err = efs.cat(path)
            print("=== %s: %s" % (path, err or "%d bytes" % len(data)), flush=True)
            if data:
                try:
                    print(data.decode("utf-8"), flush=True)
                except UnicodeDecodeError:
                    print(binascii.hexlify(data).decode(), flush=True)
        sys.exit(0)
    root = sys.argv[1] if len(sys.argv) > 1 else "/"
    depth = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    walk(efs, root, 0, depth)
