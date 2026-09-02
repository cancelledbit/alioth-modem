#!/usr/bin/env python3
"""Receive SMS through the modem's QMI Wireless Messaging Service.

The modem's routes are set to transfer-only, so incoming messages are handed to
a registered client rather than stored.  Register for the event report and sit
on the socket; QMI indications arrive at the same port the request went out on.
"""
import ctypes, struct, subprocess, sys, time

WMS_SERVICE = 5
WMS_SET_EVENT_REPORT = 0x0001
WMS_LIST_MESSAGES = 0x0031
WMS_RAW_READ = 0x0022
WMS_SEND_ACK = 0x0037

libqrtr = ctypes.CDLL("libqrtr.so.1")
txn_counter = 100


def find_service(service):
    out = subprocess.run(["qrtr-lookup"], capture_output=True, text=True, timeout=15).stdout
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 5 and f[0].isdigit() and int(f[0]) == service:
            return int(f[3]), int(f[4])
    return None, None


def qmi(msg_id, tlvs, txn, type_=0):
    body = b"".join(struct.pack("<BH", t, len(v)) + v for t, v in tlvs)
    return struct.pack("<BHHH", type_, txn, msg_id, len(body)) + body


def tlvs_of(resp):
    out, off = {}, 7
    while off + 3 <= len(resp):
        t, ln = struct.unpack_from("<BH", resp, off)
        out[t] = resp[off + 3:off + 3 + ln]
        off += 3 + ln
    return out


def unpack7(data, udl):
    chars, acc, nbits = [], 0, 0
    for b in data:
        acc |= b << nbits
        nbits += 8
        while nbits >= 7 and len(chars) < udl:
            chars.append(chr(acc & 0x7F))
            acc >>= 7
            nbits -= 7
    return "".join(chars)


def digits_of(semi, count):
    out = []
    for b in semi:
        out.append(str(b & 0x0F))
        out.append(str(b >> 4))
    return "".join(out)[:count]


def decode_deliver(pdu, has_sca=False):
    """Decode enough of an SMS-DELIVER to show who wrote what.

    QMI hands the message over without the service centre address - unlike the
    PDU an AT modem would give you - so there is nothing to skip at the front.
    """
    i = 0
    if has_sca:
        i += 1 + pdu[0]
    first = pdu[i]; i += 1
    oa_len = pdu[i]; i += 1
    oa_type = pdu[i]; i += 1
    nbytes = (oa_len + 1) // 2
    sender = digits_of(pdu[i:i + nbytes], oa_len); i += nbytes
    if oa_type & 0x70 == 0x50:
        sender = "(alphanumeric)"
    pid = pdu[i]; i += 1
    dcs = pdu[i]; i += 1
    scts = pdu[i:i + 7]; i += 7
    udl = pdu[i]; i += 1
    ud = pdu[i:]
    when = "20%02x-%02x-%02x %02x:%02x:%02x" % tuple(
        ((b & 0x0F) << 4 | (b >> 4)) for b in scts[:6])
    if dcs & 0x0C == 0x08:
        text = ud[:udl].decode("utf-16-be", "replace")
    else:
        text = unpack7(ud, udl)
    return sender, when, text


def main():
    node, port = find_service(WMS_SERVICE)
    if node is None:
        print("WMS service not found")
        return 1
    print("WMS at node %d port %d" % (node, port), flush=True)

    sock = libqrtr.qrtr_open(0)
    if sock < 0:
        print("cannot open qrtr socket")
        return 1

    # TLV 0x10: report new MT messages
    req = qmi(WMS_SET_EVENT_REPORT, [(0x10, bytes([1]))], txn=1)
    libqrtr.qrtr_sendto(sock, node, port, req, len(req))
    print("registered for incoming messages, listening", flush=True)

    buf = ctypes.create_string_buffer(8192)
    n_node = ctypes.c_uint32()
    n_port = ctypes.c_uint32()
    deadline = time.monotonic() + (float(sys.argv[1]) if len(sys.argv) > 1 else 300)
    while time.monotonic() < deadline:
        if libqrtr.qrtr_poll(sock, 1000) <= 0:
            continue
        n = libqrtr.qrtr_recvfrom(sock, buf, 8192, ctypes.byref(n_node), ctypes.byref(n_port))
        if n <= 0:
            continue
        resp = buf.raw[:n]
        typ, txn, msg_id, ln = struct.unpack_from("<BHHH", resp, 0)
        t = tlvs_of(resp)
        if typ == 4 and msg_id == 0x0001:          # event report indication
            raw = t.get(0x11)
            if raw and len(raw) >= 8:
                # ack_indicator(1) transaction_id(4) format(1) len(2) pdu
                ack_needed = raw[0]
                transaction = struct.unpack_from("<I", raw, 1)[0]
                fmt = raw[5]
                plen = struct.unpack_from("<H", raw, 6)[0]
                pdu = raw[8:8 + plen]
                try:
                    sender, when, text = decode_deliver(pdu)
                    print("\n=== SMS from %s at %s ===\n%s\n" % (sender, when, text), flush=True)
                except Exception as e:
                    print("could not decode: %s, raw %s" % (e, pdu.hex()), flush=True)
                # Without this the network keeps redelivering: the modem passes
                # the message on and waits for the client to take responsibility.
                if ack_needed:
                    global txn_counter
                    txn_counter += 1
                    ack = qmi(WMS_SEND_ACK,
                              [(0x01, struct.pack("<IBB", transaction, fmt, 1))],
                              txn=txn_counter)
                    libqrtr.qrtr_sendto(sock, node, port, ack, len(ack))
                    print("acknowledged transaction %d" % transaction, flush=True)
            else:
                print("indication, tlvs: %s" % {k: v.hex() for k, v in t.items()}, flush=True)
        else:
            print("<< type=%d msg=0x%04x tlvs=%s" %
                  (typ, msg_id, {k: v.hex()[:40] for k, v in t.items()}), flush=True)
    print("done listening", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
