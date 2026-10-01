"""ui.py - Dunkles Erscheinungsbild nach dem Vorbild des HeadRush-Web-Editors.

Farben, Schriften und die eigenen Widgets (Knoepfe, Regler, Kippschalter,
Auswahlfelder, Rig-Liste, Signalkette, Modell-Auswahl, Dialoge).

Technik: das Programm meldet sich bei Windows als DPI-bewusst an (sonst wird
das Fenster bei 125 % Skalierung unscharf hochgerechnet); Pixelmasse laufen
durch px(). tkinter kann keine geglaetteten Rundungen zeichnen, darum werden
abgerundete Flaechen, Kreise und Symbole mit Pillow 4-fach ueberabgetastet
gerendert und als Bilder auf Canvas-Flaechen gelegt (Cache in _IMAGES).
"""
import ctypes, sys, time, tkinter as tk
from tkinter import ttk, font as tkfont

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:      # mx5editor.py meldet das beim Start
    Image = None
import symbole
from rigmodel import base_name   # 'Amp 2' -> 'Amp'

# ---------------- Farben und Schriften ----------------
BG = "#0b0b0e"          # Fensterhintergrund (fast schwarz)
PANEL = "#141519"       # Seitenleisten, Kopfzeilen
CARD = "#1e1f24"        # Karten, Eingabefelder
CARD_HI = "#292a30"     # Karte unter der Maus
CARD_LO = "#17181c"     # leere Plaetze
LINE = "#2b2c33"        # Trennlinien, Signallinie
ACCENT = "#1fc9a1"      # Tuerkisgruen des Web-Editors
ACCENT_HI = "#43dcb8"
ACCENT_TXT = "#07110e"  # Text auf Akzentflaeche
TEXT = "#e8e8ea"
MUTED = "#8d9099"
DIM = "#4a4d56"
KNOB = "#d9dadd"
DANGER = "#d9443c"

FONT = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_TINY = ("Segoe UI", 7)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_HEAD = ("Segoe UI", 12, "bold")
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_CARD = ("Segoe UI", 8, "bold")

# Blockfarben des Geraets (Naeherung an die Anzeige), in der Reihenfolge von MacroColour
COLOUR_ORDER = ["Green", "Dark Green", "Yellow", "Orange", "Red", "Pink", "Purple", "Blue", "Light Blue",
                "White", "Grey", "Turquoise", "Black"]
COLOURS = {
    "Green": "#3fae49", "Dark Green": "#2a7a33", "Yellow": "#e6c229", "Orange": "#ee8a2a", "Red": "#d9443c",
    "Pink": "#e45fa8", "Purple": "#8a5ad6", "Blue": "#3f7fd9", "Light Blue": "#4fc3e8",
    "White": "#e8e8e8", "Grey": "#9a9a9a", "Turquoise": "#2fbfae", "Black": "#444444", "Off": "#3a3b41",
}

S = 1.0                 # Pixelskalierung (1.25 bei 125 %)
_IMAGES = {}            # (schluessel) -> PhotoImage
SS = 4                  # Ueberabtastung beim Rendern


def px(n):
    return int(round(n * S))


def dpi_aware():
    """Vor tk.Tk() aufrufen: Fenster in echter Aufloesung statt hochskaliert."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def setup(root, scale=1.0):
    """Skalierung ermitteln, Grundfarben und ttk-Bildlaufleisten einstellen. scale = Faktor der
    Einstellung 'Interface size' zusaetzlich zur Windows-Skalierung: 'tk scaling' vergroessert die
    Punkt-Schriften, und px() folgt ueber winfo_fpixels."""
    global S, _ROOT
    if scale != 1.0:
        root.tk.call("tk", "scaling", float(root.tk.call("tk", "scaling")) * scale)
    S = root.winfo_fpixels("1i") / 96.0
    _ROOT = root
    root.configure(bg=BG)
    root.option_add("*Font", FONT)
    st = ttk.Style(root)
    st.theme_use("clam")
    for orient in ("Vertical", "Horizontal"):
        name = "%s.TScrollbar" % orient
        st.configure(name, background=CARD_HI, troughcolor=PANEL, bordercolor=PANEL, lightcolor=CARD_HI,
                     darkcolor=CARD_HI, arrowcolor=MUTED, gripcount=0, relief="flat", width=px(10), arrowsize=px(10))
        st.map(name, background=[("active", DIM), ("pressed", DIM)], arrowcolor=[("active", TEXT)])


# ---------------- Bilder (geglaettete Formen) ----------------
def _evict(cache, limit):
    """Cache verkleinern, sobald er mehr als limit Bilder haelt. Nur Bilder, die gerade nirgends
    angezeigt werden, fliegen raus: verliert ein angezeigtes PhotoImage seine letzte Referenz,
    loescht Tk es und das Canvas-Element bleibt leer, bis es neu gezeichnet wird."""
    if len(cache) <= limit:
        return
    for k, im in list(cache.items()):
        try:
            used = _ROOT is not None and int(_ROOT.tk.call("image", "inuse", str(im)))
        except Exception:
            used = False
        if not used:
            del cache[k]


def _image(key, w, h, draw_fn, alpha=None):
    """Bild aus dem Cache oder neu mit draw_fn(dr, W, H) in SS-facher Groesse gezeichnet;
    alpha < 1 blendet das ganze Bild ab (ausgeschaltete Bloecke)."""
    w, h = max(1, int(w)), max(1, int(h))
    im = _IMAGES.get(key)
    if im is None:
        _evict(_IMAGES, 600)
        pic = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
        dr = ImageDraw.Draw(pic)
        dr.pic = pic   # fuer draw_fn, die fertige Bilder einkopieren (model_img fit)
        draw_fn(dr, w * SS, h * SS)
        if alpha is not None:
            pic.putalpha(pic.getchannel("A").point(lambda a: int(a * alpha)))
        im = ImageTk.PhotoImage(pic.resize((w, h), Image.LANCZOS))
        _IMAGES[key] = im
    return im


def rrect_img(w, h, r, fill, outline=None, width=0):
    def d(dr, W, H):
        dr.rounded_rectangle([0, 0, W - 1, H - 1], radius=r * SS, fill=fill, outline=outline, width=width * SS)
    return _image(("rr", w, h, r, fill, outline, width), w, h, d)


def circle_img(dia, fill, outline=None, width=0):
    def d(dr, W, H):
        dr.ellipse([0, 0, W - 1, H - 1], fill=fill, outline=outline, width=width * SS)
    return _image(("ci", dia, fill, outline, width), dia, dia, d)


def rrect(c, x, y, w, h, r, fill, outline=None, width=0, tags=()):
    """Abgerundetes Rechteck auf einen Canvas legen (fill '' = nur Rahmen)."""
    x, y, w, h = int(x), int(y), int(w), int(h)
    if Image is None:
        return c.create_rectangle(x, y, x + w, y + h, fill=fill, outline=outline or fill, width=width or 1, tags=tags)
    return c.create_image(x, y, image=rrect_img(w, h, r, fill or None, outline, width), anchor="nw", tags=tags)


def circle(c, cx, cy, dia, fill, outline=None, width=0, tags=()):
    if Image is None:
        return c.create_oval(cx - dia / 2, cy - dia / 2, cx + dia / 2, cy + dia / 2, fill=fill,
                             outline=outline or fill, tags=tags)
    return c.create_image(int(cx - dia / 2), int(cy - dia / 2), image=circle_img(int(dia), fill, outline, width),
                          anchor="nw", tags=tags)


def icon_img(kind, colour, size=24):
    """Symbole der Seitenleiste und der Kette, mit Pillow gezeichnet."""
    def d(dr, W, H):
        u = W / 24.0           # Einheit: 1/24 der Symbolbreite
        lw = max(1, int(2 * u))
        cx, cy = W / 2, H / 2
        if kind == "rigs":     # drei Regler
            for i, dx in enumerate((-4, 4, -2)):
                y = cy + (i - 1) * 8 * u
                dr.line([cx - 11 * u, y, cx + 11 * u, y], fill=colour, width=lw)
                dr.ellipse([cx + (dx - 3) * u, y - 3 * u, cx + (dx + 3) * u, y + 3 * u], fill=BG, outline=colour, width=lw)
        elif kind == "setlist":   # Liste: Farbkaestchen + Zeile, drei Eintraege
            for i in (-1, 0, 1):
                y = cy + i * 7.5 * u
                dr.rounded_rectangle([cx - 11 * u, y - 2.5 * u, cx - 6 * u, y + 2.5 * u], radius=1.2 * u, fill=colour)
                dr.line([cx - 3 * u, y, cx + 11 * u, y], fill=colour, width=lw)
        elif kind == "hw":     # Fussschalter
            dr.rounded_rectangle([cx - 11 * u, cy - 9 * u, cx + 11 * u, cy + 9 * u], radius=4 * u, outline=colour, width=lw)
            dr.ellipse([cx - 4 * u, cy - 4 * u, cx + 4 * u, cy + 4 * u], fill=colour)
        elif kind == "folder":
            dr.polygon([cx - 11 * u, cy - 7 * u, cx - 3 * u, cy - 7 * u, cx - 1 * u, cy - 4 * u, cx + 11 * u, cy - 4 * u,
                        cx + 11 * u, cy + 8 * u, cx - 11 * u, cy + 8 * u], outline=colour, width=lw)
        elif kind == "live":   # USB-Symbol (Dreizack): Pfeil oben, Kreis unten, links Kreis, rechts Quadrat
            lw = max(1, int(1.8 * u))
            dr.line([cx, cy - 8 * u, cx, cy + 7 * u], fill=colour, width=lw)
            dr.polygon([cx, cy - 12 * u, cx - 3.2 * u, cy - 7 * u, cx + 3.2 * u, cy - 7 * u], fill=colour)
            dr.ellipse([cx - 3 * u, cy + 6 * u, cx + 3 * u, cy + 12 * u], fill=colour)
            dr.line([cx, cy + 4 * u, cx - 6.5 * u, cy - 0.5 * u, cx - 6.5 * u, cy - 3 * u], fill=colour, width=lw,
                    joint="curve")
            dr.ellipse([cx - 9 * u, cy - 7.5 * u, cx - 4 * u, cy - 2.5 * u], fill=colour)
            dr.line([cx, cy + 1.5 * u, cx + 6.5 * u, cy - 3 * u, cx + 6.5 * u, cy - 5 * u], fill=colour, width=lw,
                    joint="curve")
            dr.rectangle([cx + 4.3 * u, cy - 9.5 * u, cx + 8.7 * u, cy - 5.1 * u], fill=colour)
        elif kind == "close":  # x zum Schliessen
            lw = max(1, int(2.2 * u))
            dr.line([cx - 6 * u, cy - 6 * u, cx + 6 * u, cy + 6 * u], fill=colour, width=lw)
            dr.line([cx - 6 * u, cy + 6 * u, cx + 6 * u, cy - 6 * u], fill=colour, width=lw)
        elif kind == "tuner":  # Stimmgabel
            dr.line([cx - 6 * u, cy - 11 * u, cx - 6 * u, cy - 2 * u], fill=colour, width=lw)
            dr.line([cx + 6 * u, cy - 11 * u, cx + 6 * u, cy - 2 * u], fill=colour, width=lw)
            dr.arc([cx - 6 * u, cy - 8 * u, cx + 6 * u, cy + 4 * u], 0, 180, fill=colour, width=lw)
            dr.line([cx, cy + 4 * u, cx, cy + 12 * u], fill=colour, width=lw)
            dr.line([cx - 4 * u, cy + 12 * u, cx + 4 * u, cy + 12 * u], fill=colour, width=lw)
        elif kind == "plug":   # Klinkenstecker (Eingang)
            dr.line([cx, cy - 12 * u, cx, cy + 2 * u], fill=colour, width=max(1, int(3 * u)))
            dr.rounded_rectangle([cx - 3 * u, cy + 1 * u, cx + 3 * u, cy + 12 * u], radius=2 * u, fill=colour)
        elif kind == "trash":   # Muelleimer (Block entfernen)
            dr.line([cx - 10 * u, cy - 6 * u, cx + 10 * u, cy - 6 * u], fill=colour, width=lw)
            dr.line([cx - 4 * u, cy - 6 * u, cx - 4 * u, cy - 10 * u, cx + 4 * u, cy - 10 * u, cx + 4 * u, cy - 6 * u],
                    fill=colour, width=lw, joint="curve")
            dr.polygon([cx - 8 * u, cy - 3 * u, cx + 8 * u, cy - 3 * u, cx + 6 * u, cy + 11 * u, cx - 6 * u, cy + 11 * u],
                       outline=colour, width=lw)
            for dx in (-3, 0, 3):
                dr.line([cx + dx * u, cy, cx + dx * u, cy + 8 * u], fill=colour, width=max(1, lw - 1))
        elif kind == "plus":    # + (neues Preset)
            lw = max(1, int(2.2 * u))
            dr.line([cx - 8 * u, cy, cx + 8 * u, cy], fill=colour, width=lw)
            dr.line([cx, cy - 8 * u, cx, cy + 8 * u], fill=colour, width=lw)
        elif kind == "save":    # Diskette (Preset ueberschreiben)
            dr.polygon([cx - 10 * u, cy - 10 * u, cx + 6 * u, cy - 10 * u, cx + 10 * u, cy - 6 * u,
                        cx + 10 * u, cy + 10 * u, cx - 10 * u, cy + 10 * u], outline=colour, width=lw)
            dr.rectangle([cx - 5 * u, cy - 10 * u, cx + 4 * u, cy - 4 * u], outline=colour, width=lw)
            dr.rectangle([cx - 6 * u, cy + 2 * u, cx + 6 * u, cy + 10 * u], fill=colour)
        elif kind == "mix":     # zwei Zweige laufen zusammen (Mischpunkt der parallelen Wege)
            lw = max(1, int(2.2 * u))
            for sgn in (-1, 1):
                pts = _round_path([(cx - 9 * u, cy + sgn * 7 * u), (cx - 3 * u, cy + sgn * 7 * u), (cx + 1 * u, cy),
                                   (cx + 4 * u, cy)], 4 * u)
                dr.line(pts, fill=colour, width=lw, joint="curve")
            dr.polygon([cx + 10 * u, cy, cx + 3.5 * u, cy - 4.5 * u, cx + 3.5 * u, cy + 4.5 * u], fill=colour)
        elif kind == "ir":      # Impulsantwort: Nadel, danach abklingende Schwingung
            import math
            pts = []
            for i in range(41):
                t = i / 40.0
                a = 10 * math.exp(-3.2 * t) * math.cos(t * 6 * math.pi)
                pts.append((cx - 7 * u + t * 18 * u, cy - a * u))
            dr.line([cx - 11 * u, cy, cx - 7 * u, cy], fill=colour, width=lw)
            dr.line(pts, fill=colour, width=lw, joint="curve")
        elif kind == "nam":     # kleines neuronales Netz: 2-3-2 Knoten
            layers = [(-8, (-5, 5)), (0, (-8, 0, 8)), (8, (-5, 5))]
            r = 2.6 * u
            for (x1, ys1), (x2, ys2) in zip(layers, layers[1:]):
                for y1 in ys1:
                    for y2 in ys2:
                        dr.line([cx + x1 * u, cy + y1 * u, cx + x2 * u, cy + y2 * u], fill=colour, width=max(1, lw // 2))
            for x, ys in layers:
                for y in ys:
                    dr.ellipse([cx + x * u - r, cy + y * u - r, cx + x * u + r, cy + y * u + r], fill=BG,
                               outline=colour, width=lw)
        elif kind == "gear":    # Zahnrad (Einstellungen)
            import math
            pts = []
            for i in range(8):
                for da, rr in ((-0.3, 7.5), (-0.17, 10.5), (0.17, 10.5), (0.3, 7.5)):   # ein Zahn je 45 Grad
                    a = i * math.pi / 4 + da
                    pts.append((cx + rr * u * math.cos(a), cy + rr * u * math.sin(a)))
            dr.polygon(pts, outline=colour, width=lw)
            dr.ellipse([cx - 3.5 * u, cy - 3.5 * u, cx + 3.5 * u, cy + 3.5 * u], outline=colour, width=lw)
        elif kind == "minimize":   # Fensterknoepfe der eigenen Titelleiste
            dr.line([cx - 6 * u, cy, cx + 6 * u, cy], fill=colour, width=max(1, int(1.2 * u)))
        elif kind == "maximize":
            dr.rectangle([cx - 6 * u, cy - 6 * u, cx + 6 * u, cy + 6 * u], outline=colour, width=max(1, int(1.2 * u)))
        elif kind == "restore":
            w_ = max(1, int(1.2 * u))
            dr.rectangle([cx - 6 * u, cy - 3.5 * u, cx + 3.5 * u, cy + 6 * u], outline=colour, width=w_)
            dr.line([cx - 3.5 * u, cy - 3.5 * u, cx - 3.5 * u, cy - 6 * u, cx + 6 * u, cy - 6 * u, cx + 6 * u, cy + 3.5 * u,
                     cx + 3.5 * u, cy + 3.5 * u], fill=colour, width=w_)
        elif kind == "winclose":
            w_ = max(1, int(1.2 * u))
            dr.line([cx - 6 * u, cy - 6 * u, cx + 6 * u, cy + 6 * u], fill=colour, width=w_)
            dr.line([cx - 6 * u, cy + 6 * u, cx + 6 * u, cy - 6 * u], fill=colour, width=w_)
        elif kind == "stereo":  # zwei Kreise, leicht ineinander (Ausgang)
            dr.ellipse([cx - 11 * u, cy - 7 * u, cx + 3 * u, cy + 7 * u], outline=colour, width=lw)
            dr.ellipse([cx - 3 * u, cy - 7 * u, cx + 11 * u, cy + 7 * u], outline=colour, width=lw)
        elif kind == "guitar":  # E-Gitarre als Umriss (Strat-Form), Hals nach rechts oben (Eingang)
            import math
            u = W / 33.0
            t = max(1, int(1.6 * u))             # Strichstaerke
            ang = math.radians(-45)
            ca, sa = math.cos(ang), math.sin(ang)

            def pt(x, y):   # Gitarrenkoordinaten (x laengs zum Kopf, y quer; Mitte bei x=4) drehen
                return (cx + ((x - 4) * ca - y * sa) * u, cy + ((x - 4) * sa + y * ca) * u)

            def spline(ctrl, n=6):   # Catmull-Rom durch die Stuetzpunkte (offen)
                out = []
                for i in range(len(ctrl) - 1):
                    p0 = ctrl[max(i - 1, 0)]
                    p1, p2 = ctrl[i], ctrl[i + 1]
                    p3 = ctrl[min(i + 2, len(ctrl) - 1)]
                    for k in range(n):
                        s_ = k / n
                        out.append(tuple(0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * s_ + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * s_ ** 2
                                              + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * s_ ** 3) for j in (0, 1)))
                out.append(ctrl[-1])
                return out
            body = spline([(1.0, -1.8), (2.8, -2.8), (3.6, -4.2), (1.6, -5.0), (-1.5, -4.5), (-3.6, -3.7), (-6.5, -4.7),
                           (-9.8, -5.1), (-12.2, -3.4), (-13.0, 0.0), (-12.2, 3.4), (-9.0, 5.0), (-5.5, 4.3), (-3.0, 3.4),
                           (-1.0, 3.9), (0.9, 3.5), (0.7, 2.0), (1.0, 1.8)])
            outline = body + [(13.0, 1.7), (17.6, 2.4), (21.0, 0.0), (18.6, -3.0), (13.0, -1.7), (1.0, -1.8)]
            dr.line([pt(x, y) for x, y in outline], fill=colour, width=t, joint="curve")
            dr.line([pt(13.0, -1.7), pt(13.0, 1.7)], fill=colour, width=t)          # Sattel
            for x, y in ((14.8, -2.2), (16.2, -2.5), (17.6, -2.8)):                   # Mechaniken
                dr.line([pt(x, y), pt(x + 0.4, y - 1.8)], fill=colour, width=t)
            for x in (-2.5, -5.0):                                                    # Tonabnehmer
                dr.line([pt(x, -2.4), pt(x, 2.4)], fill=colour, width=t)
            for x, y in ((-8.0, 2.6), (-9.8, 1.4)):                                   # Regler
                px_, py_ = pt(x, y)
                dr.ellipse([px_ - 0.8 * u, py_ - 0.8 * u, px_ + 0.8 * u, py_ + 0.8 * u], fill=colour)
    return _image(("ic", kind, colour, size), size, size, d)


def pedal_img(w, h):
    """Expression-Pedal von oben (Hardware-Dialog)."""
    def d(dr, W, H):
        u = W / 80.0
        cx = W / 2
        dr.rounded_rectangle([cx - 30 * u, 6 * u, cx + 30 * u, H - 6 * u], radius=8 * u, fill="#2a2b31",
                             outline="#4a4c55", width=max(1, int(2 * u)))
        dr.rounded_rectangle([cx - 22 * u, 22 * u, cx + 22 * u, H - 22 * u], radius=5 * u, fill="#15161a")
        n = int((H - 60 * u) / (9 * u))
        for i in range(max(1, n)):
            y = 30 * u + i * 9 * u
            dr.line([cx - 16 * u, y, cx + 16 * u, y], fill="#2f3037", width=max(1, int(3 * u)))
        dr.text((cx - 3 * u, H / 2), "HEADRUSH", fill="#4a4c55", anchor="mm")
    return _image(("pd", w, h), w, h, d)


def model_img(name, model=None, w=84, h=59, dim=False, fit=False):
    """Flaches Modell-Symbol (symbole.py) fuer Block `name` und Amp-/Cab-Modell `model`,
    Seitenverhaeltnis 10:7; dim = abgeblendet (Block aus). fit=True: das Symbol wird auf
    seinen sichtbaren Inhalt beschnitten und so gross wie moeglich in w x h eingepasst
    (schmale Treter fuellen die Hoehe, breite Amps die Breite) - fuer die Signalkette."""
    look = symbole.look_for(base_name(name or ""), model)
    if not fit:
        return _image(("md", name, model, w, h, dim), w, h, lambda dr, W, H: symbole.zeichnen(dr, W, H, look),
                      alpha=0.4 if dim else None)

    def draw(dr, W, H):
        big = Image.new("RGBA", (W * 2, int(W * 1.4)), (0, 0, 0, 0))   # 10:7, doppelt so gross wie noetig
        symbole.zeichnen(ImageDraw.Draw(big), big.width, big.height, look)
        box = big.getbbox()
        if not box:
            return
        part = big.crop(box)
        k = min(W / part.width, H / part.height)
        part = part.resize((max(1, int(part.width * k)), max(1, int(part.height * k))), Image.LANCZOS)
        dr.pic.alpha_composite(part, ((W - part.width) // 2, (H - part.height) // 2))
    return _image(("mf", name, model, w, h, dim), w, h, draw, alpha=0.4 if dim else None)


def shadow_img(w, h, r, spread):
    """Weicher Schatten unter einer abgerundeten Flaeche w x h (Bild ist um spread groesser)."""
    key = ("sh", w, h, r, spread)
    im = _IMAGES.get(key)
    if im is None:
        from PIL import ImageFilter
        pic = Image.new("RGBA", (w + 2 * spread, h + 2 * spread), (0, 0, 0, 0))
        ImageDraw.Draw(pic).rounded_rectangle([spread, spread + spread // 3, spread + w, spread + h + spread // 3],
                                              radius=r, fill=(0, 0, 0, 150))
        im = ImageTk.PhotoImage(pic.filter(ImageFilter.GaussianBlur(max(1, spread / 2))))
        _IMAGES[key] = im
    return im


# ---------------- Eigener Fensterrahmen ----------------
_WNDPROCS = []   # Rueckruf-Objekte am Leben halten (sonst stuerzt Windows beim naechsten Ereignis ab)


def _hwnd(top):
    """Aeusseres Windows-Fenster (Tk-'wrapper') eines Toplevels. GetAncestor statt GetParent:
    bei Dialogen (transient) liefert GetParent je nach Zustand den Besitzer (das Hauptfenster)."""
    return ctypes.windll.user32.GetAncestor(top.winfo_id(), 2)   # GA_ROOT


def native_frameless(top):
    """Windows-Titelleiste und -Rahmen eines Toplevels ausblenden, ohne overrideredirect: das
    Fenster bleibt ein normales Fenster (Taskleiste, Alt+Tab, Minimieren, Aero Snap, Schatten und
    runde Ecken unter Windows 11). Technik: die Fensterprozedur wird unterklassiert und
    WM_NCCALCSIZE macht das ganze Fenster zur Client-Flaeche; maximiert wird auf den Arbeits-
    bereich des Monitors begrenzt (sonst ragt das Fenster um die Rahmenbreite ueber den Rand).
    Gibt True zurueck, wenn es geklappt hat."""
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes
        user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
        if not getattr(top, "_frameless_watch", False):
            # Tk erzeugt das aeussere Fenster bei manchen Aufrufen neu (z. B. resizable()), dann ist
            # die Unterklasse weg: bei jedem Anzeigen/Groessenwechsel pruefen und nachholen
            top._frameless_watch = True
            top._frameless_hwnd = None

            def check(e=None):
                if e is not None and e.widget is not top:
                    return
                try:
                    if top.winfo_ismapped() and _hwnd(top) != top._frameless_hwnd:
                        top.after(30, lambda: native_frameless(top))
                except tk.TclError:
                    pass
            top.bind("<Map>", check, add="+")
            top.bind("<Configure>", check, add="+")
        top.update_idletasks()
        if not top.winfo_ismapped():   # noch nicht sichtbar: <Map> holt es nach
            return True
        hwnd = _hwnd(top)
        if hwnd == top._frameless_hwnd:
            return True
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM,
                                           wintypes.LPARAM]
        user32.CallWindowProcW.restype = LRESULT
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD)]
        old = [None]

        def proc(h, msg, wp, lp):
            try:
                if msg == 0x0083 and wp:   # WM_NCCALCSIZE: kein Rahmen, keine Titelleiste
                    if user32.IsZoomed(h):
                        mi = MONITORINFO()
                        mi.cbSize = ctypes.sizeof(MONITORINFO)
                        if user32.GetMonitorInfoW(user32.MonitorFromWindow(h, 2), ctypes.byref(mi)):
                            ctypes.cast(lp, ctypes.POINTER(wintypes.RECT))[0] = mi.rcWork
                    return 0
            except Exception:
                pass
            return user32.CallWindowProcW(old[0], h, msg, wp, lp)
        cb = WNDPROC(proc)
        _WNDPROCS.append(cb)
        old[0] = user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(cb, ctypes.c_void_p))   # GWLP_WNDPROC
        if not old[0]:
            return False
        for attr, val in ((20, 1),                                   # dunkler Modus
                          (33, 2),                                   # runde Ecken (Windows 11)
                          (34, int(LINE[5:7] + LINE[3:5] + LINE[1:3], 16))):   # Rahmenfarbe (COLORREF)
            v = ctypes.c_int(val)
            try:
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
            except Exception:
                pass
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)   # SWP_FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER
        top._frameless_hwnd = hwnd
        return True
    except Exception:
        return False


def _nc_drag(top, ht):
    """Die native Fensterbewegung/Groessenaenderung starten (ht = HTCAPTION, HTLEFT, ...).
    Nur einstellen (PostMessage), nicht SendMessage: die modale Schleife von Windows darf nicht
    in einem Python-Rueckruf laufen, sonst stuerzt _tkinter bei verschachtelten Tk-Ereignissen ab
    (PyEval_RestoreThread ohne Thread-Zustand). So startet sie aus der Tk-Hauptschleife."""
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    user32.ReleaseCapture()
    user32.PostMessageW(_hwnd(top), 0x00A1, ht, (pt.y & 0xFFFF) << 16 | (pt.x & 0xFFFF))   # WM_NCLBUTTONDOWN


class TitleBar(tk.Frame):
    """Eigene Titelleiste im Stil der Oberflaeche: Name links, Minimieren/Maximieren/Schliessen
    rechts; Ziehen bewegt das Fenster (mit Aero Snap), Doppelklick maximiert. Legt auch die
    unsichtbaren Griffe an den Raendern fuer die Groessenaenderung an. Ohne Windows (oder wenn
    native_frameless scheitert) wird die Leiste nicht gezeigt; .active sagt, ob sie aktiv ist."""
    H = 34
    GRIP = 5
    _CURSORS = {"n": "size_ns", "s": "size_ns", "w": "size_we", "e": "size_we",
                "nw": "size_nw_se", "se": "size_nw_se", "ne": "size_ne_sw", "sw": "size_ne_sw"}
    _HT = {"w": 10, "e": 11, "n": 12, "nw": 13, "ne": 14, "s": 15, "sw": 16, "se": 17}

    def __init__(self, top, title="", on_close=None, logo=None, logo_w=60, buttons=("winclose", "maximize", "minimize"),
                 font=FONT_SMALL, fg=MUTED, bg=BG):
        super().__init__(top, bg=bg, height=px(self.H))
        self.top, self.on_close, self.bg = top, on_close or top.destroy, bg
        self.active = native_frameless(top)
        if not self.active:
            return
        self.pack_propagate(False)
        self._press = None
        drag = [self]
        if logo:   # Schriftzug links, so breit wie die Symbolleiste darunter
            lf = tk.Frame(self, bg=BG, width=px(logo_w))
            lf.pack(side="left", fill="y")
            lf.pack_propagate(False)
            ll = tk.Label(lf, text=logo, bg=BG, fg=ACCENT, font=("Segoe UI", 13, "bold"))
            ll.pack(expand=True)
            drag += [lf, ll]
        self.lbl = tk.Label(self, text=title, bg=bg, fg=fg, font=font, anchor="w")
        self.lbl.pack(side="left", fill="x", expand=True, padx=(px(6) if logo else px(20), 0))
        drag.append(self.lbl)
        self.btns = {}
        for kind in buttons:
            c = tk.Canvas(self, width=px(46), height=px(self.H), bg=bg, highlightthickness=0)
            c.pack(side="right")
            c.bind("<Enter>", lambda e, k=kind: self._btn(k, True))
            c.bind("<Leave>", lambda e, k=kind: self._btn(k, False))
            c.bind("<ButtonRelease-1>", lambda e, k=kind: self._click(k, e))
            self.btns[kind] = c
            self._btn(kind, False)
        for w in drag:
            self.drag_from(w)
        self.grips = {}
        for side in self._HT:
            g = tk.Frame(top, bg=bg, cursor=self._CURSORS[side])
            g.bind("<Button-1>", lambda e, s=side: _nc_drag(self.top, self._HT[s]))
            self.grips[side] = g
        top.bind("<Configure>", self._on_configure, add="+")
        self._zoomed = None
        self.after(50, self._on_configure)

    def drag_from(self, w):
        """Widget w (z. B. eine Kopfzeile) bewegt beim Ziehen das Fenster, Doppelklick maximiert."""
        w.bind("<Button-1>", lambda e: setattr(self, "_press", (e.x_root, e.y_root)), add="+")
        w.bind("<B1-Motion>", self._motion, add="+")
        w.bind("<ButtonRelease-1>", lambda e: setattr(self, "_press", None), add="+")
        w.bind("<Double-Button-1>", lambda e: self.toggle_max(), add="+")

    def _motion(self, e):
        if self._press and (abs(e.x_root - self._press[0]) > 3 or abs(e.y_root - self._press[1]) > 3):
            self._press = None
            _nc_drag(self.top, 2)   # HTCAPTION: native Bewegung (Aero Snap, aus Maximiert herausziehen)

    def set_title(self, text):
        if self.active:
            self.lbl.configure(text=text)

    def zoomed(self):
        try:
            return self.top.state() == "zoomed"
        except tk.TclError:
            return False

    def toggle_max(self):
        self.top.state("normal" if self.zoomed() else "zoomed")

    def _click(self, kind, e):
        c = self.btns[kind]
        if not (0 <= e.x < c.winfo_width() and 0 <= e.y < c.winfo_height()):
            return
        if kind == "winclose":
            self.on_close()
        elif kind == "maximize":
            self.toggle_max()
        else:
            self.top.iconify()

    def _btn(self, kind, hover):
        c = self.btns.get(kind)
        if c is None:
            return
        c.delete("all")
        w, h = px(46), px(self.H)
        if hover:
            c.create_rectangle(0, 0, w, h, fill=DANGER if kind == "winclose" else CARD_HI, width=0)
        icon = "restore" if kind == "maximize" and self.zoomed() else kind
        n = px(16)
        c.create_image(w // 2 - n // 2, h // 2 - n // 2, anchor="nw",
                       image=icon_img(icon, "#ffffff" if hover and kind == "winclose" else (TEXT if hover else MUTED), n))

    def _on_configure(self, e=None):
        if e is not None and e.widget is not self.top:
            return
        z = self.zoomed()
        if z == self._zoomed:
            return
        self._zoomed = z
        self._btn("maximize", False)
        g, B = self.grips, px(self.GRIP)
        if z:   # maximiert: keine Griffe
            for f in g.values():
                f.place_forget()
            return
        g["n"].place(x=B, y=0, relwidth=1, width=-2 * B, height=B)
        g["s"].place(x=B, rely=1, y=-B, relwidth=1, width=-2 * B, height=B)
        g["w"].place(x=0, y=B, relheight=1, height=-2 * B, width=B)
        g["e"].place(relx=1, x=-B, y=B, relheight=1, height=-2 * B, width=B)
        g["nw"].place(x=0, y=0, width=B * 2, height=B * 2)
        g["ne"].place(relx=1, x=-2 * B, y=0, width=B * 2, height=B * 2)
        g["sw"].place(x=0, rely=1, y=-2 * B, width=B * 2, height=B * 2)
        g["se"].place(relx=1, x=-2 * B, rely=1, y=-2 * B, width=B * 2, height=B * 2)
        for f in g.values():
            f.lift()


# ---------------- Aufklappfenster (Kontextmenue, Farbwahl) ----------------
class _Popup(tk.Toplevel):
    """Randloses Aufklappfenster mit runden Ecken (Windows: Transparenzfarbe KEY). Schliesst bei
    Escape, bei einem Klick daneben und wenn der Fokus die Familie (Menue + Untermenue) verlaesst."""
    KEY = "#010203"

    def __init__(self, parent, owner=None):
        super().__init__(parent)
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=self.KEY)
        try:
            self.wm_attributes("-transparentcolor", self.KEY)
            self.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        self.owner = owner       # uebergeordnetes Menue (Untermenue) oder None
        self.child = None
        self.c = tk.Canvas(self, bg=self.KEY, highlightthickness=0, bd=0)
        self.c.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda e: self.close_all())
        self.bind("<FocusOut>", lambda e: self.after(60, self._check_focus))

    def family(self):
        out, p = [], self
        while p.owner is not None:
            p = p.owner
        while p is not None:
            out.append(p)
            p = p.child
        return out

    def _check_focus(self):
        if not self.winfo_exists():
            return
        try:
            f = self.focus_get()
        except (KeyError, tk.TclError):
            f = None
        fam = self.family()
        if f is None or f.winfo_toplevel() not in fam:
            self.close_all()

    def close(self):
        if self.child is not None:
            self.child.close()
        if self.owner is not None and self.owner.child is self:
            self.owner.child = None
        try:
            self.destroy()
        except tk.TclError:
            pass

    def close_all(self):
        p = self
        while p.owner is not None:
            p = p.owner
        p.close()

    def show_at(self, x, y, w, h, above=None):
        """Bei (x, y) zeigen, am Hauptbildschirm nicht ueber den Rand hinaus; above = y-Kante,
        ueber der das Fenster erscheint, wenn es unten nicht passt."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if x < sw and x + w > sw:
            x = max(0, sw - w)
        if y < sh and y + h > sh:
            y = max(0, (above if above is not None else sh) - h)
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.c.configure(width=w, height=h)
        self.deiconify()
        self.lift()
        self.focus_force()

    def _bg(self, w, h):
        rrect(self.c, 0, 0, w, h, px(8), CARD, LINE, 1)


class PopupMenu(_Popup):
    """Kontextmenue im Stil der Oberflaeche (ersetzt tk.Menu, gleiche Grundbefehle):
    add_command(label, command, state, swatch=Farbe), add_separator(), add_cascade(label, menu),
    tk_popup(x, y). Befehle laufen erst nach dem Schliessen."""

    def __init__(self, parent, owner=None):
        super().__init__(parent, owner)
        self.items = []
        self.rows = []           # (y0, y1, index)
        self.hover = None
        self.min_w = 0
        self.c.bind("<Motion>", self._motion)
        self.c.bind("<Leave>", lambda e: self._set_hover(None) if self.child is None else None)
        self.c.bind("<ButtonRelease-1>", self._release)
        self.bind("<Up>", lambda e: self._step(-1))
        self.bind("<Down>", lambda e: self._step(1))
        self.bind("<Return>", lambda e: self._activate(self.hover))
        self.bind("<Right>", lambda e: self._open_child(self.hover))
        self.bind("<Left>", lambda e: self.close() if self.owner else None)

    # tk.Menu-kompatible Befehle
    def add_command(self, label="", command=None, state="normal", swatch=None, foreground=None, **_):
        self.items.append({"kind": "cmd", "label": label, "command": command, "state": state,
                           "swatch": swatch or foreground})

    def add_separator(self):
        self.items.append({"kind": "sep"})

    def add_cascade(self, label="", menu=None, state="normal", **_):
        if menu is not None:
            menu.owner = self
        self.items.append({"kind": "cascade", "label": label, "menu": menu, "state": state, "swatch": None})

    def tk_popup(self, x, y, min_width=0):
        self.min_w = min_width
        w, h = self._measure()
        self._draw(w, h)
        self.show_at(int(x), int(y), w, h)

    def post(self, x, y):
        self.tk_popup(x, y)

    def close(self):
        super().close()
        for it in self.items:   # nie geoeffnete Untermenues (verborgene Fenster) mit aufraeumen
            if it.get("menu") is not None and it["menu"].winfo_exists():
                it["menu"].close()

    # Aufbau
    ROW, SEP, PAD = 30, 9, 6

    def _measure(self):
        f = tkfont.Font(font=FONT)
        sw = any(it.get("swatch") for it in self.items)
        tw = max([f.measure(it["label"]) for it in self.items if it["kind"] != "sep"] or [80])
        w = max(self.min_w, px(190), tw + px(28) + (px(22) if sw else 0)
                + (px(20) if any(it["kind"] == "cascade" for it in self.items) else 0))
        h = 2 * px(self.PAD) + sum(px(self.SEP) if it["kind"] == "sep" else px(self.ROW) for it in self.items)
        return w, h

    def _enabled(self, i):
        return i is not None and self.items[i]["kind"] != "sep" and self.items[i].get("state") != "disabled"

    def _draw(self, w=None, h=None):
        c = self.c
        w = w or c.winfo_reqwidth()
        h = h or c.winfo_reqheight()
        c.delete("all")
        self._bg(w, h)
        y = px(self.PAD)
        self.rows = []
        for i, it in enumerate(self.items):
            if it["kind"] == "sep":
                c.create_line(px(12), y + px(self.SEP) / 2, w - px(12), y + px(self.SEP) / 2, fill=LINE)
                y += px(self.SEP)
                continue
            rh = px(self.ROW)
            on = self._enabled(i)
            if i == self.hover and on:
                rrect(c, px(5), y + px(1), w - px(10), rh - px(2), px(6), CARD_HI)
            x = px(14)
            if it.get("swatch"):
                rrect(c, x, y + rh / 2 - px(7), px(14), px(14), px(4), it["swatch"])
                x += px(22)
            c.create_text(x, y + rh / 2, text=it["label"], anchor="w", font=FONT,
                          fill=(TEXT if i != self.hover else "#ffffff") if on else DIM)
            if it["kind"] == "cascade":
                c.create_text(w - px(14), y + rh / 2, text="›", anchor="e", font=FONT_BOLD, fill=MUTED if on else DIM)
            self.rows.append((y, y + rh, i))
            y += rh

    def _index_at(self, y):
        for y0, y1, i in self.rows:
            if y0 <= y < y1:
                return i
        return None

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self._draw()

    def _motion(self, e):
        i = self._index_at(e.y)
        if i == self.hover:
            return
        self._set_hover(i)
        if self.child is not None and (i is None or self.items[i].get("menu") is not self.child):
            self.child.close()
            self.focus_force()
        if i is not None and self.items[i]["kind"] == "cascade":
            self.after(120, lambda: self._open_child(i) if self.hover == i else None)

    def _step(self, d):
        idx = [i for i in range(len(self.items)) if self._enabled(i)]
        if not idx:
            return
        cur = idx.index(self.hover) if self.hover in idx else (-1 if d > 0 else 0)
        self._set_hover(idx[(cur + d) % len(idx)])

    def _open_child(self, i):
        if not self._enabled(i) or self.items[i]["kind"] != "cascade" or not self.winfo_exists():
            return
        sub = self.items[i]["menu"]
        if sub is None or sub is self.child:
            return
        if self.child is not None:
            self.child.close()
        self.child = sub
        y0 = next(y for y, _, j in self.rows if j == i)
        w, h = sub._measure()
        sub._draw(w, h)
        sub.show_at(self.winfo_rootx() + self.winfo_width() - px(4), self.winfo_rooty() + y0 - px(self.PAD), w, h)

    def _release(self, e):
        self._activate(self._index_at(e.y))

    def _activate(self, i):
        if not self._enabled(i):
            return
        it = self.items[i]
        if it["kind"] == "cascade":
            self._open_child(i)
            return
        root, cmd = self._root(), it.get("command")
        self.close_all()
        if cmd:
            root.after(1, cmd)


def menu(parent):
    """Kontextmenue im Stil der Oberflaeche."""
    return PopupMenu(parent)


class SwatchPopup(_Popup):
    """Farbwahl als Feld farbiger Kaestchen (wie die Palette im Hardware-Feld); darunter der Name
    der Farbe unter der Maus. names: Farbnamen des Geraets, on_pick(name)."""

    def __init__(self, parent, names, current, on_pick, cols=5):
        super().__init__(parent)
        self.names, self.current, self.on_pick = list(names), current, on_pick
        self.cols = max(1, min(cols, len(self.names)))
        self.cell, self.gap, self.pad = px(30), px(6), px(12)
        self.hover = None
        self.c.bind("<Motion>", lambda e: self._set_hover(self._at(e.x, e.y)))
        self.c.bind("<Leave>", lambda e: self._set_hover(None))
        self.c.bind("<ButtonRelease-1>", lambda e: self._pick(self._at(e.x, e.y)))

    def popup(self, x, y, above=None):
        rows = (len(self.names) + self.cols - 1) // self.cols
        w = 2 * self.pad + self.cols * self.cell + (self.cols - 1) * self.gap
        h = 2 * self.pad + rows * self.cell + (rows - 1) * self.gap + px(26)
        self.c.configure(width=w, height=h)
        self._draw(w, h)
        self.show_at(int(x), int(y), w, h, above)

    def _at(self, x, y):
        k = self.cell + self.gap
        c, r = int((x - self.pad) // k), int((y - self.pad) // k)
        if 0 <= c < self.cols and r >= 0 and (x - self.pad) % k < self.cell and (y - self.pad) % k < self.cell:
            i = r * self.cols + c
            return i if i < len(self.names) else None
        return None

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self._draw(self.c.winfo_reqwidth(), self.c.winfo_reqheight())

    def _draw(self, w, h):
        c = self.c
        c.delete("all")
        self._bg(w, h)
        for i, name in enumerate(self.names):
            x = self.pad + (i % self.cols) * (self.cell + self.gap)
            y = self.pad + (i // self.cols) * (self.cell + self.gap)
            sel, hov = name == self.current, i == self.hover
            rrect(c, x, y, self.cell, self.cell, px(7), COLOURS.get(name, COLOURS["Off"]),
                  "#ffffff" if sel else (ACCENT if hov else None), 2 if sel or hov else 0)
        name = self.names[self.hover] if self.hover is not None else self.current
        c.create_text(w / 2, h - self.pad - px(6), text=name or "", fill=TEXT if self.hover is not None else MUTED,
                      font=FONT_SMALL)

    def _pick(self, i):
        if i is None:
            return
        name, root = self.names[i], self._root()
        self.close_all()
        root.after(1, lambda: self.on_pick(name))


# ---------------- Overlay (Dialog im Fenster, Hintergrund unscharf) ----------------
_ROOT = None     # Hauptfenster (setup), Ziel der Meldungen ohne parent


def _backdrop(top):
    """Bildschirmfoto des Fensterinhalts, verkleinert, weichgezeichnet und abgedunkelt (oder None)."""
    try:
        from PIL import ImageGrab, ImageFilter
        x, y, w, h = top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height()
        im = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).convert("RGB")
    except Exception:
        return None
    small = im.resize((max(1, w // 3), max(1, h // 3)), Image.BOX).filter(ImageFilter.GaussianBlur(2.2))
    return Image.blend(small, Image.new("RGB", small.size, BG), 0.45)


class Overlay(tk.Canvas):
    """Dialog als Ebene ueber dem ganzen Fenster: der Fensterinhalt dahinter wird leicht unscharf und
    dunkler gezeigt, in der Mitte eine abgerundete Karte mit Titel, x und Inhalt in .body.
    modal: run() wartet auf close(result) und sperrt den Rest. click_out: Klick neben die Karte schliesst."""

    def __init__(self, parent, title=None, width=None, height=None, click_out=False, blur=True, closable=True):
        top = (parent or _ROOT).winfo_toplevel()
        top.update_idletasks()
        self._small = _backdrop(top) if blur and Image is not None else None
        super().__init__(top, bg=blend(BG, "#000000", 0.6), highlightthickness=0, bd=0, cursor="")
        self.result = None
        self.fixed_w = px(width) if width else None
        self.fixed_h = px(height) if height else None
        self.pad, self.r = px(22), px(14)
        self._photo = None
        self._size = None
        self.card = tk.Frame(self, bg=PANEL)
        if title or closable:
            head = tk.Frame(self.card, bg=PANEL)
            head.pack(fill="x", pady=(0, px(10)))
            self.lbl_title = tk.Label(head, text=title or "", bg=PANEL, fg=TEXT, font=FONT_HEAD, anchor="w")
            self.lbl_title.pack(side="left")
            if closable:
                x = tk.Canvas(head, width=px(26), height=px(26), bg=PANEL, highlightthickness=0, cursor="hand2")
                x.pack(side="right")
                self._x_btn(x, False)
                x.bind("<Enter>", lambda e: self._x_btn(x, True))
                x.bind("<Leave>", lambda e: self._x_btn(x, False))
                x.bind("<Button-1>", lambda e: self.cancel())
        self.body = tk.Frame(self.card, bg=PANEL)
        self.body.pack(fill="both", expand=True)
        self._win = self.create_window(0, 0, window=self.card, anchor="nw")
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.raise_()
        self.bind("<Configure>", lambda e: self._layout())
        self.card.bind("<Configure>", lambda e: self._layout())
        self.bind("<Escape>", lambda e: self.cancel())
        if click_out:
            self.bind("<Button-1>", self._click_out)
        self.focus_set()

    def _x_btn(self, c, hover):
        c.delete("all")
        s = px(26)
        if hover:
            circle(c, s / 2, s / 2, s, CARD_HI)
        n = px(16)
        c.create_image(s / 2 - n / 2, s / 2 - n / 2, anchor="nw", image=icon_img("close", TEXT if hover else MUTED, n))

    def raise_(self):
        self.tk.call("raise", self._w)

    def _layout(self):
        W, H = self.winfo_width(), self.winfo_height()
        if W < 2 or H < 2:
            return
        cw = min(self.fixed_w, W - 2 * self.pad - px(32)) if self.fixed_w else self.card.winfo_reqwidth()
        ch = min(self.fixed_h, H - 2 * self.pad - px(32)) if self.fixed_h else self.card.winfo_reqheight()
        bw, bh = cw + 2 * self.pad, ch + 2 * self.pad
        x, y = max(px(16), (W - bw) // 2), max(px(16), (H - bh) // 2)
        self.box = (x, y, x + bw, y + bh)
        self.delete("bg")
        if self._small is not None:
            if self._size != (W, H):
                self._photo = ImageTk.PhotoImage(self._small.resize((W, H), Image.BILINEAR))
                self._size = (W, H)
            self.create_image(0, 0, anchor="nw", image=self._photo, tags="bg")
        sp = px(18)
        self.create_image(x - sp, y - sp, anchor="nw", image=shadow_img(bw, bh, self.r, sp), tags="bg")
        rrect(self, x, y, bw, bh, self.r, PANEL, LINE, 1, tags="bg")
        self.coords(self._win, x + self.pad, y + self.pad)
        if self.fixed_w:
            self.itemconfigure(self._win, width=cw)
        if self.fixed_h:
            self.itemconfigure(self._win, height=ch)

    def bind_keys(self, widget=None):
        """Escape (und Enter, falls on_return gesetzt) auch in Eingabefeldern und Listen der Karte."""
        for w in (widget or self.card).winfo_children():
            if isinstance(w, (tk.Entry, tk.Listbox)):
                w.bind("<Escape>", lambda e: self.cancel(), add="+")
            self.bind_keys(w)

    def _click_out(self, e):
        x1, y1, x2, y2 = getattr(self, "box", (0, 0, 0, 0))
        if not (x1 <= e.x <= x2 and y1 <= e.y <= y2):
            self.cancel()

    def cancel(self):
        self.close(None)

    def close(self, result=None):
        self.result = result
        try:
            self.destroy()
        except tk.TclError:
            pass

    def run(self):
        """Modal: bis close(); danach das Ergebnis."""
        prev = self.grab_current()
        self.bind_keys()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.wait_window(self)
        if prev is not None:
            try:
                if prev.winfo_exists():
                    prev.grab_set()
            except tk.TclError:
                pass
        return self.result


WARN = "#f2b33d"
_ICONS = {"info": ("i", ACCENT), "warning": ("!", WARN), "error": ("!", DANGER), "question": ("?", ACCENT)}


def ask(parent, text, buttons, title=None, icon="question", detail=None, cancel=None, width=460):
    """Meldung/Rueckfrage als Overlay. text: erste Zeile fett, Rest gedaempft; buttons:
    [(Beschriftung, Wert, Art)] von links nach rechts (Art: ghost/default/primary/danger).
    Enter = der primary-Knopf, Escape/x = cancel. Gibt den Wert des Knopfes zurueck."""
    ov = Overlay(parent, title, width=width)
    row = tk.Frame(ov.body, bg=PANEL)
    row.pack(fill="x")
    sym, col = _ICONS.get(icon, _ICONS["info"])
    ic = tk.Canvas(row, width=px(34), height=px(34), bg=PANEL, highlightthickness=0)
    ic.pack(side="left", anchor="n", padx=(0, px(14)))
    circle(ic, px(17), px(17), px(34), blend(col, PANEL, 0.22))
    ic.create_text(px(17), px(17), text=sym, fill=col, font=("Segoe UI", 13, "bold"))
    tf = tk.Frame(row, bg=PANEL)
    tf.pack(side="left", fill="x", expand=True)
    head, _, rest = text.partition("\n")
    wrap = px(width) - px(48)
    tk.Label(tf, text=head, bg=PANEL, fg=TEXT, font=FONT_BOLD, anchor="w", justify="left", wraplength=wrap).pack(fill="x")
    rest = "\n".join(p for p in (rest.strip("\n"), detail) if p)
    if rest:
        tk.Label(tf, text=rest, bg=PANEL, fg=MUTED, anchor="w", justify="left", wraplength=wrap).pack(
            fill="x", pady=(px(4), 0))
    bf = tk.Frame(ov.body, bg=PANEL)
    bf.pack(fill="x", pady=(px(20), 0))
    primary = None
    for label, value, kind in reversed(buttons):
        Btn(bf, label, command=lambda v=value: ov.close(v), kind=kind, padx=14, pady=6).pack(side="right", padx=(px(8), 0))
        if kind == "primary" and primary is None:
            primary = value
    ov.cancel = lambda: ov.close(cancel)
    ov.bind("<Return>", lambda e: ov.close(primary if primary is not None else cancel))
    return ov.run()


class _MessageBox:
    """Ersatz fuer tkinter.messagebox im Stil der Oberflaeche (gleiche Aufrufe)."""

    @staticmethod
    def _title(title):
        return None if not title or title.startswith("MX5 Editor") else title

    def showinfo(self, title=None, message="", parent=None, **_):
        ask(parent, message, [("OK", True, "primary")], self._title(title), "info", cancel=True)

    def showwarning(self, title=None, message="", parent=None, **_):
        ask(parent, message, [("OK", True, "primary")], self._title(title), "warning", cancel=True)

    def showerror(self, title=None, message="", parent=None, **_):
        ask(parent, message, [("OK", True, "primary")], self._title(title), "error", cancel=True)

    def askyesno(self, title=None, message="", parent=None, **_):
        return bool(ask(parent, message, [("No", False, "ghost"), ("Yes", True, "primary")], self._title(title),
                        cancel=False))

    def askyesnocancel(self, title=None, message="", parent=None, **_):
        return ask(parent, message, [("Cancel", None, "ghost"), ("No", False, "default"), ("Yes", True, "primary")],
                   self._title(title), cancel=None)


messagebox = _MessageBox()


def wrap_words(text, width, max_lines=3):
    """Text an Wortgrenzen auf Zeilen von hoechstens `width` Zeichen umbrechen."""
    lines, cur = [], ""
    for w in text.split():
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:width - 1] + "…"
    return [l if len(l) <= width else l[:width - 1] + "…" for l in lines]


def text_on(colour):
    """Dunkle oder helle Schrift fuer eine Flaeche der Farbe '#rrggbb'."""
    try:
        r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    except (TypeError, ValueError):
        return TEXT
    return "#101114" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else "#ffffff"


def blend(colour, other, t):
    """Mischfarbe: Anteil t (0-1) von colour, Rest other (beide '#rrggbb')."""
    try:
        a = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    except (TypeError, ValueError):
        return other
    return "#%02x%02x%02x" % tuple(int(round(x * t + y * (1 - t))) for x, y in zip(a, b))


def text_size(text, font):
    f = tkfont.Font(font=font)
    return f.measure(text), f.metrics("linespace")


# ---------------- Einfache Widgets ----------------
class Panel(tk.Canvas):
    """Abgerundete Flaeche; Inhalt kommt in .inner (mit seitlichem Rand von r Pixeln)."""

    def __init__(self, parent, fill=PANEL, r=10, **kw):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, **kw)
        self.fill, self.r = fill, px(r)
        self.inner = tk.Frame(self, bg=fill)
        self.bind("<Configure>", self._layout)

    def _layout(self, e):
        self.delete("bg")
        rrect(self, 0, 0, e.width, e.height, self.r, self.fill, tags="bg")
        self.inner.place(x=self.r, y=0, width=max(1, e.width - 2 * self.r), height=e.height)


class Btn(tk.Canvas):
    """Abgerundeter Knopf. kind: default (dunkle Karte), primary (Akzent), ghost (nur Text), danger.
    icon = Name eines icon_img-Symbols statt Text (Knopf so hoch wie mit Text, quadratisch)."""
    KINDS = {"default": (CARD, TEXT, CARD_HI, TEXT), "primary": (ACCENT, ACCENT_TXT, ACCENT_HI, ACCENT_TXT),
             "ghost": (None, MUTED, None, TEXT), "danger": (CARD, TEXT, DANGER, TEXT)}

    def __init__(self, parent, text, command=None, kind="default", padx=12, pady=5, font=FONT, width=None,
                 state="normal", r=6, anchor="center", icon=None):
        self.kind, self.command, self.font, self.text = kind, command, font, text
        self.icon = icon
        self.anchor = anchor
        self.padx, self.pady, self.r = px(padx), px(pady), px(r)
        self.min_w = px(width) if width else 0
        self.hover = False
        self._state = state
        self.base_bg, self.base_fg, self.hover_bg, self.hover_fg = self.KINDS[kind]
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self._size()
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<Button-1>", self._click)

    def set_kind(self, kind):
        self.kind = kind
        self.base_bg, self.base_fg, self.hover_bg, self.hover_fg = self.KINDS[kind]
        self.redraw()

    def _size(self):
        tw, th = text_size(self.text or "M", self.font)
        self.h = th + 2 * self.pady
        self.w = max(self.min_w, self.h if self.icon else tw + 2 * self.padx)
        super().configure(width=self.w, height=self.h)
        self.redraw()

    def _hover(self, on):
        self.hover = on
        self.redraw()

    def _click(self, _):
        if self._state != "disabled" and self.command:
            self.command()

    def configure(self, cnf=None, **kw):
        if "text" in kw:
            self.text = kw.pop("text")
            self._size()
        if "state" in kw:
            self._state = kw.pop("state")
            self.redraw()
        if "command" in kw:
            self.command = kw.pop("command")
        if kw or cnf:
            super().configure(cnf, **kw)
    config = configure

    def cget(self, key):
        if key == "text":
            return self.text
        if key == "state":
            return self._state
        return super().cget(key)

    def redraw(self):
        self.delete("all")
        disabled = self._state == "disabled"
        bg, fg = self.base_bg, self.base_fg
        if disabled:
            bg, fg = (CARD if self.kind == "primary" else self.base_bg), DIM
        elif self.hover:
            bg, fg = self.hover_bg or self.base_bg, self.hover_fg
        if bg:
            rrect(self, 0, 0, self.w, self.h, self.r, bg)
        if self.icon:
            n = int(self.h * 0.62)
            self.create_image(self.w / 2 - n / 2, self.h / 2 - n / 2, anchor="nw", image=icon_img(self.icon, fg, n))
        elif self.anchor == "w":
            self.create_text(self.padx, self.h / 2, text=self.text, fill=fg, font=self.font, anchor="w")
        else:
            self.create_text(self.w / 2, self.h / 2, text=self.text, fill=fg, font=self.font)


class Badge(tk.Canvas):
    """Kleine abgerundete Marke mit Text (z. B. 'SCENE MODE' in der Kopfzeile)."""

    def __init__(self, parent, text="", fill=ACCENT, fg=ACCENT_TXT, font=FONT_CARD, padx=10, pady=4, r=6):
        self.fill, self.fg, self.font, self.r = fill, fg, font, px(r)
        self.padx, self.pady = px(padx), px(pady)
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0)
        self.set_text(text)

    def set_text(self, text):
        self.text = text
        tw, th = text_size(text, self.font)
        self.w, self.h = tw + 2 * self.padx, th + 2 * self.pady
        self.configure(width=self.w, height=self.h)
        self.delete("all")
        rrect(self, 0, 0, self.w, self.h, self.r, self.fill)
        self.create_text(self.w / 2, self.h / 2, text=text, fill=self.fg, font=self.font)


class Segmented(tk.Frame):
    """Umschalter mit 2-3 Feldern (z. B. Current | Fixed). on_pick(index)."""

    def __init__(self, parent, options, current=0, on_pick=None, padx=12):
        super().__init__(parent, bg=parent.cget("bg"))
        self.on_pick = on_pick
        self.btns = []
        for i, o in enumerate(options):
            b = Btn(self, o, command=lambda i=i: self.pick(i), kind="default", padx=padx, pady=3, font=FONT_SMALL)
            b.pack(side="left", padx=(0, px(2)))
            self.btns.append(b)
        self.set(current)

    def set(self, i):
        self.current = i
        for j, b in enumerate(self.btns):
            b.set_kind("primary" if j == i else "default")

    def pick(self, i):
        if i != self.current:
            self.set(i)
            if self.on_pick:
                self.on_pick(i)


class Entry(tk.Canvas):
    """Abgerundetes Eingabefeld; die wichtigsten Entry-Methoden werden durchgereicht."""

    def __init__(self, parent, textvariable=None, width=None, placeholder=None, font=FONT, justify="left", r=6):
        self.font, self.r = font, px(r)
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0)
        self.entry = tk.Entry(self, textvariable=textvariable, width=width or 20, bg=CARD, fg=TEXT, insertbackground=TEXT,
                              relief="flat", bd=0, highlightthickness=0, selectbackground=ACCENT,
                              selectforeground=ACCENT_TXT, font=font, justify=justify,
                              disabledbackground=CARD, disabledforeground=DIM)
        tw, th = text_size("0" * (width or 20), font)
        self.w, self.h = tw + px(16), th + px(10)
        super().configure(width=self.w, height=self.h)
        self.bind("<Configure>", self._layout)
        self.placeholder = placeholder
        if placeholder:   # als Label im Entry, weil Canvas-Fenster immer ueber Canvas-Text liegen
            self._ph = tk.Label(self.entry, text=placeholder, bg=CARD, fg=DIM, font=font)
            self._ph.bind("<Button-1>", lambda e: self.entry.focus_set())
        for ev in ("<KeyRelease>", "<FocusIn>", "<FocusOut>"):
            self.entry.bind(ev, self._update_ph, add="+")
        if textvariable is not None:
            textvariable.trace_add("write", lambda *_: self._update_ph())
        self._layout(None)

    def _layout(self, e):
        w = e.width if e else self.w
        h = e.height if e else self.h
        self.cur_w, self.cur_h = w, h
        self.delete("bg")
        rrect(self, 0, 0, w, h, self.r, CARD, LINE, 1, tags="bg")
        self.delete("win")
        self.create_window(px(8), h / 2, window=self.entry, anchor="w", width=max(1, w - px(16)), tags="win")
        self._update_ph()

    def _update_ph(self, _=None):
        if not self.placeholder:
            return
        if not self.entry.get() and self.entry.focus_get() is not self.entry:
            self._ph.place(in_=self.entry, x=1, rely=0.5, anchor="w")
        else:
            self._ph.place_forget()

    # Durchreichen
    def get(self):
        return self.entry.get()

    def insert(self, *a):
        self.entry.insert(*a)
        self._update_ph()

    def clear(self):
        self.entry.delete(0, "end")
        self._update_ph()

    def bind_entry(self, ev, fn):
        self.entry.bind(ev, fn, add="+")

    def focus_entry(self):
        self.entry.focus_set()

    def select_all(self):
        self.entry.select_range(0, "end")

    def set_enabled(self, on):
        self.entry.configure(state="normal" if on else "disabled")


class Toggle(tk.Canvas):
    """Kippschalter (An = Akzentfarbe)."""

    def __init__(self, parent, value=False, command=None, w=40, h=20, bg=None):
        self.w, self.h = px(w), px(h)
        super().__init__(parent, width=self.w, height=self.h, bg=bg or parent.cget("bg"), highlightthickness=0,
                         cursor="hand2")
        self.value, self.command = bool(value), command
        self.bind("<Button-1>", self._click)
        self.redraw()

    def _click(self, _):
        if str(self["state"]) == "disabled":
            return
        self.value = not self.value
        self.redraw()
        if self.command:
            self.command(self.value)

    def set(self, value):
        self.value = bool(value)
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = self.w, self.h
        rrect(self, 0, 0, w, h, h / 2, ACCENT if self.value else DIM)
        d = h - px(6)
        cx = w - h / 2 if self.value else h / 2
        circle(self, cx, h / 2, d, "#ffffff" if self.value else KNOB)


class Slider(tk.Canvas):
    """Regler mit Akzentfuellung. command(wert) beim Ziehen, on_release(wert) beim Loslassen."""

    def __init__(self, parent, from_=0.0, to=1.0, value=0.0, command=None, on_release=None, height=24, bg=None):
        self.pad = px(9)
        self.knob = px(14)
        self.track = px(4)
        # width klein anfordern, damit pack/grid die tatsaechliche Breite bestimmen
        super().__init__(parent, width=px(80), height=px(height), bg=bg or parent.cget("bg"), highlightthickness=0,
                         cursor="hand2")
        self.lo, self.hi = float(from_), float(to)
        self.value = float(value)
        self.command, self.on_release = command, on_release
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)

    def _frac(self):
        span = self.hi - self.lo
        return 0.0 if span <= 0 else max(0.0, min(1.0, (self.value - self.lo) / span))

    def _x_to_value(self, x):
        w = max(1, self.winfo_width() - 2 * self.pad)
        frac = max(0.0, min(1.0, (x - self.pad) / w))
        return self.lo + frac * (self.hi - self.lo)

    def _press(self, e):
        if str(self["state"]) == "disabled":
            return
        self.value = self._x_to_value(e.x)
        self.redraw()
        if self.command:
            self.command(self.value)

    def _move(self, e):
        if str(self["state"]) == "disabled":
            return
        v = self._x_to_value(e.x)
        if v != self.value:
            self.value = v
            self.redraw()
            if self.command:
                self.command(self.value)

    def _release(self, e):
        if str(self["state"]) != "disabled" and self.on_release:
            self.on_release(self.value)

    def set(self, value):
        self.value = float(value)
        self.redraw()

    def get(self):
        return self.value

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 * self.pad + 4:
            return
        y = h / 2
        kx = self.pad + self._frac() * (w - 2 * self.pad)
        t = self.track
        rrect(self, self.pad, y - t / 2, w - 2 * self.pad, t, t / 2, DIM)
        if kx - self.pad >= t:
            rrect(self, self.pad, y - t / 2, kx - self.pad, t, t / 2, ACCENT)
        circle(self, kx, y, self.knob, KNOB, "#9b9ca2", 1)


class LevelMeter(tk.Canvas):
    """Pegelanzeige wie auf der Input-/Output-Seite des Geraets: ein Balken je Kanal (names),
    dB-Skala lo..hi darunter, gruen bis warn, gelb bis clip, rot darueber; Strich = Peak.
    set([(name, current_db, peak_db)]) mit den Werten des Geraets, set(None) = keine Werte."""

    BAR = 10
    GAP = 6
    LABEL = 22
    VALUE = 70

    def __init__(self, parent, names, lo, hi, warn=-6.0, clip=0.0, bg=None):
        self.names, self.lo, self.hi, self.warn, self.clip = list(names), float(lo), float(hi), warn, clip
        self.cur = {n: None for n in self.names}      # geglaettete Anzeige
        self.peak = {n: None for n in self.names}
        h = len(self.names) * (px(self.BAR) + px(self.GAP)) + px(16)
        super().__init__(parent, width=px(80), height=h, bg=bg or parent.cget("bg"), highlightthickness=0)
        self.bind("<Configure>", lambda e: self.redraw())

    def set(self, values):
        if values is None:
            self.cur = {n: None for n in self.names}
            self.peak = {n: None for n in self.names}
        else:
            for name, cur, peak in values:
                old = self.cur.get(name)
                if cur is None or old is None or cur >= old:
                    self.cur[name] = cur                         # steigt sofort
                else:
                    self.cur[name] = old + (cur - old) * 0.35    # faellt weich
                self.peak[name] = peak
        self.redraw()

    def _x(self, db, x0, x1):
        f = (db - self.lo) / (self.hi - self.lo)
        return x0 + max(0.0, min(1.0, f)) * (x1 - x0)

    def _colour(self, db):
        return DANGER if db > self.clip else WARN if db > self.warn else ACCENT

    def redraw(self):
        self.delete("all")
        w = self.winfo_width()
        x0, x1 = px(self.LABEL), w - px(self.VALUE)
        if x1 - x0 < px(40):
            return
        bar, gap = px(self.BAR), px(self.GAP)
        y = 0
        for n in self.names:
            cur, peak = self.cur[n], self.peak[n]
            self.create_text(0, y + bar / 2, text=n, anchor="w", fill=MUTED, font=FONT_TINY)
            rrect(self, x0, y, x1 - x0, bar, px(2), CARD)
            if cur is not None and cur > self.lo:
                xe = self._x(cur, x0, x1)
                # Zonen nacheinander fuellen: gruen .. warn, gelb .. clip, rot
                for a, b, col in ((self.lo, self.warn, ACCENT), (self.warn, self.clip, WARN),
                                  (self.clip, self.hi, DANGER)):
                    xa, xb = self._x(a, x0, x1), min(xe, self._x(b, x0, x1))
                    if xb > xa:
                        self.create_rectangle(xa, y + 1, xb, y + bar - 1, fill=col, outline="")
            if peak is not None and peak > self.lo:
                xp = self._x(peak, x0, x1)
                self.create_rectangle(xp - px(1), y - 1, xp + px(1), y + bar + 1, fill=self._colour(peak), outline="")
            txt = "–" if cur is None or cur <= self.lo else "%.1f dB" % cur
            self.create_text(w, y + bar / 2, text=txt, anchor="e", font=FONT_SMALL,
                             fill=TEXT if cur is not None and cur > self.lo else DIM)
            y += bar + gap
        # Skala
        step = 12 if self.hi - self.lo > 30 else 6
        marks = sorted({self.hi, self.clip, self.warn} | set(
            v for v in range(int(self.lo), int(self.hi) + 1) if v % step == 0))
        placed = [self._x(v, x0, x1) for v in marks if v % step == 0 or v == self.hi]
        for v in marks:
            if not self.lo <= v <= self.hi:
                continue
            x = self._x(v, x0, x1)
            self.create_line(x, y - gap + px(1), x, y - gap + px(4), fill=DIM)
            if v % step and v != self.hi and any(0 < abs(x - o) < px(18) for o in placed):
                continue     # warn/clip-Marke zu nah an einer Skalenzahl: nur Strich
            self.create_text(x, y - gap + px(5), text="%+d" % v if v > 0 else "%d" % v, anchor="n",
                             fill=MUTED if v in (self.clip, self.warn) else DIM, font=FONT_TINY)
        peaks = [p for p in self.peak.values() if p is not None and p > self.lo]
        if peaks:
            pk = max(peaks)
            self.create_text(w, y - gap + px(5), text="peak %.1f" % pk, anchor="ne", font=FONT_TINY,
                             fill=self._colour(pk) if pk > self.warn else MUTED)


class Dropdown(tk.Canvas):
    """Auswahlfeld: zeigt den aktuellen Text, Klick oeffnet ein Menue (kurze Listen) oder
    einen Auswahldialog mit Filter (lange Listen). on_pick(index)."""
    MENU_MAX = 28

    def __init__(self, parent, values, current="", on_pick=None, width=18, title="Choose", on_open=None,
                 font=FONT, r=6):
        self.values = list(values)
        self.on_pick, self.on_open, self.title, self.font = on_pick, on_open, title, font
        self.text, self.r = current, px(r)
        self.hover = False
        self.enabled = True
        tw, th = text_size("0" * width, font)
        self.w, self.h = tw + px(30), th + px(10)
        super().__init__(parent, width=self.w, height=self.h, bg=parent.cget("bg"), highlightthickness=0,
                         cursor="hand2")
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", lambda e: self.open())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, on):
        self.hover = on
        self.redraw()

    def set_text(self, text):
        self.text = text
        self.redraw()

    def set_values(self, values):
        self.values = list(values)

    def set_enabled(self, on):
        self.enabled = on
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 2), max(self.winfo_height(), 2)
        rrect(self, 0, 0, w, h, self.r, CARD, ACCENT if self.hover and self.enabled else LINE, 1)
        fg = TEXT if self.enabled else DIM
        t = self.text
        while t and text_size(t, self.font)[0] > w - px(30):
            t = t[:-2] + "…"
        self.create_text(px(9), h / 2, text=t, fill=fg, font=self.font, anchor="w")
        self.create_text(w - px(10), h / 2, text="▾", fill=MUTED if self.enabled else DIM, font=self.font, anchor="e")

    def open(self):
        if not self.enabled:
            return
        if self.on_open:
            self.on_open()   # liest die Liste nach und ruft ggf. show(values)
            return
        self.show()

    def show(self, values=None):
        """Menue (kurze Liste) oder Auswahldialog mit Filter (lange Liste) zeigen."""
        if values is not None:
            self.set_values(values)
        if not self.values:
            return
        if len(self.values) <= self.MENU_MAX:
            m = menu(self)
            for i, v in enumerate(self.values):
                m.add_command(label=v, command=lambda i=i: self._pick(i))
            m.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + px(2), min_width=self.winfo_width())
            return
        res = ChoiceDialog(self.winfo_toplevel(), self.title, self.values, self.text).result
        if res is not None:
            self._pick(self.values.index(res))

    def _pick(self, i):
        self.set_text(self.values[i])
        if self.on_pick:
            self.on_pick(i)


class Card(tk.Canvas):
    """Abgerundete Karte mit optionaler Ueberschrift und Farbband links; Inhalt in .inner."""

    def __init__(self, parent, title=None, colour=None, fill=CARD, padx=12, pady=10, r=8):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0)
        self.fill, self.colour, self.r = fill, colour, px(r)
        self.padx, self.pady = px(padx), px(pady)
        self.body = tk.Frame(self, bg=fill)
        if title:
            tk.Label(self.body, text=title, bg=fill, fg=TEXT, font=FONT_BOLD, anchor="w").pack(fill="x", pady=(0, px(6)))
        self.inner = tk.Frame(self.body, bg=fill)
        self.inner.pack(fill="both", expand=True)
        self.body.bind("<Configure>", self._fit)
        self.bind("<Configure>", self._layout)

    def _fit(self, _):
        h = self.body.winfo_reqheight() + 2 * self.pady
        if int(self["height"]) != h:
            self.configure(height=h)

    def _layout(self, e):
        self.delete("all")
        w, h = e.width, e.height
        rrect(self, 0, 0, w, h, self.r, self.fill)
        left = self.padx
        if self.colour:
            rrect(self, px(6), px(8), px(4), h - px(16), px(2), self.colour)
            left += px(4)
        self.create_window(left, self.pady, window=self.body, anchor="nw", width=max(1, w - left - self.padx))
        self._fit(None)


class RailButton(tk.Canvas):
    """Knopf der linken Symbolleiste: Symbol + kleine Beschriftung."""

    def __init__(self, parent, kind, text, command=None, w=60, h=58):
        self.w, self.h = px(w), px(h)
        super().__init__(parent, width=self.w, height=self.h, bg=BG, highlightthickness=0, cursor="hand2")
        self.kind, self.text, self.command = kind, text, command
        self.active = self.lit = self.hover = False
        self.bind("<Button-1>", lambda e: self.command() if self.command else None)
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.redraw()

    def _hover(self, on):
        self.hover = on
        self.redraw()

    def set_active(self, on):
        self.active = on
        self.redraw()

    def set_lit(self, on):
        self.lit = on
        self.redraw()

    def redraw(self):
        self.delete("all")
        col = ACCENT if self.active or self.lit else (TEXT if self.hover else MUTED)
        size = px(26)
        self.create_image(self.w / 2 - size / 2, px(10), image=icon_img(self.kind, col, size), anchor="nw")
        self.create_text(self.w / 2, px(46), text=self.text, fill=col, font=FONT_TINY)


class RigList(tk.Canvas):
    """Rig-Liste mit Farbpunkt je Rig. on_pick(index) bei Klick, on_menu(event, index) bei Rechtsklick."""

    DRAG_PX = 8

    def __init__(self, parent, on_pick=None, on_menu=None, on_move=None, bg=PANEL):
        super().__init__(parent, bg=bg, highlightthickness=0)
        self.row = px(28)
        self.items = []
        self.selected = None
        self.hover = None
        self.on_pick, self.on_menu, self.on_move = on_pick, on_menu, on_move
        self.can_move = False     # Ziehen erlaubt (Setlist-Reihenfolge)
        self._press = None        # (zeile, y) beim Druecken
        self._drag = None         # Ziel-Einfuegeposition waehrend des Ziehens
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self._click)
        self.bind("<B1-Motion>", self._drag_motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Button-3>", self._rclick)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))

    def _row_at(self, y):
        i = int(self.canvasy(y) // self.row)
        return i if 0 <= i < len(self.items) else None

    def _click(self, e):
        i = self._row_at(e.y)
        self._press = (i, e.y) if i is not None else None
        self._drag = None

    def _drag_motion(self, e):
        if not self._press or not self.can_move or not self.on_move:
            return
        i, y0 = self._press
        if self._drag is None and abs(e.y - y0) < self.DRAG_PX:
            return
        # Einfuegeposition: vor Zeile k (0..n)
        k = int((self.canvasy(e.y) + self.row / 2) // self.row)
        self._drag = max(0, min(len(self.items), k))
        self.redraw()

    def _release(self, e):
        press, drag = self._press, self._drag
        self._press = self._drag = None
        if press is None:
            return
        i = press[0]
        if drag is None:
            if self.on_pick:
                self.on_pick(i)
            return
        self.redraw()
        dst = drag - 1 if drag > i else drag   # Zielindex nach dem Herausnehmen von i
        if dst != i and self.on_move:
            self.on_move(i, dst)

    def _rclick(self, e):
        i = self._row_at(e.y)
        if i is not None and self.on_menu:
            self.on_menu(e, i)

    def _motion(self, e):
        self._set_hover(self._row_at(e.y))

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.redraw()

    def set_items(self, items, selected=None):
        self.items = list(items)
        self.selected = selected
        self.redraw()

    def select(self, i, see=True):
        self.selected = i
        self.redraw()
        if see and i is not None:
            top = i * self.row
            h = self.winfo_height()
            total = max(1, len(self.items) * self.row)
            y0 = self.canvasy(0)
            if top < y0 or top + self.row > y0 + h:
                self.yview_moveto(max(0, (top - h / 2)) / total)

    def redraw(self):
        self.delete("all")
        w = self.winfo_width()
        R = self.row
        for i, (name, colour) in enumerate(self.items):
            y = i * R
            fg = TEXT
            if i == self.selected:
                rrect(self, px(4), y + px(2), w - px(8), R - px(4), px(6), ACCENT)
                fg = ACCENT_TXT
            elif i == self.hover:
                rrect(self, px(4), y + px(2), w - px(8), R - px(4), px(6), CARD_HI)
            cy = y + R / 2
            if colour:
                rrect(self, px(14), cy - px(6), px(12), px(12), px(3), colour)
            self.create_text(px(36) if colour else px(14), cy, text=name, anchor="w", fill=fg, font=FONT)
        if self._drag is not None and self._press:
            y = self._drag * R
            self.create_line(px(6), y, w - px(6), y, fill=ACCENT, width=px(2))
            name, colour = self.items[self._press[0]]
            self.create_text(px(36), y - px(6), text="▲ " + name, anchor="sw", fill=ACCENT, font=FONT_SMALL)
        self.configure(scrollregion=(0, 0, w, max(len(self.items) * R, 1)))


# Signalwege des MX5 (Chain/Routing): Spalten der Kette, je Spalte ein Platz oder zwei parallele
ROUTINGS = {
    "S": ("Serial", [[1], [2], [3], [4], [5], [6], [7], [8], [9], [10], [11]]),
    "SPS-1": ("Serial › Parallel › Serial", [[1], [2], [3], [4, 7], [5, 8], [6, 9], [10], [11]]),
    "PS-1": ("Parallel › Serial", [[1, 5], [2, 6], [3, 7], [4, 8], [9], [10], [11]]),
}
ROUTING_ORDER = ["S", "SPS-1", "PS-1"]   # Reihenfolge der Auswahlliste am Geraet
WIRE = "#34363e"                          # Signalleitung in der Kette


def _round_path(pts, r):
    """Polylinie mit abgerundeten Ecken (Viertelkreise, Radius hoechstens r) als Punktliste."""
    import math
    if len(pts) < 3:
        return list(pts)
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        d1, d2 = math.hypot(x1 - x0, y1 - y0), math.hypot(x2 - x1, y2 - y1)
        if d1 < 1e-6 or d2 < 1e-6:
            continue
        rr = min(r, d1 / 2, d2 / 2)
        ax, ay = x1 - (x1 - x0) / d1 * rr, y1 - (y1 - y0) / d1 * rr   # Beginn der Rundung
        bx, by = x1 + (x2 - x1) / d2 * rr, y1 + (y2 - y1) / d2 * rr   # Ende der Rundung
        for k in range(9):   # quadratische Bezierkurve mit der Ecke als Stuetzpunkt
            t = k / 8
            out.append(((1 - t) ** 2 * ax + 2 * t * (1 - t) * x1 + t * t * bx,
                        (1 - t) ** 2 * ay + 2 * t * (1 - t) * y1 + t * t * by))
    out.append(pts[-1])
    return out


_WIRES = {}   # eigener kleiner Zwischenspeicher: die Leitungsbilder sind so gross wie die Kette


def wires_img(paths, width, colour, dots=()):
    """Signalleitungen als ein geglaettetes Bild: paths = [[(x, y), ...]] (bereits gerundet),
    dots = [(x, y, durchmesser)]. Gibt (bild, x, y) fuer create_image(anchor='nw') zurueck."""
    pts = [p for path in paths for p in path] + [(x, y) for x, y, _ in dots]
    if not pts or Image is None:
        return None, 0, 0
    pad = width + max([d for _, _, d in dots] or [0])
    x0, y0 = int(min(p[0] for p in pts) - pad), int(min(p[1] for p in pts) - pad)
    x1, y1 = int(max(p[0] for p in pts) + pad) + 1, int(max(p[1] for p in pts) + pad) + 1
    key = (x0, y0, x1, y1, width, colour, tuple(tuple((round(x, 1), round(y, 1)) for x, y in p) for p in paths),
           tuple(dots))
    im = _WIRES.get(key)
    if im is None:
        ss = 3
        pic = Image.new("RGBA", ((x1 - x0) * ss, (y1 - y0) * ss), (0, 0, 0, 0))
        dr = ImageDraw.Draw(pic)
        lw = max(1, int(round(width * ss)))
        for path in paths:
            p = [((x - x0) * ss, (y - y0) * ss) for x, y in path]
            dr.line(p, fill=colour, width=lw, joint="curve")
            for x, y in (p[0], p[-1]):   # runde Enden
                dr.ellipse([x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2], fill=colour)
        for x, y, d in dots:
            x, y, rr = (x - x0) * ss, (y - y0) * ss, d * ss / 2
            dr.ellipse([x - rr, y - rr, x + rr, y + rr], fill=colour)
        im = ImageTk.PhotoImage(pic.reduce(ss))
        _evict(_WIRES, 6)
        _WIRES[key] = im
    return im, x0, y0


def routing_img(name, colour, w, h, block=None):
    """Kleines Schaltbild eines Signalwegs (Auswahl oben rechts): Kaestchen = Bloecke, Linie =
    Signal, bei SPS-1/PS-1 zwei parallele Zweige, die sich teilen und wieder zusammenlaufen."""
    def d(dr, W, H):
        u = H / 22.0
        lw = max(1, int(1.8 * u))
        cy = H / 2
        bw, bh = 4.4 * u, 4.4 * u
        fill = block or colour

        def box(x, y):
            dr.rounded_rectangle([x - bw / 2, y - bh / 2, x + bw / 2, y + bh / 2], radius=1.4 * u, fill=fill)

        def branch(xa, xb, dy):   # Zweig: von der Mitte bei xa nach oben/unten, gerade, zurueck bei xb
            pts = _round_path([(xa, cy), (xa + 3 * u, cy), (xa + 3 * u, cy + dy), (xb - 3 * u, cy + dy),
                               (xb - 3 * u, cy), (xb, cy)], 2.4 * u)
            dr.line(pts, fill=colour, width=lw, joint="curve")

        L, R = 2 * u, W - 2 * u
        if name == "S":
            dr.line([L, cy, R, cy], fill=colour, width=lw)
            n = 4
            for i in range(n):
                box(L + (R - L) * (i + 0.5) / n, cy)
        else:
            dy = 6.6 * u
            if name == "SPS-1":
                xa, xb = L + (R - L) * 0.28, L + (R - L) * 0.72
                dr.line([L, cy, xa, cy], fill=colour, width=lw)
                dr.line([xb, cy, R, cy], fill=colour, width=lw)
                box(L + (xa - L) * 0.45, cy)
                box(xb + (R - xb) * 0.55, cy)
                inner = [(xa + xb) / 2]
            else:
                xa, xb = L, L + (R - L) * 0.66
                dr.line([xb, cy, R, cy], fill=colour, width=lw)
                box(xb + (R - xb) * 0.5, cy)
                inner = [xa + (xb - xa) * 0.37, xa + (xb - xa) * 0.66]
            for sgn in (-1, 1):
                branch(xa, xb, sgn * dy)
                for x in inner:
                    box(x, cy + sgn * dy)
            for x in (xa, xb) if name == "SPS-1" else (xb,):
                dr.ellipse([x - 1.8 * u, cy - 1.8 * u, x + 1.8 * u, cy + 1.8 * u], fill=colour)
    return _image(("rt", name, colour, block, w, h), w, h, d)


class RoutingPicker(tk.Canvas):
    """Auswahl des Signalwegs als Segmentleiste mit Schaltbildern (routing_img) statt Text.
    on_pick(index in ROUTING_ORDER); on_hover(name oder None) fuer eine Beschriftung daneben."""

    def __init__(self, parent, current=0, on_pick=None, on_hover=None):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self.on_pick, self.on_hover = on_pick, on_hover
        self.current, self.hover = current, None
        self.sw, self.h, self.pad = px(64), px(32), px(3)
        self.w = len(ROUTING_ORDER) * self.sw + 2 * self.pad
        self.configure(width=self.w, height=self.h)
        self.enabled = True
        self.bind("<Motion>", lambda e: self._set_hover(self._at(e.x)))
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", lambda e: self.pick(self._at(e.x)))
        self.redraw()

    def _at(self, x):
        i = int((x - self.pad) // self.sw)
        return i if 0 <= i < len(ROUTING_ORDER) else None

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.redraw()
            if self.on_hover:
                self.on_hover(ROUTING_ORDER[i] if i is not None else None)

    def set(self, i):
        self.current = i
        self.redraw()

    def set_enabled(self, on):
        self.enabled = on
        self.configure(cursor="hand2" if on else "")
        self.redraw()

    def pick(self, i):
        if i is None or i == self.current or not self.enabled:
            return
        self.set(i)
        if self.on_pick:
            self.on_pick(i)

    def redraw(self):
        self.delete("all")
        rrect(self, 0, 0, self.w, self.h, px(8), CARD)
        iw, ih = self.sw - px(16), self.h - px(10)
        for i, name in enumerate(ROUTING_ORDER):
            x = self.pad + i * self.sw
            sel, hov = i == self.current, i == self.hover and self.enabled
            if sel:
                rrect(self, x, self.pad, self.sw, self.h - 2 * self.pad, px(6), ACCENT)
            elif hov:
                rrect(self, x, self.pad, self.sw, self.h - 2 * self.pad, px(6), CARD_HI)
            if sel:
                fg, blk = ACCENT_TXT, ACCENT_TXT
            elif not self.enabled:
                fg, blk = DIM, DIM
            else:
                fg, blk = (TEXT, TEXT) if hov else (MUTED, MUTED)
            self.create_image(x + (self.sw - iw) // 2, (self.h - ih) // 2, anchor="nw",
                              image=routing_img(name, fg, iw, ih, blk))


class ChainCanvas(tk.Canvas):
    """Signalkette: IN, 11 Plaetze, OUT, verbunden durch die Signallinie; parallele Wege
    (Routing SPS-1 / PS-1) als zwei uebereinander liegende Reihen mit Verzweigung und MIX.
    Plaetze: Dicts {slot, module, colour, on, sub, double, sub2}; ein doppelter Block (Amp/Cab/IR
    mit Doubling) zeigt zwei Haelften A und B.
    Rueckrufe: on_pick(modul, haelfte), on_empty(platz), on_menu(event, modul, platz, haelfte),
    on_io('Input'|'Output'), on_toggle(modul) bei Doppelklick, on_move(von, nach) nach Ziehen,
    on_mix() beim Klick auf MIX, on_delete(platz, modul) nach dem Ablegen auf dem Muelleimer
    (gibt True zurueck, wenn der Block entfernt wird).
    Ziehen: der Muelleimer erscheint nur waehrend des Ziehens am freien Ende der letzten Reihe;
    ueber einem Ziel zeigt die Kette schon die Plaetze nach dem Ablegen (plan(kette, von, nach),
    z. B. live.plan_block_move), die Karten gleiten dorthin (_pos/_tick), ebenso beim Loslassen.
    Scene-Modus (set_chain(..., scene=True)): jeder belegte Platz traegt d["scene"] =
    {"mode": 0|1|2, "preset": name} und zeigt statt des Farbbalkens einen Streifen –/AN/AUS
    und statt der Geraeteklasse den Presetnamen; nur belegte Plaetze sind klickbar, kein
    Ziehen, kein Einfuegen, Eingang/Ausgang/MIX sind gedimmt.
    Zuweisungs-Modus (assign=(beschriftung, modul, andere)): wie Scene-Modus bedienbar, der Block
    'modul' traegt einen Akzentstreifen mit der Beschriftung (z. B. 'FS 1') und einen Rahmen;
    andere = {modul: 'FS 2'} zeigt Bloecke, die schon ein anderer Schalter bedient (grauer Streifen).
    In beiden Modi sitzt oben rechts ein runder Knopf mit x (on_exit) zum Verlassen."""
    MAXC = 7   # Spalten je Reihe

    def __init__(self, parent, on_pick=None, on_empty=None, on_menu=None, on_io=None, on_toggle=None, on_move=None,
                 on_mix=None, on_exit=None, on_delete=None, plan=None, on_double=None, on_connect=None):
        super().__init__(parent, bg=BG, highlightthickness=0)
        self.on_double, self.on_connect = on_double, on_connect
        self.connect = None      # ohne Kette: 'idle' = Knopf 'Connect to Device', 'busy' = verbindet gerade
        self.connect_err = None  # Text unter dem Knopf (letzter Verbindungsversuch)
        self.connect_box = None
        self.double_box = None   # Knopf '2x' ueber dem gewaehlten Amp/Cab/IR: (x1, y1, x2, y2, modul)
        self.on_pick, self.on_empty, self.on_menu, self.on_io = on_pick, on_empty, on_menu, on_io
        self.on_toggle, self.on_move, self.on_mix, self.on_exit = on_toggle, on_move, on_mix, on_exit
        self.on_delete, self.plan = on_delete, plan
        self._pos = {}           # Modul -> gezeichnete Position (x, y) links oben, gleitet zu _targets
        self._targets = {}
        self._after = None       # laufende Animation
        self._keep_until = 0     # bis dahin behaelt set_chain die Positionen (Animation nach dem Ablegen)
        self.fly = None          # Karte, die in den Muelleimer fliegt
        self.hidden = None       # (modul, bis) nicht zeichnen (liegt im Muelleimer)
        self.trash_box = None    # (cx, cy, r) waehrend des Ziehens
        self._trash_k = 0.0      # Einblenden des Muelleimers 0..1
        self.exit_box = None     # Schliessen-Knopf im Scene-/Zuweisungs-Modus
        self.k = 1.0                           # Vergroesserung je nach Platz (_fit), 0.6-2.4
        self._scale(1.0)
        self.slots = []
        self.selected = (None, None)
        self.routing = "S"
        self.live = False
        self.hover = (None, None)
        self.hint = ""
        self.press = None        # (key, x, y) beim Druecken
        self.drag = None         # Platz, der gezogen wird
        self.drop = None         # Zielplatz unter der Maus
        self.mouse = (0, 0)
        self.mix_box = None
        self.scene = False
        self.assign = None       # (beschriftung, modul) im Zuweisungs-Modus
        self.pick_only = False   # Scene-/Zuweisungs-Modus: nur belegte Plaetze klickbar, kein Ziehen
        self.bind("<Configure>", lambda e: (self._pos.clear(), self.redraw()))
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag_motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", self._double)
        self.bind("<Button-3>", self._rclick)

    def set_chain(self, slots, selected, live, routing="S", hint="", scene=False, assign=None, connect=None,
                  connect_err=None):
        self.slots, self.live, self.hint, self.scene = list(slots), live, hint, scene
        self.connect, self.connect_err = connect, connect_err
        self.assign = assign
        self.pick_only = scene or assign is not None
        self.selected = selected if isinstance(selected, tuple) else (selected, None)
        self.routing = routing if routing in ROUTINGS else "S"
        self.drag = self.drop = self.press = None
        if time.monotonic() > self._keep_until:   # sonst gleiten die Karten von der Ablegestelle weiter
            self._pos.clear()
        if self.hidden and not any(d["module"] == self.hidden[0] for d in self.slots):
            self.hidden = None
        self.redraw()

    # ---- Layout ----
    def _display(self):
        """Plaetze, wie sie nach dem Ablegen stuenden (Vorschau beim Ziehen), sonst wie sie sind."""
        if self.drag is None or not isinstance(self.drop, int) or self.drop == self.drag or self.plan is None:
            return self.slots
        chain = [d if d["module"] else None for d in self.slots]
        return [dict(d, slot=k + 1) if d else {"slot": k + 1, "module": None, "colour": None, "on": None, "sub": None,
                                                "double": False, "sub2": None}
                for k, d in enumerate(self.plan(chain, self.drag, self.drop))]

    def _rows(self):
        """Reihen aus Spalten: [[['Input'], [1], [4, 7], ...], ...]"""
        cols = [["Input"]] + [list(c) for c in ROUTINGS[self.routing][1] if all(k <= len(self.slots) for k in c)] + [["Output"]]
        return [cols[i:i + self.MAXC] for i in range(0, len(cols), self.MAXC)]

    def p(self, n):
        """Pixel, mit dem Platzfaktor k skaliert."""
        return px(n * self.k)

    def _scale(self, k):
        """Alle Masse und Schriften fuer den Faktor k setzen (Grundmasse: Karte 76 x 92)."""
        self.k = k
        self.CW, self.CH, self.GAP, self.GY, self.RG = self.p(76), self.p(92), self.p(14), self.p(22), self.p(44)
        self.XG = self.p(18)                           # Zusatzabstand vor/nach parallelen Zweigen
        self.IOW, self.IOH = self.p(46), self.p(60)   # Eingang/Ausgang: kleiner, mittig auf der Signallinie
        self.EW = self.p(58)                           # leerer Platz: schlankeres Kaestchen
        self.f_tiny = ("Segoe UI", max(7, int(round(7 * k))))
        self.f_card = ("Segoe UI", max(8, int(round(8 * k))), "bold")
        self.f_plus = ("Segoe UI", max(12, int(round(16 * k))))

    @staticmethod
    def _col_xs(cols, cw, gap, xg):
        """x der Spalten einer Reihe (ab 0): vor und nach einer parallelen Gruppe xg mehr Abstand,
        damit Verzweigung und Mischpunkt Platz haben. Dazu die Breite samt Platz nach einer
        Gruppe am Reihenende."""
        xs, x = [], 0
        for c, col in enumerate(cols):
            if c > 0 and (len(col) > 1) != (len(cols[c - 1]) > 1):
                x += xg
            xs.append(x)
            x += cw + gap
        return xs, x - gap + (xg if len(cols[-1]) > 1 else 0)

    def _fit(self):
        """Faktor k so waehlen, dass die Kette die Flaeche ausfuellt (in Zehnteln, 0,6 bis 2,4,
        damit die Symbol-Zwischenspeicher nicht mit Zwischengroessen volllaufen)."""
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50 or not self.slots:
            return
        rows = self._rows()
        two = len(rows) > 1
        full = max([self._col_xs(r, 76, 14, 18)[1] for r in rows] + [self.MAXC * 76 + (self.MAXC - 1) * 14])
        bw = full + 26 + (44 if two else 18) + 16
        heights = [2 * 92 + 22 if any(len(c) > 1 for c in r) else 92 for r in rows]
        bh = sum(heights) + (len(rows) - 1) * 44 + 24
        k = min(w / px(bw), h / px(bh))
        k = max(0.6, min(2.4, int(k * 10) / 10))
        if k != self.k:
            self._scale(k)

    def _layout(self, slots=None):
        """Positionen: boxes {key: (x, y)}, rows [(y_top, height, cols, xs)]; slots = anzuzeigende
        Plaetze (Vorschau), sonst die echten. In Reihen mit parallelen Wegen liegen die seriellen
        Bloecke auf der Mittelachse, die beiden Zweige darueber und darunter."""
        self._fit()
        w, h = self.winfo_width(), self.winfo_height()
        rows = self._rows()
        heights = [2 * self.CH + self.GY if any(len(c) > 1 for c in r) else self.CH for r in rows]
        total = sum(heights) + (len(rows) - 1) * self.RG
        y = max(self.p(10), (h - total) / 2)
        rel = [self._col_xs(cols, self.CW, self.GAP, self.XG) for cols in rows]
        self._full = max([f for _, f in rel] + [self.MAXC * self.CW + (self.MAXC - 1) * self.GAP])
        x0 = max(self.p(26), (w - self._full) / 2)
        boxes, rowinfo = {}, []
        for r, cols in enumerate(rows):
            axis = y + heights[r] / 2
            xs = [x0 + x for x in rel[r][0]]
            for c, col in enumerate(cols):
                for i, key in enumerate(col):
                    bw, bh = self._size(key, slots)
                    cy = axis if len(col) == 1 else y + i * (self.CH + self.GY) + self.CH / 2
                    boxes[key] = (xs[c] + (self.CW - bw) / 2, cy - bh / 2)
            rowinfo.append((y, heights[r], cols, xs))
            y += heights[r] + self.RG
        return boxes, rowinfo, x0

    def _size(self, key, slots=None):
        if key in ("Input", "Output"):
            return self.IOW, self.IOH
        d = (slots or self.slots)[key - 1] if isinstance(key, int) else None
        if d and d["module"] is None:
            return self.EW, self.CH
        return self.CW, self.CH

    def _hit(self, x, y):
        """(key, haelfte) unter der Maus; key = 'Input'/'Output'/platz/'Mix'/'Double'/'Connect' oder None."""
        if not self.slots:
            b = self.connect_box
            return ("Connect", None) if b and b[0] <= x <= b[2] and b[1] <= y <= b[3] else (None, None)
        b = self.double_box
        if b and b[0] <= x <= b[2] and b[1] <= y <= b[3]:
            return "Double", None
        boxes, _, _ = self._layout()
        for key, (bx, by) in boxes.items():
            bw, bh = self._size(key)
            if bx <= x <= bx + bw and by <= y <= by + bh:
                d = self._slot(key)
                if self.pick_only and (d is None or d["module"] is None):
                    return None, None   # Scene: nur belegte Plaetze
                half = None
                if d and d["module"] and d["double"] and not self.pick_only:
                    half = "A" if y < by + self.CH / 2 else "B"
                return key, half
        if self.mix_box and not self.pick_only:
            x1, y1, x2, y2 = self.mix_box
            if x1 <= x <= x2 and y1 <= y <= y2:
                return "Mix", None
        if self.exit_box:
            x1, y1, x2, y2 = self.exit_box
            if x1 <= x <= x2 and y1 <= y <= y2:
                return "Exit", None
        return None, None

    def _slot(self, key):
        return self.slots[key - 1] if isinstance(key, int) else None

    # ---- Maus ----
    def _motion(self, e):
        self._set_hover(self._hit(e.x, e.y))

    def _set_hover(self, hit):
        hit = hit or (None, None)
        if hit != self.hover:
            self.hover = hit
            self.configure(cursor="hand2" if hit[0] is not None else "")
            self.redraw()

    def _press(self, e):
        if self.fly:
            return
        key, half = self._hit(e.x, e.y)
        self.press = (key, e.x, e.y)

    def _in_trash(self, x, y):
        if not self.trash_box or self.on_delete is None:
            return False
        cx, cy, r = self.trash_box
        return (x - cx) ** 2 + (y - cy) ** 2 <= (r + self.p(10)) ** 2

    def _drag_motion(self, e):
        if not self.press:
            return
        key, x0, y0 = self.press
        if self.drag is None:
            if not isinstance(key, int) or not self._slot(key)["module"] or self.on_move is None or self.pick_only:
                return
            if abs(e.x - x0) < self.p(8) and abs(e.y - y0) < self.p(8):
                return
            self.drag = key
            self.configure(cursor="fleur")
            self.drop = None
            self._trash_k = 0.0
            self.mouse = (e.x, e.y)
            self.redraw()
            return
        if self._in_trash(e.x, e.y):
            drop = "Trash"
        else:
            target, _ = self._hit(e.x, e.y)
            drop = target if isinstance(target, int) else None
        if drop == self.drop:   # nur die gezogene Karte mitfuehren, nicht alles neu zeichnen
            self.move("ghost", e.x - self.mouse[0], e.y - self.mouse[1])
            self.mouse = (e.x, e.y)
            return
        self.drop = drop
        self.mouse = (e.x, e.y)
        self.redraw()

    def _release(self, e):
        if self.fly:
            return
        key, half = self._hit(e.x, e.y)
        if self.drag is not None:
            src, dst = self.drag, self.drop
            d = self._slot(src)
            mx, my = self.mouse
            ghost = (mx - self.CW / 2, my - self.CH / 2)
            self.drag = self.drop = self.press = None
            self.configure(cursor="hand2" if key is not None else "")
            self._keep_until = time.monotonic() + 1.0
            if dst == "Trash":   # Karte fliegt in den Muelleimer, danach fragt on_delete nach
                self.drag, self.drop = src, "Trash"   # Muelleimer bleibt sichtbar, bis sie angekommen ist
                self.hidden = (d["module"], time.monotonic() + 10)
                self.fly = {"d": d, "slot": src, "x": mx, "y": my, "s": 0.6}
                self.redraw()
                return
            # die Karte gleitet von der Maus an ihren Platz: den neuen (on_move -> set_chain) oder
            # zurueck, falls nichts verschoben wird; die anderen gleiten aus der Vorschau weiter
            self._pos[d["module"]] = ghost
            self.redraw()
            if dst is not None and dst != src:
                self.on_move(src, dst)
            return
        self.press = None
        if key is None:
            return
        if key == "Exit":
            if self.on_exit:
                self.on_exit()
            return
        if key == "Connect":
            if self.on_connect:
                self.on_connect()
            return
        if key == "Double":
            if self.on_double and self.double_box:
                self.on_double(self.double_box[4])
            return
        if key == "Mix":
            if self.on_mix:
                self.on_mix()
            return
        if key in ("Input", "Output"):
            if self.on_io:
                self.on_io(key)
            return
        d = self._slot(key)
        if d["module"]:
            if self.on_pick:
                self.on_pick(d["module"], half)
        elif self.on_empty:
            self.on_empty(d["slot"])

    def _double(self, e):
        key, _ = self._hit(e.x, e.y)
        if isinstance(key, int) and self._slot(key)["module"] and self.on_toggle:
            self.on_toggle(self._slot(key)["module"])

    def _rclick(self, e):
        key, half = self._hit(e.x, e.y)
        if isinstance(key, int) and self.on_menu:
            d = self._slot(key)
            self.on_menu(e, d["module"], d["slot"], half)

    # ---- Zeichnen ----
    def _card(self, x, y, d, hovered, ghost=False):
        """Block als grosses Modell-Symbol ohne Rahmen: duenner Farbbalken darueber, Platznummer
        (oder AUS) darunter; Auswahl = Akzentrahmen, Maus darueber = leichte Flaeche.
        Doppelte Bloecke: zwei Symbole A/B untereinander."""
        cw, ch = self.CW, self.CH
        module, colour, on, sub = d["module"], d["colour"], d["on"], d["sub"]
        icon = d.get("icon") or module   # eigenes Symbol (NAM im Anxiety OD)
        sel_mod, sel_half = self.selected
        band = DIM if on is False else (colour or DIM)
        dim = on is False
        foot, foot_fg = d.get("label") or class_label(module), (DIM if dim else MUTED)
        if self.scene:
            self._scene_card(x, y, d, hovered)
            return
        if self.assign is not None and not d["double"]:
            label, target, others = self.assign
            if module == target:
                rrect(self, x, y, cw, ch, self.p(8), CARD if hovered else "", ACCENT, 2)
                sh = self.p(13)
                rrect(self, x + self.p(6), y + self.p(3), cw - self.p(12), sh, self.p(4), ACCENT)
                self.create_text(x + cw / 2, y + self.p(3) + sh / 2, text=label, fill=ACCENT_TXT, font=self.f_tiny)
                iw, ih = cw - self.p(4), ch - self.p(34)
                self.create_image(x + self.p(2), y + self.p(19), anchor="nw", image=model_img(icon, sub, iw, ih, dim, fit=True))
                self.create_text(x + cw / 2, y + ch - self.p(3), text=foot, fill=foot_fg, font=self.f_tiny, anchor="s")
                return
            if hovered:
                rrect(self, x, y, cw, ch, self.p(8), CARD)
            if module in (others or {}):   # von einem anderen Schalter bedient: grauer Streifen
                sh = self.p(13)
                rrect(self, x + self.p(6), y + self.p(3), cw - self.p(12), sh, self.p(4), CARD_HI)
                self.create_text(x + cw / 2, y + self.p(3) + sh / 2, text=others[module], fill=MUTED, font=self.f_tiny)
                iw, ih = cw - self.p(4), ch - self.p(34)
                self.create_image(x + self.p(2), y + self.p(19), anchor="nw", image=model_img(icon, sub, iw, ih, dim, fit=True))
            else:
                rrect(self, x + self.p(10), y + self.p(5), cw - self.p(20), self.p(4), self.p(2), band)
                iw, ih = cw - self.p(4), ch - self.p(26)
                self.create_image(x + self.p(2), y + self.p(12), anchor="nw", image=model_img(icon, sub, iw, ih, dim, fit=True))
            self.create_text(x + cw / 2, y + ch - self.p(3), text=foot, fill=foot_fg, font=self.f_tiny, anchor="s")
            return
        if d["double"]:
            hh = (ch - self.p(16)) / 2
            iw, ih = cw - self.p(22), hh - self.p(10)
            for i, (half, model) in enumerate((("A", sub), ("B", d["sub2"]))):
                hy = y + i * (hh + self.p(4))
                sel = module == sel_mod and (sel_half == half or sel_half is None)
                hov = hovered and self.hover[1] == half
                if hov or ghost or sel:
                    rrect(self, x, hy, cw, hh, self.p(7), CARD if hov or ghost else "", ACCENT if sel else None, 2 if sel else 0)
                rrect(self, x + self.p(10), hy + self.p(3), cw - self.p(20), self.p(3), self.p(2), band)
                self.create_image(x + self.p(4), hy + self.p(8), anchor="nw", image=model_img(icon, model, iw, ih, dim, fit=True))
                self.create_text(x + cw - self.p(6), hy + hh / 2 + self.p(3), text=half, fill=MUTED if dim else TEXT,
                                 font=self.f_card, anchor="e")
            self.create_text(x + cw / 2, y + ch - self.p(1), text=foot, fill=foot_fg, font=self.f_tiny, anchor="s")
            return
        sel = module == sel_mod
        if hovered or ghost or sel:
            rrect(self, x, y, cw, ch, self.p(8), CARD if hovered or ghost else "", ACCENT if sel else None, 2 if sel else 0)
        rrect(self, x + self.p(10), y + self.p(5), cw - self.p(20), self.p(4), self.p(2), band)
        iw, ih = cw - self.p(4), ch - self.p(26)
        self.create_image(x + self.p(2), y + self.p(12), anchor="nw", image=model_img(icon, sub, iw, ih, dim, fit=True))
        self.create_text(x + cw / 2, y + ch - self.p(3), text=foot, fill=foot_fg, font=self.f_tiny, anchor="s")

    def _scene_card(self, x, y, d, hovered):
        """Platz im Scene-Modus: Streifen mit –/AN/AUS (Farbe des Blocks, Akzent, Rot), Symbol im
        Zustand nach dem Schalten, darunter der Presetname (leer = Klasse, gedimmt)."""
        cw, ch = self.CW, self.CH
        module, colour, on, sub = d["module"], d["colour"], d["on"], d["sub"]
        icon = d.get("icon") or module   # eigenes Symbol (NAM im Anxiety OD)
        sc = d.get("scene") or {"mode": 0, "preset": ""}
        mode, preset = sc.get("mode", 0), sc.get("preset", "")
        sel = module == self.selected[0]
        if hovered or sel:
            rrect(self, x, y, cw, ch, self.p(8), CARD if hovered else "", ACCENT if sel else None, 2 if sel else 0)
        result_on = True if mode == 1 else False if mode == 2 else on
        dim = result_on is False
        sh = self.p(13)
        if mode == 1:
            fill, fg, label = ACCENT, ACCENT_TXT, "ON"
        elif mode == 2:
            fill, fg, label = DANGER, "#ffffff", "OFF"
        else:
            fill = (colour or CARD_HI) if not dim else CARD_HI
            fg, label = text_on(colour) if colour and not dim else MUTED, "–"
        rrect(self, x + self.p(6), y + self.p(3), cw - self.p(12), sh, self.p(4), fill)
        self.create_text(x + cw / 2, y + self.p(3) + sh / 2, text=label, fill=fg, font=self.f_tiny)
        iw, ih = cw - self.p(4), ch - self.p(34)
        self.create_image(x + self.p(2), y + self.p(19), anchor="nw", image=model_img(icon, sub, iw, ih, dim, fit=True))
        if preset:
            t = preset.upper()
            while t and text_size(t, self.f_tiny)[0] > cw - self.p(6):
                t = t[:-2] + "…"
            self.create_text(x + cw / 2, y + ch - self.p(3), text=t, fill=ACCENT, font=self.f_tiny, anchor="s")
        else:
            self.create_text(x + cw / 2, y + ch - self.p(3), text=d.get("label") or class_label(module), fill=DIM, font=self.f_tiny, anchor="s")

    def redraw(self):
        self.delete("all")
        self.mix_box = self.exit_box = self.double_box = None
        if self.pick_only and self.winfo_width() >= 50:
            W = self.winfo_width()
            rrect(self, self.p(1), self.p(1), W - self.p(2), self.winfo_height() - self.p(2), self.p(10), "", ACCENT, 1)
            # runder Schliessen-Knopf oben rechts (geglaettet gerendert)
            r = px(14)
            cx, cy = W - px(12) - r, px(12) + r
            hov = self.hover[0] == "Exit"
            circle(self, cx, cy, 2 * r, ACCENT if hov else CARD_HI, ACCENT, 1)
            n = px(14)
            self.create_image(int(cx - n / 2), int(cy - n / 2), anchor="nw",
                              image=icon_img("close", ACCENT_TXT if hov else TEXT, n))
            self.exit_box = (cx - r, cy - r, cx + r, cy + r)
        self.connect_box = None
        if not self.slots or self.winfo_width() < 50:
            self._draw_empty()
            return
        disp = self._display()
        boxes, rows, x0 = self._layout(disp)
        cw, ch = self.CW, self.CH
        # Signalleitungen als ein geglaettetes Bild: Achse je Reihe, parallele Gruppen als Klammer
        # (Verzweigungspunkt links, beide Zweige ueber/unter der Achse, Mischpunkt rechts), dazu
        # die Schleife zur naechsten Reihe; alle Ecken gerundet
        paths, dots, merges = [], [], []
        R = self.p(16)
        xl = x0 - self.p(18)
        xr = x0 + self._full + self.p(18)
        for r, (ytop, height, cols, xs) in enumerate(rows):
            my = ytop + height / 2
            start = boxes[cols[0][0]][0] if len(cols[0]) == 1 else None
            c = 0
            while c < len(cols):
                if len(cols[c]) == 1:
                    c += 1
                    continue
                c2 = c
                while c2 + 1 < len(cols) and len(cols[c2 + 1]) > 1:
                    c2 += 1
                gap_b = xs[c] - (xs[c - 1] + cw) if c > 0 else self.GAP + self.XG
                gap_a = xs[c2 + 1] - (xs[c2] + cw) if c2 + 1 < len(cols) else self.GAP + self.XG
                sx, mx = xs[c] - gap_b / 2, xs[c2] + cw + gap_a / 2
                if start is not None:
                    paths.append([(start, my), (sx, my)])
                elif r > 0:
                    paths.append([(xl, my), (sx, my)])
                for i in range(2):
                    ly = ytop + i * (ch + self.GY) + ch / 2
                    paths.append(_round_path([(sx, my), (sx, ly), (mx, ly), (mx, my)], R))
                dots.append((sx, my, self.p(10)))
                merges.append((mx, my))
                start = mx
                c = c2 + 1
            if r + 1 < len(rows):   # Schleife zur naechsten Reihe (rechts am Mischpunkt vorbei)
                nytop, nh, ncols, _ = rows[r + 1]
                ny = nytop + nh / 2
                ymid = (ytop + height + nytop) / 2
                nx = boxes[ncols[0][0]][0]
                x_start = start if start is not None else xl
                paths.append(_round_path([(x_start, my), (xr, my), (xr, ymid), (xl, ymid), (xl, ny), (nx, ny)], R))
            elif len(cols[-1]) == 1:
                x_last = boxes[cols[-1][0]][0] + self._size(cols[-1][0], disp)[0]
                paths.append([(start if start is not None else xl, my), (x_last, my)])
        im, wx, wy = wires_img(paths, 4 * self.k * S, WIRE, dots)
        if im is not None:
            self.create_image(wx, wy, anchor="nw", image=im)
        else:
            for p in paths:
                self.create_line(*[v for pt in p for v in pt], fill=WIRE, width=self.p(4))
        for mx, my in merges:   # Mischpunkt: Klick oeffnet die Mischung der Zweige
            d = self.p(26)
            hov = self.hover[0] == "Mix" and not self.pick_only
            sel = self.selected[0] == "Chain" and not self.pick_only   # Mischung im Parameterfeld (MIX)
            circle(self, mx, my, d, ACCENT if hov else (CARD_LO if self.pick_only else CARD_HI),
                   ACCENT if hov or sel else WIRE, 2)
            n = self.p(18)
            self.create_image(int(mx - n / 2), int(my - n / 2), anchor="nw",
                              image=icon_img("mix", ACCENT_TXT if hov else (DIM if self.pick_only else TEXT), n))
            self.mix_box = (mx - d / 2, my - d / 2, mx + d / 2, my + d / 2)
        # Kaestchen: Eingang/Ausgang und leere Plaetze fest, Bloecke gesammelt und danach gezeichnet
        hidden = self.hidden[0] if self.hidden and time.monotonic() < self.hidden[1] else None
        dragged = self._slot(self.drag)["module"] if isinstance(self.drag, int) else None
        preview = disp is not self.slots
        cards, targets = [], {}
        for key, (x, y) in boxes.items():
            hovered = self.hover[0] == key and self.drag is None
            if key in ("Input", "Output"):
                bw, bh = self.IOW, self.IOH
                sel = key == self.selected[0] and not self.pick_only
                rrect(self, x, y, bw, bh, self.p(8), CARD_HI if hovered else (CARD_LO if self.pick_only else CARD),
                      ACCENT if sel else None, 2 if sel else 0)
                self.create_text(x + bw / 2, y + self.p(11), text="IN" if key == "Input" else "OUT",
                                 fill=DIM if self.pick_only else TEXT, font=self.f_card)
                size = self.p(36)
                self.create_image(x + bw / 2 - size / 2, y + self.p(19), anchor="nw",
                                  image=icon_img("guitar" if key == "Input" else "stereo",
                                                 DIM if self.pick_only else (TEXT if hovered else MUTED), size))
                continue
            d = disp[key - 1]
            m = d["module"]
            bw = self._size(key, disp)[0]
            if m is not None and m == dragged and not self.fly:
                if preview:   # Landeplatz der gezogenen Karte: gedimmt mit Akzentrahmen
                    rrect(self, x - self.p(3), y - self.p(3), cw + self.p(6), ch + self.p(6), self.p(10), "", ACCENT, 2)
                    self._card(x, y, dict(d, on=False), False)
                else:         # Quelle beim Ziehen: nur ein Schatten
                    rrect(self, x, y, cw, ch, self.p(8), CARD_LO, LINE, 1)
                continue
            if self.drop == key and self.drag is not None and not preview:
                rrect(self, x - self.p(3), y - self.p(3), bw + self.p(6), ch + self.p(6), self.p(10), "", ACCENT, 2)
            if m is None or m == hidden:
                ex = x + (bw - self.EW) / 2
                rrect(self, ex, y, self.EW, ch, self.p(8), CARD_HI if hovered and self.live else CARD_LO, LINE, 1)
                self.create_text(ex + self.EW / 2, y + ch / 2, text="+",
                                 fill=MUTED if self.live and not self.pick_only else DIM, font=self.f_plus)
                self.create_text(ex + self.EW / 2, y + ch - self.p(10), text=str(d["slot"]), fill=DIM, font=self.f_tiny)
                continue
            targets[m] = (x, y)
            cards.append((d, hovered))
        # Bloecke an ihrer (gleitenden) Position; die noch unterwegs sind, liegen obenauf
        self._pos = {m: p for m, p in self._pos.items() if m in targets}
        self._targets = targets
        cards.sort(key=lambda c: self._pos.get(c[0]["module"], targets[c[0]["module"]]) != targets[c[0]["module"]])
        for d, hovered in cards:
            x, y = self._pos.setdefault(d["module"], targets[d["module"]])
            self._card(x, y, d, hovered)
            if d["module"] == self.selected[0] and d.get("can_double") and not self.pick_only \
                    and self.drag is None and not self.fly and self.on_double:
                self._double_btn(x, y, d)
        # Muelleimer: nur waehrend des Ziehens, am freien Ende der letzten Reihe (hinter OUT);
        # liegt ueber der gezogenen/fliegenden Karte, damit sie darin verschwindet
        show_trash = self.on_delete is not None and (self.drag is not None or self.fly is not None)
        if self.fly:   # Karte auf dem Weg in den Muelleimer, schrumpft dabei
            self._mini(self.fly["d"], self.fly["x"], self.fly["y"], self.fly["s"])
        elif self.drag is not None:    # gezogene Karte unter der Maus (Tag "ghost" fuer _drag_motion)
            self.addtag_all("fixed")
            mx, my = self.mouse
            if self.drop == "Trash":
                self._mini(self._slot(self.drag), mx, my, 0.6)
            else:
                self._card(mx - cw / 2, my - ch / 2, self._slot(self.drag), False, ghost=True)
            for i in self.find_all():
                if "fixed" not in self.gettags(i):
                    self.addtag_withtag("ghost", i)
        self.trash_box = None
        if show_trash:
            n0 = len(self.find_all())
            ytop, height, cols, _ = rows[-1]
            if len(cols) < self.MAXC:
                cx, cy = x0 + (self.MAXC - 1) * (cw + self.GAP) + cw / 2, ytop + height / 2
            else:
                cx, cy = self.winfo_width() - self.p(44), self.winfo_height() - self.p(44)
            hot = self.drop == "Trash"
            k = 1 - (1 - self._trash_k) ** 2   # Einblenden: wachsen, abgebremst
            r = self.p(26) * (0.5 + 0.5 * k) * (1.15 if hot else 1.0)
            circle(self, cx, cy, 2 * r, DANGER if hot else CARD, DANGER if hot else LINE, 1)
            size = max(8, int(r * 1.1))
            self.create_image(int(cx - size / 2), int(cy - size / 2), anchor="nw",
                              image=icon_img("trash", "#ffffff" if hot else MUTED, size))
            if k > 0.6:
                self.create_text(cx, cy + r + self.p(9), text="Remove", fill=DANGER if hot else MUTED, font=self.f_tiny)
            self.trash_box = (cx, cy, self.p(26))
            for i in self.find_all()[n0:]:
                self.addtag_withtag("fixed", i)
        moving = self.fly is not None or any(self._pos[m] != t for m, t in targets.items()) \
            or (show_trash and self._trash_k < 1)
        if moving and self._after is None:
            self._after = self.after(15, self._tick)

    def _double_btn(self, x, y, d):
        """Knopf '2x' mittig ueber der Karte: Doppelung (zwei Amps/Cabs/IRs) an/aus."""
        on = bool(d.get("double"))
        bw, bh = self.p(34), self.p(17)
        cx, top = x + self.CW / 2, max(self.p(1), y - bh + self.p(3))
        hov = self.hover[0] == "Double"
        fill = (ACCENT_HI if hov else ACCENT) if on else (CARD_HI if hov else CARD)
        rrect(self, cx - bw / 2, top, bw, bh, bh / 2, fill, ACCENT, 1)
        self.create_text(cx, top + bh / 2, text="2x", fill=ACCENT_TXT if on else (TEXT if hov else ACCENT),
                         font=self.f_card)
        self.double_box = (cx - bw / 2, top, cx + bw / 2, top + bh, d["module"])

    def _draw_empty(self):
        """Keine Kette: Hinweis und, solange nicht verbunden, der Knopf 'Connect to Device'
        (self.connect = 'idle' | 'busy' | None, darunter ggf. self.connect_err)."""
        W, H = self.winfo_width(), self.winfo_height()
        if W < 50:
            return
        if self.connect is None:
            if self.hint:
                self.create_text(W / 2, H / 2, text=self.hint, fill=DIM, font=FONT)
            return
        busy = self.connect == "busy"
        text = "Connecting …" if busy else "Connect to Device"
        tw, th = text_size(text, FONT_HEAD)
        isz = px(22)
        bw, bh = tw + isz + px(52), th + px(24)
        x, y = W / 2 - bw / 2, H / 2 - bh / 2 - px(10)
        hov = self.hover[0] == "Connect" and not busy
        sp = px(14)
        self.create_image(int(x - sp), int(y - sp), anchor="nw", image=shadow_img(int(bw), int(bh), px(10), sp))
        rrect(self, x, y, bw, bh, px(10), CARD_HI if busy else (ACCENT_HI if hov else ACCENT))
        fg = MUTED if busy else ACCENT_TXT
        self.create_image(int(x + px(20)), int(y + bh / 2 - isz / 2), anchor="nw", image=icon_img("live", fg, isz))
        self.create_text(x + px(20) + isz + px(10), y + bh / 2, text=text, fill=fg, font=FONT_HEAD, anchor="w")
        if not busy:
            self.connect_box = (x, y, x + bw, y + bh)
        sub = self.connect_err or self.hint
        if sub:
            self.create_text(W / 2, y + bh + px(22), text=sub, fill=WARN if self.connect_err else DIM, font=FONT_SMALL,
                             width=px(520), justify="center", anchor="n")

    def _mini(self, d, cx, cy, s):
        """Nur das Modell-Symbol, auf s verkleinert, mittig bei (cx, cy) (Weg in den Muelleimer);
        Groessen in 4-px-Stufen, damit der Bild-Zwischenspeicher klein bleibt."""
        iw = max(8, int((self.CW - self.p(4)) * s / 4) * 4)
        ih = max(8, int((self.CH - self.p(26)) * s / 4) * 4)
        self.create_image(int(cx - iw / 2), int(cy - ih / 2), anchor="nw",
                          image=model_img(d.get("icon") or d["module"], d["sub"], iw, ih, d["on"] is False, fit=True))

    # ---- Animation ----
    def _tick(self):
        """Ein Schritt: jede Karte ein Stueck (30 %) naeher an ihren Platz, Muelleimer einblenden,
        fliegende Karte Richtung Muelleimer; ~15 ms je Schritt, gut 0,15 s bis zum Ziel."""
        self._after = None
        a = 0.3
        for m, (tx, ty) in self._targets.items():
            x, y = self._pos.get(m, (tx, ty))
            self._pos[m] = (tx, ty) if abs(tx - x) < 0.8 and abs(ty - y) < 0.8 else (x + (tx - x) * a, y + (ty - y) * a)
        if self.drag is not None or self.fly:
            self._trash_k = min(1.0, self._trash_k + 0.2)
        if self.fly:
            f = self.fly
            cx, cy, _ = self.trash_box or (f["x"], f["y"], 0)
            f["x"] += (cx - f["x"]) * a
            f["y"] += (cy - f["y"]) * a
            f["s"] = max(0.2, f["s"] * 0.8)
            if abs(cx - f["x"]) < 2 and abs(cy - f["y"]) < 2:
                self._fly_done()
                return
        self.redraw()

    def _fly_done(self):
        """Karte ist im Muelleimer: on_delete fragt nach; abgebrochen = sie gleitet zurueck."""
        f, self.fly = self.fly, None
        m, tb = f["d"]["module"], self.trash_box
        self.drag = self.drop = None
        self.redraw()
        ok = False
        try:
            ok = self.on_delete(f["slot"], m)
        finally:
            if ok and any(d["module"] == m for d in self.slots):
                self.hidden = (m, time.monotonic() + 3)   # bis die Kette ohne ihn neu gesetzt wird
            elif not ok:
                self.hidden = None
                if tb and any(d["module"] == m for d in self.slots):
                    self._pos[m] = (tb[0] - self.CW / 2, tb[1] - self.CH / 2)
                self.redraw()


# ---------------- Dialoge ----------------
class OverlayDialog(Overlay):
    """Grundlage der modalen Dialoge als Overlay (Inhalt in .body, Ergebnis in .result, run())."""

    def __init__(self, parent, title, width=None, height=None):
        super().__init__(parent, title, width=width, height=height)

    def resizable(self, *_):
        pass

    def minsize(self, *_):
        pass


class ChoiceDialog(OverlayDialog):
    """Auswahl aus einer langen Liste mit Filterfeld."""

    def __init__(self, parent, title, values, current=None):
        super().__init__(parent, title, width=440)
        self.resizable(False, True)
        self.values = values
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.fill())
        e = Entry(self.body, textvariable=self.filter, width=40, placeholder="Filter …")
        e.pack(fill="x", pady=(0, px(8)))
        lf = tk.Frame(self.body, bg=PANEL)
        lf.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(lf, height=18, activestyle="none", exportselection=False, bg=CARD, fg=TEXT,
                                  selectbackground=ACCENT, selectforeground=ACCENT_TXT, bd=0, highlightthickness=0,
                                  font=FONT)
        sb = ttk.Scrollbar(lf, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<Double-Button-1>", lambda ev: self.ok())
        self.listbox.bind("<Return>", lambda ev: self.ok())
        bf = tk.Frame(self.body, bg=PANEL)
        bf.pack(fill="x", pady=(px(14), 0))
        Btn(bf, "Apply", command=self.ok, kind="primary").pack(side="right")
        Btn(bf, "Cancel", command=self.destroy, kind="ghost").pack(side="right", padx=px(8))
        self.fill()
        if current in values:
            i = self.shown.index(current)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(i)
            self.listbox.see(i)
        e.focus_entry()
        self.run()

    def fill(self):
        q = self.filter.get().lower()
        self.shown = [v for v in self.values if q in v.lower()]
        self.listbox.delete(0, "end")
        for v in self.shown:
            self.listbox.insert("end", v)
        if self.shown:
            self.listbox.selection_set(0)

    def ok(self):
        sel = self.listbox.curselection()
        if sel:
            self.result = self.shown[sel[0]]
            self.destroy()


class TextDialog(OverlayDialog):
    """Eine Zeile Text abfragen (Name, Programmnummer). result = Text oder None."""

    def __init__(self, parent, title, label, initial="", hint=None, ok="Apply", width=36):
        super().__init__(parent, title, width=440)
        tk.Label(self.body, text=label, bg=PANEL, fg=TEXT, font=FONT_BOLD, anchor="w").pack(fill="x", pady=(px(4), px(6)))
        self.var = tk.StringVar(value=initial)
        e = Entry(self.body, textvariable=self.var, width=width)
        e.pack(fill="x")
        e.bind_entry("<Return>", lambda ev: self.ok())
        if hint:
            tk.Label(self.body, text=hint, bg=PANEL, fg=MUTED, justify="left", anchor="w", wraplength=px(420)).pack(
                fill="x", pady=(px(6), 0))
        bf = tk.Frame(self.body, bg=PANEL)
        bf.pack(fill="x", pady=(px(18), 0))
        Btn(bf, ok, command=self.ok, kind="primary").pack(side="right")
        Btn(bf, "Cancel", command=self.destroy, kind="ghost").pack(side="right", padx=px(8))
        e.focus_entry()
        e.select_all()
        self.run()

    def ok(self):
        self.result = self.var.get()
        self.destroy()


# Kategorien der Modell-Auswahl (wie im Web-Editor); Blocknamen ohne die Endung " 2"
CATEGORIES = [
    ("Amp", ["Amp"]),
    ("Cab/IR", ["Cab", "IR", "IR (1024)"]),
    ("Overdrive", ["Green JRC-OD", "White Boost", "Anxiety OD", "Anxiety OD V2", "S1 Drive", "B2 Drive",
                   "D250 Drive", "K Drive", "Glorious Drive"]),
    ("Distortion/Fuzz", ["Tri Fuzz", "B Dist 7000", "Oct Fuzz", "D1 Dist", "Round Fuzz", "MX Dist", "Black OP",
                         "DC Distort", "8-Bit Crush"]),
    ("EQ", ["Bass EQ", "Graphic EQ", "Ten Freq EQ", "Para EQ", "Acoustic Pre"]),
    ("Compressor", ["Gray Comp", "DynIII Comp", "Side Comp", "Sustain"]),
    ("Delay", ["Tape Echo", "Time Warp", "Reverse Delay", "BBD Delay", "Dyn Delay", "Reso Delay", "AIR Delay",
               "Pitch Delay", "Hold"]),
    ("Reverb", ["AIR Reverb", "Eleven Reverb", "Spring Reverb", "Shimmer", "Ambi Verb", "Party Verb"]),
    ("Chorus", ["Chorus", "Multi Chorus", "Dim Chorus", "Stereo Doubler"]),
    ("Phaser/Flanger", ["Flanger", "AIR Flanger", "Vibe Phaser", "Orange Phaser", "Tron Phaser", "Stone Phaser"]),
    ("Vib/Trem/Rotary", ["Vibrato", "AIR Vibrato", "Rotary", "Tremolo", "Panner"]),
    ("Wah/Filter", ["Shine Wah", "Black Wah", "More Wah", "White Bass Wah", "AIR Filter", "Tron Filter",
                    "Env Filter"]),
    ("Pitch", ["Wham", "Chord Wham", "Harm", "Smart Harm", "Octaves", "Octaves Up", "Drop Tune", "Detune",
               "Ring Mod", "Feedback"]),
    ("Volume/Dynamics", ["Volume", "Noise Filter", "Gate", "Auto Swell"]),
    ("Tools", ["Acoust Sim", "FX-Loop"]),
]
# Bloecke, deren Modelle in der Auswahl als eigene Karten erscheinen: Block -> (Parameter, Art)
MODEL_PARAM = {"Amp": ("Type", "amp"), "Cab": ("CabType", "cab"), "IR": ("IR", "cab"), "IR (1024)": ("IR", "cab")}


def _norm(n):
    return " ".join(n.lower().split())


_CATEGORY_INDEX = {_norm(n): cat for cat, names in CATEGORIES for n in names}


def category_of(name):
    return _CATEGORY_INDEX.get(_norm(base_name(name)), "Other")


def class_label(name):
    """Kurze Geraeteklasse unter der Karte in der Signalkette ('Amp', 'Reverb', 'EQ', ...);
    bei Sammelkategorien entscheidet der Blockname (Phaser/Flanger, Wah/Filter, ...)."""
    base = base_name(name or "")
    cat = category_of(base)
    n = base.lower()
    if cat == "Cab/IR":
        return "IR" if n.startswith("ir") else "Cab"
    if cat == "Distortion/Fuzz":
        return "Fuzz" if "fuzz" in n else "Distortion"
    if cat == "Phaser/Flanger":
        return "Flanger" if "flanger" in n else "Phaser"
    if cat == "Vib/Trem/Rotary":
        return "Vibrato" if "vib" in n else "Tremolo" if "trem" in n else "Rotary" if "rotary" in n else "Panner"
    if cat == "Wah/Filter":
        return "Wah" if "wah" in n else "Filter"
    if cat == "Volume/Dynamics":
        return "Volume" if "volume" in n else "Swell" if "swell" in n else "Gate"
    if cat == "Tools":
        return "Acoustic" if "acoust" in n else base
    if cat == "Other":
        return base
    return cat


class ModelSelector(OverlayDialog):
    """Modell-Auswahl wie im Web-Editor: Kategorien links, Karten in der Mitte, Presets des
    gewaehlten Blocktyps rechts. names: Blocktypen des Geraets; models: {Block: [Modellnamen]}
    fuer Amp/Cab. nam: {Basisname: Anzeigename} der Bloecke, die die NAM-Mod spielt - sie erscheinen
    unter diesem Namen mit NAM-Symbol in der Kategorie Amp. Ergebnis: (Basisname, Modell oder None,
    Preset-Dict oder None)."""

    def __init__(self, parent, title, names, current=None, models=None, current_model=None, presets=None, nam=None):
        super().__init__(parent, title, 1140, 620)
        self.resizable(True, True)
        self.minsize(px(900), px(480))
        self.CARD_W, self.CARD_H, self.PAD = px(112), px(124), px(10)
        self.models = models or {}
        self.nam = nam or {}
        # presets: Funktion(basisname) -> [{name, ...}] oder None (ohne Presets); gewaehltes Preset
        # kommt als drittes Element des Ergebnisses zurueck
        self.presets = presets
        self.preset = None
        self.preset_items = []
        # Eintraege: (Anzeigename, Basisblock, Modell)
        self.items = []
        for b in sorted(set(base_name(n) for n in names), key=str.lower):
            if b in self.nam:   # NAM vorn: in "Amp" vor den 53 Amp-Modellen, sonst muesste man scrollen
                self.items.insert(sum(1 for it in self.items if it[1] in self.nam), (self.nam[b], b, None))
            elif self.models.get(b):
                for m in self.models[b]:
                    self.items.append((m, b, m))
            else:
                self.items.append((b, b, None))
        self.cats = ["All"] + [c for c, _ in CATEGORIES if any(self.cat_of(b) == c for _, b, _ in self.items)]
        if any(self.cat_of(b) == "Other" for _, b, _ in self.items):
            self.cats.append("Other")
        cur_base = base_name(current) if current else None
        self.cat = self.cat_of(cur_base) if cur_base else "All"
        self.pick = None
        for it in self.items:
            if it[1] == cur_base and (it[2] is None or it[2] == current_model):
                self.pick = it
        self.cat_labels = {}
        self.body.configure(padx=px(12))
        left = tk.Frame(self.body, bg=PANEL, width=px(200))
        left.pack(side="left", fill="y", padx=(px(8), px(12)), pady=(px(4), px(12)))
        left.pack_propagate(False)
        for c in self.cats:
            l = Btn(left, c, command=lambda c=c: self.set_cat(c), kind="ghost", padx=12, pady=4, width=190, anchor="w")
            l.pack(fill="x", pady=1)
            self.cat_labels[c] = l
        right = tk.Frame(self.body, bg=PANEL)
        right.pack(side="left", fill="both", expand=True, pady=(px(4), px(12)))
        top = tk.Frame(right, bg=PANEL)
        top.pack(fill="x", pady=(0, px(8)))
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.fill())
        Entry(top, textvariable=self.filter, placeholder="Search …", width=26).pack(side="left")
        self.lbl_pick = tk.Label(top, text="Choose model", bg=PANEL, fg=MUTED, font=FONT)
        self.lbl_pick.pack(side="right")
        self.btn_ok = Btn(top, "Apply", command=self.ok, kind="primary")
        self.btn_ok.pack(side="right", padx=(0, px(12)))
        gf = Panel(right, fill=CARD_LO, r=8)
        gf.pack(fill="both", expand=True)
        self.grid = tk.Canvas(gf.inner, bg=CARD_LO, highlightthickness=0)
        sb = ttk.Scrollbar(gf.inner, command=self.grid.yview)
        self.grid.configure(yscrollcommand=sb.set)
        self.grid.pack(side="left", fill="both", expand=True, pady=px(4))
        sb.pack(side="right", fill="y", pady=px(8))
        self.grid.bind("<Configure>", lambda e: self.fill())
        self.grid.bind("<Button-1>", self._click)
        self.grid.bind("<Double-Button-1>", lambda e: (self._click(e), self.ok()))
        self.grid.bind("<MouseWheel>", lambda e: self.grid.yview_scroll(int(-e.delta / 120), "units"))
        if self.presets:
            pf = tk.Frame(self.body, bg=PANEL, width=px(230))
            pf.pack(side="left", fill="y", padx=(px(12), px(4)), pady=(px(4), px(12)))
            pf.pack_propagate(False)
            tk.Label(pf, text="PRESET", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x", pady=(px(8), px(6)))
            self.plist = tk.Canvas(pf, bg=PANEL, highlightthickness=0, width=px(200))
            psb = ttk.Scrollbar(pf, command=self.plist.yview)
            self.plist.configure(yscrollcommand=psb.set)
            self.plist.pack(side="left", fill="both", expand=True)
            psb.pack(side="right", fill="y")
            self.plist.bind("<Button-1>", self._click_preset)
            self.plist.bind("<Double-Button-1>", lambda e: (self._click_preset(e), self.ok()))
            self.plist.bind("<MouseWheel>", lambda e: self.plist.yview_scroll(int(-e.delta / 120), "units"))
        self.bind("<Return>", lambda e: self.ok())
        self.paint_cats()
        self.fill()
        self.run()

    def cat_of(self, base):
        return "Amp" if base in self.nam else category_of(base)

    def paint_cats(self):
        for c, l in self.cat_labels.items():
            l.font = FONT_BOLD if c == self.cat else FONT
            l.set_kind("primary" if c == self.cat else "ghost")

    def set_cat(self, c):
        self.cat = c
        self.paint_cats()
        self.fill()

    def shown_items(self):
        q = self.filter.get().lower()
        return [it for it in self.items if (self.cat == "All" or self.cat_of(it[1]) == self.cat)
                and (q in it[0].lower() or q in it[1].lower())]

    def fill(self):
        g = self.grid
        g.delete("all")
        self.shown = self.shown_items()
        cw, ch, pad = self.CARD_W, self.CARD_H, self.PAD
        cols = max(1, (g.winfo_width() - pad) // (cw + pad))
        self.boxes = []
        for i, it in enumerate(self.shown):
            name, base, model = it
            x = pad + (i % cols) * (cw + pad)
            y = pad + (i // cols) * (ch + pad)
            self.boxes.append((it, x, y))
            sel = it == self.pick
            rrect(g, x, y, cw, ch, px(7), CARD, ACCENT if sel else None, 2 if sel else 0)
            iw, ih = px(90), px(63)
            g.create_image(x + cw / 2 - iw / 2, y + px(8), anchor="nw", image=model_img("NAM" if base in self.nam else base, model, iw, ih))
            lines = wrap_words(name, 16, 2)
            ty = y + ch - px(30) - (len(lines) - 1) * px(7)
            for l in lines:
                g.create_text(x + cw / 2, ty, text=l, fill=TEXT, font=FONT_SMALL)
                ty += px(15)
        rows = (len(self.shown) + cols - 1) // cols
        g.configure(scrollregion=(0, 0, g.winfo_width(), rows * (ch + pad) + pad))
        text = self.pick[0] if self.pick else "Choose model"
        if self.preset:
            text += "  ·  " + self.preset["name"]
        self.lbl_pick.configure(text=text, fg=TEXT if self.pick else MUTED)
        self.btn_ok.configure(state="normal" if self.pick else "disabled")
        if self.presets:
            self.fill_presets()

    ROW_H = 26

    def fill_presets(self):
        """Presets des gewaehlten Blocktyps (rechte Spalte); Klick waehlt eines mit aus."""
        c = self.plist
        c.delete("all")
        self.preset_items = (self.presets(self.pick[1]) or []) if self.pick else []
        if self.preset and self.preset not in self.preset_items:
            self.preset = None
        rh, w = px(self.ROW_H), max(c.winfo_width(), px(200))
        if self.pick and not self.preset_items:
            c.create_text(px(4), rh / 2, text="no presets", fill=DIM, font=FONT_SMALL, anchor="w")
        for i, it in enumerate(self.preset_items):
            y = i * rh
            sel = it == self.preset
            if sel:
                rrect(c, 0, y + 1, w - px(4), rh - 2, px(5), ACCENT)
            c.create_text(px(8), y + rh / 2, text=it["name"], fill=ACCENT_TXT if sel else TEXT, font=FONT_SMALL,
                          anchor="w")
        c.configure(scrollregion=(0, 0, w, max(1, len(self.preset_items)) * rh))

    def _click_preset(self, e):
        i = int(self.plist.canvasy(e.y) // px(self.ROW_H))
        if 0 <= i < len(self.preset_items):
            it = self.preset_items[i]
            self.preset = None if it == self.preset else it   # zweiter Klick waehlt ab
            self.fill()

    def _click(self, e):
        x, y = self.grid.canvasx(e.x), self.grid.canvasy(e.y)
        for it, bx, by in self.boxes:
            if bx <= x <= bx + self.CARD_W and by <= y <= by + self.CARD_H:
                if it != self.pick:
                    self.preset = None
                self.pick = it
                self.fill()
                return

    def ok(self):
        if self.pick:
            self.result = (self.pick[1], self.pick[2], self.preset)
            self.destroy()
