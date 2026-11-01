#!/usr/bin/env python3
"""NAM-Mod gefuehrt einbinden (fuer patcher_gui.py): den OFFIZIELLEN Installer der NAM-Mod
(github.com/lolgab/headrush-nam-mod, GPLv3, wird nicht mitgeliefert) aus deren neuestem Release
laden, in einem eigenen Arbeitsordner starten und warten, bis er dort
"HeadRush MX5 Firmware Updater (NAM mod).exe" geschrieben hat. Der Nutzer waehlt im Installer
MX5 + Instanzen und klickt "Install NAM Mod"; der Installer laedt die Original-Firmware selbst.

Gepruefte Eigenschaften des Installers (Quelle v0.1.6, app/main.c): ignoriert Argumente; 7z.exe
und ca-bundle.crt sucht er neben seiner EXE (GetModuleFileName), die Ausgabe schreibt er in das
aktuelle Verzeichnis (getcwd): "HeadRush <Modell> Firmware Updater (NAM mod).exe", danach die
unveraenderte Kopie "... (stock).exe".

macOS (Quelle v0.1.6): "headrush-nam-gui-macos" (tar.gz, braucht SDL2 aus Homebrew) schreibt
"<Name der offiziellen .app> (NAM mod).app" + "(stock).app", z. B. "HeadRush MX5 2.7 Firmware
Updater (NAM mod).app". Linux: "headrush-nam-gui-linux" (braucht libSDL2) schreibt nur
"Update_nam.img" (kein Updater - das Modell prueft patcher.build am FIT-Kopf)."""
import glob, json, os, shutil, subprocess, sys, tarfile, time, urllib.request, zipfile

REPO = 'lolgab/headrush-nam-mod'
if sys.platform == 'win32':
    ASSET, EXE, SUFFIX = 'headrush-nam-gui-windows.zip', 'headrush-nam-gui-windows.exe', '.exe'
elif sys.platform == 'darwin':
    ASSET, EXE, SUFFIX = 'headrush-nam-gui-macos.tar.gz', 'headrush-nam-gui-macos', '.app'
else:
    ASSET, EXE, SUFFIX = 'headrush-nam-gui-linux.tar.gz', 'headrush-nam-gui-linux', None
LINUX_IMG = 'Update_nam.img'
OUT_GLOB = 'HeadRush * Firmware Updater (NAM mod)%s' % (SUFFIX or '')
MX5_NAME = 'HeadRush MX5 Firmware Updater (NAM mod).exe'
# fehlende Bibliotheken: was der Nutzer installieren muss (README der NAM-Mod)
LIB_HINT = ('On a Mac the NAM installer needs SDL2 from Homebrew: run "brew install sdl2" '
            '(Intel Macs: "brew install curl xz sdl2") and try again.' if sys.platform == 'darwin' else
            'On Linux the NAM installer needs SDL2, e.g. "sudo apt install libsdl2-2.0-0" (Debian/Ubuntu) '
            'or "sudo dnf install SDL2" (Fedora), and try again.')


def out_name(device):
    """Ausgabename des Installers fuer ein Geraet ('MX5', 'Pedalboard', 'Gigboard') unter Windows."""
    return MX5_NAME.replace('MX5', device)


def for_device(path, device):
    """Ausgabe des Installers fuer device? Windows: "HeadRush mx5 Firmware Updater (NAM mod).exe"
    (klein geschrieben), macOS: "HeadRush MX5 2.7 Firmware Updater (NAM mod).app"."""
    return os.path.basename(path).lower().startswith('headrush %s ' % device.lower())


def _size(path):
    """Groesse einer Datei oder eines Ordners (.app) in Bytes."""
    if not os.path.isdir(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(os.path.join(r, n)) for r, _, fs in os.walk(path) for n in fs)


def _remove(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path):
        os.remove(path)


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
    raise NamError('The latest NAM mod release (%s) has no installer for this system (%s).' % (rel.get('tag_name'), ASSET))


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
    if ASSET.endswith('.zip'):
        with zipfile.ZipFile(zpath) as z:
            z.extractall(d)
    else:   # tar.gz behaelt das x-Recht
        with tarfile.open(zpath) as t:
            for m in t.getmembers():
                if not (m.isfile() or m.isdir()) or m.name.startswith('/') or '..' in m.name.split('/'):
                    raise NamError('Unexpected entry in the NAM mod download: %s' % m.name)
            t.extractall(d)
        if os.path.exists(exe):
            os.chmod(exe, 0o755)
    os.remove(zpath)
    if not os.path.exists(exe):
        raise NamError('%s is missing in the NAM mod download.' % EXE)
    return exe, tag, page


def _stable(path, secs=2.0):
    """Datei/.app existiert und waechst seit secs nicht mehr (der Installer schreibt sie in einem Zug)."""
    try:
        size = _size(path)
    except OSError:
        return False
    time.sleep(secs)
    try:
        return size > 0 and _size(path) == size
    except OSError:
        return False


def find_window(pid, timeout=10.0, alive=None):
    """HWND des sichtbaren Hauptfensters des Prozesses pid (Windows), sonst None; alive() -> False
    bricht ab (Prozess schon beendet)."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None
    if not hasattr(ctypes, 'windll'):
        return None
    u = ctypes.windll.user32
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    end = time.time() + timeout
    while time.time() < end and (alive is None or alive()):
        found = []

        def cb(hwnd, _):
            p = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid and u.IsWindowVisible(hwnd):
                found.append(hwnd)
                return False
            return True
        u.EnumWindows(proto(cb), 0)
        if found:
            return found[0]
        time.sleep(0.2)
    return None


def run(exe, workdir, log, cancelled, on_window=None, device='MX5'):
    """Installer im Arbeitsordner starten und auf seine Ausgabe fuer device warten. cancelled() -> True
    bricht ab. Sobald die Ausgabe fertig ist, wird der Installer geschlossen: sein Fertig-Bildschirm
    bietet "Open" fuer den reinen NAM-Updater an, und genau den haben Nutzer dann statt des
    Bridge-Updaters geflasht. on_window(hwnd) bekommt sein Fenster (zum Anordnen).
    Liefert (Pfad der "(NAM mod).exe/.app" bzw. Update_nam.img, Pfad der "(stock)"-Kopie oder None)."""
    os.makedirs(workdir, exist_ok=True)
    for old in glob.glob(os.path.join(workdir, 'HeadRush * Firmware Updater (*)*')) + [os.path.join(workdir, LINUX_IMG)]:
        _remove(old)
    log('The NAM mod installer opens in its own window. In it:\n'
        '  1. choose %s and the number of NAM instances,\n' % device +
        '  2. click "Install NAM Mod".\n'
        'Then just wait: the patcher closes the NAM installer by itself and adds the bridge.\n'
        'Do NOT click "Open" in the NAM installer - that updater has no bridge.')
    errlog = open(os.path.join(workdir, 'installer.log'), 'wb')
    try:
        proc = subprocess.Popen([exe], cwd=workdir, stdout=errlog, stderr=subprocess.STDOUT)
    except OSError as e:
        raise NamError('Could not start the NAM mod installer: %s' % e)
    started = time.time()
    if on_window:
        hwnd = find_window(proc.pid, alive=lambda: proc.poll() is None and not cancelled())
        if hwnd:
            on_window(hwnd)
    told_other = set()
    while True:
        if cancelled():
            raise NamError('Cancelled.')
        made = glob.glob(os.path.join(workdir, OUT_GLOB)) if SUFFIX else []
        # der Installer schreibt den Modellnamen klein ("HeadRush mx5 ...") - ohne Gross/Klein vergleichen
        mx5 = [p for p in made if for_device(p, device)]
        if not SUFFIX and os.path.exists(os.path.join(workdir, LINUX_IMG)):
            mx5 = [os.path.join(workdir, LINUX_IMG)]
        for p in made:
            if p not in mx5 and p not in told_other:
                told_other.add(p)
                log('The NAM installer built "%s" - that is not the %s. Choose %s and click '
                    '"Install NAM Mod" again.' % (os.path.basename(p), device, device))
        if mx5 and _stable(mx5[0]):
            stock = mx5[0].replace('(NAM mod)', '(stock)') if SUFFIX else None
            # die Stock-Kopie schreibt der Installer direkt danach - kurz darauf warten
            for _ in range(20 if stock else 0):
                if os.path.exists(stock) and _stable(stock, 0.5):
                    break
                time.sleep(0.5)
            time.sleep(1.0)       # danach raeumt er nur noch seinen Temp-Ordner auf
            if proc.poll() is None:
                proc.terminate()
                log('The NAM installer has built its part - closed it. Now adding the bridge ...')
            else:
                log('The NAM installer has built its part. Now adding the bridge ...')
            return mx5[0], (stock if stock and os.path.exists(stock) else None)
        if proc.poll() is not None:
            if mx5 and _stable(mx5[0], 0.5):
                continue
            errlog.flush()
            out = open(errlog.name, 'rb').read().decode('utf-8', 'replace').strip()
            if time.time() - started < 5 and proc.returncode != 0:   # startet gar nicht: meist fehlt SDL2
                raise NamError('The NAM mod installer did not start (exit code %s).\n%s\n%s'
                               % (proc.returncode, out[-600:], LIB_HINT if os.name != 'nt' else ''))
            raise NamError('The NAM mod installer was closed before it built the %s updater.' % device)
        time.sleep(0.5)


def drop_intermediate(path):
    """Den reinen NAM-Updater (ohne Bridge) nach erfolgreichem Bau loeschen, damit ihn niemand
    versehentlich startet; der Bridge-Updater enthaelt NAM ja schon."""
    try:
        if path:
            _remove(path)
    except OSError:
        pass


def keep_stock(stock, out_parent):
    """Unveraenderten Original-Updater fuer den Notfall neben den Ausgabeordner legen."""
    if not stock:
        return None
    dest = os.path.join(out_parent, os.path.basename(stock))
    if os.path.abspath(dest) != os.path.abspath(stock):
        if os.path.isdir(stock):
            _remove(dest)
            shutil.copytree(stock, dest, symlinks=True)
        else:
            shutil.copy(stock, dest)
    return dest
