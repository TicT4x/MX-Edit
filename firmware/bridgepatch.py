#!/usr/bin/env python3
"""Was die MX5 Bridge am rootfs aendert - gemeinsam fuer build.py (Linux, debugfs) und
patcher.py (Windows/ueberall, reines Python ueber ext4.py). Meldungen englisch: der Patcher
zeigt sie Endnutzern.

plan(cat) liest die noetigen Originaldateien ueber cat(pfad) -> bytes (b'' = fehlt) und
liefert {zielpfad: (inhalt bytes, modus int)}. Die Versionsnummer steht nur hier (VERSION);
sie wird fuer @VERSION@ in alle Dateien aus mod/ eingesetzt."""
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(HERE, 'mod')
BIN = os.path.join(HERE, 'bin')

VERSION = '0.7'

# Name, unter dem Evil das USB-MIDI-Gadget fuehrt (Dateinamen der Assignment-QML;
# Leerzeichen -> Unterstrich, wie bei "HG04_Control_Surface_MIDI_1"; in 0.1 bestaetigt)
NAME = 'f_midi'

MIDI_BLOCK = '''    ### MX5 Bridge: USB-MIDI-Funktion (nicht kritisch) ###
    { ( mkdir -p functions/midi.mx5bridge &&
        echo 1 >functions/midi.mx5bridge/in_ports &&
        echo 1 >functions/midi.mx5bridge/out_ports &&
        ln -s functions/midi.mx5bridge configs/c.1 ) ||
      logger -t mx5bridge "USB-MIDI-Funktion konnte nicht angelegt werden"; true; } &&
'''
ENABLE = '    ### Enable the gadget:\n    echo ff580000.usb >UDC\n)\n'
HOOK = '/usr/Evil/Scripts/mx5bridge-usb.sh'
DBHOOK = '/usr/Evil/Scripts/mx5bridge-db.sh'
SQLITE_TARGET = '/usr/Evil/Scripts/mx5bridge-sqlite3'
DAEMON = ('# MX5 Bridge: USB-MIDI-Dienst und Datenbankdienst (nicht kritisch)\n'
          'setsid %s daemon >/dev/null 2>&1 </dev/null &\n'
          'setsid %s daemon >/dev/null 2>&1 </dev/null &\n\n' % (HOOK, DBHOOK))


class PatchError(Exception):
    pass


def need(cond, msg):
    if not cond:
        raise PatchError(msg)


def mod_text(name):
    """Datei aus mod/ mit eingesetzter Version."""
    text = open(os.path.join(MOD, name), encoding='ascii').read().replace('@VERSION@', VERSION)
    assert '@VERSION@' not in text
    return text


def patch_start(text):
    need(text.count(ENABLE) == 1, 'USB start script has an unexpected layout')
    need('mx5bridge' not in text, 'USB start script is already patched (MX5 Bridge already installed?)')
    need('ln -s functions/uac2_az01.otg0 configs/c.1 &&\n' + ENABLE in text, 'USB start script has an unexpected layout')
    mp = 'modprobe configfs &&\n'
    need(text.count(mp) == 1, 'USB start script has an unexpected layout')
    text = text.replace(mp, '%s evil-begin audio\n' % HOOK + mp)
    return text.replace(ENABLE, MIDI_BLOCK + ENABLE)


def patch_stop(text):
    first = '(\n    cd /sys/kernel/config/usb_gadget/g1 &&\n'
    uac = '    rm /sys/kernel/config/usb_gadget/g1/configs/c.1/uac2_az01.otg0\n'
    cfg = '    rmdir /sys/kernel/config/usb_gadget/g1/configs/c.1\n'
    for s in (first, uac, cfg):
        need(text.count(s) == 1, 'USB stop script has an unexpected layout: %r' % s)
    need(text.endswith(')\n'), 'USB stop script has an unexpected layout')
    text = text.replace(uac, uac + '    rm /sys/kernel/config/usb_gadget/g1/configs/c.1/midi.mx5bridge 2>/dev/null\n')
    text = text.replace(cfg, cfg + '    rmdir /sys/kernel/config/usb_gadget/g1/functions/midi.mx5bridge 2>/dev/null\n')
    return text + '%s evil-end\n' % HOOK


def patch_ms_setup(text):
    dv = '. /usr/Evil/Scripts/def_vars\n'
    need(text.count(dv) == 1 and 'mx5bridge' not in text, 'setup-mass-storage.sh has an unexpected layout')
    return text.replace(dv, dv + '\n%s evil-begin storage\n' % HOOK)


def patch_ms_remove(text):
    need('mx5bridge' not in text and text.endswith('fi\n'), 'remove-mass-storage.sh has an unexpected layout')
    return text + '%s evil-end\n' % HOOK


# App-Start in der Startschleife; die NAM-Mod setzt 'env LD_PRELOAD=... NAM_HOOK_SLOT_..._ADDR=...'
# davor (core/launcher_script.c der Mod) und einen Kommentarblock vor 'while [ 1 ]'
EVIL_START = '\tsystemd-inhibit --what=handle-power-key /usr/Evil/Evil\n'
EVIL_RUN = re.compile(r'\tsystemd-inhibit --what=handle-power-key '
                      r'(env LD_PRELOAD=/usr/Evil/libnam_preload\.so'
                      r'(?: NAM_HOOK_SLOT_GONK(?:_V2)?_ADDR=0x[0-9a-f]+)+ )?'
                      r'/usr/Evil/Evil\n\texitCode=\$\?\n')
NAM_BLOCK = '# --- NAM mod ---\n'
NAM_LIBS = ('/usr/Evil/libnam_preload.so', '/usr/Evil/libnam_hook.so')
NAM_INFO = '/usr/Evil/Scripts/mx5bridge-nam.txt'


def patch_evil(text):
    """Startschleife: prestart, postexit, Neustart-Marker. Mit NAM-Mod startet die App nur mit
    der NAM-Zeile der Mod, wenn 'mx5bridge-db.sh nam' ja sagt, sonst wie im Original.
    Liefert (Text, NAM-Startzeile oder None)."""
    need('mx5bridge' not in text, 'start script "evil" is already patched (MX5 Bridge already installed?)')
    runs = list(EVIL_RUN.finditer(text))
    code = [l for l in text.split('\n') if not l.lstrip().startswith('#')]   # der NAM-Block erwaehnt es
    need(len(runs) == 1 and sum('systemd-inhibit' in l for l in code) == 1, 'start script "evil" has an unexpected layout')
    m = runs[0]
    need(text[:m.start()].endswith('while [ 1 ]\ndo\n'), 'start script "evil" has an unexpected layout')
    nam = m.group(0).split('\n')[0] + '\n' if m.group(1) else None
    need(bool(nam) == (NAM_BLOCK in text), 'NAM start line and NAM comment block do not match')
    start = EVIL_START
    if nam:
        start = ('\t### NAM-Mod (github.com/lolgab/headrush-nam-mod) nur, wenn eingeschaltet\n'
                 '\tif %s nam; then\n\t%s\telse\n\t%s\tfi\n' % (DBHOOK, nam, EVIL_START))
    patch = ('\t### MX5 Bridge: Sicherung zurueckspielen (falls angefordert), Absturzzaehler, Neustart-Marker\n'
             '\t%s prestart\n'
             '\tmx5bStart=$(date +%%s)\n'
             '%s'
             '\texitCode=$?\n'
             '\t%s postexit $exitCode $mx5bStart\n'
             '\tif [ -e /tmp/mx5bridge/restart ]; then\n'
             '\t\trm -f /tmp/mx5bridge/restart\n'
             '\t\tsleep 2\n'
             '\t\tcontinue\n'
             '\tfi\n' % (DBHOOK, start, DBHOOK))
    return text[:m.start()] + patch + text[m.end():], nam


def patch_runevil(text):
    anchor = 'log info "Starting application ..."\n'
    need(text.count(anchor) == 1 and 'mx5bridge' not in text, 'runevil has an unexpected layout')
    return text.replace(anchor, DAEMON + anchor)


def sqlite_binary():
    p = os.path.join(BIN, 'sqlite3')
    need(os.path.exists(p), 'bin/sqlite3 is missing - run tools/build-sqlite3.sh first')
    data = open(p, 'rb').read()
    need(data[:4] == b'\x7fELF' and data[4] == 1 and data[18] == 0x28, 'bin/sqlite3 is not a 32-bit ARM binary')
    return data


def plan(cat, nam_info=None, log=print):
    """Liefert ({zielpfad: (bytes, modus)}, nam-startzeile oder None). cat(pfad) -> bytes, b'' = fehlt.
    nam_info: Herkunftstext der NAM-Mod (tools/nam-mod.sh), sonst 'unbekannt'."""
    text = lambda p: cat(p).decode()
    files = {}
    enc = lambda s: s.encode('ascii') if isinstance(s, str) else s
    files['/usr/Evil/Scripts/usb-otg-audio-start.sh'] = (enc(patch_start(text('/usr/Evil/Scripts/usb-otg-audio-start.sh'))), 0o100755)
    files['/usr/Evil/Scripts/usb-otg-audio-stop.sh'] = (enc(patch_stop(text('/usr/Evil/Scripts/usb-otg-audio-stop.sh'))), 0o100755)
    files['/usr/Evil/Scripts/mx5bridge-diag.sh'] = (enc(mod_text('mx5bridge-diag.sh')), 0o100755)
    files['/usr/Evil/Scripts/mx5bridge-usb.sh'] = (enc(mod_text('mx5bridge-usb.sh')), 0o100755)
    files[DBHOOK] = (enc(mod_text('mx5bridge-db.sh')), 0o100755)
    files[SQLITE_TARGET] = (sqlite_binary(), 0o100755)
    for target, fn in (('/usr/Evil/Scripts/setup-mass-storage.sh', patch_ms_setup),
                       ('/usr/Evil/Scripts/remove-mass-storage.sh', patch_ms_remove),
                       ('/usr/Evil/Scripts/runevil', patch_runevil)):
        files[target] = (fn(text(target)).encode(), 0o100755)
    evil, nam = patch_evil(text('/usr/Evil/Scripts/evil'))
    files['/usr/Evil/Scripts/evil'] = (evil.encode(), 0o100755)

    # NAM-Mod: nur wenn die Eingabe sie schon enthaelt (tools/nam-mod.sh oder GUI der Mod)
    libs = [len(cat(p)) for p in NAM_LIBS]
    need(all(libs) == bool(nam) and any(libs) == bool(nam),
         'NAM libraries and NAM start line do not match: %s' % libs)
    if nam:
        log('NAM mod found: ' + nam.strip())
        info = nam_info or 'nam_mod_ref=unbekannt\n'
        info += 'startzeile=%s' % nam.strip().replace('systemd-inhibit --what=handle-power-key ', '') + '\n'
        files[NAM_INFO] = (info.encode('ascii'), 0o100644)
    for kind in ('Device', 'Assignments'):
        tpl = mod_text('Bridge_%s.qml.in' % kind)
        if kind == 'Device':
            assert 'bridgeVersion: "MX5Bridge-%s"' % VERSION in tpl
        files['/usr/Evil/Assignments/%s_%s.qml' % (NAME, kind)] = (enc(tpl.replace('@NAME@', NAME)), 0o100644)
    # Neue Dateien duerfen keine Originaldateien ueberschreiben; Skripte brauchen LF
    for target, (data, mode) in files.items():
        if target.endswith(('.sh', '.qml')) or target.endswith(('runevil', '/evil')):
            need(b'\r' not in data, 'CRLF in ' + target)
        if target in (DBHOOK, SQLITE_TARGET, NAM_INFO) or '/Assignments/' in target:
            need(cat(target) == b'', 'already exists: ' + target)
    return files, nam
