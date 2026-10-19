#!/usr/bin/env python3
"""MX5 Bridge firmware patcher - builds the bridge updater from the OFFICIAL HeadRush 2.7
updater (MX5; Pedalboard/Gigboard experimental - model from the FIT header, --model) on the user's own computer (like the NAM mod does), so no HeadRush code is shipped.

Usage:
    python patcher.py                      download the official updater from inMusic, patch it
    python patcher.py <input>              patch a local copy instead; <input> may be the
                                           official .zip, the updater .exe (also one made by the
                                           NAM mod GUI), a folder with Update.img, or Update.img
    python patcher.py <input> --out <dir>  output folder (default: next to this script)

Reines Python 3 (Standardbibliothek); entpackt den 7z-Updater mit sevenzip.py (Rueckfall: tar.exe
von Windows, 7z, bsdtar), schreibt das ext4-rootfs mit ext4.py (statt debugfs)
und komprimiert mit xzblocks.py wie das Original. Was geaendert wird: bridgepatch.py."""
import argparse, hashlib, json, lzma, os, shutil, subprocess, sys, tempfile, time, urllib.request, zipfile, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Download und Ausgabe neben das Skript bzw. die EXE (in der EXE ist HERE ein temporaerer
# Entpackordner, der beim Beenden geloescht wird; mod/ und bin/ liest bridgepatch von dort)
FROZEN = getattr(sys, 'frozen', False)
BASE = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else HERE
import bridgepatch, ext4, fitpatch, sevenzip, xzblocks

MODEL_KEYS = [m['key'] for m in bridgepatch.offered()]   # mx5 (+ pedalboard, gigboard in der Testausgabe)
UPDATER_FILES = ('FirmwareUpdater.exe', 'libusb-1.0.dll', 'Background.png')
SIG7Z = b"7z\xbc\xaf\x27\x1c"


def _print_progress(got, total):
    print('  %3d %%  (%d of %d MB)' % (got * 100 // total, got >> 20, total >> 20), flush=True)


# Ausgabe-Haken: Konsole (print) oder GUI (patcher_gui setzt eigene Funktionen)
LOG = [lambda text: print(text, flush=True)]
PROGRESS = [_print_progress]      # (empfangen, gesamt) in Bytes, hoechstens einmal pro Sekunde


def say(*a):
    LOG[0](' '.join(str(x) for x in a))


class Fail(Exception):
    pass


# ---- Eingabe besorgen ----
def download(dest, model):
    say('Downloading the official HeadRush %s 2.7 updater from inMusic ...' % model['device'])
    say('  ' + model['url'])
    tmp = dest + '.part'
    with urllib.request.urlopen(model['url'], timeout=60) as r, open(tmp, 'wb') as f:
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
                PROGRESS[0](got, total)
    os.replace(tmp, dest)
    say('  done, %d MB' % (os.path.getsize(dest) >> 20))


def sfx_archive(exe):
    """7z-Archiv aus einem 7z-SFX-Updater schneiden (der Stub enthaelt die Signatur auch als
    Text - gueltig ist die Stelle, deren Startkopf-CRC stimmt)."""
    d = open(exe, 'rb').read()
    i = -1
    while True:
        i = d.find(SIG7Z, i + 1)
        if i < 0:
            raise Fail('%s does not look like a HeadRush updater (no 7z archive inside)' % exe)
        hdr = d[i + 12:i + 32]
        if len(hdr) == 20 and zlib.crc32(hdr) == int.from_bytes(d[i + 8:i + 12], 'little'):
            return d[i:]


def extract_7z(archive, dest):
    """Zuerst der eigene Entpacker (sevenzip.py); das tar.exe von Windows 10 / aelteren Windows-11-
    Builds kann kein LZMA (libarchive ohne liblzma) - externe Programme nur noch als Rueckfall."""
    try:
        sevenzip.extract(open(archive, 'rb').read(), dest)
        if os.path.exists(os.path.join(dest, 'Update.img')):
            return
        why = ['built-in: no Update.img in the archive']
    except (sevenzip.Error, lzma.LZMAError, MemoryError) as e:
        why = ['built-in: %s' % e]
    tools = []
    win_tar = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'tar.exe')
    if os.path.exists(win_tar):
        tools.append([win_tar, '-xf', archive, '-C', dest])
    for exe in ('7z', '7za', '7zz'):
        if shutil.which(exe):
            tools.append([exe, 'x', '-y', '-o' + dest, archive])
    if shutil.which('bsdtar'):
        tools.append(['bsdtar', '-xf', archive, '-C', dest])
    flags = 0x08000000 if os.name == 'nt' else 0      # CREATE_NO_WINDOW: kein Konsolenblitz in der GUI
    for cmd in tools:
        try:
            r = subprocess.run(cmd, capture_output=True, creationflags=flags)
        except OSError as e:
            why.append('%s: %s' % (os.path.basename(cmd[0]), e))
            continue
        if r.returncode == 0 and os.path.exists(os.path.join(dest, 'Update.img')):
            return
        err = (r.stderr or r.stdout).decode('utf-8', 'replace').strip().splitlines()
        why.append('%s: %s' % (os.path.basename(cmd[0]), err[-1] if err else 'exit code %d' % r.returncode))
    raise Fail('Could not unpack the updater:\n  ' + '\n  '.join(why))


def unpack(src, work):
    """Liefert den Ordner mit Update.img (und, wenn vorhanden, den Updater-Dateien)."""
    if os.path.isdir(src):
        if not os.path.exists(os.path.join(src, 'Update.img')):
            raise Fail('No Update.img in folder %s' % src)
        return src
    low = src.lower()
    if low.endswith('.img'):
        d = os.path.join(work, 'img')
        os.makedirs(d)
        shutil.copy(src, os.path.join(d, 'Update.img'))
        return d
    if low.endswith('.zip'):
        with zipfile.ZipFile(src) as z:
            exes = [n for n in z.namelist() if n.lower().endswith('.exe')]
            if len(exes) != 1:
                raise Fail('Expected exactly one .exe in %s, found %s' % (src, exes))
            z.extract(exes[0], work)
            src = os.path.join(work, exes[0])
    say('Unpacking %s ...' % os.path.basename(src))
    archive = os.path.join(work, 'updater.7z')
    open(archive, 'wb').write(sfx_archive(src))
    d = os.path.join(work, 'updater')
    os.makedirs(d)
    extract_7z(archive, d)
    os.remove(archive)
    return d


# ---- Patchen ----
def model_of(raw):
    """Modell aus dem FIT-Kopf des Update.img ('compatible' = inmusic,hg04 / mg01 / hg02)."""
    _, props = fitpatch.parse(raw)
    _, _, _, off, ln = fitpatch.get(props, '', 'compatible')
    return bridgepatch.model_of_fit(raw[off:off + ln].rstrip(b'\0').decode('ascii', 'replace'))


def patch(raw, nam_info=None, need_nam=False, device=None):
    if not fitpatch.verify(raw):
        raise Fail('Update.img is damaged (checksum mismatch)')
    say('Unpacking the root file system ...')
    img = lzma.decompress(fitpatch.extract(raw, 'rootfs'))
    fs = ext4.Ext4(img)
    fs.check()

    def cat(p):
        try:
            return fs.cat(p)
        except FileNotFoundError:
            return b''
    files, nam = bridgepatch.plan(cat, nam_info, log=say, device=device)
    if need_nam and not nam:
        raise Fail('This file does not contain the NAM mod. Choose the "(NAM mod).exe" made by the NAM '
                   'installer, or untick "Use a firmware file I already have" so the patcher runs the NAM installer.')
    say('Writing %d files%s ...' % (len(files), ' (NAM mod found - kept, switchable)' if nam else ''))
    for target, (data, mode) in files.items():
        fs.write_file(target, data, mode)
    new_img = fs.finish()

    # Zuruecklesen aus einem frisch geparsten Image
    check = ext4.Ext4(new_img)
    check.check()
    for target, (data, mode) in files.items():
        n = check.lookup(target)
        m, got = check.read(n)
        if got != data or m != mode:
            raise Fail('Verification failed for %s' % target)
    say('All files verified. Compressing (takes a minute or two) ...')
    xz = xzblocks.compress(new_img)
    if lzma.decompress(xz) != new_img:
        raise Fail('Compression check failed')
    new = fitpatch.replace_image(raw, 'rootfs', xz)
    if not fitpatch.verify(new):
        raise Fail('Final image check failed')
    for im in ('splash', 'recoverysplash'):
        if fitpatch.extract(new, im) != fitpatch.extract(raw, im):
            raise Fail('Unexpected change in %s' % im)
    return new, nam


def config_json(nam, device='MX5', original=None):
    """Config.json des Updaters. original: die des offiziellen Updaters (Text) - dann bleibt alles
    ausser Titel und Startknopf wie bei HeadRush (beim Gigboard steht z. B. "HeadRush Gigboard "
    mit Leerzeichen als deviceName; ob der Updater das Geraet daran erkennt, ist unbekannt)."""
    title = '%s %s%s' % (bridgepatch.label(device), bridgepatch.VERSION, ' + NAM' if nam else '')
    if original:
        try:
            cfg = json.loads(original)
            cfg['config']['appName'] = 'HeadRush %s v2.7 + %s (unofficial)' % (device, title)
            cfg['config']['startButtonText'] = 'Install %s' % title
            return json.dumps(cfg, indent=4, ensure_ascii=False) + '\n'
        except (ValueError, KeyError, TypeError):
            pass
    cfg = {"config": {
        "appName": "HeadRush %s v2.7 + %s (unofficial)" % (device, title),
        "startButtonText": "Install %s" % title,
        "deviceName": "HeadRush %s" % device,
        "notConnectedTitle": "HEADRUSH %s IS NOT DETECTED" % device.upper(),
        "notConnectedSubtitle": "Put the HeadRush %s into firmware update mode and connect it to this computer via USB" % device,
        "notConnectedDescription": "To put the HeadRush %s into firmware update mode, go to the \u201cglobal settings\u201d "
                                   "page, tap the more actions button (\u2026), and tap \u201cfirmware update\u201d. " % device,
        "notPoweredTitle": "HEADRUSH %s IS NOT PLUGGED IN" % device.upper(),
        "notPoweredSubtitle": "Please connect the power supply and retry",
        "doNotSwitchOff": "Do not power off or disconnect the HeadRush %s" % device,
        "startButtonY": 0.75, "startButtonWidth": 0.6, "startButtonHeight": 0.07,
        "allowUpdateOnBattery": True, "forceUpdate": False}}
    return json.dumps(cfg, indent=4, ensure_ascii=False) + '\n'


def install_hint(out, nam, device='MX5'):
    return ('To install:\n'
            '  1. Connect the %s to power and USB.\n'
            '  2. On the %s: Global Settings > ... (more) > Firmware Update.\n'
            '  3. Run FirmwareUpdater.exe in %s and click "Install %s %s%s".\n'
            '     Do not disconnect until it has finished.'
            % (device, device, out, bridgepatch.label(device), bridgepatch.VERSION, ' + NAM' if nam else ''))


def risk_note(model):
    """Warnung fuer Modelle, auf denen die Bruecke noch nicht geprueft ist (None = MX5)."""
    if model['tested']:
        return None
    rec = ('If it does not start any more: %s and flash the official updater.' % model['recovery']
           if model['recovery'] else
           'The %s has NO recovery mode - if the firmware does not start, it cannot be re-flashed '
           'with a footswitch combination.' % model['device'])
    return ('EXPERIMENTAL: the bridge has not been tested on a real HeadRush %s yet. '
            'The firmware changes are the same as on the tested MX5, but you are one of the first testers. %s'
            % (model['device'], rec))


def beta_note(model):
    """Hinweis fuer Modelle, deren Unterstuetzung noch Beta ist (Pedalboard), sonst None."""
    if not model.get('beta'):
        return None
    return ('BETA: the bridge runs on the HeadRush %s (tested by users), and MX-Edit supports it as a beta '
            '(MX-Edit 0.9.6 beta or newer; setlists/songs are not supported yet). Back up your rigs first. '
            'If the device does not start any more: %s and flash the official updater. '
            'Please report what works and what doesn\u2019t on GitHub.' % (model['device'], model['recovery']))


def updater_name(model):
    """Dateiname des geladenen Original-Updaters neben Skript/EXE."""
    return 'HeadRush_%s_2.7_Updater.zip' % model['device']


def build(src=None, out=None, need_nam=False, out_parent=None, model=None):
    """Updater bauen. src: Eingabe (None = offiziellen Updater laden bzw. den schon geladenen
    nehmen), out: Ausgabeordner (None = neben Skript/EXE). need_nam: Eingabe muss die NAM-Mod
    enthalten (GUI: Haken NAM + eigene Datei). out_parent: Ordner, in dem der Ausgabeordner
    MX5Bridge_<v>[_<Geraet>][_NAM]_Updater angelegt wird (Standard neben Skript/EXE; beim MX5
    ohne Geraetenamen wie bisher). model: 'mx5'/'pedalboard'/'gigboard' - fuer den Download
    (Standard MX5) und als Pruefung einer eigenen Datei (None = aus der Datei erkennen).
    Liefert (Ausgabeordner, nam, fehlende Dateien, Modell); Fehler als Fail/PatchError/Ext4Error."""
    want = bridgepatch.model(model) if model else None
    work = tempfile.mkdtemp(prefix='mx5bridge_')
    try:
        if not src:
            want = want or bridgepatch.model('mx5')
            src = os.path.join(BASE, updater_name(want))
            if os.path.exists(src):
                say('Using the already downloaded %s' % os.path.basename(src))
            else:
                download(src, want)
        if not os.path.exists(src):
            raise Fail('Not found: %s' % src)
        folder = unpack(os.path.abspath(src), work)
        raw = open(os.path.join(folder, 'Update.img'), 'rb').read()
        if not fitpatch.verify(raw):
            raise Fail('Update.img is damaged (checksum mismatch)')
        found = model_of(raw)
        if found['key'] not in MODEL_KEYS:
            raise Fail('This firmware is for the HeadRush %s. Support for it is still being tested – use the '
                       'testing patcher from %s.' % (found['device'], bridgepatch.TESTING_URL))
        if want and found['key'] != want['key']:
            raise Fail('This firmware is for the HeadRush %s, not the %s.' % (found['device'], want['device']))
        sha = hashlib.sha1(raw).hexdigest()
        if sha == found['sha1']:
            say('Found the official HeadRush %s 2.7 firmware.' % found['device'])
        else:
            say('Update.img is not the plain official 2.7 firmware (sha1 %s) - that is fine for an '
                'updater made by the NAM mod; anything else is refused below if it does not match.' % sha[:12])
        note = risk_note(found) or beta_note(found)
        if note:
            say('\n' + note + '\n')
        nam_info = None
        info = os.path.abspath(src) + '.nam.txt'     # Herkunft von tools/nam-mod.sh
        if os.path.exists(info):
            nam_info = open(info, encoding='ascii').read()
        new, nam = patch(raw, nam_info, need_nam, found['device'])

        tag = '' if found['key'] == 'mx5' else '_' + found['device']
        out = out or os.path.join(out_parent or BASE, '%s_%s%s%s_Updater' % (bridgepatch.file_tag(found['device']), bridgepatch.VERSION, tag,
                                                                            '_NAM' if nam else ''))
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, 'Update.img'), 'wb').write(new)
        orig = os.path.join(folder, 'Config.json')
        orig = open(orig, encoding='utf-8-sig').read() if os.path.exists(orig) else None
        open(os.path.join(out, 'Config.json'), 'w', encoding='utf-8', newline='\n').write(config_json(nam, found['device'], orig))
        missing = []
        for name in UPDATER_FILES:
            p = os.path.join(folder, name)
            if os.path.exists(p):
                shutil.copy(p, os.path.join(out, name))
            else:
                missing.append(name)
        return out, nam, missing, found
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description='Build the ' + bridgepatch.BRAND + ' firmware updater from the official HeadRush 2.7 '
                                             'updater (%s).' % ', '.join(MODEL_KEYS))
    ap.add_argument('input', nargs='?', help='official updater (.zip/.exe), NAM mod updater (.exe), folder or Update.img; '
                                             'omitted = download the official updater')
    ap.add_argument('--out', help='output folder (default: MX5Bridge_<version>_Updater next to this script)')
    ap.add_argument('--model', choices=MODEL_KEYS, help='device to download the updater for (default mx5); with an '
                                                        'input file: refuse it if it is for another device')
    a = ap.parse_args()
    say('%s %s firmware patcher (unofficial - use at your own risk)\n' % (bridgepatch.BRAND, bridgepatch.VERSION))
    try:
        out, nam, missing, found = build(a.input, a.out, model=a.model)
    except (Fail, bridgepatch.PatchError, ext4.Ext4Error) as e:
        say('\nERROR: %s' % e)
        return 1
    say('\nDone: %s' % out)
    if missing:
        say('Copy these files from the official HeadRush updater into that folder: ' + ', '.join(missing))
    say('\n' + install_hint('the folder above', nam, found['device']))
    if risk_note(found):
        say('\n' + risk_note(found))
    return 0


if __name__ == '__main__':
    rc = main()
    if FROZEN and sys.stdin and sys.stdin.isatty():   # Doppelklick: Fenster nicht sofort schliessen
        try:
            input('\nPress Enter to close this window.')
        except EOFError:
            pass
    sys.exit(rc)
