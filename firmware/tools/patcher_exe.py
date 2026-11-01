#!/usr/bin/env python3
"""Patcher als EXE bauen (eine Datei, kein Python beim Nutzer noetig).

Aufruf:   python tools\\patcher_exe.py           (braucht: pip install pyinstaller pillow)
Ergebnis: <Quellcode>\\exe\\MX5Bridge_Patcher.exe (Zwischendateien in exe\\build, werden geloescht);
          unter macOS exe/MX5Bridge_Patcher.app, unter Linux exe/MX5Bridge_Patcher (eine Datei).
          PyInstaller baut nur fuer das System, auf dem es laeuft - Mac/Linux baut der Workflow
          .github/workflows/build.yml auf GitHub.

mod/ und bin/sqlite3 kommen als Daten in die EXE (bridgepatch liest sie aus sys._MEIPASS);
Download und Ausgabeordner legt patcher.py neben die EXE (BASE). Fensterprogramm (patcher_gui.py);
die Konsolenversion bleibt python patcher.py. Das Icon (tuerkises
"MX5" mit Pfeil nach unten) wird hier erzeugt."""
import os, shutil, subprocess, sys

Q = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(Q, 'exe')
ICON = os.path.join(Q, 'patcher.ico')    # auch fuer patcher_gui.py aus dem Quellcode


def bold_font(size):
    """Fette Schrift fuer die Icons: Windows Segoe UI/Arial, macOS Helvetica/Arial, Linux DejaVu;
    sonst Pillows eingebaute Schrift."""
    from PIL import ImageFont
    cands = [os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', n) for n in ('segoeuib.ttf', 'arialbd.ttf')]
    cands += ['/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/Library/Fonts/Arial Bold.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf']
    for p in cands:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def make_icon(text='MX5', path=ICON):
    from PIL import Image, ImageDraw, ImageFont
    S = 256
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, S - 8, S - 8), radius=52, fill='#141519', outline='#1fc9a1', width=10)
    font = bold_font(84)
    box = d.textbbox((0, 0), text, font=font)
    w = box[2] - box[0]
    d.text(((S - w) / 2 - box[0], 40 - box[1]), text, font=font, fill='#1fc9a1')
    # Pfeil nach unten (Firmware aufspielen)
    d.rectangle((S / 2 - 14, 140, S / 2 + 14, 180), fill='#e8e8ea')
    d.polygon([(S / 2 - 40, 178), (S / 2 + 40, 178), (S / 2, 222)], fill='#e8e8ea')
    if path.endswith('.icns'):
        im.resize((512, 512), Image.LANCZOS).save(path, format='ICNS')
    else:
        im.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main():
    """--testing: Testausgabe fuer das Repo MX-Edit-Testing (HeadRush_Bridge_Testing_Patcher.exe,
    mit testing.flag - bietet auch Pedalboard und Gigboard an)."""
    testing = '--testing' in sys.argv[1:]
    name = 'HeadRush_Bridge_Testing_Patcher' if testing else 'MX5Bridge_Patcher'
    os.makedirs(OUT, exist_ok=True)
    make_icon()
    work = os.path.join(OUT, 'build_' + name)
    os.makedirs(work, exist_ok=True)
    icon = ICON
    if testing:   # Testausgabe (alle HeadRush-Geraete): "HR" statt "MX5", im EXE ebenfalls als patcher.ico
        icon = os.path.join(work, 'patcher.ico')
        make_icon('HR', icon)
    sep = os.pathsep
    mac = sys.platform == 'darwin'
    if mac:   # macOS: .app (onedir) mit .icns; Linux: eine Datei; Windows: eine EXE
        bundle_icon = os.path.join(work, 'patcher.icns')
        make_icon('HR' if testing else 'MX5', bundle_icon)
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
           '--name', name, '--icon', bundle_icon if mac else icon,
           '--distpath', OUT, '--workpath', work, '--specpath', work,
           '--add-data', os.path.join(Q, 'mod') + sep + 'mod',
           '--add-data', os.path.join(Q, 'bin', 'sqlite3') + sep + 'bin',
           '--add-data', icon + sep + '.']
    cmd += ['--osx-bundle-identifier', 'com.tict4x.mx5bridge.patcher'] if mac else ['--onefile']
    if testing:
        flag = os.path.join(work, 'testing.flag')
        open(flag, 'w').write('MX-Edit-Testing\n')
        cmd += ['--add-data', flag + sep + '.']
    cmd.append(os.path.join(Q, 'patcher_gui.py'))
    subprocess.run(cmd, check=True, cwd=Q)
    shutil.rmtree(work, ignore_errors=True)
    exe = os.path.join(OUT, name + ('.exe' if os.name == 'nt' else '.app' if mac else ''))
    print('Fertig:', exe, '%.1f MB' % (os.path.getsize(exe) / 1e6) if os.path.isfile(exe) else '')


if __name__ == '__main__':
    main()
