#!/bin/bash
# Talk to the modem in the window it stays up.  Answers here separate "the modem
# is genuinely running mission mode" from "it reached AMSS and does nothing".
set -u
QMI=/dev/wwan0qmi0

until [ -e "$QMI" ]; do sleep 0.05; done
echo "QMIPROBE: port up" > /dev/kmsg
# the Sahara server floods the log once its channel goes away
pkill -f sahara_srv.py 2>/dev/null

for cmd in --dms-get-ids \
           --dms-get-manufacturer \
           --dms-get-model \
           --dms-get-revision \
           --dms-get-operating-mode \
           --uim-get-card-status \
           --nas-get-signal-info \
           --nas-get-serving-system; do
    echo "=========== $cmd"
    echo "QMIPROBE: $cmd" > /dev/kmsg
    timeout 4 qmicli -d "$QMI" $cmd 2>&1 | head -40
done
echo "QMIPROBE: done" > /dev/kmsg
