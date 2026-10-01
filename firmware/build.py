#!/usr/bin/env python3
"""Baut die MX5-Bridge-Firmware aus dem Original-Update.img (HeadRush MX5 2.7).

Aufruf (Linux/WSL, braucht debugfs, e2fsck, xz):
    python3 build.py <Original Update.img> <Ausgabe Update.img>
Vorher einmal tools/build-sqlite3.sh ausfuehren (erzeugt bin/sqlite3).

Mit NAM-Mod (optional, https://github.com/lolgab/headrush-nam-mod, wird NICHT mit der
Bridge ausgeliefert): Eingabe ist dann ein Update.img, auf das die NAM-Mod schon angewendet
wurde - von tools/nam-mod.sh (laedt die Mod von GitHub und baut ihr Werkzeug) oder aus dem
Updater, den die GUI der Mod erzeugt. build.py erkennt das und laesst die App nur dann mit
NAM (LD_PRELOAD) starten, wenn NAM eingeschaltet ist ('mx5bridge-db.sh nam', Aktionen
nam-on/nam-off). Ohne LD_PRELOAD verhaelt sich das gepatchte Evil wie das Original (das
Trampolin der Mod springt dann in den originalen Anxiety OD).

Was geaendert wird, steht in bridgepatch.py (gemeinsam mit patcher.py, der dasselbe ohne Linux
macht); dort steht auch die Versionsnummer (VERSION).

0.7 gegenueber 0.6: NAM-Mod als Option (siehe oben); Status meldet den NAM-Zustand; stuerzt
die App mit NAM dreimal in Folge kurz nach dem Start ab, schaltet der Absturzwaechter zuerst
NAM ab (erst danach greift die Datenbank-Wiederherstellung).

0.5 gegenueber 0.4: Zeichen ausserhalb von ASCII gehen in beiden Richtungen als Escape
(0x7F + vier Hex-Ziffern) statt als '?' ueber die Leitung; Befehl 0x06 (RIG, nie
funktionsfaehig) entfernt; Versionsangaben aller Skripte aus VERSION.
0.4 gegenueber 0.3: Datenbankdienst schreibt (0x09) und fuehrt Aktionen aus (0x0A:
status/backup/restore/restart); die Startschleife /usr/Evil/Scripts/evil ruft den
Dienst vor jedem App-Start (Wiederherstellung) und nach jedem App-Ende (Absturz-
zaehler) auf und wertet den Neustart-Marker der Bridge aus."""
import hashlib, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitpatch, bridgepatch

def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit('Befehl fehlgeschlagen: %s' % cmd)
    return r.stdout + r.stderr

def debugfs_cat_bytes(img, path):
    return subprocess.run(['debugfs', '-R', 'cat "%s"' % path, img], capture_output=True).stdout

def main(stock_img, out_img):
    raw = open(stock_img, 'rb').read()
    print('Original Update.img sha1:', hashlib.sha1(raw).hexdigest())
    assert fitpatch.verify(raw)
    work = tempfile.mkdtemp(prefix='mx5b_')
    xz_in = os.path.join(work, 'rootfs.xz')
    img = os.path.join(work, 'rootfs.img')
    open(xz_in, 'wb').write(fitpatch.extract(raw, 'rootfs'))
    run('xz -dc "%s" > "%s"' % (xz_in, img), shell=True)

    info = stock_img + '.nam.txt'   # Herkunft von tools/nam-mod.sh, sonst unbekannt
    nam_info = open(info, encoding='ascii').read() if os.path.exists(info) else None
    plan, nam = bridgepatch.plan(lambda p: debugfs_cat_bytes(img, p), nam_info)
    if not nam:
        print('ohne NAM-Mod')
    files = {}
    for i, (target, (data, mode)) in enumerate(plan.items()):
        local = os.path.join(work, 'f%02d' % i)
        open(local, 'wb').write(data)
        files[target] = (local, '0%o' % mode)

    # In das ext4-Image schreiben
    cmds = []
    for target, (local, mode) in files.items():
        cmds.append('rm "%s"' % target)
        cmds.append('write "%s" "%s"' % (local, target))
        cmds.append('sif "%s" mode %s' % (target, mode))
        cmds.append('sif "%s" uid 0' % target)
        cmds.append('sif "%s" gid 0' % target)
    script = os.path.join(work, 'debugfs.cmd')
    open(script, 'w').write('\n'.join(cmds) + '\n')
    subprocess.run(['debugfs', '-w', '-f', script, img], capture_output=True)
    # Pruefen: Inhalte zuruecklesen, Dateisystem checken
    for target, (local, mode) in files.items():
        got = debugfs_cat_bytes(img, target)
        assert got == open(local, 'rb').read(), 'Rueckleseprobe fehlgeschlagen: ' + target
        st = run(['debugfs', '-R', 'stat "%s"' % target, img])
        assert ('Mode:  %s' % mode[-4:]) in st and 'User:     0   Group:     0' in st, st[:200]
    fsck = subprocess.run(['e2fsck', '-fn', img], capture_output=True, text=True)
    print(fsck.stdout.strip().splitlines()[-1])
    assert fsck.returncode == 0, fsck.stdout + fsck.stderr
    print('%d Dateien geschrieben und verifiziert, e2fsck sauber' % len(files))

    # Komprimieren wie das Original: CRC32, 64 MiB Woerterbuch, 128 MiB Bloecke
    xz_out = os.path.join(work, 'rootfs_new.xz')
    run('xz -zc -T2 --check=crc32 --block-size=134217728 --lzma2=preset=6e,dict=64MiB "%s" > "%s"'
        % (img, xz_out), shell=True)
    run('xz -dc "%s" | cmp - "%s"' % (xz_out, img), shell=True)
    new = fitpatch.replace_image(raw, 'rootfs', open(xz_out, 'rb').read())
    assert fitpatch.verify(new)
    # Splash-Bilder und Header-Metadaten muessen unveraendert sein
    for im in ('splash', 'recoverysplash'):
        assert fitpatch.extract(new, im) == fitpatch.extract(raw, im)
    open(out_img, 'wb').write(new)
    print('Fertig:', out_img, len(new), 'Bytes, sha1', hashlib.sha1(new).hexdigest())
    shutil.rmtree(work)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
