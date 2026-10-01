#!/usr/bin/env python3
"""Patcher als EXE bauen (eine Datei, kein Python beim Nutzer noetig).

Aufruf:   python tools\\patcher_exe.py           (braucht: pip install pyinstaller pillow)
Ergebnis: <Quellcode>\\exe\\MX5Bridge_Patcher.exe (Zwischendateien in exe\\build, werden geloescht).

mod/ und bin/sqlite3 kommen als Daten in die EXE (bridgepatch liest sie aus sys._MEIPASS);
Download und Ausgabeordner legt patcher.py neben die EXE (BASE). Konsolenprogramm, damit der
Fortschritt sichtbar ist; per Doppelklick wartet es am Ende auf Enter. Das Icon (tuerkises
"MX5" mit Pfeil nach unten) wird hier erzeugt."""
import os, shutil, subprocess, sys

Q = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(Q, 'exe')
ICON = os.path.join(OUT, 'patcher.ico')


def make_icon():
    from PIL import Image, ImageDraw, ImageFont
    S = 256
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, S - 8, S - 8), radius=52, fill='#141519', outline='#1fc9a1', width=10)
    font = None
    for name in ('segoeuib.ttf', 'arialbd.ttf'):
        try:
            font = ImageFont.truetype(os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', name), 84)
            break
        except OSError:
            pass
    font = font or ImageFont.load_default()
    box = d.textbbox((0, 0), 'MX5', font=font)
    w = box[2] - box[0]
    d.text(((S - w) / 2 - box[0], 40 - box[1]), 'MX5', font=font, fill='#1fc9a1')
    # Pfeil nach unten (Firmware aufspielen)
    d.rectangle((S / 2 - 14, 140, S / 2 + 14, 180), fill='#e8e8ea')
    d.polygon([(S / 2 - 40, 178), (S / 2 + 40, 178), (S / 2, 222)], fill='#e8e8ea')
    im.save(ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main():
    os.makedirs(OUT, exist_ok=True)
    make_icon()
    work = os.path.join(OUT, 'build')
    sep = os.pathsep
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--console',
           '--name', 'MX5Bridge_Patcher', '--icon', ICON,
           '--distpath', OUT, '--workpath', work, '--specpath', work,
           '--add-data', os.path.join(Q, 'mod') + sep + 'mod',
           '--add-data', os.path.join(Q, 'bin', 'sqlite3') + sep + 'bin',
           os.path.join(Q, 'patcher.py')]
    subprocess.run(cmd, check=True, cwd=Q)
    shutil.rmtree(work, ignore_errors=True)
    exe = os.path.join(OUT, 'MX5Bridge_Patcher.exe')
    print('Fertig:', exe, '%.1f MB' % (os.path.getsize(exe) / 1e6))


if __name__ == '__main__':
    main()
