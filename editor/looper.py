"""looper.py - "Looper" als Ebene ueber dem Editor (ui.Overlay, wie der Tuner): zeigt die
Looper-Ansicht am MX5 und bedient den Looper des Geraets - Aufnahme/Overdub, Start/Stop, Peel
(letzte Ebene entfernen), Loeschen, Rueckwaerts, halbe/doppelte Geschwindigkeit und Laenge,
Loop-Pegel, Feedback, Position vor/nach der Kette und die Belegung der Fussschalter (Main/Alt).

Das Fenster fragt den Zustand ab (~25x pro Sekunde, waehrend einer Aufnahme ~45x); der Editor
setzt seine normale Abfrage so lange aus. Die Position im Loop liefert das Geraet nur in
1-%-Schritten alle ~35 ms - Ring und Abspielkopf laufen deshalb mit ~60 Bildern/s ueber eine
eigene Phase (Phase), die aus Loop-Laenge und Geraetewerten nachgefuehrt wird. Ring und
Huellkurven werden mit Pillow geglaettet gerendert.

Ebenen: Der Loop selbst liegt nur im Speicher der Geraete-App, darum zeichnet das Fenster je
Ebene die Huellkurve des Eingangspegels, den es waehrend der Aufnahme mitliest (Layers). Ebenen,
die vor dem Oeffnen des Fensters entstanden sind, erscheinen als Zeile ohne Pegeldaten.

Schliessen (x, Escape, "Close looper") verlaesst die Looper-Ansicht am Geraet wieder, der Loop
laeuft dabei weiter; verlaesst das Geraet die Ansicht selbst, schliesst sich die Ebene.
Tasten: Leertaste Start/Stop, R Aufnahme/Overdub, U Peel.
"""
import ctypes, sys, time, tkinter as tk

import live as L
import ui as U
from ui import PANEL, CARD, LINE, ACCENT, TEXT, MUTED, DIM, DANGER, px
from ui import FONT_SMALL, FONT_BOLD, FONT_HEAD, FONT_CARD

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:      # mx5editor.py prueft Pillow beim Start
    Image = None

TICK_MS = 25            # Pause zwischen zwei Abfragen
REC_TICK_MS = 8         # ... waehrend einer Aufnahme (mehr Pegelwerte fuer die Huellkurve)
FRAME_MS = 16           # Animation von Ring und Abspielkopf (~60 Bilder/s)
SLOW_MS = 500           # Pause nach einem Fehler
GRACE = 1.0             # s: eigene Einstellung nicht von der Abfrage ueberschreiben lassen
AMBER = "#f2b33d"
HINT = "The looper runs on the device. Keys: Space start/stop · R record/overdub · U peel."
STATE_COLOUR = {"RECORD": DANGER, "OVERDUB": DANGER, "PLAY": ACCENT, "READY": AMBER}
LAYER_COLOURS = [ACCENT, "#4aa8ff", "#b77cff", "#f2b33d", "#ff7aa8", "#7fd36b", "#4fd8e6", "#ff9a52"]

BINS = 400              # Aufloesung einer Ebenen-Huellkurve ueber eine Loop-Laenge
FLOOR_DB = -60.0        # darunter gilt der Pegel als still
SS = 3                  # Ueberabtastung beim Rendern
LANES_ROWS = 4          # feste Hoehe der Ebenen-Flaeche in Zeilen (der Dialog springt so nicht)
ROW_H, ROW_GAP, ROW_MIN = 34, 4, 10   # Zeilenhoehe, Abstand, kleinste Hoehe bei vielen Ebenen (px)
EASE = 0.28             # Anteil des Wegs je Bild beim Gleiten/Auf- und Zuklappen der Zeilen
REC_RENDER_S = 0.06     # eine wachsende Aufnahme-Zeile hoechstens so oft neu rendern
LANE_FONT_SMALL = ("Segoe UI", 8)   # Beschriftung flacher Zeilen (nicht fett, damit nichts springt)


def _mult(text):
    """MultText "x 2" -> 2.0 (Laengenfaktor des Loops)."""
    t = (text or "x 1").replace("x", "").strip()
    try:
        if "/" in t:
            a, b = t.split("/")
            return float(a) / float(b)
        return float(t)
    except ValueError:
        return 1.0


def _timer_resolution(on):
    """Windows-Zeitgeber auf 1 ms stellen, solange das Fenster offen ist (sonst landet after()
    auf 15,6-ms-Schritten und die Animation laeuft mit ~32 statt ~60 Bildern/s)."""
    if sys.platform == "win32":
        try:
            (ctypes.windll.winmm.timeBeginPeriod if on else ctypes.windll.winmm.timeEndPeriod)(1)
        except (AttributeError, OSError):
            pass


def _rgb(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


# ---------------- Phase: fluessige Position zwischen den Abfragen ----------------
class Phase:
    """Schaetzt die Position im Loop (0..100) fuer jeden Zeitpunkt. Nennrate = 100 % / Loop-Laenge
    (LengthText beruecksichtigt Geschwindigkeit und Laenge); jede Geraeteablesung zieht die Phase
    sanft nach (wie eine PLL), grosse Abweichungen (Sprung, Neustart) werden direkt uebernommen."""

    LAG = 0.5           # %: Geraetewert ist abgeschnitten (1-%-Schritte) -> im Mittel +0,5
    DELAY = 0.020       # s: Alter einer Ablesung bei ihrer Ankunft (Abfrage + Aktualisierungstakt)

    def __init__(self):
        self.anchor = None      # Position zur Zeit t0
        self.t0 = 0.0
        self.rate = 0.0         # %/s
        self.nominal = 0.0
        self.running = False

    def update(self, t, pos, seconds, running):
        self.running = running and bool(seconds)
        if not self.running:
            self.anchor, self.t0, self.rate = pos, t, 0.0
            return
        nominal = 100.0 / max(0.05, seconds)
        if abs(nominal - self.nominal) > 1e-6 * nominal:   # Laenge/Geschwindigkeit geaendert
            self.nominal, self.rate = nominal, nominal
        measured = pos + self.LAG + self.rate * self.DELAY
        if self.anchor is None:
            self.anchor, self.t0 = measured % 100.0, t
            return
        pred = self.at(t)
        err = (measured - pred + 50.0) % 100.0 - 50.0
        if abs(err) > 12.0:
            self.anchor, self.t0 = measured % 100.0, t
            return
        self.anchor, self.t0 = (pred + 0.12 * err) % 100.0, t
        # Rate leicht nachfuehren (LengthText hat nur 0,1 s Aufloesung), hoechstens +-10 %
        self.rate = max(0.9 * self.nominal, min(1.1 * self.nominal, self.rate * (1.0 + 0.004 * err)))

    def at(self, t):
        if self.anchor is None:
            return 0.0
        if not self.running:
            return self.anchor
        return (self.anchor + self.rate * (t - self.t0)) % 100.0


# ---------------- Layers: Pegel-Huellkurven der Ebenen ----------------
class Layers:
    """Ebenenliste wie am Geraet (verifiziert 2026-10-11): die erste Aufnahme ist Ebene 1, ein
    Overdub ergibt je vollem Durchlauf eine Ebene - NumLayers springt genau eine Loop-Laenge nach
    dem Einstiegspunkt um. Ein angefangener, nicht vollendeter Durchlauf (Rest am Ende, kurzes
    Overdub) ist keine eigene Ebene, er gehoert zur letzten (Peel braucht so viele Schritte, wie
    NumLayers zeigt). items = gezeigte Zeilen {kind: base|dub|unknown, bins: [dB oder None] * BINS
    ueber eine Loop-Laenge, mult: Laengenfaktor bei der Aufnahme}; waehrend eines Overdubs ist die
    letzte Zeile der laufende, noch ungezaehlte Durchlauf (Index dub).
    Die erste Aufnahme wird nach Zeit gesammelt (ihre Laenge steht erst beim Schliessen fest),
    Overdubs nach Position im Loop."""

    def __init__(self):
        self.items = []
        self.base = None          # (t0, [(t, dB)]) waehrend der ersten Aufnahme
        self.dub = None           # Index der Zeile des laufenden Durchlaufs (Overdub)
        self.last_frac = None     # letzte Position (0..1) der laufenden Zeile
        self.dev_layers = 0       # NumLayers des Geraets bei der letzten Ablesung
        self.synced = False       # erster Abgleich erledigt (fehlende Ebenen davor = vor dem Fenster)
        self.version = 0          # zaehlt jede Aenderung (fuer das Neuzeichnen)
        self._keys = getattr(self, "_keys", 0)   # laufende Zeilennummer (bleibt ueber Clear hinweg eindeutig)

    def _key(self):
        self._keys += 1
        return self._keys

    def counted(self):
        return len(self.items) - (1 if self.dub is not None else 0)

    def feed(self, info, t, frac):
        """Eine Ablesung verarbeiten. frac = Position im Loop (0..1, aus der Phase)."""
        start, rec = info.get("start"), info.get("rec")
        level, mult = info.get("level"), _mult(info.get("mult"))
        n = info.get("layers") or 0
        if start == "Empty" and rec != "Rec":
            if self.items or self.base:
                self.__init__()
                self.version += 1
            self.synced = True
            self.dev_layers = 0
            return
        if start == "Empty" and rec == "Rec":            # erste Aufnahme laeuft
            if self.base is None:
                self.items, self.dub = [], None
                self.base = (t, [], self._key())
            self.base[1].append((t - self.base[0], level))
            self.version += 1
            self.dev_layers = n
            self.synced = True
            return
        if self.base is not None:                        # Loop eben geschlossen
            self.items = [self._finish_base(t)]
            self.base = None
            self.version += 1
        recording = rec == "Rec"
        if self.dub is not None and n > self.dev_layers and self.dev_layers:
            # Geraet hat den laufenden Durchlauf als Ebene gezaehlt -> Zeile abschliessen
            for _ in range(n - self.dev_layers):
                self.dub = None
                if recording:                            # naechster Durchlauf beginnt hier
                    self._new_row(mult, frac)
            self.version += 1
        if not recording and self.dub is not None:
            # Ausgestiegen: der angefangene Durchlauf gehoert zur letzten Ebene (das Geraet zaehlt nur
            # waehrend der Aufnahme, nie beim Aussteigen - gemessen an fuenf Einstiegen). Sofort
            # uebernehmen: ein schnelles Wieder-Einsteigen beginnt einen neuen Durchlauf.
            rest = self.items.pop(self.dub)
            self.dub = None
            if self.items and self.items[-1].get("bins") and any(b is not None for b in rest["bins"]):
                prev = self.items[-1]
                if abs((rest.get("mult") or 1.0) - (prev.get("mult") or 1.0)) < 1e-6:
                    prev["bins"] = [b if a is None else (a if b is None else max(a, b))
                                    for a, b in zip(rest["bins"], prev["bins"])]
                    prev["rev"] = prev.get("rev", 0) + 1
            self.version += 1
        if recording:
            if self.dub is None:                         # eingestiegen: neuer Durchlauf
                self._new_row(mult, None)
            self._paint(self.items[self.dub], frac, level)
            self.version += 1
        if self.dub is None:
            self.sync(n)
        self.dev_layers = n

    def _new_row(self, mult, frac):
        self.items.append({"kind": "dub", "bins": [None] * BINS, "mult": mult, "key": self._key(), "rev": 0})
        self.dub = len(self.items) - 1
        self.last_frac = frac      # None = erst ab der naechsten Ablesung malen

    def _finish_base(self, t):
        t0, samples, _ = self.base
        total = max(0.05, t - t0)
        bins = [None] * BINS
        for ts, db in samples:
            i = min(BINS - 1, int(ts / total * BINS))
            if db is not None:
                bins[i] = db if bins[i] is None else max(bins[i], db)
        # gleicher Schluessel wie die Aufnahme-Zeile, damit die Anzeige sie nahtlos weiterfuehrt
        return {"kind": "base", "bins": _fill(bins), "mult": 1.0, "key": self.base[2], "rev": 0}

    def _paint(self, layer, frac, db):
        """Pegel von der letzten bis zur aktuellen Position eintragen (vorwaerts, ueber das Ende hinweg)."""
        if db is None:
            return
        bins = layer["bins"]
        i1 = int(frac * BINS) % BINS
        i0 = i1 if self.last_frac is None else int(self.last_frac * BINS) % BINS
        span = (i1 - i0) % BINS
        if span > BINS // 3:    # Sprung (Neustart, Rueckspulen): nur die aktuelle Stelle
            i0, span = i1, 0
        for k in range(span + 1):
            j = (i0 + k) % BINS
            bins[j] = db if bins[j] is None else max(bins[j], db)
        layer["rev"] = layer.get("rev", 0) + 1
        self.last_frac = frac

    def sync(self, n):
        """Ebenenzahl mit dem Geraet abgleichen (nur ohne laufenden Durchlauf). Peel senkt NumLayers
        -> letzte Zeilen weg. Fehlen Zeilen, sind sie beim ersten Abgleich vor dem Fenster
        entstanden (Zeilen ohne Pegel davor), spaeter verpasste Durchlaeufe (hinten)."""
        changed = False
        if n >= 1:                                       # 0 bei laufendem Loop: nicht ernst nehmen
            while len(self.items) > n:
                self.items.pop()
                changed = True
            if len(self.items) < n:
                rows = [{"kind": "unknown", "bins": None, "mult": 1.0, "before": not self.synced,
                         "key": self._key(), "rev": 0} for _ in range(n - len(self.items))]
                if self.synced:
                    self.items.extend(rows)
                else:
                    self.items[:0] = rows
                changed = True
            self.synced = True
        if changed:
            self.version += 1

    def recording_base(self):
        return self.base


def _fill(bins):
    """Luecken (keine Ablesung in diesem Abschnitt) linear zwischen den Nachbarn fuellen."""
    idx = [i for i, v in enumerate(bins) if v is not None]
    if not idx:
        return bins
    out = list(bins)
    for a, b in zip(idx, idx[1:]):
        for i in range(a + 1, b):
            out[i] = bins[a] + (bins[b] - bins[a]) * (i - a) / (b - a)
    for i in range(idx[0]):
        out[i] = bins[idx[0]]
    for i in range(idx[-1] + 1, len(out)):
        out[i] = bins[idx[-1]]
    return out


def _height(db):
    """dB -> 0..1 (Hoehe der Huellkurve)."""
    if db is None:
        return 0.0
    v = max(0.0, min(1.0, (db - FLOOR_DB) / -FLOOR_DB))
    return v ** 0.85


# ---------------- Rendering ----------------
def ring_image(size, frac, colour, full=False):
    """Fortschrittsring als geglaettetes Bild: Spur + Bogen von 12 Uhr im Uhrzeigersinn mit runden Enden."""
    S = size * SS
    im = Image.new("RGB", (S, S), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    w = int(px(9) * SS)
    m = w / 2 + SS * 2
    box = [m, m, S - m, S - m]
    dr.ellipse(box, outline=_rgb(CARD), width=w)
    col = _rgb(colour)
    if full:
        dr.ellipse(box, outline=col, width=w)
    elif frac > 0.002:
        a1 = -90 + 360.0 * frac
        dr.arc(box, -90, a1, fill=col, width=w)
        import math
        r = (S - 2 * m) / 2 - w / 2 + 0.5
        cx = cy = S / 2
        for a in (-90, a1):    # runde Enden
            x, y = cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))
            dr.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=col)
    return im.resize((size, size), Image.LANCZOS)


def row_image(w, h, row, colour, mult_now):
    """Eine Ebenen-Zeile als geglaettetes Bild: abgerundeter Hintergrund + gespiegelte Huellkurve.
    row: Ebene aus Layers.items oder {"kind": "rec", "samples": [(t, dB)]} fuer die erste Aufnahme."""
    W, H = max(1, w) * SS, max(1, h) * SS
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([0, 0, W - 1, H - 1], radius=int(min(px(5), h / 2) * SS), fill=_rgb(CARD))
    mid, amp = H / 2, max(0.0, H / 2 - 3 * SS)
    if row["kind"] == "unknown":
        for x in range(int(4 * SS), W - int(4 * SS), int(10 * SS)):   # gestrichelte Mittellinie
            dr.line([x, mid, x + 5 * SS, mid], fill=_rgb(DIM), width=SS)
    else:
        vals = []
        if row["kind"] == "rec":   # erste Aufnahme: Laenge offen, Kurve auf die bisherige Zeit gestreckt
            samples = row["samples"]
            t_end, k = max(0.25, samples[-1][0] if samples else 0.25), 0
            for x in range(0, W + 1, SS):
                ts = x / W * t_end
                while k + 1 < len(samples) and samples[k + 1][0] <= ts:
                    k += 1
                vals.append(samples[k][1] if samples else None)
        else:
            bins, factor = row["bins"], mult_now / (row.get("mult") or 1.0)
            for x in range(0, W + 1, SS):
                vals.append(bins[min(BINS - 1, int(((x / W * factor) % 1.0) * BINS))])
        top = [(x * SS, mid - max(0.6 * SS, _height(v) * amp)) for x, v in enumerate(vals)]
        bot = [(x, 2 * mid - y) for x, y in reversed(top)]
        dr.polygon(top + bot, fill=_rgb(U.blend(colour, CARD, 0.8)))
    return im.resize((max(1, w), max(1, h)), Image.LANCZOS)


class _Lane:
    """Eine gezeigte Zeile: animierte Lage (y, h -> ty, th) und ihre Canvas-Elemente."""

    def __init__(self, ty):
        self.y, self.h, self.ty, self.th = ty, 0.0, ty, 0.0
        self.img = self.dot = self.txt = self.note = self.note_bg = None
        self.src = None            # gerendertes Bild in Zielhoehe
        self.sig = None            # (Inhalt, Farbe, Breite, Hoehe) des gerenderten Bilds
        self.photo = None
        self.shown_h = None        # Hoehe des gezeigten PhotoImage
        self.rendered_at = 0.0
        self.dot_colour = None
        self.dying = False
        self.label_big = True


class LooperDialog(U.Overlay):
    """first: erste Ablesung (live.looper_open). Der Editor haelt die Ebene in editor.looper_dialog
    und wird ueber editor.looper_dialog_done(dlg, device_exited) vom Schliessen unterrichtet."""

    def __init__(self, editor, first):
        super().__init__(editor, "Looper", width=720, click_out=True)
        self.ed = editor
        self.pending = False        # Abfrage unterwegs
        self.acting = 0             # Tastendruecke unterwegs (Anzeige erst danach wieder von der Abfrage)
        self.closed = False
        self.info = first
        self.phase = Phase()
        self.layers = Layers()
        self._ring_key = None
        self._written = {}          # Pfad -> Zeit des eigenen Schreibzugriffs
        self._instant = time.time() + 0.6   # bis dahin: Zeilen sofort in voller Hoehe (Oeffnen)
        self.build()
        self.observe(first)
        self.show(first)
        # erstes Bild schon jetzt (unter der Einblende), statt Ring und Ebenen sichtbar nachzuzeichnen
        self.update_idletasks()
        self.draw_ring()
        self.draw_lanes()
        # Tasten am ganzen Fenster (die Ebene hat nicht immer den Fokus), beim Schliessen wieder entfernt
        top = self.winfo_toplevel()
        self._keys = [(key, top.bind(key, lambda e, n=name: self.key(e, n), add="+"))
                      for key, name in (("<space>", "play"), ("r", "record"), ("R", "record"),
                                        ("u", "undo"), ("U", "undo"))]
        _timer_resolution(True)
        self.after(TICK_MS, self.tick)
        self.after(FRAME_MS, self.frame)

    # ---------------- Aufbau ----------------
    def build(self):
        b = self.body
        b.configure(padx=px(6))
        top = tk.Frame(b, bg=PANEL)
        top.pack(fill="x")
        self.ring_size = s = int(px(124))
        self.ring = tk.Canvas(top, width=s, height=s, bg=PANEL, highlightthickness=0)
        self.ring.pack(side="left")
        self._ring_photo = ImageTk.PhotoImage(Image.new("RGB", (s, s), _rgb(PANEL)))
        self.ring.create_image(0, 0, image=self._ring_photo, anchor="nw")
        self.ring_state = self.ring.create_text(s / 2, s / 2 - px(8), text="", fill=DIM, font=FONT_HEAD)
        self.ring_pct = self.ring.create_text(s / 2, s / 2 + px(13), text="", fill=MUTED, font=FONT_SMALL)
        info = tk.Frame(top, bg=PANEL)
        info.pack(side="left", fill="both", expand=True, padx=(px(22), 0))
        self.lbl_len = tk.Label(info, text="", bg=PANEL, fg=TEXT, font=("Segoe UI", 28, "bold"), anchor="w")
        self.lbl_len.pack(fill="x", pady=(px(4), 0))
        self.lbl_info = tk.Label(info, text="", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w", justify="left")
        self.lbl_info.pack(fill="x")
        self.lbl_remain = tk.Label(info, text="", bg=PANEL, fg=DIM, font=FONT_SMALL, anchor="w")
        self.lbl_remain.pack(fill="x", pady=(px(4), 0))

        # Ebenen
        self.lanes = tk.Canvas(b, height=LANES_ROWS * (px(ROW_H) + px(ROW_GAP)) - px(ROW_GAP), width=px(200),
                               bg=PANEL, highlightthickness=0)
        self.lanes.pack(fill="x", pady=(px(14), 0))
        self._lanes = {}           # Schluessel -> _Lane
        self._head = None
        self._empty = None

        # Bedienung wie die Fussschalter
        row = tk.Frame(b, bg=PANEL)
        row.pack(fill="x", pady=(px(14), 0))
        big = dict(padx=16, pady=9, font=FONT_BOLD, width=128)
        self.b_rec = U.Btn(row, "RECORD", icon="record", command=lambda: self.action("record"), kind="danger", **big)
        self.b_rec.pack(side="left", padx=(0, px(8)))
        self.b_play = U.Btn(row, "START", icon="play", command=lambda: self.action("play"), **big)
        self.b_play.pack(side="left", padx=(0, px(8)))
        self.b_undo = U.Btn(row, "PEEL", icon="undo", command=lambda: self.action("undo"), **big)
        self.b_undo.pack(side="left", padx=(0, px(8)))
        self.b_clear = U.Btn(row, "CLEAR", icon="trash", command=lambda: self.action("clear"), kind="danger", **big)
        self.b_clear.pack(side="left")

        # Wiedergabe
        row = tk.Frame(b, bg=PANEL)
        row.pack(fill="x", pady=(px(14), 0))
        self.lbl_speed = self._stepper(row, "Speed", "half_speed", "double_speed")
        self.lbl_mult = self._stepper(row, "Length", "half_len", "double_len", padl=px(24))
        rev = tk.Frame(row, bg=PANEL)
        rev.pack(side="right")
        tk.Label(rev, text="Reverse", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=(0, px(8)))
        self.tg_rev = U.Toggle(rev, value=False, command=lambda on: self.action("reverse"))
        self.tg_rev.pack(side="left")

        tk.Frame(b, bg=LINE, height=1).pack(fill="x", pady=(px(14), px(10)))

        # Einstellungen
        grid = tk.Frame(b, bg=PANEL)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.sl_mix, self.lbl_mix = self._slider(grid, 0, "Loop level", L.LOOPER_MIX)
        self.sl_fb, self.lbl_fb = self._slider(grid, 1, "Feedback", L.LOOPER_FEEDBACK)
        tk.Label(grid, text="Position", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").grid(
            row=2, column=0, sticky="w", pady=(px(8), 0))
        self.seg_loc = U.Segmented(grid, ["Pre (before the chain)", "Post (after the chain)"],
                                   on_pick=lambda i: self.write(L.LOOPER_LOC, "index", i))
        self.seg_loc.grid(row=2, column=1, columnspan=2, sticky="w", pady=(px(8), 0))
        tk.Label(grid, text="Footswitches", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").grid(
            row=3, column=0, sticky="w", pady=(px(8), 0))
        fs = tk.Frame(grid, bg=PANEL)
        fs.grid(row=3, column=1, columnspan=2, sticky="w", pady=(px(8), 0))
        self.seg_alt = U.Segmented(fs, ["Main", "Alt"], on_pick=lambda i: self.write(L.LOOPER_ALT_FS, "state", i))
        self.seg_alt.pack(side="left")
        self.lbl_fs = tk.Label(fs, text="", bg=PANEL, fg=DIM, font=FONT_SMALL, anchor="w")
        self.lbl_fs.pack(side="left", padx=(px(10), 0))

        row = tk.Frame(b, bg=PANEL)
        row.pack(fill="x", pady=(px(14), 0))
        self.lbl_hint = tk.Label(row, text=HINT, bg=PANEL, fg=DIM, font=FONT_SMALL, anchor="w")
        self.lbl_hint.pack(side="left", fill="x", expand=True)
        U.Btn(row, "Close looper", command=self.close, kind="primary").pack(side="right")

    def _stepper(self, parent, label, down, up, padl=0):
        f = tk.Frame(parent, bg=PANEL)
        f.pack(side="left", padx=(padl, 0))
        tk.Label(f, text=label, bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=(0, px(8)))
        btn_down = U.Btn(f, "½", command=lambda: self.action(down), padx=8, pady=2)
        btn_down.pack(side="left")
        lbl = tk.Label(f, text="", bg=PANEL, fg=TEXT, font=FONT_BOLD, width=6)
        lbl.pack(side="left")
        btn_up = U.Btn(f, "×2", command=lambda: self.action(up), padx=8, pady=2)
        btn_up.pack(side="left")
        lbl.btns = (btn_down, btn_up)
        return lbl

    def _slider(self, grid, r, label, path):
        tk.Label(grid, text=label, bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").grid(
            row=r, column=0, sticky="w", padx=(0, px(14)))
        val = tk.Label(grid, text="", bg=PANEL, fg=TEXT, font=FONT_SMALL, width=6, anchor="e")
        sl = U.Slider(grid, 0, 100, 0,
                      command=lambda v: (val.configure(text="%d %%" % round(v)),
                                         self.write(path, "unnormalized", int(round(v)))))
        sl.grid(row=r, column=1, sticky="ew")
        val.grid(row=r, column=2, sticky="e")
        return sl, val

    # ---------------- Abfrage ----------------
    def tick(self):
        if self.closed or not self.winfo_exists():
            return
        self.raise_()    # bleibt ueber allem, was der Editor inzwischen einblendet
        s = self.ed.session
        if not s:
            self.close(quiet=True)
            return
        if self.pending:
            self.after(TICK_MS, self.tick)
            return
        self.pending = True
        s.get_many(L.LOOPER_PATHS, self.reply)

    def reply(self, res):
        self.pending = False
        if self.closed or not self.winfo_exists():
            return
        info = L.looper_parse(res) if isinstance(res, dict) else {"ok": False}
        if not info.get("ok"):
            self.lbl_hint.configure(text="No reply from the device … %s" % ((res or {}).get("err") or ""), fg=AMBER)
            self.after(SLOW_MS, self.tick)
            return
        if info.get("board") and info["board"] not in ("Looper", "Tuner", "FreeText"):
            # Looper-Ansicht am Geraet verlassen -> Fenster schliessen (der Loop laeuft weiter)
            self.close(device_exited=True)
            return
        self.observe(info)
        if not self.acting:
            self.show(info)
        if self.lbl_hint.cget("fg") != DIM:
            self.lbl_hint.configure(text=HINT, fg=DIM)
        self.after(REC_TICK_MS if info.get("rec") == "Rec" else TICK_MS, self.tick)

    def observe(self, info):
        """Phase und Ebenen mit einer Ablesung nachfuehren (auch Antworten auf Tastendruecke)."""
        t = time.time()
        playing = info.get("start") == "Playing"
        self.phase.update(t, info.get("pos") or 0.0, info.get("seconds"), playing)
        self.layers.feed(info, t, self.phase.at(t) / 100.0)

    # ---------------- Anzeige ----------------
    def show(self, info):
        self.info = info
        recording = info.get("rec") == "Rec"
        empty = info.get("start") == "Empty" and not recording
        playing = info.get("start") == "Playing"
        self.lbl_len.configure(text=info.get("length") or "00:00.0",
                               fg=DANGER if recording else (TEXT if not empty else DIM))
        n = info.get("layers") or 0
        parts = ["%d layer%s" % (n, "" if n == 1 else "s")] if n else ["No loop recorded"]
        if self.layers.dub is not None and recording:
            parts.append("recording layer %d" % (self.layers.dub + 1))
        if info.get("modified"):
            parts.append("not saved on the device")
        self.lbl_info.configure(text="  ·  ".join(parts))
        self.lbl_remain.configure(text=("Recording time left: %s" % info["remaining"].lower())
                                  if info.get("remaining") else "")
        self.b_rec.configure(text=info.get("record_text") or "RECORD")
        self.b_rec.set_kind("rec" if recording else "danger")
        self.b_play.configure(text=info.get("play_text") or "START", state="disabled" if empty else "normal")
        icon = "stop" if (playing or recording) else "play"
        if self.b_play.icon != icon:
            self.b_play.icon = icon
            self.b_play.redraw()
        self.b_undo.configure(text=info.get("undo_text") or "PEEL", state="disabled" if empty else "normal")
        self.b_clear.configure(state="disabled" if empty else "normal")
        self.lbl_speed.configure(text=(info.get("speed") or "x 1").replace("x ", "×"))
        self.lbl_mult.configure(text=(info.get("mult") or "x 1").replace("x ", "×"))
        for lbl in (self.lbl_speed, self.lbl_mult):
            for btn in lbl.btns:
                btn.configure(state="disabled" if empty else "normal")
        if self.tg_rev.value != bool(info.get("reverse")):
            self.tg_rev.set(bool(info.get("reverse")))
        now = time.time()

        def fresh(path):
            return now - self._written.get(path, 0) > GRACE
        if info.get("mix") is not None and fresh(L.LOOPER_MIX):
            self.sl_mix.set(info["mix"])
            self.lbl_mix.configure(text="%d %%" % round(info["mix"]))
        if info.get("feedback") is not None and fresh(L.LOOPER_FEEDBACK):
            self.sl_fb.set(info["feedback"])
            self.lbl_fb.configure(text="%d %%" % round(info["feedback"]))
        if info.get("loc") in ("Pre", "Post") and fresh(L.LOOPER_LOC):
            self.seg_loc.set(0 if info["loc"] == "Pre" else 1)
        if fresh(L.LOOPER_ALT_FS):
            self.seg_alt.set(1 if info.get("alt") else 0)
            self.lbl_fs.configure(text="FS2 undo (peel) · FS3 back to Main" if info.get("alt")
                                  else "FS1 start/stop · FS2 record/overdub · FS3 Alt")

    def frame(self):
        """Ein Animationsbild: Ring und Abspielkopf aus der Phase, Ebenenbild bei neuen Daten."""
        if self.closed or not self.winfo_exists():
            return
        t = time.perf_counter()
        try:
            self.draw_ring()
            self.draw_lanes()
        finally:   # Arbeitszeit abziehen, damit der Takt bei ~60 Bildern/s bleibt
            self.after(max(1, FRAME_MS - int((time.perf_counter() - t) * 1000)), self.frame)

    def draw_ring(self):
        info = self.info or {}
        state = info.get("state") or "EMPTY"
        col = STATE_COLOUR.get(state, MUTED)
        first_rec = info.get("start") == "Empty" and info.get("rec") == "Rec"
        has_loop = info.get("start") not in (None, "Empty")
        pos = self.phase.at(time.time()) if has_loop else 0.0
        frac = round(pos / 100.0 * 720) / 720.0    # halbe Grad - darunter sieht man keinen Unterschied
        key = (frac if has_loop else -1, col, first_rec)
        if key != self._ring_key:
            self._ring_key = key
            self._ring_photo.paste(ring_image(self.ring_size, frac if has_loop else 0.0, col, full=first_rec))
        c = self.ring
        c.itemconfigure(self.ring_state, text=state, fill=col if state != "EMPTY" else DIM)
        c.itemconfigure(self.ring_pct, text=("%d %%" % int(pos)) if has_loop else "")

    def lane_rows(self):
        """Gewuenschte Zeilen: [(Schluessel, Zeile, Farbe, Beschriftung, Inhaltsstand)]."""
        lay = self.layers
        out = []
        for r, it in enumerate(lay.items):
            if it["kind"] == "unknown":
                colour, name = DIM, "Layer"
            else:
                colour = DANGER if r == lay.dub else LAYER_COLOURS[r % len(LAYER_COLOURS)]
                name = "Base" if it["kind"] == "base" else "Overdub"
            out.append((it["key"], it, colour, "%d  %s" % (r + 1, name), it.get("rev", 0)))
        if lay.base is not None:
            t0, samples, key = lay.base
            out.append((key, {"kind": "rec", "samples": samples}, DANGER, "1  Recording", len(samples)))
        return out

    def draw_lanes(self):
        """Ein Bild der Ebenen-Flaeche: Zeilen gleiten in ihre Lage, neue wachsen auf, entfernte
        schrumpfen weg; gerendert wird nur eine Zeile mit neuem Inhalt oder neuer Zielhoehe."""
        c = self.lanes
        w, H = c.winfo_width(), c.winfo_height()
        if w < 50 or Image is None:
            return
        now = time.time()
        label_w = int(px(78))
        lane_w = w - label_w
        gap = px(ROW_GAP)
        rows = self.lane_rows()
        instant = now < self._instant
        n = len(rows)
        row_h = min(px(ROW_H), max(px(ROW_MIN), (H - gap * (n - 1)) / max(1, n)))
        total = n * (row_h + gap) - gap
        offset = min(0.0, H - total)          # zu viele Zeilen: die neuesten bleiben sichtbar
        mult_now = _mult((self.info or {}).get("mult"))
        wanted = set()
        for i, (key, row, colour, label, rev) in enumerate(rows):
            wanted.add(key)
            ty = offset + i * (row_h + gap)
            ln = self._lanes.get(key)
            if ln is None:
                ln = self._lanes[key] = _Lane(ty)
                if instant:   # beim Oeffnen schon vorhandene Ebenen: gleich in voller Hoehe
                    ln.h = row_h
            ln.ty, ln.th, ln.dying = ty, row_h, False
            ln.row, ln.colour, ln.label, ln.rev = row, colour, label, rev
        for key, ln in self._lanes.items():
            if key not in wanted and not ln.dying:
                ln.dying, ln.th = True, 0.0
                for item in (ln.img, ln.dot, ln.txt, ln.note_bg, ln.note):   # unter die bleibenden Zeilen
                    if item:
                        c.tag_lower(item)
        budget = [99 if instant else 1]   # hoechstens eine Zeile je Bild neu rendern (sonst Ruckler bei vielen Zeilen)
        for key in list(self._lanes):
            ln = self._lanes[key]
            for a, t in (("y", "ty"), ("h", "th")):
                cur, tgt = getattr(ln, a), getattr(ln, t)
                setattr(ln, a, tgt if abs(tgt - cur) < 0.4 else cur + (tgt - cur) * EASE)
            if ln.dying and ln.h < 0.5:
                for item in (ln.img, ln.dot, ln.txt, ln.note, ln.note_bg):
                    if item:
                        c.delete(item)
                del self._lanes[key]
                continue
            self._place_lane(c, ln, label_w, lane_w, mult_now, now, budget)
        # Hinweis ohne Ebenen
        if not self._lanes:
            if self._empty is None:
                self._empty = (c.create_text(w / 2, H / 2 - px(8), text="Layers appear here while you record",
                                             fill=MUTED, font=FONT_SMALL),
                               c.create_text(w / 2, H / 2 + px(10), fill=DIM, font=FONT_SMALL,
                                             text="(level envelope of the input, read live from the device)"))
        elif self._empty is not None:
            for item in self._empty:
                c.delete(item)
            self._empty = None
        # Abspielkopf (jedes Bild, immer obenauf)
        if self._head is None:
            self._head = c.create_line(0, 0, 0, 0, fill=TEXT, width=max(1, int(px(2))))
        info = self.info or {}
        if info.get("start") not in (None, "Empty") and self.layers.base is None and self._lanes:
            x = label_w + self.phase.at(now) / 100.0 * lane_w
            c.coords(self._head, x, 0, x, min(H, max(0.0, total)))
            c.itemconfigure(self._head, state="normal")
            c.tag_raise(self._head)
        else:
            c.itemconfigure(self._head, state="hidden")

    def _place_lane(self, c, ln, label_w, lane_w, mult_now, now, budget):
        """Bild, Punkt und Beschriftung einer Zeile an ihre aktuelle (animierte) Lage setzen."""
        th = max(1, int(round(ln.th))) if not ln.dying else (ln.src.height if ln.src else 1)
        sig = (ln.rev, ln.colour, lane_w, th, mult_now if ln.row.get("kind") != "rec" else 0)
        if not ln.dying and sig != ln.sig:
            if ln.src is None:
                go = True
            else:
                content = sig[:3] != ln.sig[:3] or sig[4] != ln.sig[4]
                settled = abs(ln.h - ln.th) < 0.5      # nur die Hoehe neu: erst nach der Animation scharf rendern
                go = budget[0] > 0 and ((content and (ln.colour != DANGER or now - ln.rendered_at > REC_RENDER_S))
                                        or (not content and settled))
            if go:
                budget[0] -= 1
                ln.src, ln.sig, ln.rendered_at, ln.shown_h = row_image(lane_w, th, ln.row, ln.colour, mult_now), sig, now, None
        h = int(round(ln.h))
        y = ln.y
        if h < 1 or ln.src is None:
            if ln.img:
                c.itemconfigure(ln.img, state="hidden")
        else:
            if h != ln.shown_h or ln.photo is None or ln.sig != getattr(ln, "_shown_sig", None):
                pic = ln.src if h == ln.src.height else ln.src.resize((ln.src.width, h), Image.BILINEAR)
                ln.photo = ImageTk.PhotoImage(pic)
                ln.shown_h, ln._shown_sig = h, ln.sig
                if ln.img is None:
                    ln.img = c.create_image(label_w, y, image=ln.photo, anchor="nw")
                else:
                    c.itemconfigure(ln.img, image=ln.photo, state="normal")
            c.coords(ln.img, label_w, y)
        # Punkt + Beschriftung (blenden mit der Hoehe ein und aus)
        cy = y + ln.h / 2
        k = min(1.0, ln.h / max(1.0, px(ROW_MIN)))
        if ln.dot is None or ln.dot_colour != ln.colour:
            if ln.dot:
                c.delete(ln.dot)
            ln.dot = U.circle(c, px(8), cy, px(8), ln.colour)
            ln.dot_colour = ln.colour
        c.coords(ln.dot, int(px(8) - px(8) / 2), int(cy - px(8) / 2))
        c.itemconfigure(ln.dot, state="normal" if ln.h >= px(8) else "hidden")
        fg = U.blend(TEXT if ln.colour != DIM else MUTED, PANEL, k)
        font = FONT_SMALL if ln.th >= px(22) or (ln.dying and ln.label_big) else LANE_FONT_SMALL
        if not ln.dying:
            ln.label_big = ln.th >= px(22)
        if ln.txt is None:
            ln.txt = c.create_text(px(18), cy, text=ln.label, fill=fg, font=font, anchor="w")
        else:
            c.coords(ln.txt, px(18), cy)
            c.itemconfigure(ln.txt, text=ln.label, fill=fg, font=font)
        c.itemconfigure(ln.txt, state="normal" if ln.h >= px(9) else "hidden")
        if ln.row.get("kind") == "unknown":
            note = "recorded before this window – no level data" if ln.row.get("before") else "no level data (missed)"
            if ln.note is None:
                ln.note_bg = c.create_rectangle(0, 0, 0, 0, fill=CARD, outline="")
                ln.note = c.create_text(0, 0, text=note, fill=MUTED, font=FONT_SMALL)
            c.coords(ln.note, label_w + lane_w / 2, cy)
            x1, y1, x2, y2 = c.bbox(ln.note)
            c.coords(ln.note_bg, x1 - px(8), y1, x2 + px(8), y2)
            state = "normal" if ln.h >= px(16) else "hidden"
            c.itemconfigure(ln.note, state=state)
            c.itemconfigure(ln.note_bg, state=state)
            c.tag_raise(ln.note_bg)
            c.tag_raise(ln.note)

    # ---------------- Bedienung ----------------
    def action(self, name):
        s = self.ed.session
        if not s or self.closed:
            return
        i = self.info or {}
        if name in ("play", "undo", "clear") and i.get("start") == "Empty" and i.get("rec") != "Rec":
            return
        self.acting += 1

        def done(res):
            self.acting -= 1
            if self.closed or not self.winfo_exists():
                return
            if isinstance(res, dict) and res.get("ok") is False and "start" not in res:
                self.lbl_hint.configure(text="Looper: %s" % res.get("err"), fg=AMBER)
                return
            if isinstance(res, dict):
                self.observe(res)
                if not self.acting:
                    self.show(res)
        s.run(lambda br: L.looper_action(br, name), done)

    def key(self, e, name):
        if self.closed or isinstance(e.widget, (tk.Entry, tk.Text)):
            return
        self.action(name)
        return "break"

    def write(self, path, field, value):
        s = self.ed.session
        if not s:
            return
        self._written[path] = time.time()
        s.set(path, field, value)

    def cancel(self):
        self.close()

    def close(self, device_exited=False, quiet=False):
        """quiet: nur das Fenster schliessen (der Editor kuemmert sich selbst um das Geraet)."""
        if self.closed:
            return
        self.closed = True
        _timer_resolution(False)
        top = self.winfo_toplevel()
        for key, fid in self._keys:
            try:
                top.unbind(key, fid)
            except tk.TclError:
                pass
        if not quiet:
            self.ed.looper_dialog_done(self, device_exited)
        U.Overlay.close(self)
