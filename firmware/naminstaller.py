#!/usr/bin/env python3
"""NAM-Mod gefuehrt einbinden (fuer patcher_gui.py): den OFFIZIELLEN Installer der NAM-Mod
(github.com/lolgab/headrush-nam-mod, GPLv3, wird nicht mitgeliefert) aus deren neuestem Release
laden, in einem eigenen Arbeitsordner starten und warten, bis er dort
"HeadRush MX5 Firmware Updater (NAM mod).exe" geschrieben hat. Der Nutzer waehlt im Installer
MX5 + Instanzen und klickt "Install NAM Mod"; der Installer laedt die Original-Firmware selbst.

Gepruefte Eigenschaften des Installers (Quelle v0.1.6, app/main.c): ignoriert Argumente; 7z.exe
und ca-bundle.crt sucht er neben seiner EXE (GetModuleFileName), die Ausgabe schreibt er in das
aktuelle Verzeichnis (getcwd): "HeadRush <Modell> Firmware Updater (NAM mod).exe", danach die
unveraenderte Kopie "... (stock).exe"."""
import glob, json, os, shutil, subprocess, time, urllib.request, zipfile

REPO = 'lolgab/headrush-nam-mod'
ASSET = 'headrush-nam-gui-windows.zip'
EXE = 'headrush-nam-gui-windows.exe'
OUT_GLOB = 'HeadRush * Firmware Updater (NAM mod).exe'
MX5_NAME = 'HeadRush MX5 Firmware Updater (NAM mod).exe'


class NamError(Exception):
    pass


def latest_release():
    """(tag, Download-URL des Windows-Zips, Release-Seite)."""
    req = urllib.request.Request('https://api.github.com/repos/%s/releases/latest' % REPO,
                                 headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'mx5bridge-patcher'})
    with urllib.request.urlopen(req, timeout=30) as r:
        rel = json.load(r)
    for a in rel.get('assets', []):
        if a['name'] == ASSET:
            return rel['tag_name'], a['browser_download_url'], rel['html_url']
    raise NamError('The latest NAM mod release (%s) has no Windows installer (%s).' % (rel.get('tag_name'), ASSET))


def fetch(base, log, progress):
    """Installer laden und entpacken (Zwischenspeicher je Version unter base/NAM installer/<tag>);
    liefert (Pfad der EXE, tag, Release-Seite)."""
    tag, url, page = latest_release()
    d = os.path.join(base, 'NAM installer', tag)
    exe = os.path.join(d, EXE)
    if os.path.exists(exe):
        log('Using the NAM mod installer %s (already downloaded).' % tag)
        return exe, tag, page
    log('Downloading the NAM mod installer %s from GitHub (lolgab/headrush-nam-mod) ...' % tag)
    os.makedirs(d, exist_ok=True)
    zpath = os.path.join(d, ASSET)
    req = urllib.request.Request(url, headers={'User-Agent': 'mx5bridge-patcher'})
    with urllib.request.urlopen(req, timeout=60) as r, open(zpath + '.part', 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0)
        got, last = 0, 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total and time.time() - last > 1:
                last = time.time()
                progress(got, total)
    os.replace(zpath + '.part', zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(d)
    os.remove(zpath)
    if not os.path.exists(exe):
        raise NamError('%s is missing in the NAM mod download.' % EXE)
    return exe, tag, page


def _stable(path, secs=2.0):
    """Datei existiert und waechst seit secs nicht mehr (der Installer schreibt sie in einem Zug)."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    time.sleep(secs)
    try:
        return size > 0 and os.path.getsize(path) == size
    except OSError:
        return False


def run(exe, workdir, log, cancelled):
    """Installer im Arbeitsordner starten und auf seine MX5-Ausgabe warten. cancelled() -> True
    bricht ab. Liefert (Pfad der "(NAM mod).exe", Pfad der "(stock).exe" oder None)."""
    os.makedirs(workdir, exist_ok=True)
    for old in glob.glob(os.path.join(workdir, 'HeadRush * Firmware Updater (*).exe')):
        os.remove(old)
    log('The NAM mod installer opens in its own window. In it:\n'
        '  1. choose MX5 and the number of NAM instances,\n'
        '  2. click "Install NAM Mod" and wait until it says it is done.\n'
        'The patcher continues by itself. Do not run the updater the NAM installer creates.')
    proc = subprocess.Popen([exe], cwd=workdir)
    told_other = set()
    while True:
        if cancelled():
            raise NamError('Cancelled.')
        made = glob.glob(os.path.join(workdir, OUT_GLOB))
        # der Installer schreibt den Modellnamen klein ("HeadRush mx5 ...") - ohne Gross/Klein vergleichen
        mx5 = [p for p in made if os.path.basename(p).lower() == MX5_NAME.lower()]
        for p in made:
            if p not in mx5 and p not in told_other:
                told_other.add(p)
                log('The NAM installer built "%s" - that is not the MX5. Choose MX5 and click '
                    '"Install NAM Mod" again.' % os.path.basename(p))
        if mx5 and _stable(mx5[0]):
            stock = mx5[0].replace('(NAM mod)', '(stock)')
            # die Stock-Kopie schreibt der Installer direkt danach - kurz darauf warten
            for _ in range(20):
                if os.path.exists(stock) and _stable(stock, 0.5):
                    break
                time.sleep(0.5)
            log('The NAM installer has built the MX5 updater. You can close its window.')
            return mx5[0], (stock if os.path.exists(stock) else None)
        if proc.poll() is not None:
            made = glob.glob(os.path.join(workdir, MX5_NAME))
            if made and _stable(made[0], 0.5):
                continue
            raise NamError('The NAM mod installer was closed before it built the MX5 updater.')
        time.sleep(0.5)


def keep_stock(stock, out_parent):
    """Unveraenderten Original-Updater fuer den Notfall neben den Ausgabeordner legen."""
    if not stock:
        return None
    dest = os.path.join(out_parent, os.path.basename(stock))
    if os.path.abspath(dest) != os.path.abspath(stock):
        shutil.copy(stock, dest)
    return dest
