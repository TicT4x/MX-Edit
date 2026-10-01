#!/bin/sh
# MX5 Bridge @VERSION@ (inoffiziell)
# Schreibt Diagnosedaten auf das USB-Laufwerk des Geraets (Ordner MX5Bridge) und gibt den
# Dateipfad aus. Aufruf: mx5bridge-diag.sh <kennung> (ab 0.6 nur noch auf Anfrage: Aktion 'diag')

TAG="${1:-manual}"
MNT=/media/az01-internal/Evil/usb_mnt
DIR="$MNT/MX5Bridge"

# Nur schreiben, wenn das USB-Image auf dem Geraet eingehaengt ist
grep -qs " $MNT " /proc/mounts || exit 0
mkdir -p "$DIR" || exit 0

OUT="$DIR/diag_$TAG.txt"
J=/tmp/mx5bridge-journal.txt
journalctl -b --no-pager > "$J" 2>&1
{
	echo "=== MX5 Bridge Diagnose ($TAG) ==="
	date
	uname -a
	echo
	echo "=== Firmware ==="
	cat /tmp/evil-firmware-version 2>/dev/null; echo
	echo
	echo "=== USB-Gadget g1 ==="
	ls -la /sys/kernel/config/usb_gadget/g1/functions 2>&1
	ls -la /sys/kernel/config/usb_gadget/g1/configs/c.1 2>&1
	cat /sys/kernel/config/usb_gadget/g1/UDC 2>&1
	echo
	echo "=== ALSA Karten ==="
	cat /proc/asound/cards 2>&1
	echo
	echo "=== ALSA rawmidi ==="
	ls -la /dev/snd 2>&1
	for f in /proc/asound/card*/midi*; do echo "--- $f"; cat "$f" 2>&1; done
	echo
	echo "=== ALSA Sequencer ==="
	cat /proc/asound/seq/clients 2>&1
	echo
	aconnect -l 2>&1
	echo
	echo "=== Journal: relevante Zeilen ==="
	grep -i -E "midi|assign|bridge|device url|qml|gadget|f_midi|usb" "$J" | tail -n 800
	echo
	echo "=== Journal: letzte 1500 Zeilen ==="
	tail -n 1500 "$J"
	echo
	echo "=== dmesg (Ende) ==="
	dmesg 2>&1 | tail -n 300
} > "$OUT" 2>&1
rm -f "$J"

sync
echo "$OUT"
exit 0
