#!/usr/bin/env python3
"""MX-Edit.exe bauen (eine Datei, kein Python beim Nutzer noetig).

Aufruf (im Editor-Ordner oder von ueberall):  python werkzeuge\\exe_bauen.py
                                    Diagnose:  python werkzeuge\\exe_bauen.py diagnose
Braucht:  pip install pyinstaller mido python-rtmidi pillow
Ergebnis: <Editor-Ordner>\\exe\\MX-Edit.exe (Zwischendateien in exe\\build, werden geloescht);
          unter macOS exe/MX-Edit.app, unter Linux exe/MX-Edit (eine Datei). PyInstaller baut nur fuer
          das laufende System - Mac/Linux baut der Workflow .github/workflows/build.yml auf GitHub.

Das Icon mxedit.ico (Drehregler, ui.app_icon - dieselbe Zeichnung wie das Logo der Titelleiste,
jede Groesse 16-256 px eigens gezeichnet) wird hier neu erzeugt und in die EXE eingebettet;
mx5editor.py setzt es auch als Fenster-/Taskleisten-Icon. catalog.json und
modellseiten.json kommen als Daten mit (der Editor liest sie neben sich, in der EXE aus dem
Entpackordner sys._MEIPASS). mido laedt sein Backend per importlib - daher hidden-import."""
import os, shutil, subprocess, sys

ED = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ED, 'exe')
ICON = os.path.join(ED, 'mxedit.ico')


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


def make_icon(path=ICON):
    """Programm-Icon aus ui.app_icon (alle Groessen; .icns fuer macOS)."""
    sys.path.insert(0, ED)
    import ui
    if path.endswith('.icns'):   # ohne Tk-Fenster (der Linux-/Mac-Build laeuft ohne Bildschirm)
        ui.app_icon(512).save(path, format='ICNS')
        return
    import tkinter as tk
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
    font = bold_font(104)
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
    work = os.path.join(OUT, 'build')
    os.makedirs(work, exist_ok=True)
    mac = sys.platform == 'darwin'
    if os.name == 'nt':
        make_icon()
    icon = ICON
    if mac:   # macOS: .app (onedir) mit .icns; mxedit.ico liegt im Repo und kommt als Daten mit
        icon = os.path.join(work, 'mxedit.icns')
        make_icon(icon)
    sep = os.pathsep
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
           '--name', 'MX-Edit', '--icon', icon,
           '--distpath', OUT, '--workpath', work, '--specpath', work,
           '--add-data', os.path.join(ED, 'catalog.json') + sep + '.',
           '--add-data', os.path.join(ED, 'modellseiten.json') + sep + '.',
           '--add-data', ICON + sep + '.',
           '--hidden-import', 'mido.backends.rtmidi',
           '--hidden-import', 'PIL._tkinter_finder']   # Linux: ImageTk findet Tk sonst nicht
    cmd += ['--osx-bundle-identifier', 'com.tict4x.mxedit'] if mac else ['--onefile']
    cmd.append(os.path.join(ED, 'mx5editor.py'))
    subprocess.run(cmd, check=True, cwd=ED)
    shutil.rmtree(work, ignore_errors=True)
    exe = os.path.join(OUT, 'MX-Edit' + ('.exe' if os.name == 'nt' else '.app' if mac else ''))
    print('Fertig:', exe, '%.1f MB' % (os.path.getsize(exe) / 1e6) if os.path.isfile(exe) else '')


if __name__ == '__main__':
    main()
