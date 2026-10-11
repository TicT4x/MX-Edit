#!/usr/bin/env python3
"""MX-Edit.exe bauen (eine Datei, kein Python beim Nutzer noetig).

Aufruf (im Editor-Ordner oder von ueberall):  python werkzeuge\\exe_bauen.py
                                    Diagnose:  python werkzeuge\\exe_bauen.py diagnose
Braucht:  pip install pyinstaller mido python-rtmidi pillow
Ergebnis: <Editor-Ordner>\\exe\\MX-Edit.exe (Zwischendateien in exe\\build, werden geloescht).

Das Icon mxedit.ico (Drehregler, ui.app_icon - dieselbe Zeichnung wie das Logo der Titelleiste,
jede Groesse 16-256 px eigens gezeichnet) wird hier neu erzeugt und in die EXE eingebettet;
mx5editor.py setzt es auch als Fenster-/Taskleisten-Icon. catalog.json und
modellseiten.json kommen als Daten mit (der Editor liest sie neben sich, in der EXE aus dem
Entpackordner sys._MEIPASS). mido laedt sein Backend per importlib - daher hidden-import."""
import os, shutil, subprocess, sys

ED = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ED, 'exe')
ICON = os.path.join(ED, 'mxedit.ico')


def make_icon(path=ICON):
    """Programm-Icon aus ui.app_icon (alle Groessen)."""
    sys.path.insert(0, ED)
    import tkinter as tk
    import ui
    root = tk.Tk()
    root.withdraw()
    ui.setup(root, 1.0)
    ui.save_app_icon(path)
    root.destroy()


def make_text_icon(text, path):
    """Icon mit Schriftzug (Diagnoseprogramm: "HR")."""
    from PIL import Image, ImageDraw, ImageFont
    S = 256
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, S - 8, S - 8), radius=52, fill='#141519', outline='#1fc9a1', width=10)
    font = None
    for name in ('segoeuib.ttf', 'arialbd.ttf'):
        try:
            font = ImageFont.truetype(os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', name), 104)
            break
        except OSError:
            pass
    font = font or ImageFont.load_default()
    box = d.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((S - w) / 2 - box[0], (S - h) / 2 - box[1]), text, font=font, fill='#1fc9a1')
    im.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def build_diagnose():
    """HeadRush_Bridge_Diagnose.exe: Konsolenprogramm werkzeuge/geraet_diagnose.py fuer Tester
    (Pedalboard/Gigboard), mit diagnose_pfade.txt als Daten."""
    work = os.path.join(OUT, 'build_diag')
    os.makedirs(work, exist_ok=True)
    icon = os.path.join(work, 'diagnose.ico')     # "HR" (HeadRush) - fuer alle drei Geraete
    make_text_icon('HR', icon)
    here = os.path.dirname(os.path.abspath(__file__))
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--console',
           '--name', 'HeadRush_Bridge_Diagnose', '--icon', icon,
           '--distpath', OUT, '--workpath', work, '--specpath', work,
           '--add-data', os.path.join(here, 'diagnose_pfade.txt') + os.pathsep + '.',
           '--paths', ED, '--hidden-import', 'mido.backends.rtmidi',
           os.path.join(here, 'geraet_diagnose.py')]
    subprocess.run(cmd, check=True, cwd=ED)
    shutil.rmtree(work, ignore_errors=True)
    exe = os.path.join(OUT, 'HeadRush_Bridge_Diagnose.exe')
    print('Fertig:', exe, '%.1f MB' % (os.path.getsize(exe) / 1e6))


def main():
    if sys.argv[1:] == ['diagnose']:
        return build_diagnose()
    make_icon()
    work = os.path.join(OUT, 'build')
    sep = os.pathsep
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
           '--name', 'MX-Edit', '--icon', ICON,
           '--distpath', OUT, '--workpath', work, '--specpath', work,
           '--add-data', os.path.join(ED, 'catalog.json') + sep + '.',
           '--add-data', os.path.join(ED, 'modellseiten.json') + sep + '.',
           '--add-data', ICON + sep + '.',
           '--hidden-import', 'mido.backends.rtmidi',
           os.path.join(ED, 'mx5editor.py')]
    subprocess.run(cmd, check=True, cwd=ED)
    shutil.rmtree(work, ignore_errors=True)
    exe = os.path.join(OUT, 'MX-Edit.exe')
    print('Fertig:', exe, '%.1f MB' % (os.path.getsize(exe) / 1e6))


if __name__ == '__main__':
    main()
