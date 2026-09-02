#!/usr/bin/env python3
"""Send an SMS through the modem's QMI Wireless Messaging Service.

qmicli cannot send: its WMS support stops at routes.  ModemManager could, but it
does not recognise this modem - it wants a net device on the QRTR bus and ours is
on MHI.  So talk to the service directly: QMI over QRTR is just a 7-byte header
plus TLVs sent to the service's node and port.
"""
import ctypes, struct, subprocess, sys

WMS_SERVICE = 5
WMS_RAW_SEND = 0x0020

libqrtr = ctypes.CDLL("libqrtr.so.1")
libqrtr.qrtr_open.restype = ctypes.c_int
libqrtr.qrtr_sendto.restype = ctypes.c_int
libqrtr.qrtr_recvfrom.restype = ctypes.c_int


def find_service(service):
    out = subprocess.run(["qrtr-lookup"], capture_output=True, text=True, timeout=15).stdout
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 5 and f[0].isdigit() and int(f[0]) == service:
            return int(f[3]), int(f[4])
    return None, None


def semi_octets(number):
    """Phone digits go out nibble-swapped, odd counts padded with F."""
    digits = "".join(c for c in number if c.isdigit())
    if len(digits) % 2:
        digits += "F"
    out = bytearray()
    for i in range(0, len(digits), 2):
        out.append((int(digits[i + 1], 16) << 4) | int(digits[i], 16))
    return len([c for c in number if c.isdigit()]), bytes(out)


def pack7(text):
    """GSM 03.38 default alphabet, seven bits per character."""
    bits = ""
    for ch in reversed(text):
        bits += format(ord(ch) & 0x7F, "07b")
    bits = bits[::-1]  # keep character order, build the septet stream
    septets = [format(ord(c) & 0x7F, "07b") for c in text]
    stream = "".join(reversed(septets))
    out = bytearray()
    # pack septets little-endian, the way GSM does it
    acc, nbits = 0, 0
    for c in text:
        acc |= (ord(c) & 0x7F) << nbits
        nbits += 7
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8
    if nbits:
        out.append(acc & 0xFF)
    return len(text), bytes(out)


def submit_pdu(number, text):
    ndigits, addr = semi_octets(number)
    udl, ud = pack7(text)
    tpdu = bytes([0x11, 0x00, ndigits, 0x91]) + addr + bytes([0x00, 0x00, 0xAA, udl]) + ud
    return b"\x00" + tpdu          # no SC address: use the one from the SIM


def qmi_request(msg_id, tlvs, txn=1):
    body = b"".join(struct.pack("<BH", t, len(v)) + v for t, v in tlvs)
    return struct.pack("<BHHH", 0, txn, msg_id, len(body)) + body


def main():
    number, text = sys.argv[1], sys.argv[2]
    node, port = find_service(WMS_SERVICE)
    if node is None:
        print("WMS service not found on the qrtr bus")
        return 1
    print("WMS at node %d port %d" % (node, port))

    pdu = submit_pdu(number, text)
    print("PDU: %s" % pdu.hex())

    sock = libqrtr.qrtr_open(0)
    if sock < 0:
        print("cannot open qrtr socket")
        return 1

    payload = struct.pack("<BH", 0x06, len(pdu)) + pdu   # 0x06 = GSM/WCDMA
    req = qmi_request(WMS_RAW_SEND, [(0x01, payload)])
    if libqrtr.qrtr_sendto(sock, node, port, req, len(req)) < 0:
        print("send failed")
        return 1

    buf = ctypes.create_string_buffer(4096)
    n_node = ctypes.c_uint32()
    n_port = ctypes.c_uint32()
    for _ in range(40):
        if libqrtr.qrtr_poll(sock, 500) <= 0:
            continue
        n = libqrtr.qrtr_recvfrom(sock, buf, 4096, ctypes.byref(n_node), ctypes.byref(n_port))
        if n <= 0:
            continue
        resp = buf.raw[:n]
        print("reply from %d:%d: %s" % (n_node.value, n_port.value, resp.hex()))
        # TLV 0x02 carries {result, error}; 0,0 means the network took it
        off = 7
        while off + 3 <= len(resp):
            t, ln = struct.unpack_from("<BH", resp, off)
            val = resp[off + 3:off + 3 + ln]
            if t == 0x02 and ln >= 4:
                result, err = struct.unpack("<HH", val[:4])
                print("result=%d error=%d %s" % (result, err,
                      "SENT" if result == 0 else "FAILED"))
            elif t == 0x01 and ln >= 2:
                print("message reference: %d" % struct.unpack("<H", val[:2])[0])
            off += 3 + ln
        return 0
    print("no reply")
    return 1


if __name__ == "__main__":
    sys.exit(main())
