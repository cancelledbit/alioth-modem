#!/bin/bash
# One AMSS run with both host-side killers disabled.
#
#   sdx_health=0  the two-second health check still looks and still prints what
#                 it saw, but never starts recovery.  Recovery is what took the
#                 link down and, through the bandwidth ring, hung the machine.
#   sdx_rpm=0     no runtime suspend, so the host cannot be the one that put the
#                 modem to sleep.
#
# Everything the watchers print also goes to /dev/kmsg, so ramoops keeps it if
# the box dies anyway.
set -u

STAMP=$(date +%Y%m%d-%H%M%S)
DIR=/root/logs/$STAMP
mkdir -p "$DIR"
ln -sfn "$DIR" /root/logs/last
echo "logs in $DIR"

rm -f /sys/fs/pstore/* 2>/dev/null
dmesg -C
setsid nohup dmesg -w                      > "$DIR/dmesg.log"     2>&1 &
setsid nohup python3 -u /root/mdmwatch.py  > "$DIR/mdmwatch.log"  2>&1 &
setsid nohup python3 -u /root/gpiowatch.py > "$DIR/gpiowatch.log" 2>&1 &

# The modem looks host files up over TFTP on QRTR while it boots, so this has
# to be running before it does - starting it afterwards is too late.
mkdir -p /readwrite
setsid nohup /usr/bin/tqftpserv > "$DIR/tqftp.log" 2>&1 &
# protection domain registry: the modem looks domains up while it starts
setsid nohup /usr/bin/pd-mapper > "$DIR/pdmapper.log" 2>&1 &
modprobe qrtr_mhi
modprobe mhi_wwan_ctrl
setsid nohup python3 -u /root/sahara_srv.py > "$DIR/sahara.log" 2>&1 &
sleep 1

echo "RUN: loading mhi_pci_generic sdx_health=0 sdx_rpm=0" > /dev/kmsg
setsid nohup python3 -u /root/efs_srv.py > "$DIR/efs.log" 2>&1 &
setsid nohup bash /root/diagboot.sh > "$DIR/diagboot.log" 2>&1 &
modprobe mhi_pci_generic sdx_health=0 sdx_rpm=0

# Mission mode landed at ~20 s after modprobe last time and the device stopped
# answering 16 s later; 240 s leaves room to see whether it ever comes back.
for i in $(seq 1 120); do
    sleep 1
    if [ $((i % 20)) -eq 0 ]; then
        echo "RUN: t=${i}s wwan=$(ls /dev/wwan* 2>/dev/null | tr '\n' ' ')" > /dev/kmsg
        echo "t=${i}s  wwan: $(ls /dev/wwan* 2>/dev/null | tr '\n' ' ')"
    fi
done

echo "RUN: over" > /dev/kmsg
pkill -x dmesg
pkill -f mdmwatch.py
pkill -f gpiowatch.py
pkill -f sahara_srv.py
sleep 1
wc -l "$DIR"/*.log
echo "DONE $DIR"
