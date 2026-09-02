#!/bin/sh
# Build the fw-alioth.tar.gz that this aport expects.
#
# The blobs are not in the repository on purpose: they are Xiaomi's, they weigh
# 21 MB, and every handset already carries its own copy.  Take them off a phone
# that still runs a working system - the stock one, or the Linux install that is
# being replaced - and hand the tarball to abuild.
#
#   ./make-tarball.sh root@10.15.19.82        pull over ssh
#   ./make-tarball.sh                         take them from the running phone
set -eu

SRC=/lib/firmware/qcom/sm8250/xiaomi/alioth
GPU=/lib/firmware/qcom
OUT=$(dirname "$0")/fw-alioth.tar.gz

if [ $# -ge 1 ]; then
	ssh "$1" "tar cf - -C $(dirname $SRC) $(basename $SRC)" | tar xf - -C /tmp
	ssh "$1" "tar cf - -C $GPU a650_sqe.fw a650_gmu.bin" | tar xf - -C "/tmp/$(basename $SRC)"
	tar czf "$OUT" -C /tmp "$(basename $SRC)"
	rm -rf "/tmp/$(basename $SRC)"
else
	tmp=$(mktemp -d)
	cp -r "$SRC" "$tmp/alioth"
	cp "$GPU"/a650_sqe.fw "$GPU"/a650_gmu.bin "$tmp/alioth/"
	tar czf "$OUT" -C "$tmp" alioth
	rm -rf "$tmp"
fi

ls -la "$OUT"
echo "now run: pmbootstrap checksum firmware-xiaomi-alioth"
