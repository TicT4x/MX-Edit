#!/usr/bin/env bash
# NAM-Mod von GitHub holen und ein Original-Update.img damit patchen (Linux/WSL).
#
# Die NAM-Mod (Neural Amp Modeler statt Anxiety OD) stammt von lolgab:
#     https://github.com/lolgab/headrush-nam-mod   (GPLv3, NAM-Kern MIT)
# Sie wird NICHT mit der MX5 Bridge ausgeliefert. Dieses Skript laedt den Quelltext der
# festgelegten Version (NAM_REF) von GitHub, baut daraus das Kommandozeilenwerkzeug der
# Mod (gui-core-cli, dieselbe Patch-Pipeline wie ihre GUI) und wendet es auf das
# Original-Update.img an. Danach legt build.py die Bridge darueber:
#
#     bash tools/nam-mod.sh <Original Update.img> <NAM Update.img> [2|4]
#     python3 build.py <NAM Update.img> <Bridge+NAM Update.img>
#
# 2|4 = Anzahl NAM-Instanzen (2: nur Anxiety OD, 4: auch Anxiety OD V2), Vorgabe 2.
# Umgebung: NAM_REF  Tag oder Commit der Mod (Vorgabe unten; bewusst von Hand erhoehen)
#           NAM_WORK Arbeitsordner (Vorgabe ~/mx5bridge-nam, liegt nicht im Repo)
#
# Einmalig noetig (Ubuntu/WSL):
#     sudo apt install -y cmake gcc make bzip2 curl libext2fs-dev libblkid-dev uuid-dev liblzma-dev libcurl4-openssl-dev
# Die ARM-Werkzeugkette (Bootlin) laedt das Skript selbst, von der Adresse, die die Mod in
# docker/Dockerfile angibt. Alles Heruntergeladene bleibt im Arbeitsordner (Cache).
set -euo pipefail

REF=${NAM_REF:-v0.1.6}
REPO=https://github.com/lolgab/headrush-nam-mod
WORK=${NAM_WORK:-$HOME/mx5bridge-nam}

die() { echo "FEHLER: $*" >&2; exit 1; }

[ $# -ge 2 ] || die "Aufruf: bash $0 <Original Update.img> <Ausgabe Update.img> [2|4]"
IN=$(realpath "$1")
OUT=$(realpath -m "$2")
INST=${3:-2}
[ "$INST" = 2 ] || [ "$INST" = 4 ] || die "Instanzen muessen 2 oder 4 sein, nicht '$INST'"
[ -f "$IN" ] || die "Eingabe fehlt: $IN"
[ "$IN" != "$OUT" ] || die "Eingabe und Ausgabe muessen verschieden sein"

# Werkzeuge pruefen (eine apt-Zeile fuer alles Fehlende)
fehlt=""
for c in curl tar bzip2 cmake cc make sha256sum; do
	command -v "$c" >/dev/null 2>&1 || fehlt="$fehlt $c"
done
for h in ext2fs/ext2fs.h blkid/blkid.h uuid/uuid.h lzma.h curl/curl.h; do
	[ -f "/usr/include/$h" ] || [ -n "$(find /usr/include -path "*/$h" -print -quit 2>/dev/null)" ] \
		|| fehlt="$fehlt $h"
done
[ -z "$fehlt" ] || die "es fehlt:$fehlt
  sudo apt install -y cmake gcc make bzip2 curl libext2fs-dev libblkid-dev uuid-dev liblzma-dev libcurl4-openssl-dev"

# 1. Quelltext der Mod (Version REF) von GitHub
SRC=$WORK/src-$REF
TGZ=$WORK/headrush-nam-mod-$REF.tar.gz
mkdir -p "$WORK"
if [ ! -f "$SRC/CMakeLists.txt" ]; then
	echo "Lade NAM-Mod $REF von $REPO ..."
	curl -fL -o "$TGZ.part" "$REPO/archive/$REF.tar.gz"
	mv "$TGZ.part" "$TGZ"
	rm -rf "$SRC"; mkdir -p "$SRC"
	tar -xzf "$TGZ" -C "$SRC" --strip-components=1
fi
[ -f "$SRC/tools/gui_core_cli.c" ] || die "$SRC ist keine NAM-Mod (tools/gui_core_cli.c fehlt)"
cd "$SRC"

# 2. ARM-Werkzeugkette, wie die Mod sie angibt
TC_URL=$(sed -n 's/^ARG TOOLCHAIN_URL=//p' docker/Dockerfile | head -n 1)
[ -n "$TC_URL" ] || die "TOOLCHAIN_URL nicht in docker/Dockerfile gefunden"
TC=$WORK/$(basename "$TC_URL" .tar.bz2)
if [ ! -x "$TC/bin/arm-buildroot-linux-gnueabihf-g++" ]; then
	echo "Lade ARM-Werkzeugkette $(basename "$TC_URL") ..."
	rm -rf "$TC"; mkdir -p "$TC"
	curl -fL "$TC_URL" | tar -xj -C "$TC" --strip-components=1
	# Bootlin-Ketten muessen nach dem Auspacken ihre Pfade einmal anpassen
	[ -x "$TC/relocate-sdk.sh" ] && "$TC/relocate-sdk.sh" >/dev/null
fi

# 3. NAM-Kern + Blobs (libnam_hook.so, libnam_preload.so, Trampolin) mit den Skripten der Mod
./scripts/fetch_nam_core.sh
if [ ! -f blobs/libnam_hook.so ] || [ ! -f blobs/libnam_preload.so ] || [ ! -f blobs/trampoline_gonk.bin ]; then
	echo "Baue NAM-Blobs (ARM, einige Minuten) ..."
	PATH="$TC/bin:$PATH" ./scripts/build_blobs_native.sh
fi
touch blobs/*   # sonst will CMake sie per Docker neu bauen (wie im CI der Mod)

# 4. Kommandozeilenwerkzeug der Mod
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build build --target gui-core-cli --parallel >/dev/null
CLI=$SRC/build/gui-core-cli
[ -x "$CLI" ] || die "gui-core-cli wurde nicht gebaut"

# 5. Patchen
echo "Wende NAM-Mod $REF an (MX5, $INST Instanzen) ..."
"$CLI" "$IN" "$OUT" --model mx5 --instances "$INST"

# Herkunft neben die Ausgabe schreiben (build.py liest sie und uebernimmt sie ins Image-Protokoll)
{
	echo "nam_mod_repo=$REPO"
	echo "nam_mod_ref=$REF"
	[ -f "$TGZ" ] && echo "nam_mod_tar_sha256=$(sha256sum "$TGZ" | cut -d' ' -f1)"
	echo "nam_instanzen=$INST"
	echo "toolchain=$(basename "$TC_URL")"
	echo "eingabe_sha1=$(sha1sum "$IN" | cut -d' ' -f1)"
	echo "ausgabe_sha1=$(sha1sum "$OUT" | cut -d' ' -f1)"
	echo "erstellt=$(date -Iseconds)"
} > "$OUT.nam.txt"
echo "Fertig: $OUT (Herkunft: $OUT.nam.txt)"
