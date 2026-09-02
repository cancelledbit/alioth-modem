#!/bin/sh
# Copy these aports into a pmaports checkout so pmbootstrap can build them.
#
# The files here are symlinks into ../services, ../tools and ../kernel/patches,
# so that the same script is not maintained twice - once for postmarketOS and
# once for everyone else.  pmbootstrap only ever looks inside its own pmaports
# checkout, where those links would dangle, so they are dereferenced on the way
# in with cp -L.
set -eu

PMAPORTS=${1:-$HOME/.local/var/pmbootstrap/cache_git/pmaports}
HERE=$(cd "$(dirname "$0")" && pwd)

[ -f "$PMAPORTS/pmaports.cfg" ] || {
	echo "not a pmaports checkout: $PMAPORTS"
	echo "usage: $0 [path-to-pmaports]"
	exit 1
}

for a in device/testing/linux-postmarketos-alioth \
	 device/testing/device-xiaomi-alioth \
	 device/testing/firmware-xiaomi-alioth \
	 modem/alioth-modem; do
	rm -rf "${PMAPORTS:?}/$a"
	mkdir -p "$PMAPORTS/$(dirname "$a")"
	cp -rL "$HERE/$a" "$PMAPORTS/$a"
	echo "installed $a"
done

cat <<'MSG'

Now, in that checkout:

  pmbootstrap config device xiaomi-alioth
  pmbootstrap config ui plasma-mobile
  pmbootstrap config kernel alioth

  device/testing/firmware-xiaomi-alioth/make-tarball.sh root@<phone>
  pmbootstrap checksum linux-postmarketos-alioth device-xiaomi-alioth \
                       firmware-xiaomi-alioth alioth-modem
  pmbootstrap install --no-image --filesystem ext4

The two patched Alpine packages are not shipped here - see README.
MSG
