#!/usr/bin/env python3
"""MX5 Editor 0.9 - Editor fuer HeadRush-MX5-Rigs (inoffiziell).

Start:  python mx5editor.py [Ordner mit Rigs]
Offline: bearbeitet .rig-Dateien direkt (vor jedem Speichern wird gesichert).
Live:    bearbeitet Rigs am Geraet ueber die MX5 Bridge (braucht Brueckenfirmware 0.5):
         Setlists, Rig-Liste (aus der Datenbank des Geraets, Rigs ueber ihre ID), Rig laden,
         speichern, Bloecke einfuegen und entfernen, Fussschalter/Scenes/Pedale; Rigs als
         .rig-Datei sichern und das ganze Geraet (Rigs, Setlists, Block-Presets) auf einmal;
         in die Datenbank schreiben: Rigs duplizieren/umbenennen/faerben/nummerieren/loeschen,
         Setlists anlegen/umbenennen/loeschen und befuellen (Kontextmenue der Rig-Liste,
         Setlist-Menue, Setlist-Manager). Bricht die Verbindung ab, verbindet sich der Editor
         selbst wieder (connection_lost).
Oberflaeche: dunkles Erscheinungsbild nach dem Vorbild des HeadRush-Web-Editors (ui.py).
"""
import json, os, queue, sys, threading, time, tkinter as tk
from tkinter import ttk, filedialog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rigmodel import Rig, Catalog, RigError, T_NUMBER, T_BOOL, T_BOOL3, T_ENUM, T_TEXT, SPECIAL_MODULES
import live as L
import ui as U
from ui import BG, PANEL, LINE, ACCENT, TEXT, MUTED, DIM, COLOURS, px
from ui import FONT, FONT_SMALL, FONT_BOLD, FONT_HEAD, FONT_TITLE
from ui import messagebox   # Meldungen im Stil der Oberflaeche (Overlay), gleiche Aufrufe wie tkinter
from hardware import HardwarePanel, FootBar, read_tempo, SCENE_MODES, state_name
from irs import IRDialog
from nam import NAMDialog, NAMBrowser
import settings
from tuner import TunerDialog
from setlists import SetlistManager

APP = "MX5 Editor 0.9"
MIN_BRIDGE = (0, 5)   # Datenbank lesen/schreiben + Umlaute; aeltere Firmware wird abgelehnt


class BridgeTooOld(RuntimeError):
    pass
POLL_MS = 150         # kuerzester Abstand der Abfragen (Aenderungen am Geraet -> Editor)
POLL_RETRY = 80       # ms: naechster Versuch, wenn die Abfrage gerade nicht laufen durfte
POLL_SHARE = 3        # Abstand >= 3 x Dauer einer Abfrage: hoechstens 1/3 der Leitung fuer das Abfragen
WRITE_QUIET = 0.4     # s: waehrend eigener Schreibzugriffe (Regler ziehen) nicht abfragen
RECONNECT_S = 2.0     # s: Pause zwischen Verbindungsversuchen nach einem Verbindungsverlust
METER_MS = 15        # Pause zwischen zwei Pegel-Abfragen (Input/Output-Seite; eine Abfrage ~5 ms)
METER_SLOW_MS = 400   # ... nach einem Fehler oder solange ein Ablauf/der Tuner laeuft
HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(os.path.expanduser("~"), "MX5Editor_Sicherungen")
MIX = "Chain"          # Pseudo-Modul: Mischung der parallelen Wege (Pfad /Engine/Patch/Chain/...)
PARA_PARAMS = ["Para1Level", "Para1Pan", "Para2Level", "Para2Pan", "ParaDelay"]
HEAD_PARAMS = {"Doubling", "DoubleStates", "Colour"}
NAM_ROWS = [("Model", "Drive"), ("Input", "Tone"), ("Output", "Level")]   # Anxiety OD mit NAM-Mod   # Knopf '2x' in der Kette, Farbfeld im Kopf - keine Zeilen
SPECIAL_LABELS = {"Rig": "Rig", "Input": "Input", "Output": "Output", MIX: "Parallel paths"}
NO_PRESET = "– no preset –"
WRITE_GRACE = 2.0     # s: so lange nach einem eigenen Schreibzugriff ueberschreibt die Abfrage den Wert nicht


def fmt(v):
    if isinstance(v, float):
        return ("%.4f" % v).rstrip("0").rstrip(".")
    return str(v)


def slider_range(seen_lo, seen_hi, cur):
    """Reglerbereich aus beobachteten Werten. Prozentartige Werte (alles
    innerhalb 0..100) bekommen 0..100, sonst der beobachtete Bereich."""
    if seen_lo is None or seen_hi is None:
        return None, None
    lo, hi = min(seen_lo, cur), max(seen_hi, cur)
    if 0 <= lo and hi <= 100 and hi > 10:
        return 0, 100
    return lo, hi


def load_model_pages():
    """Reglerseiten je Modell, wie das Geraet sie zeigt (modellseiten.json, gelesen mit
    werkzeuge/amp_seiten.py): {Block: {Modell: [(Beschriftung, Parameter der Haelfte A)]}}."""
    try:
        with open(os.path.join(HERE, "modellseiten.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {b: {m: [tuple(r) for r in rows] for m, rows in v.items()} for b, v in data.items() if isinstance(v, dict)}


MODEL_PAGES = load_model_pages()


class Editor(tk.Tk):
    def __init__(self, folder=None):
        U.dpi_aware()
        super().__init__()
        self.title(APP)
        try:   # Fenster-/Taskleisten-Icon (werkzeuge/exe_bauen.py erzeugt es; fehlt es, bleibt das Tk-Icon)
            self.iconbitmap(default=os.path.join(HERE, "mx5editor.ico"))
        except tk.TclError:
            pass
        self.prefs = settings.load()   # Einstellungen (settings.py), z. B. 'audition'
        self.ui_scale = self.prefs["ui_scale"]   # beim Start gesetzte Groesse (Aenderung gilt ab Neustart)
        U.setup(self, self.ui_scale / 100.0)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()   # groessere Oberflaeche: nicht ueber den Bildschirm
        self.geometry("%dx%d" % (min(px(1480), sw - 40), min(px(820), sh - 80)))
        self.minsize(min(px(1240), sw - 40), min(px(720), sh - 80))
        self.catalog = Catalog(os.path.join(HERE, "catalog.json"))
        self.folder = None
        self.files = []
        self.shown = []
        self.rig = None           # Offline-Rig
        self.presets_offline = {} # Block-Presets aus Blocks\ neben dem Rig-Ordner: TYP -> [{name, content}]
        self.session = None       # Live-Sitzung
        self.lrig = None          # Live-Rig
        self.live_shown = []      # sichtbare Live-Rigs [(index, name, farbe, id)] (live.LiveRig.rigs)
        self.module = None
        self.half = None          # "A"/"B" bei doppelten Bloecken (Doubling), sonst None
        self._inbox = queue.Queue()
        self._batch_id = 0
        self._busy = False        # Sammelabfrage laeuft
        self._job = False         # laengere Geraeteaktion laeuft (Laden, Speichern, Rig-Liste)
        self._written = {}        # Pfad -> Zeit des letzten eigenen Schreibzugriffs
        self._last_write = 0.0    # Zeit des letzten eigenen Schreibzugriffs ueberhaupt
        self._sync_s = 0.0        # Dauer der letzten Abfrage (live_sync)
        self.live_widgets = {}    # Pfad -> Funktion(info), aktualisiert ein Parameter-Widget
        self._rows = None         # (Modul, params_for) der gezeigten Parameterzeilen
        self._meter = None        # (Modul, ui.LevelMeter) der Input-/Output-Seite
        self._meter_token = 0     # beendet eine alte Pegel-Abfrageschleife
        self.hw_panel = None      # Feld 'Hardware' unter dem Signalpfad (hardware.HardwarePanel)
        self.fsbar = None         # zugeklappte Form davon: die drei Fussschalter + 'Zuweisen' (hardware.FootBar)
        self.scene = None         # (Fussschalter 5-7, Zustand 1-2): Scene, die im Signalpfad bearbeitet wird
        self.assign = None        # Fussschalter 5-7 im Toggle-Modus, dessen Block im Signalpfad gewaehlt wird
        self.scene_dd = None      # Preset-Auswahl im Parameterfeld (Scene-Modus)
        self.ir_dialog = None
        self.nam_dialog = None
        self.nam_browser = None   # Modellauswahl eines NAM-Blocks (nam.NAMBrowser)
        self.settings_dialog = None
        self._nam_auto_told = False  # Hinweis "NAM automatisch abgeschaltet" nur einmal je Sitzung
        self.tuner_dialog = None
        self._colour_entries = []  # Auswahlliste 'Colour' der Bloecke (live, einmal gelesen)
        self._connecting = False   # Verbindungsversuch laeuft (Knopf 'Connect to Device')
        self._connect_err = None   # Hinweis unter dem Knopf nach einem Fehlschlag
        self._reconnect = 0        # >0: automatische Wiederverbindung laeuft (Nummer des Versuchs-Threads)
        self._reconnect_seq = 0    # laufende Nummer der Versuchs-Threads (nie wiederverwendet)
        self.irs_offline = None   # IR-Dateien aus 'Impulse Responses' neben dem Rig-Ordner (offline)
        self.setlist_mgr = None   # Setlist-Manager (setlists.SetlistManager), ersetzt solange die Hauptansicht
        self._build()
        self.after(20, self._pump)
        if folder:
            self.open_folder(folder)
        elif self.prefs["auto_connect"]:   # ohne Ordner: gleich verbinden (still, bei Fehlschlag bleibt der Knopf)
            self.after(300, lambda: self.connect(quiet=True))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- Aufbau ----------------
    def title(self, text=None):
        """Fenstertitel (Taskleiste) und eigene Titelleiste gemeinsam setzen."""
        if text is None:
            return self.wm_title()
        if getattr(self, "titlebar", None):
            self.titlebar.set_title(text)
        return self.wm_title(text)

    def _build(self):
        # eigene Titelleiste statt der von Windows (ohne Windows: normale Leiste)
        self.titlebar = U.TitleBar(self, self.wm_title(), on_close=self.on_close, logo="MX5")
        if self.titlebar.active:
            self.titlebar.pack(side="top", fill="x")
        # Statuszeile
        status = tk.Frame(self, bg=BG)
        status.pack(side="bottom", fill="x")
        self.status = tk.StringVar(value="“Live” connects to the device, “Folder” opens .rig files.")
        tk.Label(status, textvariable=self.status, bg=BG, fg=MUTED, font=FONT_SMALL, anchor="w",
                 padx=px(14), pady=px(4)).pack(side="left", fill="x", expand=True)
        self.lbl_mode = tk.Label(status, text="OFFLINE", bg=BG, fg=MUTED, font=("Segoe UI", 9, "bold"), padx=px(14))
        self.lbl_mode.pack(side="right")

        # Symbolleiste links
        rail = tk.Frame(self, bg=BG, width=px(60))
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        if self.titlebar.active:   # der Schriftzug sitzt dann in der Titelleiste
            tk.Frame(rail, bg=BG, height=px(10)).pack()
        else:
            tk.Label(rail, text="MX5", bg=BG, fg=ACCENT, font=("Segoe UI", 13, "bold")).pack(pady=(px(16), px(12)))
        self.rail_rigs = U.RailButton(rail, "rigs", "Rig", command=self.show_rig_view)
        self.rail_rigs.pack()
        self.rail_tuner = U.RailButton(rail, "tuner", "Tuner", command=self.open_tuner)
        self.rail_tuner.pack()
        self.rail_sets = U.RailButton(rail, "setlist", "Setlists", command=self.open_setlists)
        self.rail_sets.pack()
        self.rail_irs = U.RailButton(rail, "ir", "IRs", command=self.manage_irs)
        self.rail_irs.pack()
        self.rail_nam = U.RailButton(rail, "nam", "NAM", command=self.manage_nam)
        self.rail_nam.pack()
        self.rail_settings = U.RailButton(rail, "gear", "Settings", command=self.open_settings)
        self.rail_settings.pack(side="bottom", pady=(0, px(8)))
        self.rail_folder = U.RailButton(rail, "folder", "Folder", command=self.ask_folder)
        self.rail_folder.pack(side="bottom")
        self.rail_live = U.RailButton(rail, "live", "Live", command=self.toggle_live)
        self.rail_live.pack(side="bottom")

        # Rig-Liste
        lp = U.Panel(self, width=px(290))
        self.lpanel = lp
        lp.pack(side="left", fill="y", pady=(px(8), px(8)))
        lp.pack_propagate(False)
        left = lp.inner
        head = tk.Frame(left, bg=PANEL)
        head.pack(fill="x", padx=px(4), pady=(px(10), px(4)))
        self.btn_setlist = U.Btn(head, "Rigs  ▾", command=self.open_setlist_menu, kind="ghost", font=FONT_HEAD, padx=4)
        self.btn_setlist.base_fg = TEXT
        self.btn_setlist.redraw()
        self.btn_setlist.pack(side="left")
        self.lbl_count = tk.Label(head, text="", bg=PANEL, fg=MUTED, font=FONT_SMALL)
        self.lbl_count.pack(side="right")
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.fill_list())
        U.Entry(left, textvariable=self.filter, placeholder="Search …").pack(fill="x", padx=px(4), pady=(px(2), px(8)))
        lf = tk.Frame(left, bg=PANEL)
        lf.pack(fill="both", expand=True, pady=(0, px(6)))
        self.riglist = U.RigList(lf, on_pick=self.on_pick_rig, on_menu=self.rig_menu, on_move=self.on_move_rig)
        sb = ttk.Scrollbar(lf, command=self.riglist.yview)
        self.riglist.configure(yscrollcommand=sb.set)
        self.riglist.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Parameter rechts
        rp = U.Panel(self, width=px(440))
        self.rpanel = rp
        rp.pack(side="right", fill="y", pady=(px(8), px(8)), padx=(0, px(8)))
        rp.pack_propagate(False)
        right = rp.inner
        self.phead = tk.Frame(right, bg=PANEL, padx=px(8), pady=px(14))
        self.phead.pack(fill="x")
        self.colour_box = tk.Canvas(self.phead, width=px(24), height=px(24), bg=PANEL, highlightthickness=0,
                                    cursor="hand2")   # Klick: Farbe des Blocks waehlen
        self.colour_box.bind("<Button-1>", lambda e: self.pick_block_colour())
        self.colour_box.bind("<Enter>", lambda e: self.draw_colour_box(True))
        self.colour_box.bind("<Leave>", lambda e: self.draw_colour_box(False))
        self.model_box = tk.Canvas(self.phead, width=px(50), height=px(35), bg=PANEL, highlightthickness=0)
        self.param_title = tk.Label(self.phead, text="", bg=PANEL, fg=TEXT, font=FONT_TITLE, anchor="w")
        self.param_title.pack(side="left", fill="x", expand=True)
        self.head_toggle = U.Toggle(self.phead, command=self.on_head_toggle, w=46, h=24)
        self.param_sub = tk.Label(right, text="", bg=PANEL, fg=ACCENT, font=FONT_SMALL, anchor="w", padx=px(8))
        self.head_btns = tk.Frame(right, bg=PANEL, padx=px(8))
        self.preset_row = tk.Frame(right, bg=PANEL, padx=px(8))
        self.preset_dd = None
        self.psep = tk.Frame(right, bg=LINE, height=1)
        self.psep.pack(fill="x", padx=px(8))
        pf = tk.Frame(right, bg=PANEL)
        pf.pack(fill="both", expand=True, padx=(px(8), 0), pady=(px(8), px(8)))
        self.canvas = tk.Canvas(pf, bg=PANEL, highlightthickness=0)
        psb = ttk.Scrollbar(pf, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=psb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        psb.pack(side="right", fill="y")
        self.params = tk.Frame(self.canvas, bg=PANEL)
        self.params.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._pwin = self.canvas.create_window((0, 0), window=self.params, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._pwin, width=e.width))
        self.bind_all("<MouseWheel>", self._wheel)

        # Mitte: Kopfzeile mit Rig-Name und Aktionen, darunter die Signalkette
        center = tk.Frame(self, bg=BG)
        center.pack(side="left", fill="both", expand=True, padx=px(8), pady=(px(8), px(8)))
        self.center = center
        tp = U.Panel(center, height=px(52))
        tp.pack(fill="x")
        tp.pack_propagate(False)
        top = tk.Frame(tp.inner, bg=PANEL)
        top.pack(fill="both", expand=True, pady=px(8))
        actions = tk.Frame(top, bg=PANEL)
        actions.pack(side="right")
        self.btn_revert = U.Btn(actions, "Discard", command=self.revert, kind="ghost", state="disabled")
        self.btn_revert.pack(side="left", padx=(0, px(6)))
        self.btn_save = U.Btn(actions, "Save", command=self.save, kind="primary", state="disabled")
        self.btn_save.pack(side="left", padx=(0, px(6)))
        U.Btn(actions, "⋯", command=self.open_menu, kind="ghost", padx=8, font=("Segoe UI", 13, "bold")).pack(side="left")
        mid = tk.Frame(top, bg=PANEL)
        mid.pack(side="left", fill="x", expand=True)
        name_row = tk.Frame(mid, bg=PANEL)
        name_row.pack()
        self.scene_badge = U.Badge(name_row, "SCENE MODE")   # nur im Scene-Modus sichtbar (set_scene)
        self.btn_prev = U.Btn(name_row, "◀", command=lambda: self.step_rig(-1), kind="ghost", padx=10)
        self.btn_prev.pack(side="left")
        self.lbl_name = tk.Label(name_row, text="No rig open", bg=PANEL, fg=TEXT, font=FONT_HEAD, cursor="hand2",
                                 padx=px(16))
        self.lbl_name.pack(side="left")
        self.lbl_name.bind("<Button-1>", lambda e: self.view and not self.scene and self.pick_module("Rig"))
        self.lbl_name.bind("<Double-Button-1>", lambda e: self.begin_rename())
        self.name_edit = None     # tk.Entry, solange der Name direkt bearbeitet wird
        self.lbl_dirty = tk.Label(name_row, text="", bg=PANEL, fg=ACCENT, font=FONT_HEAD)
        self.lbl_dirty.pack(side="left")
        self.btn_next = U.Btn(name_row, "▶", command=lambda: self.step_rig(1), kind="ghost", padx=10)
        self.btn_next.pack(side="left")

        rb = tk.Frame(center, bg=BG)
        rb.pack(fill="x", pady=(px(8), 0))
        self.seg_routing = U.RoutingPicker(rb, 0, on_pick=self.set_routing, on_hover=self.show_routing_name)
        self.seg_routing.pack(side="right")
        self.lbl_route_name = tk.Label(rb, text="", bg=BG, fg=TEXT, font=FONT_SMALL)
        self.lbl_route_name.pack(side="right", padx=(0, px(10)))
        tk.Label(rb, text="Routing", bg=BG, fg=MUTED, font=FONT_SMALL).pack(side="right", padx=(0, px(6)))
        self.chain = U.ChainCanvas(center, on_pick=self.pick_module, on_empty=self.on_empty_slot,
                                   on_menu=self.block_menu, on_io=self.pick_module, on_toggle=self.toggle,
                                   on_move=self.move_block, on_mix=lambda: self.pick_module(MIX),
                                   on_exit=self.exit_fs_mode, on_delete=self.drop_block,
                                   plan=L.plan_block_move, on_double=self.chain_double,
                                   on_connect=lambda: self.connect())
        self.chain.pack(fill="both", expand=True, pady=(px(4), 0))
        self.draw_chain()
        foot = tk.Frame(center, bg=BG)
        foot.pack(fill="x", padx=px(4), pady=(0, px(2)))
        self.foot = foot   # das Hardware-Feld bzw. die Fussschalter-Leiste wird davor eingehaengt
        self.fsbar = FootBar(self, center)   # nur live sichtbar (show_fsbar)
        self.btn_assign = self.fsbar.btn_assign
        self.lbl_chain = tk.Label(foot, text="", bg=BG, fg=DIM, font=FONT_SMALL)
        self.lbl_chain.pack(side="right")

    @property
    def view(self):
        return self.lrig if self.session else self.rig

    def _wheel(self, e):
        """Mausrad an die Liste oder das Parameterfeld unter dem Zeiger weiterreichen."""
        w = self.winfo_containing(e.x_root, e.y_root)
        step = int(-e.delta / 120)
        while w is not None:
            if w is self.riglist:
                self.riglist.yview_scroll(step, "units")
                return
            if w is self.canvas:
                self.canvas.yview_scroll(step, "units")
                return
            if hasattr(w, "scroll_wheel"):   # Listen des Setlist-Managers
                w.scroll_wheel(step)
                return
            w = w.master

    def write(self, path, field, value, callback=None):
        """Schreiben ueber die Sitzung; merkt sich die Zeit, damit die Abfrage den Wert nicht
        gleich wieder mit einem alten Stand ueberschreibt."""
        self._written[path] = self._last_write = time.time()
        self.session.set(path, field, value, callback)

    def set_mode_badge(self, version=None, text=None):
        if version:
            self.lbl_mode.configure(text="●  LIVE   " + version, fg=ACCENT)
        elif text:
            self.lbl_mode.configure(text=text, fg=U.WARN)
        else:
            self.lbl_mode.configure(text="OFFLINE", fg=MUTED)
        self.rail_live.set_lit(bool(version))

    # ---------------- Ordner und Liste ----------------
    def ask_folder(self):
        d = filedialog.askdirectory(title="Choose a folder with rigs")
        if d:
            self.open_folder(d)

    def open_folder(self, d):
        self.stop_reconnect()
        if self.session:
            self.disconnect()
        if os.path.isdir(os.path.join(d, "Rigs")):
            d = os.path.join(d, "Rigs")
        if not self.confirm_discard():
            return
        self.folder = d
        self.files = sorted(f for f in os.listdir(d) if f.lower().endswith(".rig"))
        self.presets_offline = self.read_block_files(os.path.join(os.path.dirname(d), "Blocks"))
        self.irs_offline = L.read_ir_folder(os.path.join(os.path.dirname(d), "Impulse Responses"))
        self.fill_list()
        n = sum(len(v) for v in self.presets_offline.values())
        self.status.set("%d rigs in %s%s" % (len(self.files), d, ", %d block presets" % n if n else ""))

    @staticmethod
    def read_block_files(folder):
        """Blocks/<Typ>/<Name>.block (USB-Export oder 'Alles sichern') -> {TYP: [{name, content}]}."""
        out = {}
        if not os.path.isdir(folder):
            return out
        for typ in sorted(os.listdir(folder)):
            tdir = os.path.join(folder, typ)
            if not os.path.isdir(tdir):
                continue
            for f in sorted(os.listdir(tdir)):
                if not f.lower().endswith(".block"):
                    continue
                try:
                    with open(os.path.join(tdir, f), encoding="utf-8") as fh:
                        d = json.load(fh)
                    json.loads(d["content"])
                except (OSError, ValueError, KeyError, TypeError):
                    continue
                out.setdefault(str(d.get("type", typ)).upper(), []).append({"name": f[:-6], "content": d["content"]})
        return out

    def fill_list(self):
        q = self.filter.get().lower()
        if self.session:
            self.live_shown = [r for r in self.lrig.rigs() if q in r[1].lower()]
            self.riglist.can_move = self.can_write() and self.lrig.setlist != L.ALL_RIGS and not q
            self.riglist.set_items([(name, COLOURS.get(col)) for _, name, col, _ in self.live_shown])
            self.lbl_count.configure(text="%d rigs" % len(self.lrig.rigs()))
            self.select_current()
            self.refresh_setlists()
            return
        self.btn_setlist.configure(text=(os.path.basename(self.folder) if self.folder else "Rigs") + "  ▾")
        if not self.folder:
            self.riglist.set_items([])
            self.lbl_count.configure(text="")
            return
        self.shown = [f for f in self.files if q in f.lower()]
        self.riglist.set_items([(f[:-4], None) for f in self.shown])
        self.lbl_count.configure(text="%d rigs" % len(self.files))
        self.select_current()

    def on_pick_rig(self, i):
        if self.session:
            if i >= len(self.live_shown):
                return
            index, name, _, rid = self.live_shown[i]
            if rid == self.lrig.rig_id:
                return
            if self._job:
                self.status.set("Please wait, the device is still busy.")
                self.select_current()
                return
            if self.lrig.dirty:
                how = self.ask_unsaved("Save before loading “%s”?" % name)
                if how is None:
                    self.select_current()
                    return
                if how != "discard":   # erst speichern, danach das gewaehlte Rig laden
                    self.select_current()
                    self.live_store(how, then=lambda: self.load_rig_id(rid))
                    return
            self.live_load_rig(index, name, discard=self.lrig.dirty)
            return
        if i >= len(self.shown):
            return
        path = os.path.join(self.folder, self.shown[i])
        if self.rig and path == self.rig.path:
            return
        if not self.confirm_discard():
            self.select_current()
            return
        self.load_rig(path)

    def ask_unsaved(self, question, discard="Discard"):
        """Rueckfrage bei ungespeicherten Aenderungen am Geraet: 'save', 'new' (als neues Rig
        speichern), 'discard' oder None (abbrechen)."""
        buttons = [("Cancel", None, "ghost"), (discard, "discard", "danger")]
        if self.can_write():
            buttons.append(("Save as new rig …", "new", "default"))
        buttons.append(("Save", "save", "primary"))
        self.focus_set()
        return U.ask(self, "“%s” has unsaved changes.\n%s" % (self.lrig.name, question), buttons,
                     icon="warning", width=520,
                     detail="“%s” throws them away (the MX5's own prompt is answered automatically)." % discard)

    def load_rig_id(self, rig_id):
        """Rig nach ID aus der (ggf. neu gelesenen) Liste laden - nach dem Speichern."""
        lr = self.lrig
        if not lr or rig_id == lr.rig_id:
            return
        for index, n, _, rid in lr.rigs():
            if rid == rig_id:
                self.live_load_rig(index, n, discard=lr.dirty)
                return
        self.status.set("The rig is no longer in the list.")

    def rig_menu(self, event, i):
        m = U.menu(self)
        if self.session:
            index, name, _, rid = self.live_shown[i]
            m.add_command(label="Load “%s”" % name, command=lambda: self.on_pick_rig(i))
            m.add_command(label="Back up as .rig file …", command=lambda: self.live_export_rig(rid, name))
            if self.can_write():
                lr = self.lrig
                m.add_separator()
                m.add_command(label="Duplicate …", command=lambda: self.live_duplicate_rig(i))
                m.add_command(label="Rename …", command=lambda: self.live_rename_rig(i))
                cm = U.menu(self)
                for ci, cname in enumerate(L.RIG_COLOURS):
                    cm.add_command(label=cname, command=lambda c=ci: self.live_set_color(i, c),
                                   swatch=COLOURS.get(cname, COLOURS["Off"]))
                m.add_cascade(label="Colour", menu=cm)
                m.add_command(label="Program number …", command=lambda: self.live_set_prognum(i))
                if lr.setlists and lr.setlist_ids:
                    sm = U.menu(self)
                    for sname in lr.setlists:
                        if sname in lr.setlist_ids:
                            sm.add_command(label=sname, command=lambda n=sname: self.live_setlist_add(i, n))
                    m.add_cascade(label="Add to setlist", menu=sm)
                if lr.setlist != L.ALL_RIGS:
                    m.add_command(label="Remove from “%s”" % lr.setlist, command=lambda: self.live_setlist_remove(i))
                m.add_separator()
                m.add_command(label="Delete …", command=lambda: self.live_delete_rig(i))
        else:
            m.add_command(label="Open", command=lambda: self.on_pick_rig(i))
        m.tk_popup(event.x_root, event.y_root)

    def on_move_rig(self, src, dst):
        """Rig in der Setlist verschieben (Ziehen in der Liste): src -> dst (Indizes der Anzeige)."""
        lr = self.lrig
        if not self.can_write() or lr.setlist == L.ALL_RIGS or self.filter.get():
            return
        ids = [r["id"] for r in lr.rows]
        if not (0 <= src < len(ids) and 0 <= dst < len(ids)):
            return
        rid = ids.pop(src)
        ids.insert(dst, rid)
        sid = lr.setlist_ids[lr.setlist]
        name = self.live_shown[src][1]
        self.db_job(lambda br: L.setlist_set_order(br, sid, ids), "Moving “%s” to position %d …" % (name, dst + 1))

    # ---- Datenbank schreiben ----
    def can_write(self):
        """Live verbunden (die Bruecke ist mindestens MIN_BRIDGE, das prueft open_bridge)."""
        return bool(self.session and self.lrig)

    def _shown_rig(self, i):
        """(index in der Liste, Anzeigename, Datenbank-ID) des i-ten sichtbaren Rigs."""
        index, name, _, rid = self.live_shown[i]
        return index, name, rid

    def db_job(self, fn, text, reload=False, restart=False, then=None, refresh=True, load_result=False, confirm=True,
               restart_action="restart"):
        """fn(br) schreibt in die Datenbank; danach liest das Geraet die aktive Liste neu
        (refresh_lists, ca. 1 s, das geladene Rig bleibt samt Aenderungen; restart=True:
        App-Neustart, noetig fuer Setlist-Aenderungen). reload=True: das geladene Rig danach
        neu laden, weil seine eigene Zeile geaendert wurde (Aenderungen gehen verloren, wird
        gefragt). refresh=False: die aktive Liste ist nicht betroffen, nichts neu lesen.
        load_result=True: fn liefert die ID des Rigs, das danach geladen wird (save_rig_as -
        fn speichert den Stand, darum keine Rueckfrage). confirm=False: der Aufrufer hat schon
        gefragt. restart_action: Aktion der Bruecke, die neu startet (nam-on/nam-off schalten NAM
        vorher um). Liefert True, wenn der Auftrag gestartet wurde."""
        lr = self.lrig
        if not self.can_write():
            return False
        if self._job:
            self.status.set("Please wait, the device is still busy.")
            return False
        if confirm and lr.dirty and (reload or restart) and not messagebox.askyesno(
                APP, "“%s” has unsaved changes on the device that will be lost.\n"
                     "Continue anyway?%s" % (lr.name, "\n\n(The device app will restart, about 15 s.)" if restart else "")):
            return False
        setlists, setlist, ids, rig_id = lr.setlists, lr.setlist, lr.setlist_ids, lr.rig_id
        progress = lambda t: self._inbox.put(lambda: self.status.set(t))

        def job(br):
            result = fn(br)
            rid = result if load_result else (rig_id if reload or restart else None)
            if restart:   # lr.setlist darf fn geaendert haben (Setlist umbenannt/geloescht)
                res = L.restart_app(br, rig_id=rid, setlist=lr.setlist, progress=progress, action=restart_action)
            elif refresh or load_result:
                res = L.refresh_lists(br, setlists, setlist, ids, reload_id=rid, reload_row=reload)
            else:
                res = {}
            res["result"] = result
            return res

        def done(res, err):
            if err:
                messagebox.showwarning(APP, err)
                self.live_scan_rigs()
                return
            after = (lambda: then(res["result"])) if then else None
            if "rows" in res:
                self._rig_list_done(res, None)
                self.live_reload(then=after)   # then() nach dem Neulesen, damit seine Meldung stehen bleibt
            else:
                self.status.set("Done.")
                if after:
                    after()
        self.run_job(job, done, text)
        return True

    def ask_text(self, title, label, initial="", hint=None):
        self.focus_set()
        self.update()
        return U.TextDialog(self, title, label, initial, hint).result

    def live_duplicate_rig(self, i):
        index, name, rid = self._shown_rig(i)
        lr = self.lrig
        new = self.ask_text("Duplicate rig", "Name of the copy of “%s”:" % name, name + " 2",
                            "The copy contains the saved state of the rig%s."
                            % (" and is appended to “%s”" % lr.setlist if lr.setlist != L.ALL_RIGS else ""))
        if not new:
            return
        sid = lr.setlist_ids.get(lr.setlist) if lr.setlist != L.ALL_RIGS else None
        color = int(lr.rows[index].get("color") or 0)
        self.db_job(lambda br: L.create_rig(br, new, src_id=rid, color=color, setlist_id=sid),
                    "Creating “%s” …" % new.upper())

    def live_rename_rig(self, i):
        index, name, rid = self._shown_rig(i)
        row = self.lrig.rows[index]
        new = self.ask_text("Rename rig", "New name for “%s”:" % name, row.get("name", name),
                            "ASCII characters only, the device shows upper case.")
        if not new or new == row.get("name"):
            return
        self.db_job(lambda br: L.rename_rig(br, rid, new), "Renaming to “%s” …" % new.upper(),
                    reload=(rid == self.lrig.rig_id))

    def live_set_color(self, i, color):
        index, name, rid = self._shown_rig(i)
        self.db_job(lambda br: L.set_rig_color(br, rid, color), "Setting the colour of “%s” …" % name,
                    reload=(rid == self.lrig.rig_id))

    def live_set_prognum(self, i):
        index, name, rid = self._shown_rig(i)
        cur = L._prog(self.lrig.rows[index])
        txt = self.ask_text("Program number", "MIDI program number for “%s” (1–128, empty = none):" % name,
                            str(cur) if cur else "", "If another rig already has this number, it loses it.")
        if txt is None:
            return
        txt = txt.strip()
        if txt and not txt.isdigit():
            messagebox.showwarning(APP, "Please enter a number from 1 to 128.")
            return
        prog = int(txt) if txt else None
        self.db_job(lambda br: L.set_rig_prognum(br, rid, prog), "Setting the program number of “%s” …" % name,
                    reload=(rid == self.lrig.rig_id))

    def live_delete_rig(self, i):
        index, name, rid = self._shown_rig(i)
        if rid == self.lrig.rig_id:
            messagebox.showinfo(APP, "The loaded rig cannot be deleted.\nPlease load another rig first.")
            return
        if not messagebox.askyesno(APP, "Delete rig “%s” from the device for good?\n"
                                        "It also disappears from all setlists." % name):
            return
        self.db_job(lambda br: L.delete_rig(br, rid), "Deleting “%s” …" % name)

    def live_setlist_add(self, i, setlist_name):
        index, name, rid = self._shown_rig(i)
        sid = self.lrig.setlist_ids[setlist_name]
        # eine andere Setlist liest das Geraet beim naechsten Betreten ohnehin neu
        self.db_job(lambda br: L.setlist_add(br, sid, rid), "Appending “%s” to “%s” …" % (name, setlist_name),
                    refresh=(setlist_name == self.lrig.setlist),
                    then=lambda _: self.status.set("“%s” appended to “%s”." % (name, setlist_name)))

    def live_setlist_remove(self, i):
        index, name, rid = self._shown_rig(i)
        lr = self.lrig
        sid = lr.setlist_ids[lr.setlist]
        ids = [r["id"] for r in lr.rows]
        if index >= len(ids):
            return
        del ids[index]
        self.db_job(lambda br: L.setlist_set_order(br, sid, ids), "Removing “%s” from “%s” …" % (name, lr.setlist))

    def live_new_setlist(self):
        lr = self.lrig
        new = self.ask_text("New setlist", "Name of the new setlist:", "",
                            "The device reads setlists only when its app starts – it will be restarted (about 15 s).")
        if not new:
            return
        rig_ids = []
        if lr.rig_id and messagebox.askyesno(APP, "Add the loaded rig “%s” to the new setlist right away?" % lr.name):
            rig_ids = [lr.rig_id]
        self.db_job(lambda br: L.create_setlist(br, new, rig_ids), "Creating setlist “%s” …" % new.upper(), restart=True)

    def live_rename_setlist(self):
        lr = self.lrig
        if lr.setlist == L.ALL_RIGS or lr.setlist not in (lr.setlist_ids or {}):
            return
        new = self.ask_text("Rename setlist", "New name for “%s”:" % lr.setlist, lr.setlist,
                            "The device app will restart afterwards (about 15 s).")
        if not new or new.upper() == lr.setlist:
            return
        sid = lr.setlist_ids[lr.setlist]

        def rename(br):
            n = L.rename_setlist(br, sid, new)
            lr.setlist = n   # restart_app betritt die Setlist unter dem neuen Namen
            return n
        self.db_job(rename, "Renaming setlist to “%s” …" % new.upper(), restart=True)

    def live_delete_setlist(self):
        lr = self.lrig
        if lr.setlist == L.ALL_RIGS or lr.setlist not in (lr.setlist_ids or {}):
            return
        if not messagebox.askyesno(APP, "Delete setlist “%s” from the device?\nThe rigs are kept.\n\n"
                                        "The device app will restart afterwards (about 15 s)." % lr.setlist):
            return
        sid = lr.setlist_ids[lr.setlist]

        def delete(br):
            L.delete_setlist(br, sid)
            lr.setlist = L.ALL_RIGS
        self.db_job(delete, "Deleting setlist “%s” …" % lr.setlist, restart=True)

    def current_index(self):
        """Position des geoeffneten Rigs in der sichtbaren Liste (oder None)."""
        if self.session:
            for i, (_, _, _, rid) in enumerate(self.live_shown):
                if rid == self.lrig.rig_id:
                    return i
        elif self.rig:
            name = os.path.basename(self.rig.path)
            if name in self.shown:
                return self.shown.index(name)
        return None

    def select_current(self):
        self.riglist.select(self.current_index())

    def step_rig(self, d):
        """Vorheriges/naechstes Rig der Liste laden."""
        if not self.view:
            return
        i = self.current_index()
        n = len(self.live_shown if self.session else self.shown)
        if i is None or not (0 <= i + d < n):
            return
        self.on_pick_rig(i + d)

    def load_rig(self, path, module=None):
        try:
            self.rig = Rig(path)
        except (RigError, OSError) as e:
            messagebox.showerror(APP, str(e))
            return
        self.module = module if module and self.rig.has_module(module) else None
        if not self.module:
            mods = self.rig.modules()
            self.module = mods[0] if mods else None
        self.refresh()
        self.status.set("Opened: " + path)

    def open_setlist_menu(self):
        m = U.menu(self)
        if self.session:
            lr = self.lrig
            for name in lr.setlist_choices():
                mark = "●  " if name == lr.setlist else "    "
                m.add_command(label=mark + name, command=lambda n=name: self.on_pick_setlist(n))
            if self.can_write():
                own = lr.setlist != L.ALL_RIGS and lr.setlist in (lr.setlist_ids or {})
                m.add_separator()
                m.add_command(label="Setlist manager …", command=self.open_setlists)
                m.add_command(label="New setlist …", command=self.live_new_setlist)
                m.add_command(label="Rename “%s” …" % lr.setlist if own else "Rename setlist …",
                              command=self.live_rename_setlist, state="normal" if own else "disabled")
                m.add_command(label="Delete “%s” …" % lr.setlist if own else "Delete setlist …",
                              command=self.live_delete_setlist, state="normal" if own else "disabled")
        else:
            m.add_command(label="Open folder …", command=self.ask_folder)
        m.tk_popup(self.btn_setlist.winfo_rootx(), self.btn_setlist.winfo_rooty() + self.btn_setlist.winfo_height())

    def open_menu(self):
        live = self.session is not None
        db = live
        m = U.menu(self)
        m.add_command(label="Reread rig", command=self.live_reload, state="normal" if live else "disabled")
        m.add_command(label="Reread rig list", command=self.live_scan_rigs, state="normal" if live else "disabled")
        m.add_separator()
        m.add_command(label="Back up rig as file …", command=self.live_export_rig, state="normal" if db else "disabled")
        m.add_command(label="Back up everything …", command=self.live_backup_all, state="normal" if db else "disabled")
        w = self.can_write()
        m.add_separator()
        m.add_command(label="Copy rig files to the device …", command=self.live_import_rigs,
                      state="normal" if w else "disabled")
        m.add_command(label="Restore everything …", command=self.live_restore_all, state="normal" if w else "disabled")
        m.add_command(label="Manage impulse responses …", command=self.open_ir_dialog,
                      state="normal" if (live and getattr(self.session.bridge, "v3", False)) else "disabled")
        m.add_command(label="Tuner …", command=self.open_tuner, state="normal" if live else "disabled")
        m.add_command(label="Footswitches & pedals …", command=self.open_hardware,
                      state="normal" if live else "disabled")
        m.add_command(label="Setlist manager …", command=self.open_setlists, state="normal" if w else "disabled")
        nam = self.lrig.nam if live and self.lrig else None
        if nam and nam.get("installed"):
            m.add_separator()
            m.add_command(label="NAM models …", command=self.open_nam_dialog, state="normal" if w else "disabled")
            m.add_command(label="Turn NAM off …" if nam.get("on") else "Turn NAM on …",
                          command=lambda: self.nam_switch(not nam.get("on")), state="normal" if w else "disabled")
        m.add_separator()
        m.add_command(label="Save as …", command=self.save_as,
                      state="normal" if (not live and self.rig) else "disabled")
        m.add_command(label="Open folder …", command=self.ask_folder)
        m.add_command(label="Disconnect live" if live else "Connect live", command=self.toggle_live)
        m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    # ---------------- Anzeige ----------------
    def refresh(self):
        r = self.view
        if r is None:
            return
        live = self.session is not None
        self.refresh_head()
        if r.routing in U.ROUTING_ORDER:
            self.seg_routing.set(U.ROUTING_ORDER.index(r.routing))
        self.show_routing_name()
        if self.scene:
            self.lbl_chain.configure(text="Scene: click = choose state and preset · double-click = – / On / Off")
        elif self.assign:
            self.lbl_chain.configure(text="Toggle: click a block to assign it to footswitch %d" % (self.assign - 4))
        else:
            self.lbl_chain.configure(text="Click = edit · double-click = on/off · drag = move (onto the trash can = remove)%s"
                                          % ("  · empty slot = insert block" if live else ""))
        self.draw_chain()
        self.draw_params()
        self.select_current()

    # ---- Rig-Name direkt in der Kopfzeile bearbeiten (Doppelklick) ----
    def begin_rename(self):
        """Doppelklick auf den Rig-Namen: an seiner Stelle ein Eingabefeld; Enter uebernimmt,
        Escape oder Klick daneben bricht ab. Live schreibt es in die Datenbank."""
        v = self.view
        if v is None or self.scene or self.assign or self.name_edit is not None:
            return
        if self._job:
            self.status.set("Please wait, the device is still busy.")
            return
        var = tk.StringVar(value=v.name)
        e = tk.Entry(self.lbl_name.master, textvariable=var, bg=U.CARD, fg=TEXT, insertbackground=TEXT,
                     relief="flat", bd=0, highlightthickness=1, highlightbackground=ACCENT, highlightcolor=ACCENT,
                     selectbackground=ACCENT, selectforeground=U.ACCENT_TXT, font=FONT_HEAD, justify="center",
                     width=max(12, len(v.name) + 4))
        e.pack(side="left", before=self.lbl_name, padx=px(8), ipady=px(2))
        self.lbl_name.pack_forget()
        self.name_edit = e
        e.focus_set()
        e.select_range(0, "end")
        e.icursor("end")
        e.bind("<Return>", lambda ev: self.end_rename(var.get()))
        e.bind("<KP_Enter>", lambda ev: self.end_rename(var.get()))
        e.bind("<Escape>", lambda ev: self.end_rename(None))
        e.bind("<FocusOut>", lambda ev: self.end_rename(None))
        self.status.set("Enter = rename · Esc = cancel")

    def end_rename(self, text):
        e, self.name_edit = self.name_edit, None
        if e is None:
            return
        self.lbl_name.pack(side="left", before=e)
        e.destroy()
        v = self.view
        if text is None or v is None:
            self.status.set("")
            return
        new = " ".join(text.split())
        if not new or new == v.name:
            self.status.set("")
            return
        if self.session:
            try:
                new = L.check_rig_name(new)
            except L.LiveError as err:
                messagebox.showwarning(APP, str(err))
                return
            if new == v.name:
                return
            rid = self.lrig.rig_id
            if not rid:
                self.status.set("The loaded rig was not found in the device database.")
                return
            self.db_job(lambda br: L.rename_rig(br, rid, new), "Renaming to “%s” …" % new, reload=True,
                        then=lambda _: self.status.set("Renamed to “%s”." % new))
            return
        new = new.upper()   # wie am Geraet (zeigt nur Grossbuchstaben)
        try:
            self.rig.rename(new)
        except RigError as err:
            messagebox.showwarning(APP, str(err))
            return
        self.refresh()
        self.status.set("Renamed to “%s” – not saved yet (the file keeps its name)." % new)

    def refresh_head(self):
        """Nur Name, Titel und Speichern-Knoepfe (geaendert/ungeaendert)."""
        r = self.view
        dirty = r.dirty
        self.lbl_name.configure(text=r.name)
        self.lbl_dirty.configure(text="●" if dirty else "")
        self.title("%s – %s%s" % (APP, r.name, " *" if dirty else ""))
        for b in (self.btn_save, self.btn_revert):
            b.configure(state="normal" if dirty else "disabled")
        self.btn_assign.configure(state="normal" if self.session else "disabled")

    def draw_chain(self):
        v = self.view
        if v is None:
            if self.session:
                self.chain.set_chain([], None, True, hint="Reading the rig from the device …")
            else:   # nicht verbunden: Knopf 'Connect to Device' in der Mitte
                self.chain.set_chain([], None, False, hint="or open .rig files with “Folder” on the left",
                                     connect="busy" if self._connecting else "idle", connect_err=self._connect_err)
            return
        slots = []
        scene = self.scene_slots()   # [(block, modus, preset)] im Scene-Modus, sonst None
        for slot, module in v.chain():
            if module and v.has_module(module):
                d = {"slot": slot, "module": module, "colour": COLOURS.get(v.colour(module) or ""),
                     "on": v.is_on(module), "sub": self.model_of(module), "double": self.is_double(module),
                     "sub2": self.model_of(module, "B"), "can_double": self.can_double(module)}
                if scene:
                    _, mode, preset = scene[slot - 1]
                    d["scene"] = {"mode": mode, "preset": preset}
                if self.is_nam(module):
                    d["label"], d["icon"] = self.block_title(module), "NAM"   # "NAM", "NAM 2"
                slots.append(d)
            else:
                slots.append({"slot": slot, "module": None, "colour": None, "on": None, "sub": None, "double": False,
                              "sub2": None})
        assign = None
        if self.assign and self.lrig and self.lrig.hw:
            others = {}   # Bloecke, die ein anderer Toggle-Schalter bedient
            for n, d in self.lrig.hw["fs"].items():
                m = d["module"].get("string", "") if d["mode"].get("string") != "Scene" else ""
                if n != self.assign and m and self.slot_of(m) is not None:
                    others[m] = "FS %d" % (n - 4)
            assign = ("FS %d" % (self.assign - 4), self.assign_module(), others)
        self.chain.set_chain(slots, (self.module, self.half), self.session is not None, v.routing,
                             scene=self.scene is not None, assign=assign)
        self.rail_rigs.set_active(self.module is not None and not self.scene and not self.assign)

    # ---------------- Scene-Modus ----------------
    def scene_slots(self):
        """Die 11 Plaetze [(block, modus, preset)] der bearbeiteten Scene oder None."""
        if not self.scene or not self.lrig or not self.lrig.hw:
            return None
        n, state = self.scene
        d = self.lrig.hw["fs"].get(n)
        if not d or d["mode"].get("string") != "Scene" or state > int(d["states"].get("unnormalized", 1) or 1):
            return None
        return d["scenes"][state - 1]

    def scene_name(self, n, state):
        """'Fußschalter 1 · Scene B' (zwei Zustaende) bzw. 'Fußschalter 1 · Scene'."""
        d = self.lrig.hw["fs"].get(n) if self.lrig and self.lrig.hw else None
        return "Footswitch %d · %s" % (n - 4, state_name(d, state) if d else "Scene %s" % "AB"[state - 1])

    def exit_fs_mode(self):
        """Scene- bzw. Zuweisungs-Modus verlassen (runder x-Knopf im Signalpfad)."""
        if self.scene:
            self.set_scene(None)
        elif self.assign:
            self.set_assign(None)

    def slot_of(self, m):
        """Platznummer (1-11) eines Kettenblocks oder None."""
        v = self.view
        if v is None or not m:
            return None
        return next((slot for slot, module in v.chain() if module == m), None)

    def _fs_badge(self, text):
        """Kopfzeile im Scene-/Zuweisungs-Modus: Marke statt Rig-Pfeilen und Punkt; None = normal."""
        self.scene_badge.pack_forget()
        for b in (self.btn_prev, self.btn_next, self.lbl_dirty):   # Rig-Wechsel erst danach
            b.pack_forget()
        if text:
            self.scene_badge.set_text(text)
            self.scene_badge.pack(side="left", padx=(0, px(6)), before=self.lbl_name)
            self.lbl_name.configure(font=FONT_BOLD, padx=px(8))
        else:
            self.lbl_name.configure(font=FONT_HEAD, padx=px(16))
            self.btn_prev.pack(side="left", before=self.lbl_name)
            self.lbl_dirty.pack(side="left", after=self.lbl_name)
            self.btn_next.pack(side="left", after=self.lbl_dirty)

    def set_scene(self, sel):
        """Scene (fussschalter, zustand) im Signalpfad bearbeiten; None = normaler Signalpfad."""
        if sel is not None and (not self.session or not self.hw_panel):
            sel = None
        self.scene = sel
        if sel:
            self.assign = None
            n, state = sel
            self._fs_badge("SCENE MODE  ·  " + self.scene_name(n, state).replace("Footswitch", "FS"))
            if self.slot_of(self.module) is None:
                self.module, self.half = next((m for _, m in self.view.chain() if m), None), None
            self.status.set("Scene mode: %s – choose state and preset per block in the signal chain."
                            % self.scene_name(n, state))
        else:
            self._fs_badge(None)
            if self.view:
                self.status.set("Live: %s" % self.view.name)
        if self.hw_panel:
            self.hw_panel.refresh()
        if self.view:
            self.refresh()

    def set_assign(self, n):
        """Toggle-Fussschalter n: der naechste Klick im Signalpfad weist ihm den Block zu; None = aus."""
        if n is not None and (not self.session or not self.hw_panel):
            n = None
        self.assign = n
        if n:
            self.scene = None
            self._fs_badge("TOGGLE  ·  FS %d · choose block" % (n - 4))
            self.status.set("Footswitch %d (Toggle): click a block in the signal chain to assign it." % (n - 4))
        else:
            self._fs_badge(None)
            if self.view:
                self.status.set("Live: %s" % self.view.name)
        if self.hw_panel:
            self.hw_panel.refresh()
        if self.view:
            self.refresh()

    def assign_module(self):
        """Block, den der Toggle-Fussschalter self.assign schaltet (None = keiner / kein Kettenblock)."""
        d = self.lrig.hw["fs"].get(self.assign) if self.lrig and self.lrig.hw else None
        m = d["module"].get("string", "") if d else ""
        return m if m and self.slot_of(m) is not None else None

    def assign_block(self, module):
        """Block (oder einen anderen Listeneintrag wie 'Unassigned') dem Toggle-Fussschalter zuweisen."""
        n = self.assign
        d = self.lrig.hw["fs"][n]
        if module not in d["modules"]:
            self.status.set("%s is not in the choice list of footswitch %d." % (module, n - 4))
            return
        self.hw_set("%s/ModuleList%d" % (L.FSW, n), "index", d["modules"].index(module))

    def draw_assign_params(self):
        """Parameterfeld im Zuweisungs-Modus: Block und Funktion des Toggle-Fussschalters."""
        g, n = self.params, self.assign
        d = self.lrig.hw["fs"][n] if self.lrig.hw else None
        if not d:
            tk.Label(g, text="Reading the assignment from the device …", bg=PANEL, fg=MUTED, font=FONT).grid(
                row=0, column=0, columnspan=2, sticky="w")
            return
        fsw = L.FSW
        self.label(g, "Block", 0)
        U.Dropdown(g, [self.block_title(x) for x in d["modules"]], self.block_title(d["module"].get("string", "")), width=22,
                   on_pick=lambda i: self.hw_set("%s/ModuleList%d" % (fsw, n), "index", i),
                   title="Block for footswitch %d" % (n - 4)).grid(row=0, column=1, sticky="w")
        self.label(g, "Function", 1)
        U.Dropdown(g, d["operations"], d["operation"].get("string", ""), width=16,
                   on_pick=lambda i: self.hw_set("%s/OperationList%d" % (fsw, n), "index", i),
                   title="Function").grid(row=1, column=1, sticky="w")
        tk.Label(g, text="Clicking a block in the signal chain assigns it to the footswitch; the function "
                         "(usually “On” = on/off) depends on the block. “Unassigned” removes the assignment. "
                         "Grey bars mark blocks that another footswitch already controls.",
                 bg=PANEL, fg=DIM, font=FONT_SMALL, wraplength=px(380), justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(px(14), 0))

    def scene_menu(self, menu, module, slot):
        """Kontextmenue eines Blocks im Scene-Modus."""
        n, state = self.scene
        scene = self.scene_slots()
        if not scene:
            return
        _, mode, preset = scene[slot - 1]
        for i, label in enumerate(("unchanged", "On", "Off")):
            menu.add_command(label=("●  " if i == mode else "○  ") + label,
                             command=lambda i=i: self.hw_set_scene(n, state, slot - 1, i))
        menu.add_separator()
        menu.add_command(label="Choose preset …", command=lambda: self.pick_scene_preset(module))
        if preset:
            menu.add_command(label="Remove preset “%s”" % preset,
                             command=lambda: self.hw_set_scene_preset(n, state, slot - 1, ""))

    def pick_scene_preset(self, module):
        self.pick_module(module)
        if self.scene_dd:
            self.scene_dd.open()

    def draw_scene_params(self):
        """Parameterfeld im Scene-Modus: Zustand (–/An/Aus) und Preset des gewaehlten Blocks."""
        m, g = self.module, self.params
        n, state = self.scene
        self.scene_dd = None
        slot = self.slot_of(m)
        scene = self.scene_slots()
        if slot is None or scene is None:
            tk.Label(g, text="Click a block in the signal chain to choose its state and preset in "
                             "this scene." if scene else "Reading the scene from the device …",
                     bg=PANEL, fg=MUTED, font=FONT, wraplength=px(380), justify="left").grid(
                row=0, column=0, columnspan=2, sticky="w")
            return
        _, mode, preset = scene[slot - 1]
        self.label(g, "State", 0)
        U.Segmented(g, SCENE_MODES, mode if 0 <= mode < 3 else 0, padx=14,
                    on_pick=lambda i: self.hw_set_scene(n, state, slot - 1, i)).grid(row=0, column=1, sticky="w")
        self.label(g, "Preset", 1)
        cell = tk.Frame(g, bg=PANEL)
        cell.grid(row=1, column=1, sticky="w")
        dd = U.Dropdown(cell, [], preset or NO_PRESET, width=24, font=FONT_SMALL,
                        on_open=lambda: self.open_scene_presets(m, n, state, slot - 1),
                        title="Preset for %s" % m)
        dd.pack(side="left")
        self.scene_dd = dd
        if self.can_write():
            def current():   # Preset der Scene, sonst das gerade in den Block geladene
                sc = self.scene_slots()
                return (sc[slot - 1][2] if sc else "") or self.preset_name_of(m, half)
            half = self.half or "A"
            self.preset_buttons(cell, m, half, current,
                                then=lambda name: self.hw_set_scene_preset(n, state, slot - 1, name))
        text = ("When %s is pressed:\n“On”/“Off” switches the block, “–” leaves it as it is. A chosen "
                "preset is loaded into the block – without a preset its settings stay unchanged."
                % self.scene_name(n, state))
        if self.can_write():
            text += ("\nThe controls below change the block directly (also in the rig). + saves them as a new preset "
                     "for this scene, the disk overwrites the scene's preset.")
        tk.Label(g, text=text, bg=PANEL, fg=DIM, font=FONT_SMALL, wraplength=px(380), justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(px(10), px(6)))
        tk.Frame(g, bg=LINE, height=1).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, px(6)))
        self.draw_live_params(m, start=4)

    def open_scene_presets(self, m, n, state, slot):
        dd = self.scene_dd

        def done(res, err):
            if err:
                messagebox.showwarning(APP, "Could not read presets:\n%s" % err)
                return
            if not res:
                self.status.set("No presets for %s." % m)
                return
            if dd is None or not dd.winfo_exists():
                return
            def pick(i):
                self.hw_set_scene_preset(n, state, slot, "" if i == 0 else res[i - 1]["name"])
                if i:   # auch in den Block laden, damit die Regler das Preset zeigen und man es anpassen kann
                    self.live_load_preset(m, res[i - 1], self.half or "A")
            dd.on_pick = pick
            dd.show([NO_PRESET] + [r["name"] for r in res])
        self.run_job(lambda br: L.db_presets_of(br, m), done, "Reading presets …")

    def param_info(self, module, param):
        """Gelesener Wert (live: Antwort-Dict, offline: Knoten) oder None."""
        if not module:
            return None
        if self.session:
            return self.lrig.info(module, param)
        try:
            return self.rig.node(module, param)
        except RigError:
            return None

    def model_of(self, module, half="A"):
        """Amp-/Cab-/IR-Modell eines Blocks (Untertitel der Karte), Haelfte A oder B, sonst None."""
        param = U.MODEL_PARAM.get(U.base_name(module or ""), (None,))[0]
        if not param:
            return None
        info = self.param_info(module, param + ("2" if half == "B" else ""))
        name = info.get("string") if info else None
        if name and U.base_name(module) in L.IR_MODULES:
            return L.ir_label(name, folder=False) or None   # '[directory](Ordner)[name](Name)' -> Name
        return name or None

    def is_ir(self, module):
        return U.base_name(module or "") in L.IR_MODULES

    def ir_param(self, module, p):
        return self.is_ir(module) and p in ("IR", "IR2")

    def can_double(self, module):
        return self.param_info(module, "Doubling") is not None

    def is_double(self, module):
        info = self.param_info(module, "Doubling")
        return bool(info and info.get("state"))

    def all_params(self, m):
        """Alle Parameternamen eines Moduls (beide Haelften)."""
        if m == MIX:
            return PARA_PARAMS
        return self.lrig.params(m) if self.session else self.rig.params(m)

    def params_for(self, m):
        """[(Beschriftung, Parameter)] fuer die Anzeige: ohne Doubling-Knoepfe, ohne 'On'; bei doppelten
        Bloecken je Haelfte (B = Parameter mit Endung 2, gemeinsame Parameter in beiden)."""
        if self.is_nam(m):   # NAM-Mod: Drive = Modell, Tone/Level = Pegel, Hi-Lo ohne Wirkung
            return NAM_ROWS
        allp = self.all_params(m)
        twins = {q for q in allp if q.endswith("2") and q[:-1] in allp}
        out = []
        for q in allp:
            if q == "On" or q in HEAD_PARAMS:
                continue
            if q in twins:
                if self.half == "B" and self.is_double(m):
                    out.append((q[:-1], q))
                continue
            if q + "2" in allp and self.half == "B" and self.is_double(m):
                continue          # A-Wert, in Haelfte B durch den Zwilling ersetzt
            out.append((q, q))
        page = self.model_page(m)
        if page is not None:
            own = {p for rows in MODEL_PAGES[U.base_name(m)].values() for _, p in rows}
            own |= {p + "2" for p in own}
            out = [(label, q) for label, q in out if q not in own] + page
        return out

    def model_page(self, m):
        """Regler des eingestellten Amp-Modells in Reihenfolge und Beschriftung des Geraets
        (jedes Modell hat nur einen Teil der Amp-Parameter), None wenn das Modell unbekannt ist."""
        pages = MODEL_PAGES.get(U.base_name(m or ""))
        if not pages:
            return None
        half_b = self.half == "B" and self.is_double(m)
        rows = pages.get(self.model_of(m, "B" if half_b else "A") or "")
        if rows is None:
            return None
        allp = set(self.all_params(m))
        out = []
        for label, p in rows:
            q = p + "2" if half_b and p + "2" in allp else p   # Tremolo/TremSync gelten fuer beide Haelften
            if q in allp:
                out.append((label, q))
        return out

    def rows_changed(self):
        """Passen die gezeigten Parameterzeilen nicht mehr zum Block (z. B. anderes Amp-Modell)?"""
        return not self.assign and self._rows != self._row_key(self.module)

    def _row_key(self, m):
        if not m or not (self.session or self.rig):
            return None
        try:
            return m, self.params_for(m)
        except RigError:
            return m, None

    def set_double(self, m, on):
        """Doppelung (zwei Amps/Cabs/IRs in einem Block) ein-/ausschalten."""
        if self.session:
            self.write(self.lrig.path(m, "Doubling"), "state", int(on), self.live_reply_chain)
            return
        self.apply(m, "Doubling", on)
        if not on:
            self.half = None
        self.refresh()

    def copy_a_to_b(self, m):
        """Aktion DoubleStates: Einstellungen von A nach B kopieren (verifiziert am Geraet)."""
        if not self.session:
            self.status.set("Copy A → B is only available in live mode.")
            return
        path = self.lrig.path(m, "DoubleStates")

        def done(res, err):
            if err:
                self.status.set("Error: %s" % err)
                return
            self.status.set("%s: copied A to B" % m)
            self.live_mark_dirty()
            self.live_reload()
        self.run_job(lambda br: (br.set(path, "state", 0), time.sleep(0.1), br.set(path, "state", 1))[-1], done,
                     "Copying A to B …")

    def show_routing_name(self, hovered=None):
        """Name des Signalwegs neben der Auswahl: der unter der Maus, sonst der aktuelle."""
        v = self.view
        name = hovered or (v.routing if v is not None else None)
        self.lbl_route_name.configure(text=U.ROUTINGS[name][0] if name in U.ROUTINGS else "",
                                      fg=ACCENT if hovered and v is not None and hovered != v.routing else TEXT)

    def set_routing(self, i):
        """Signalweg umstellen (S / SPS-1 / PS-1)."""
        v = self.view
        if v is None:
            return
        name = U.ROUTING_ORDER[i]
        if name == v.routing:
            return
        if self.session:
            def reply(path, info):
                if not self.session:
                    return
                if info.get("ok"):
                    self.status.set("Routing: %s" % U.ROUTINGS[name][0])
                    self.live_mark_dirty()
                    self.live_reload()
                else:
                    self.status.set("Error: %s" % info.get("err"))
            self.write(L.ENGINE + "/Chain/Routing", "index", i, reply)
            return
        self.rig.set_routing(name)
        self.refresh()

    def show_rig_view(self):
        if self.setlist_mgr:
            self.close_setlists()
            return
        if not self.view:
            return
        if self.module is None:
            mods = self.view.modules()
            self.pick_module(mods[0] if mods else "Rig")

    # ---- Setlist-Manager (setlists.py) ----
    def open_setlists(self):
        """Setlist-Manager an Stelle von Rig-Liste, Signalkette und Parameterfeld zeigen."""
        if self.setlist_mgr:
            return
        if not self.can_write():
            messagebox.showinfo(APP, "The setlist manager needs a live connection to the MX5.")
            return
        if self._job:
            self.status.set("Please wait, the device is still busy.")
            return
        if self.name_edit is not None:
            self.end_rename(None)
        self._panes = [(w, w.pack_info()) for w in (self.lpanel, self.rpanel, self.center)]
        for w, _ in self._panes:
            w.pack_forget()
        self.setlist_mgr = SetlistManager(self, self)
        self.setlist_mgr.pack(side="left", fill="both", expand=True, padx=px(8), pady=px(8))
        self.rail_sets.set_active(True)
        self.rail_rigs.set_active(False)
        self.status.set("Reading setlists from the device …")
        self.setlist_mgr.load()

    def close_setlists(self, device=True):
        """Setlist-Manager schliessen. Die Aenderungen stehen schon in der Datenbank; das Geraet
        liest aber Listen nur beim Betreten neu und die Set-Auswahl nur beim App-Start. Darum
        einmal: App-Neustart (Setlist angelegt/umbenannt/geloescht), sonst die aktive Liste
        auffrischen, wenn sie betroffen ist, und das geladene Rig neu laden, wenn seine Zeile
        geaendert wurde (bei ungespeicherten Aenderungen nur auf Wunsch)."""
        mgr, self.setlist_mgr = self.setlist_mgr, None
        if not mgr:
            return
        fx = mgr.effects()
        mgr.destroy()
        for w, info in self._panes:
            w.pack(**info)
        self.rail_sets.set_active(False)
        self.draw_chain()
        if not device or not self.session:
            if fx["restart"]:
                self.status.set("The MX5 shows the changed setlists after its app restarts.")
            return
        lr = self.lrig
        active = (lr.setlist_ids or {}).get(lr.setlist) if lr.setlist != L.ALL_RIGS else None
        if active in fx["deleted"]:
            lr.setlist = L.ALL_RIGS
        elif active in fx["renamed"]:
            lr.setlist = fx["renamed"][active]
        loaded = lr.rig_id in fx["rows"]
        if fx["restart"]:
            if not self.db_job(lambda br: None, "Restarting the device app so it shows the changed setlists …",
                               restart=True):
                self.status.set("The MX5 shows the changed setlists after its app restarts.")
                if not self._job:
                    self.live_scan_rigs()
            return
        shown = {r["id"] for r in lr.rows}
        affected = active in fx["lists"] or bool(fx["rows"] & shown) or (lr.setlist == L.ALL_RIGS and fx["rows"])
        if not (affected or loaded):
            self.status.set("Setlists saved." if fx["lists"] or fx["rows"] else "Setlist manager closed.")
            return
        reload = loaded
        if loaded and lr.dirty:
            reload = U.ask(self, "“%s” was changed in the setlist manager.\nReload it now?" % lr.name,
                           [("Keep my edits", False, "ghost"), ("Reload (edits are lost)", True, "primary")],
                           detail="The MX5 shows the new name, colour or program number of the loaded rig "
                                  "only after it has been reloaded.", cancel=False)
        self.db_job(lambda br: None, "Updating the rig list on the device …", reload=bool(reload), confirm=False)

    def show_fsbar(self, show):
        """Fussschalter-Leiste (zugeklapptes Hardware-Feld) unter dem Signalpfad ein-/ausblenden;
        die Einstellung 'footswitch_bar' blendet sie dauerhaft aus."""
        show = show and self.prefs["footswitch_bar"]
        if show and not self.fsbar.winfo_ismapped():
            self.fsbar.pack(fill="x", pady=(px(8), 0), before=self.foot)
            self.fsbar.set(self.lrig.fs_display() if self.lrig else None)
        elif not show:
            self.fsbar.pack_forget()

    def press_footswitch(self, k):
        """Klick auf einen Schalter der Leiste: Fussschalter k (1-3) am Geraet druecken und die
        Anzeige (Schalter, Kette, Parameter) nachziehen."""
        if not self.session or self._job:
            return

        def done(res, err):
            if err:
                self.status.set("Footswitch %d: %s" % (k, err))
                return
            for p, info in res.items():
                self.lrig.store(p, info)
            self.fsbar.set(self.lrig.fs_display())
            self.status.set("Footswitch %d pressed" % k)
            self.live_sync()
        self.run_job(lambda br: L.press_footswitch(br, k), done, "Pressing footswitch %d …" % k)

    def open_hardware(self):
        """Feld 'Hardware' unter dem Signalpfad ein- bzw. ausblenden (nur live)."""
        if not self.session:
            self.status.set("Footswitches and pedals are only available in live mode.")
            return
        if self.hw_panel:
            self.close_hardware()
            return
        if self.lrig.hw is None:
            self.live_load_hw()

        def done(res, err):
            if err:
                messagebox.showwarning(APP, "Could not read tempo: %s" % err)
                res = {}
            if not self.session or self.hw_panel:
                return
            self.show_fsbar(False)
            self.hw_panel = HardwarePanel(self, self.center, res)
            self.hw_panel.pack(fill="x", pady=(px(8), 0), before=self.foot)
            self.status.set("Hardware: footswitches, pedals and tempo of the rig.")
        self.run_job(read_tempo, done, "Reading tempo …")

    def close_hardware(self):
        """Hardware-Feld schliessen; ein Scene-Modus endet damit."""
        panel, self.hw_panel = self.hw_panel, None
        if self.scene:
            self.set_scene(None)
        if self.assign:
            self.set_assign(None)
        if panel:
            panel.destroy()
        if self.session:
            self.show_fsbar(True)

    def open_tuner(self):
        """Fenster 'Tuner' (nur live): oeffnet die Tuner-Seite am Geraet; das Fenster fragt Note
        und Cents dann ~30x pro Sekunde ab (tuner.TunerDialog)."""
        if not self.session:
            self.status.set("The tuner is only available in live mode.")
            return
        if self.tuner_dialog and self.tuner_dialog.winfo_exists():
            self.tuner_dialog.raise_()
            return

        def done(res, err):
            if err:
                messagebox.showwarning(APP, "Tuner not opened: %s" % err)
                return
            self.tuner_dialog = TunerDialog(self, res)
            self.rail_tuner.set_active(True)
            self.status.set("Tuner running – the editor polls the device ~30× per second.")
        self.run_job(L.tuner_open, done, "Opening the tuner on the device …")

    def tuner_dialog_done(self, dlg, device_exited):
        """Beim Schliessen des Tuner-Fensters: Tuner am Geraet verlassen (ausser das Geraet hat ihn
        schon selbst verlassen, z. B. per Fussschalter)."""
        if self.tuner_dialog is dlg:
            self.tuner_dialog = None
        self.rail_tuner.set_active(False)
        if not self.session:
            return
        if device_exited:
            self.status.set("Tuner closed on the device.")
            return

        def done(res):
            if isinstance(res, dict) and res.get("ok") is False:
                self.status.set("Closing the tuner: %s" % res.get("err"))
            else:
                self.status.set("Tuner closed.")
        self.session.run(L.tuner_close, done)

    def tuner_open(self):
        return bool(self.tuner_dialog and self.tuner_dialog.winfo_exists())

    def pick_module(self, m, half=None):
        if self.assign:
            if self.slot_of(m) is not None:
                self.assign_block(m)
            return
        if self.scene and self.slot_of(m) is None:
            return   # Scene-Modus: nur Kettenbloecke
        self.module = m
        self.half = half if (half and self.is_double(m)) else ("A" if m and self.is_double(m) else None)
        self.draw_chain()
        if self.session and m not in self.lrig.loaded_modules:
            self.live_load_module(m)
        self.draw_params()

    def on_empty_slot(self, slot):
        if self.session:
            self.live_add_block(slot)
        else:
            self.status.set("Inserting blocks is only possible in live mode.")

    def set_on(self, m, on):
        if self.session:
            self.write(self.lrig.path(m, "On"), "state", int(on), self.live_reply_chain)
            return
        self.apply(m, "On", on)
        self.refresh()

    def toggle(self, m):
        if self.assign:
            return
        if self.scene:   # Doppelklick im Scene-Modus: – -> An -> Aus -> –
            scene, slot = self.scene_slots(), self.slot_of(m)
            if scene and slot:
                n, state = self.scene
                self.hw_set_scene(n, state, slot - 1, (scene[slot - 1][1] + 1) % 3)
            return
        if self.view.is_on(m) is not None:
            self.set_on(m, not self.view.is_on(m))

    def on_head_toggle(self, on):
        if self.module and self.view:
            self.set_on(self.module, on)

    def move_block(self, src, dst):
        """Block von Platz src nach dst wie am MX5 (L.plan_block_move): freies Ziel = hinstellen,
        sonst ruecken die Bloecke bis zur naechsten Luecke auf, ohne Luecke wird getauscht."""
        v = self.view
        cur = [m for _, m in v.chain()]
        desired = L.plan_block_move(cur, src, dst)
        m = cur[src - 1]
        if desired == cur:
            return
        swap = cur[dst - 1] and desired[src - 1] == cur[dst - 1]
        how = "swapped with %s" % cur[dst - 1] if swap else "moved to slot %d" % dst
        if not self.session:
            self.rig.set_chain(desired)
            self.refresh()
            self.status.set("%s %s" % (m, how))
            return
        if self._job:
            self.status.set("Please wait, the device is still busy.")
            return
        # Sofort anzeigen; das Geraet zieht in einem Rutsch nach (L.move_chain, ~0,3 s). Die
        # Parameter der Bloecke haengen am Blocknamen, nicht am Platz - nichts neu zu lesen.
        lr = self.lrig
        for i, name in enumerate(desired):
            lr.apply_overview(lr.slot_path(i + 1), {"ok": True, "string": name or L.EMPTY})
        self.draw_chain()
        types = lr.block_types

        def job(br):
            t = types or br.entries(L.LiveRig.slot_path(1))
            return dict(L.move_chain(br, desired, t), types=t)

        def done(res, err):
            if not self.session or lr is not self.lrig:
                return
            if err:
                messagebox.showwarning(APP, "Moving failed:\n%s" % err)
                self.live_reload()
                return
            lr.block_types = res["types"]
            lr.dirty = True
            self.refresh_head()
            lr.hw = None   # Scene-Eintraege und Auswahllisten haengen an den Plaetzen
            if self.hw_panel or self.scene or self.assign:
                self.live_load_hw()
            self.status.set("%s %s" % (m, how))
        self.run_job(job, done)

    def block_menu(self, event, module, slot, half=None):
        menu = U.menu(self)
        if self.scene:
            if module is None:
                return
            self.scene_menu(menu, module, slot)
            menu.tk_popup(event.x_root, event.y_root)
            return
        if self.assign:
            if module is None:
                return
            n = self.assign
            menu.add_command(label="Assign footswitch %d" % (n - 4), command=lambda: self.assign_block(module))
            if self.assign_module() == module:
                menu.add_command(label="Remove assignment", command=lambda: self.assign_block("Unassigned"))
            menu.tk_popup(event.x_root, event.y_root)
            return
        if module is None:
            if not self.session:
                return
            menu.add_command(label="Insert block …", command=lambda: self.live_add_block(slot))
        else:
            if self.view.is_on(module) is not None:
                menu.add_command(label="Off" if self.view.is_on(module) else "On", command=lambda: self.toggle(module))
            if self.can_double(module):
                dbl = self.is_double(module)
                menu.add_command(label="Doubling off" if dbl else "Double (A + B)",
                                 command=lambda: self.set_double(module, not dbl))
                if dbl and self.session:
                    menu.add_command(label="Copy A → B", command=lambda: self.copy_a_to_b(module))
            if self.session:
                if self.is_double(module):
                    menu.add_command(label="Change model A …", command=lambda: self.live_add_block(slot, module, "A"))
                    menu.add_command(label="Change model B …", command=lambda: self.live_add_block(slot, module, "B"))
                else:
                    menu.add_command(label="Change block type …", command=lambda: self.live_add_block(slot, module))
                if self.can_write():
                    h = half or self.half or "A"
                    label = "Save preset …" if not self.is_double(module) else "Save preset of %s …" % h
                    menu.add_command(label=label, command=lambda: self.live_save_preset(module, h))
                    cur = self.preset_name_of(module, h)
                    if cur and not cur.startswith("+"):
                        menu.add_command(label="Delete preset “%s” …" % cur, command=lambda: self.live_delete_preset(module, h))
                menu.add_separator()
                menu.add_command(label="Remove block", command=lambda: self.live_remove_block(slot, module))
        menu.tk_popup(event.x_root, event.y_root)

    def preset_name_of(self, module, half="A"):
        info = self.lrig.values.get(L.preset_name_path(module, half)) if self.session else None
        return (info or {}).get("string", "") or ""

    def live_save_preset(self, module, half="A"):
        """Block-Menue 'Preset speichern …': Namen erfragen (vorbelegt mit dem geladenen Preset)."""
        cur = self.preset_name_of(module, half)
        self.live_new_preset(module, half, initial="" if cur.startswith("+") else cur)

    def _preset_ready(self):
        if not self.can_write() or not self.lrig.rig_id:
            return False
        if self._job:
            self.status.set("Please wait, the device is still busy.")
            return False
        return True

    def live_new_preset(self, module, half="A", then=None, initial=""):
        """Aktuelle Werte des Blocks als neues Block-Preset in der Datenbank speichern (Bruecke 0.4);
        gibt es den Namen schon, wird einmal gefragt, ob er ueberschrieben werden soll."""
        if not self._preset_ready():
            return
        name = self.ask_text("New preset", "Name of the preset for %s:" % module, initial,
                             "The block's current values are saved as a preset on the device "
                             "(block menu › Preset). Factory presets (+) cannot be overwritten.")
        if not name or not name.strip():
            return
        self._store_preset(module, half, " ".join(name.split()), False, then)

    def live_overwrite_preset(self, module, half="A", name="", then=None):
        """Diskette: das Preset `name` mit den aktuellen Werten des Blocks ueberschreiben (einmal
        nachfragen). Ohne eigenes Preset (keins oder Werkspreset) wird ein neues angelegt."""
        if not self._preset_ready():
            return
        if not name or name.startswith("+"):
            self.status.set("Factory presets cannot be overwritten – creating a new preset."
                            if name else "No user preset loaded – creating a new preset.")
            self.live_new_preset(module, half, then)
            return
        if not messagebox.askyesno(APP, "Overwrite preset “%s” with the current values of %s?"
                                        % (name, SPECIAL_LABELS.get(module, module))):
            return
        self._store_preset(module, half, name, True, then)

    def _store_preset(self, module, half, name, replace, then=None):
        lr = self.lrig
        rig_id = lr.rig_id

        def save(br, replace=replace):
            return L.save_block_preset(br, rig_id, module, name, half, replace=replace)

        def done(res, err):
            if err and "already exists" in err and not replace:
                if messagebox.askyesno(APP, "%s" % err + chr(10) + "Overwrite?"):
                    self._store_preset(module, half, name, True, then)
                return
            if err:
                messagebox.showwarning(APP, err)
                return
            pid, what = res
            if lr.presets is not None:
                lr.presets.pop(L.preset_type(module), None)

            def after():
                self.status.set("Preset “%s” %s." % (name, "saved" if what == "neu" else "overwritten"))
                if then:
                    then(name)
            if lr is self.lrig:
                self.live_load_module(module, after)   # liest auch den neuen Presetnamen des Blocks
        self.run_job(save, done, "Saving preset “%s” …" % name)

    def live_delete_preset(self, module, half="A"):
        lr = self.lrig
        name = self.preset_name_of(module, half)
        if not self.can_write() or not name or name.startswith("+"):
            return
        if not messagebox.askyesno(APP, "Delete preset “%s” (%s) from the device?" % (name, L.preset_type(module))):
            return

        def delete(br):
            rows = L.db_presets_of(br, module)
            hit = [r for r in rows if r["name"] == name and not r["readonly"]]
            if not hit:
                raise L.LiveError("Preset '%s' not found." % name)
            L.delete_block_preset(br, hit[0]["id"])
            br.set(L.preset_name_path(module, half), "string", "")
            return name

        def done(res, err):
            if err:
                messagebox.showwarning(APP, err)
                return
            if lr.presets is not None:
                lr.presets.pop(L.preset_type(module), None)
            self.live_load_module(module)
            self.status.set("Preset “%s” deleted." % res)
        self.run_job(delete, done, "Deleting preset “%s” …" % name)

    def clear_params(self):
        for w in self.params.winfo_children():
            w.destroy()
        self.live_widgets = {}
        self.canvas.yview_moveto(0)

    def draw_head(self):
        """Kopf des Parameterfelds: Farbe, Name, Modell, An/Aus."""
        m, v = self.module, self.view
        self.colour_box.pack_forget()
        self.model_box.pack_forget()
        self.head_toggle.pack_forget()
        self.param_sub.pack_forget()
        for w in self.head_btns.winfo_children():
            w.destroy()
        self.head_btns.pack_forget()
        if self.assign:
            self.draw_preset_row(None)
            n = self.assign
            self.param_title.configure(text="Footswitch %d" % (n - 4))
            target = self.assign_module()
            self.param_sub.configure(text="Toggle  ·  switches %s" % (target or "nichts"))
            self.param_sub.pack(fill="x", pady=(0, px(8)), before=self.psep)
            if target:
                self.model_box.delete("all")
                self.model_box.create_image(0, 0, anchor="nw", image=U.model_img(self.icon_of(target), self.model_of(target), px(50), px(35)))
                self.model_box.pack(side="left", padx=(0, px(10)), before=self.param_title)
            return
        if not m or v is None:
            self.param_title.configure(text="")
            self.draw_preset_row(None)
            return
        if self.scene:
            self.draw_preset_row(None)   # Preset-Zeile weg, im Scene-Modus steht das Preset unten
            self.param_title.configure(text=self.block_title(m))
            n, state = self.scene
            self.param_sub.configure(text=self.scene_name(n, state))
            self.param_sub.pack(fill="x", pady=(0, px(8)), before=self.psep)
            self.show_colour_box(m)
            self.model_box.delete("all")
            self.model_box.create_image(0, 0, anchor="nw", image=U.model_img(self.icon_of(m), self.model_of(m), px(50), px(35)))
            self.model_box.pack(side="left", padx=(0, px(10)), before=self.param_title)
            return
        self.param_title.configure(text=self.block_title(m) + ("  ·  %s" % self.half if self.half else ""))
        model = self.model_of(m, self.half or "A")
        if model:
            sub = model
            if self.is_ir(m):
                info = self.param_info(m, "IR2" if self.half == "B" else "IR")
                sub = L.ir_label(info.get("string", "")) if info else model
            self.param_sub.configure(text=sub)
            self.param_sub.pack(fill="x", pady=(0, px(8)), before=self.psep)
        elif self.is_nam(m):
            info = self.param_info(m, "Drive")
            self.param_sub.configure(text="NAM amp  ·  " + (self.nam_model_label(L.nam_index_of(info)) if info else "…"))
            self.param_sub.pack(fill="x", pady=(0, px(8)), before=self.psep)
        self.draw_preset_row(m)
        if self.is_double(m):   # doppelt (Knopf '2x' in der Kette): Haelfte waehlen
            self.head_btns.pack(fill="x", pady=(0, px(8)), before=self.psep)
            U.Btn(self.head_btns, "A", command=lambda: self.pick_module(m, "A"),
                  kind="primary" if self.half == "A" else "default", padx=10, pady=3, font=FONT_SMALL).pack(side="left")
            U.Btn(self.head_btns, "B", command=lambda: self.pick_module(m, "B"),
                  kind="primary" if self.half == "B" else "default", padx=10, pady=3, font=FONT_SMALL).pack(side="left", padx=(px(2), 0))
            if self.session:
                U.Btn(self.head_btns, "Copy A → B", command=lambda: self.copy_a_to_b(m), kind="ghost",
                      padx=8, pady=3, font=FONT_SMALL).pack(side="left", padx=(px(8), 0))
        self.show_colour_box(m)
        if m not in ("Rig", "Input", "Output") and m not in L.HW_MODULES:
            self.model_box.delete("all")
            self.model_box.create_image(0, 0, anchor="nw", image=U.model_img(self.icon_of(m), model, px(50), px(35)))
            self.model_box.pack(side="left", padx=(0, px(10)), before=self.param_title)
        on = v.is_on(m)
        if on is not None:
            self.head_toggle.set(on)
            self.head_toggle.pack(side="right", padx=(px(12), 0))

    # ---- Blockfarbe (Feld oben links im Kopf) ----
    def block_colour(self, m):
        """Farbname des Blocks ('' = unbekannt) oder None, wenn der Block keine Farbe hat."""
        if not m or self.view is None or self.param_info(m, "Colour") is None:
            return None
        return self.view.colour(m) or ""

    def show_colour_box(self, m):
        if self.block_colour(m) is not None:
            self.draw_colour_box()
            self.colour_box.pack(side="left", padx=(0, px(12)), before=self.param_title)

    def draw_colour_box(self, hover=False):
        c = self.colour_box
        c.delete("all")
        name = self.block_colour(self.module)
        if name is None:
            return
        s, col = px(24), COLOURS.get(name, COLOURS["Off"])
        U.rrect(c, 0, 0, s, s, px(6), col, "#ffffff" if hover else None, 2 if hover else 0)
        if hover:
            c.create_text(s / 2, s / 2 + px(1), text="▾", fill=U.text_on(col), font=FONT_SMALL)

    def colour_names(self):
        """Farben fuer Bloecke: live die Auswahlliste des Geraets (einmal gelesen), offline die in
        Rig-Dateien gesehenen Farben in der Reihenfolge des Geraets."""
        if self.session:
            return self._colour_entries
        seen = set()
        for mod in self.catalog.modules.values():
            seen |= set(mod.get("params", {}).get("Colour", {}).get("values", []))
        return [c for c in U.COLOUR_ORDER if c in seen] or list(U.COLOUR_ORDER)

    def pick_block_colour(self):
        """Klick auf das Farbfeld: Farben als Kaestchen aufklappen, Klick setzt die Farbe des Blocks."""
        m = self.module
        cur = self.block_colour(m)
        if cur is None or self.assign:
            return
        box = self.colour_box
        x, y = box.winfo_rootx() - px(4), box.winfo_rooty() + box.winfo_height() + px(6)

        def show(names):
            if self.module == m and names:
                U.SwatchPopup(self, [n for n in names if n], cur, lambda name: self.set_block_colour(m, name)).popup(
                    x, y, above=box.winfo_rooty() - px(6))
        if not self.session or self._colour_entries:
            show(self.colour_names())
            return
        path = self.lrig.path(m, "Colour")

        def done(res, err):
            if err:
                self.status.set("Could not read the colour list: %s" % err)
                return
            self._colour_entries = list(res)
            show(self._colour_entries)
        self.run_job(lambda br: br.entries(path), done, "Reading the colour list …")

    def set_block_colour(self, m, name):
        if self.block_colour(m) == name:
            return
        if not self.session:
            self.apply(m, "Colour", name)
            self.refresh()
            return
        lr = self.lrig

        def reply(path, res):
            if not self.session:
                return
            if res.get("ok"):
                lr.store(path, res)
                self.draw_chain()
                if self.module == m:
                    self.draw_head()
                self.status.set("%s: colour %s" % (m, res.get("string", name)))
                self.live_mark_dirty()
            else:
                self.status.set("Colour not set: %s" % res.get("err"))
        self.write(lr.path(m, "Colour"), "index", self._colour_entries.index(name), reply)

    def chain_double(self, m):
        """Knopf '2x' in der Kette: Doppelung des gewaehlten Amps/Cabs/IRs umschalten."""
        if self.view is None or not self.can_double(m):
            return
        on = not self.is_double(m)
        if not on and self.module == m:
            self.half = None
        self.set_double(m, on)
        self.status.set("%s: %s" % (m, "double (A + B)" if on else "einfach"))

    def has_presets(self, m):
        """Bloecke mit Preset-Menue am Geraet: Kette, Eingang, Ausgang, Parallelwege."""
        return bool(m) and m != "Rig" and m not in L.HW_MODULES

    def preset_path(self, m):
        return L.preset_name_path(m, self.half or "A")

    def preset_name(self, m):
        if self.session:
            info = self.lrig.values.get(self.preset_path(m))
            return (info or {}).get("string", "")
        for mod in self.offline_preset_modules(m):
            try:
                return self.rig.node(mod, "PresetName" + ("2" if self.half == "B" else "")).get("string", "")
            except RigError:
                pass
        return ""

    def draw_preset_row(self, m):
        """Kopfzeile 'Preset': Name des geladenen Presets, Klick zeigt die Presets des Blocktyps."""
        self.preset_row.pack_forget()
        for w in self.preset_row.winfo_children():
            w.destroy()
        self.preset_dd = None
        if not self.has_presets(m) or (not self.session and not self.presets_offline):
            return
        tk.Label(self.preset_row, text="Preset", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=(0, px(8)))
        name = self.preset_name(m)
        dd = U.Dropdown(self.preset_row, [], name or NO_PRESET, width=26, font=FONT_SMALL,
                        on_open=lambda: self.open_presets(m), title="Preset for %s" % self.block_title(m))
        dd.pack(side="left")
        self.preset_dd = dd
        if self.can_write():
            self.preset_buttons(self.preset_row, m, self.half or "A")
        self.preset_row.pack(fill="x", pady=(0, px(8)), before=self.psep)
        if self.session:
            self.live_widgets[self.preset_path(m)] = lambda i: dd.set_text(i.get("string") or NO_PRESET)

    def preset_buttons(self, parent, m, half, current=None, then=None):
        """Knoepfe neben dem Preset-Dropdown: + = aktuelle Werte als neues Preset, Diskette = das
        Preset `current()` (sonst das geladene) ueberschreiben. then(name) nach dem Speichern."""
        def tip(b, text):
            b.bind("<Enter>", lambda e: self.status.set(text), add="+")

        new = U.Btn(parent, "", icon="plus", kind="ghost", padx=4, pady=3, font=FONT_SMALL,
                    command=lambda: self.live_new_preset(m, half, then))
        new.pack(side="left", padx=(px(6), 0))
        tip(new, "Save the current values of %s as a new preset" % self.block_title(m))
        save = U.Btn(parent, "", icon="save", kind="ghost", padx=4, pady=3, font=FONT_SMALL,
                     command=lambda: self.live_overwrite_preset(
                         m, half, current() if current else self.preset_name_of(m, half), then))
        save.pack(side="left", padx=(px(2), 0))
        tip(save, "Overwrite the preset with the current values")

    def open_presets(self, m):
        """Presetliste des Blocktyps zeigen (live aus der Datenbank, offline aus dem Blocks-Ordner)."""
        dd = self.preset_dd

        def show(items):
            if not items:
                self.status.set("No presets for %s." % self.block_title(m))
                return
            dd.on_pick = lambda i: self.load_preset(m, items[i])
            dd.show([it["name"] for it in items])
        if self.session:
            def done(res, err):
                if err:
                    messagebox.showwarning(APP, "Could not read presets:\n%s" % err)
                    return
                if self.lrig.presets is not None:
                    self.lrig.presets[L.preset_type(m)] = res
                show(res)
            self.run_job(lambda br: L.db_presets_of(br, m), done, "Reading presets …")
        else:
            show(self.presets_offline.get(L.preset_type(m), []))

    def load_preset(self, m, preset, half=None):
        half = half or self.half or "A"
        if self.session:
            self.live_load_preset(m, preset, half)
            return
        self.offline_load_preset(m, preset, half)

    @staticmethod
    def offline_preset_modules(m):
        # Parallelwege: Parameter unter 'Chain', Presetname unter 'Mix' (wie am Geraet)
        return ["Chain", "Mix"] if m == MIX else [m]

    def offline_load_preset(self, m, preset, half="A"):
        """Preset in das Offline-Rig uebernehmen (nur Parameter, die der Block im Rig hat)."""
        writes = L.preset_writes(m, preset["content"], half)
        n = 0
        for path, field, value in writes:
            param = path.rsplit("/", 1)[1]
            for mod in self.offline_preset_modules(m):
                try:
                    self.rig.set_value(mod, param, value if field != "state" else bool(value))
                    n += 1
                except RigError:
                    pass
        if not n:
            messagebox.showwarning(APP, "None of the parameters of preset “%s” exists in this block." % preset["name"])
            return
        for mod in self.offline_preset_modules(m):
            try:
                self.rig.set_value(mod, "PresetName" + ("2" if half == "B" else ""), preset["name"])
            except RigError:
                pass
        self.status.set("%s: preset “%s” loaded (%d values)" % (self.block_title(m), preset["name"], n))
        self.refresh()

    def label(self, parent, text, row, fg=TEXT):
        tk.Label(parent, text=text, bg=parent.cget("bg"), fg=fg, font=FONT, anchor="w").grid(
            row=row, column=0, sticky="w", padx=(0, px(10)), pady=px(5))

    def draw_params(self):
        self.clear_params()
        self.draw_head()
        m = self.module
        self._rows = self._row_key(m)
        if self.view is None or (not m and not self.assign):
            return
        self.params.columnconfigure(1, weight=1)
        if self.assign:
            self.draw_assign_params()
            return
        if self.scene:
            self.draw_scene_params()
            return
        if self.session:
            self.draw_live_params(m)
            return
        row = 0
        if m == "Rig":
            self.label(self.params, "Name", row)
            tk.Label(self.params, text=self.rig.name, bg=PANEL, fg=MUTED, anchor="w").grid(row=row, column=1, sticky="w")
            tk.Label(self.params, text="(double-click the name above to rename)", bg=PANEL, fg=DIM,
                     font=FONT_SMALL, anchor="w").grid(row=row + 1, column=1, sticky="w")
            row += 2
        for label, p in self.params_for(m):
            node = self.rig.node(m, p)
            self.label(self.params, label, row)
            self.param_widget(m, p, node, row)
            row += 1

    def editable_value(self, parent, text, on_commit, width=9):
        """Wertanzeige rechts vom Regler; Klick macht daraus ein Eingabefeld (Enter uebernimmt)."""
        cell = tk.Frame(parent, bg=PANEL)
        lbl = tk.Label(cell, text=text, bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="e", width=width, cursor="xterm")
        lbl.pack(fill="x")

        def edit(_=None):
            ent = U.Entry(cell, width=width, font=FONT_SMALL, justify="right")
            ent.insert(0, cell.raw() if cell.raw else lbl.cget("text"))
            lbl.pack_forget()
            ent.pack(fill="x")
            ent.focus_entry()
            ent.select_all()
            state = {"open": True}

            def close(_=None):
                if state["open"]:
                    state["open"] = False
                    ent.destroy()
                    lbl.pack(fill="x")

            def commit(_=None):
                v = ent.get()
                close()
                on_commit(v)
            ent.bind_entry("<Return>", commit)
            ent.bind_entry("<Escape>", close)
            ent.bind_entry("<FocusOut>", close)
        lbl.bind("<Button-1>", edit)
        cell.set_text = lambda t: lbl.configure(text=t)
        cell.raw = None       # Funktion, die den Rohwert fuer das Eingabefeld liefert
        return cell

    def param_widget(self, m, p, node, row):
        t = node.get("type")
        cell = tk.Frame(self.params, bg=PANEL)
        cell.grid(row=row, column=1, sticky="ew")
        if t == T_NUMBER:
            cur = node.get("value")
            seen_lo, seen_hi = self.catalog.range(m, p)
            lo, hi = slider_range(seen_lo, seen_hi, cur)

            def commit(txt):
                try:
                    v = float(txt.replace(",", "."))
                except ValueError:
                    val.set_text(fmt(self.rig.value(m, p)))
                    self.status.set("Invalid number for %s/%s" % (m, p))
                    return
                if lo is not None and hi is not None and not (lo <= v <= hi):
                    if not messagebox.askyesno(APP, "%s is outside the slider range (%s … %s).\n"
                                                    "The device's real range is not known yet.\n"
                                                    "Apply anyway?" % (fmt(v), fmt(lo), fmt(hi))):
                        val.set_text(fmt(self.rig.value(m, p)))
                        return
                self.apply(m, p, v)
                val.set_text(fmt(self.rig.value(m, p)))
                if scale is not None:
                    scale.set(min(max(v, lo), hi))
            val = self.editable_value(cell, fmt(cur), commit)
            val.pack(side="right")
            scale = None
            if lo is not None and hi is not None and hi > lo:
                span = hi - lo
                is_int = all(isinstance(x, int) for x in (lo, hi, cur))

                def rounded(v):
                    return round(v) if is_int else round(v, 2 if span <= 100 else 0)
                scale = U.Slider(cell, from_=lo, to=hi, value=min(max(cur, lo), hi),
                                 command=lambda v: val.set_text(fmt(rounded(v))),
                                 on_release=lambda v: commit(fmt(rounded(v))))
                scale.pack(side="left", fill="x", expand=True, padx=(0, px(8)))
            else:
                tk.Label(cell, text="range unknown", bg=PANEL, fg=DIM, font=FONT_SMALL).pack(side="left")
        elif t in (T_BOOL, T_BOOL3):
            U.Toggle(cell, value=bool(node.get("state")),
                     command=lambda on: (self.apply(m, p, on), self.refresh())).pack(side="left")
        elif t == T_ENUM:
            cur = node.get("string", "")
            values = self.catalog.choices(m, p)
            if cur not in values:
                values = [cur] + values
            dd = U.Dropdown(cell, values, cur, on_pick=lambda i: (self.apply(m, p, values[i]), self.refresh()),
                            width=26, title="%s / %s" % (m, p))
            dd.pack(side="left")
            if len(values) <= 1:
                tk.Label(cell, text="further values unknown", bg=PANEL, fg=DIM, font=FONT_SMALL).pack(side="left", padx=8)
        elif t == T_TEXT and self.ir_param(m, p):
            self.ir_row(cell, m, p, node.get("string", ""))
        elif t == T_TEXT:
            var = tk.StringVar(value=node.get("string", ""))
            e = U.Entry(cell, textvariable=var)
            e.pack(side="left", fill="x", expand=True)
            e.bind_entry("<Return>", lambda ev: self.apply(m, p, var.get()))
            e.bind_entry("<FocusOut>", lambda ev: self.apply(m, p, var.get()))
        else:
            tk.Label(cell, text="Type %s is not supported" % t, bg=PANEL, fg=DIM, font=FONT_SMALL).pack(side="left")

    # ---------------- Bearbeiten (offline) ----------------
    def apply(self, m, p, v):
        if not self.rig:
            return
        try:
            changed = self.rig.set_value(m, p, v)
        except (RigError, ValueError) as e:
            messagebox.showerror(APP, str(e))
            return
        if changed:
            self.status.set("%s / %s = %s" % (m, p, fmt(v)))
            self.refresh_head()
            if self.rows_changed():              # anderes Amp-Modell: andere Regler
                self.after_idle(self.draw_params)

    def save(self):
        if self.session:
            self.live_save()
            return
        if not self.rig:
            return
        self.focus_set()  # offene Eingabe uebernehmen
        self.update()
        try:
            self.rig.save(BACKUP_DIR)
        except (OSError, RigError) as e:
            messagebox.showerror(APP, "Saving failed:\n%s" % e)
            return
        self.status.set("Saved. Backup of the old version in %s" % BACKUP_DIR)
        self.refresh()

    def save_as(self):
        if not self.rig or self.session:
            return
        self.focus_set()
        self.update()
        name = self.ask_text("Save as", "Name of the new rig:", self.rig.name + " 2")
        if not name:
            return
        try:
            path = self.rig.save_as(self.folder, name, BACKUP_DIR)
        except (OSError, RigError) as e:
            messagebox.showerror(APP, str(e))
            self.rig.revert()
            self.refresh()
            return
        self.files = sorted(set(self.files) | {os.path.basename(path)})
        self.fill_list()
        self.select_current()
        self.status.set("Saved as a new rig: %s  (run “Sync” on the MX5 if needed)" % path)
        self.refresh()

    def revert(self):
        if self.session:
            self.live_revert()
            return
        if self.rig and messagebox.askyesno(APP, "Discard all unsaved changes?"):
            self.load_rig(self.rig.path, self.module)

    def confirm_discard(self):
        if self.rig and self.rig.dirty:
            r = U.ask(self, "“%s” was changed. Save?" % self.rig.name,
                      [("Cancel", None, "ghost"), ("Discard", False, "danger"), ("Save", True, "primary")],
                      icon="warning")
            if r is None:
                return False
            if r:
                self.save()
        return True

    def on_close(self):
        if not self.confirm_discard():
            return
        if self.session and self.lrig.dirty:
            how = self.ask_unsaved("Save before quitting? (Unsaved, the changes stay on the MX5 "
                                   "until another rig is loaded there.)", discard="Don't save")
            if how is None:
                return
            if how != "discard":
                self.live_store(how, then=self.on_close)
                return
        self.stop_reconnect()
        if self.session:
            self.disconnect()
        self.destroy()

    # ================= LIVE =================
    def _pump(self):
        try:
            while True:
                self._inbox.get_nowait()()
        except queue.Empty:
            pass
        self.after(20, self._pump)

    def toggle_live(self):
        if self.session:
            self.disconnect()
        elif self._reconnect:
            self.stop_reconnect()
            self.status.set("Reconnecting cancelled.")
        else:
            self.connect()

    @staticmethod
    def open_bridge(bridge=None, ports=("", "")):
        """MIDI-Port suchen (ohne bridge; ports = fest gewaehlte (Eingang, Ausgang) aus den
        Einstellungen, "" = automatisch) und die Bruecke anpingen -> (bridge, version)."""
        if bridge is None:
            from bridge import Bridge
            bridge = Bridge(*settings.find_ports(*ports)) if any(ports) else Bridge.auto()
        try:
            version = bridge.ping()
            if bridge.vnum < MIN_BRIDGE:
                raise BridgeTooOld(version)
        except Exception:
            bridge.close()
            raise
        return bridge, version

    def connect(self, bridge=None, quiet=False):
        """Mit dem MX5 verbinden. Ohne bridge sucht ein Hintergrund-Thread den Port (die Oberflaeche
        bleibt bedienbar, in der Mitte steht 'Verbinde …'); quiet = beim Fehlschlag keine Meldung,
        nur der Hinweis unter dem Knopf 'Connect to Device' (automatischer Versuch beim Start)."""
        if self.session or self._connecting:
            return
        if self.rig and self.rig.dirty and not self.confirm_discard():
            return
        if bridge is not None:   # Skripte: gleich verbinden
            self._connected(*self.open_bridge(bridge))
            return
        self._connecting, self._connect_err = True, None
        if self.view is None:
            self.draw_chain()
        self.status.set("Looking for the MX5 …")
        ports = self.midi_ports()

        def work():
            try:
                res = self.open_bridge(ports=ports)
                self._inbox.put(lambda: self._connected(*res))
            except Exception as e:
                self._inbox.put(lambda e=e: self._connect_failed(e, quiet))
        threading.Thread(target=work, daemon=True).start()

    def _connect_failed(self, e, quiet):
        self._connecting = False
        if isinstance(e, ImportError):
            self._connect_err = "For live mode please install: pip install mido python-rtmidi"
        elif isinstance(e, BridgeTooOld):
            self._connect_err = ("The MX5 runs %s – this editor needs bridge firmware %d.%d or newer.\n"
                                 "Please flash MX5Bridge %d.%d (see ANLEITUNG.txt in its folder)."
                                 % ((e,) + MIN_BRIDGE + MIN_BRIDGE))
        else:
            self._connect_err = ("No MX5 found (%s).\nIs it connected via USB and switched on? "
                                 "The MIDI port appears about 10 s after it starts." % e)
            if any(self.midi_ports()):
                self._connect_err += "\nThe MIDI ports are chosen in Settings – try “Automatic” there."
        self.status.set("Not connected." if quiet else "No connection to the MX5 bridge.")
        if self.view is None:
            self.draw_chain()
        if not quiet:
            messagebox.showwarning(APP, "No connection to the MX5 bridge.\n" + self._connect_err)

    def _connected(self, bridge, version):
        self._connecting, self._connect_err = False, None
        if self.session:   # schon verbunden (doppelter Versuch)
            bridge.close()
            return
        if self.rig and self.rig.dirty and not self.confirm_discard():
            bridge.close()
            self.draw_chain()
            return
        self._colour_entries = []
        self.session = L.LiveSession(bridge, self._inbox.put, on_lost=self.connection_lost)
        self.lrig = L.LiveRig(self.session, self.catalog)
        self.module = None
        self.rig = None
        self.folder = None
        self.set_mode_badge(version)
        self.fill_list()
        self.show_fsbar(True)
        self.status.set("Connected. Reading the active rig …")
        self.live_reload(then=self.live_scan_rigs)
        self.nam_read()
        self._poll_job = self.after(POLL_MS, self.live_poll)

    # ---- Verbindungsverlust (USB gezogen, Geraet aus, App-Neustart am Geraet) ----
    def connection_lost(self):
        """Der Worker meldet: das Geraet antwortet nicht mehr (auch nicht auf einen Ping). Sitzung
        abbauen und im Hintergrund neu verbinden, bis die Bruecke wieder antwortet; danach wird alles
        frisch gelesen wie beim ersten Verbinden."""
        if not self.session:
            return
        self.disconnect(lost=True)
        self._reconnect_seq += 1
        self._reconnect = self._reconnect_seq
        self._connecting = True
        self._connect_err = ("Connection to the MX5 lost – reconnecting automatically …\n"
                             "(Click LIVE on the left to stop.)")
        self.set_mode_badge(None, "RECONNECTING …")
        self.draw_chain()
        self.status.set("Connection to the MX5 lost – reconnecting …")
        token = self._reconnect
        ports = self.midi_ports()

        def work():
            while token == self._reconnect:
                try:
                    res = self.open_bridge(ports=ports)
                except Exception:
                    time.sleep(RECONNECT_S)
                    continue
                self._inbox.put(lambda: self._reconnected(token, res))
                return
        threading.Thread(target=work, daemon=True).start()

    def _reconnected(self, token, res):
        if token != self._reconnect or self.session:
            res[0].close()   # abgebrochen oder inzwischen anders verbunden
            return
        self.stop_reconnect()
        self._connected(*res)
        self.status.set("Reconnected to the MX5. Reading the active rig …")

        self.after(1000, lambda: self._restore_dialog_check(self.session, 8))

    def _restore_dialog_check(self, session, left):
        """Nach einem Neustart der Geraete-App fragt das MX5 einige Sekunden spaeter 'letzten Zustand
        wiederherstellen?' - das entscheidet der Nutzer am Geraet; der Editor weist nur darauf hin."""
        if session is None or session is not self.session:
            return

        def done(buttons):
            if session is not self.session:
                return
            if isinstance(buttons, list) and "Yes" in [b.strip() for b in buttons]:
                messagebox.showinfo(APP, "The MX5 was restarted and asks on its display whether to restore "
                                         "the last state.\nPlease answer on the device – the editor follows.")
            elif left > 1:
                self.after(1500, lambda: self._restore_dialog_check(session, left - 1))
        session.run(L.dialog_buttons, done)

    def stop_reconnect(self):
        if self._reconnect:
            self._reconnect = 0   # der Versuchs-Thread sieht seine Nummer nicht mehr und endet
            self._connecting, self._connect_err = False, None
            self.set_mode_badge(None)
            if self.view is None:
                self.draw_chain()

    def disconnect(self, lost=False):
        """Live-Sitzung beenden. lost=True: das Geraet antwortet nicht mehr - nichts mehr senden."""
        if not self.session:
            return
        self.after_cancel(self._poll_job)
        if self.tuner_open() and lost:
            self.tuner_dialog.close(quiet=True)
        elif self.tuner_open():
            # Fenster nur schliessen und den Tuner am Geraet direkt verlassen, sobald der Worker ruht
            self.tuner_dialog.close(quiet=True)
            for _ in range(50):
                if self.session.idle():
                    break
                time.sleep(0.01)
            try:
                L.tuner_close(self.session.bridge)
            except Exception:
                pass
        self.tuner_dialog = None
        self.rail_tuner.set_active(False)
        self.close_setlists(device=False)
        self.close_hardware()   # beendet auch den Scene-Modus (Pfeile und Punkt in der Kopfzeile zurueck)
        self.session.close()
        self.session = None
        self.show_fsbar(False)
        self.lrig = None
        self.module = None
        self._batch_id += 1
        self._busy = self._job = False
        self.set_mode_badge(None)
        if self.ir_dialog and self.ir_dialog.winfo_exists():
            self.ir_dialog.changed = False   # ohne Sitzung kein Neustart
            self.ir_dialog.close()
        self.ir_dialog = None
        if self.nam_dialog and self.nam_dialog.winfo_exists():
            self.nam_dialog.changed = False   # ohne Sitzung kein Neustart
            self.nam_dialog.close()
        self.nam_dialog = None
        if self.nam_browser and self.nam_browser.winfo_exists():
            self.nam_browser.close()
        self.nam_browser = None
        self._nam_auto_told = False
        self.clear_params()
        self.draw_head()
        self.fill_list()
        if self.rig:
            self.refresh()
        else:
            self.lbl_name.configure(text="No rig open")
            self.lbl_dirty.configure(text="")
            self.lbl_chain.configure(text="")
            self.show_routing_name()
            self.title(APP)
            self.draw_chain()
            for b in (self.btn_save, self.btn_revert, self.btn_assign):
                b.configure(state="disabled")
        self.status.set("Live connection closed.")

    def batch(self, paths, on_each, on_done, compact=False):
        """Liest mehrere Pfade in einer Sammelabfrage; on_done nach der Antwort. compact: nur
        Wert/Text/Zustand (L.get_compact) - on_each muss die Werte in vorhandene Eintraege mischen."""
        self._batch_id += 1
        bid = self._batch_id
        if not paths:
            on_done()
            return
        self._busy = True

        def cb(res):
            if not self.session or bid != self._batch_id:
                return
            self._busy = False
            if not isinstance(res, dict) or not res.get("ok", True):
                self.status.set("Error: %s" % (res or {}).get("err"))
                return
            for p in paths:
                if p in res:
                    on_each(p, res[p])
            on_done()
        if compact:
            self.session.run(lambda br: L.get_compact(br, paths), cb)
        else:
            self.session.get_many(paths, cb)

    def run_job(self, fn, on_done, text=None):
        """Laengere Geraeteaktion im Hintergrund (Laden, Speichern, Rig-Liste)."""
        if self._job:
            self.status.set("Please wait, the device is still busy.")
            return
        self._job = True
        if text:
            self.status.set(text)

        def cb(res):
            self._job = False
            if not self.session:
                return
            if isinstance(res, dict) and res.get("ok") is False:
                on_done(None, res.get("err"))
            else:
                on_done(res, None)
        self.session.run(fn, cb)

    def live_reload(self, then=None):
        if not self.session:
            return
        lr = self.lrig
        for m in list(lr.loaded_modules):
            lr.forget_module(m)
        lr.hw = None   # Auswahllisten haengen an der Kette

        def overview_done():
            self.batch(self.chain_paths() + L.fs_display_paths(), lr.store, chain_done)

        def chain_done():
            if not self.module or not (lr.has_module(self.module) or self.module == MIX) or self.module in L.HW_MODULES:
                self.module = next((m for m in lr.modules()), None)
            self.refresh()
            self.fsbar.set(lr.fs_display())
            self.status.set("Live: %s  (%d request errors)" % (lr.name, self.session.errors))
            if self.module:
                self.live_load_module(self.module, then)   # then() zuletzt, seine Meldung bleibt stehen
            elif then:
                then()
            if self.hw_panel:
                self.live_load_hw()
        self.batch(lr.overview_paths(), lr.apply_overview, overview_done)

    def chain_paths(self):
        """An/Aus, Farbe und Amp-/Cab-Modell aller Bloecke der Kette."""
        lr = self.lrig
        paths = []
        for m in lr.modules():
            if m in SPECIAL_MODULES:
                continue
            paths += [lr.path(m, "On"), lr.path(m, "Colour")]
            param = U.MODEL_PARAM.get(U.base_name(m), (None,))[0]
            if param:
                paths += [lr.path(m, param), lr.path(m, param + "2"), lr.path(m, "Doubling")]
        return paths

    def live_poll(self):
        """Laufend (ab 250 ms, je nach Dauer einer Abfrage): Rig/Kette (Neuladen bei Aenderung), dazu
        An/Aus + Modell aller Bloecke, die Fussschalter-Anzeige und die Parameter des gezeigten
        Blocks - Aenderungen am Geraet selbst (Fussschalter, Regler) landen so im Editor, ohne alles
        neu zu lesen. Ist das Geraet gerade beschaeftigt, wird bald erneut versucht."""
        if not self.session:
            return
        delay = POLL_RETRY
        if not self._busy and not self._job and self.session.idle() and not self.tuner_open() \
                and time.time() - self._last_write >= WRITE_QUIET:
            self.live_sync()
            delay = max(POLL_MS, int(self._sync_s * 1000 * POLL_SHARE))
        self._poll_job = self.after(delay, self.live_poll)

    def live_sync(self):
        """Ein Abgleich mit dem Geraet (Kern von live_poll; auch direkt nach einem Fussschalterdruck)."""
        if self.session:
            lr = self.lrig
            overview = lr.overview_paths()
            chain = self.chain_paths()
            fs = L.fs_display_paths()
            extra = list(chain) + fs
            m = self.module
            if m and m in lr.loaded_modules:
                extra += [lr.path(m, p) for p in self.all_params(m) if lr.path(m, p) not in extra]
                if self.has_presets(m):
                    extra.append(self.preset_path(m))
            changed = [False]
            chain_changed = [False]
            fs_changed = [False]
            params_changed = []
            was_dirty = lr.dirty
            now = time.time()

            def key(i):
                return (i.get("value"), i.get("string"), i.get("state"), i.get("index"))

            def each(p, info):
                if p in overview:
                    changed[0] |= lr.apply_overview(p, info)
                    return
                if not info.get("ok") or now - self._written.get(p, 0) < WRITE_GRACE:
                    return
                old = lr.values.get(p)
                if old is None or key(old) != key(info):
                    lr.store(p, dict(old or {}, **info))   # kompakt: Grenzen/Listenlaenge vom vollen Lesen behalten
                    if p in chain:
                        chain_changed[0] = True
                    elif p in fs:
                        fs_changed[0] = True
                    if p in self.live_widgets:
                        params_changed.append(p)

            def done():
                self._sync_s = time.time() - now
                if changed[0]:
                    self.status.set("Rig or chain changed on the device – rereading …")
                    self.live_reload()
                    return
                if was_dirty != lr.dirty:
                    self.refresh_head()
                if chain_changed[0]:
                    self.draw_chain()
                    self.draw_head()
                if fs_changed[0]:
                    self.fsbar.set(lr.fs_display())
                if chain_changed[0] and self.rows_changed():
                    self.draw_params()           # Amp-Modell am Geraet gewechselt: andere Regler
                else:
                    for p in params_changed:
                        self.live_widgets[p](lr.values[p])
                if params_changed or chain_changed[0]:
                    names = sorted({p.rsplit("/", 1)[1] for p in params_changed}) or ["Block on/off"]
                    self.status.set("Changed on the device: %s" % ", ".join(names))
            self.batch(overview + extra, each, done, compact=True)

    def live_load_module(self, m, then=None):
        lr = self.lrig
        params = self.all_params(m)
        paths = [lr.path(m, p) for p in params]
        if self.has_presets(m):
            paths += [L.preset_name_path(m, h) for h in ("A", "B")]
        self.status.set("Reading %d values of %s …" % (len(paths), self.block_title(m)))

        def done():
            lr.loaded_modules.add(m)
            if self.module == m:
                self.draw_params()
            self.status.set("Live: %s" % lr.name)
            if then:
                then()
        self.batch(paths, lr.store, done)

    def live_reply_chain(self, path, info):
        if self.session and info.get("ok"):
            self.lrig.store(path, info)
            if path.endswith("/Doubling"):
                self.live_mark_dirty()
                if self.module and not self.is_double(self.module):
                    self.half = None
                elif self.module and self.half is None:
                    self.half = "A"
            self.draw_chain()
            if self.module and path.startswith(L.ENGINE + "/" + self.module + "/"):
                self.draw_params()
        elif self.session:
            self.status.set("Error: %s" % info.get("err"))

    # ---- Setlists, Rig-Liste, Laden, Speichern ----
    def live_load_hw(self):
        lr = self.lrig
        if lr.hw_loading:
            return
        lr.hw_loading = True

        def done(res):
            if not self.session or lr is not self.lrig:
                return
            lr.hw_loading = False
            if isinstance(res, dict) and res.get("ok") is False:
                self.status.set("Could not read hardware assignments: %s" % res.get("err"))
                return
            lr.hw = res
            self.on_hw_loaded()
        self.session.run(L.read_hardware, done)

    def on_hw_loaded(self):
        """Zuweisungen neu gelesen: Hardware-Feld, im Scene-Modus auch Signalpfad und Parameterfeld."""
        if self.hw_panel:
            self.hw_panel.refresh()
        hw = self.lrig.hw if self.lrig else None
        if self.scene:
            if self.scene_slots() is None:   # Schalter ist keine Scene mehr / Zustand 2 weg
                n = self.scene[0]
                d = hw["fs"].get(n) if hw else None
                if d and d["mode"].get("string") == "Scene":
                    self.set_scene((n, 1))
                elif d:
                    self.set_assign(n)
                else:
                    self.set_scene(None)
                return
            self.draw_chain()
            self.draw_params()
        elif self.assign:
            d = hw["fs"].get(self.assign) if hw else None
            if d and d["mode"].get("string") == "Scene":   # Schalter ist jetzt eine Scene
                self.set_scene((self.assign, 1))
                return
            self.draw_chain()
            self.draw_params()

    def refresh_setlists(self):
        lr = self.lrig
        if lr.setlist is None:
            self.btn_setlist.configure(text="Rigs  ▾")
        else:
            self.btn_setlist.configure(text="%s%s  ▾" % (lr.setlist, "" if lr.setlist_sure else " (?)"))

    def _rig_list_done(self, res, err):
        if err:
            self.status.set("Could not read the rig list: %s" % err)
            self.refresh_setlists()
            return
        lr = self.lrig
        lr.apply_rig_list(res)
        self.fill_list()
        self.status.set("Live: %s  – %d rigs in “%s”%s" % (
            lr.name, len(lr.rows), lr.setlist, "" if lr.setlist_sure else " (guessed)"))

    def live_scan_rigs(self):
        if not self.session:
            return
        self.run_job(L.read_rig_list, self._rig_list_done,
                     "Reading setlists and rig list from the device …")

    def on_pick_setlist(self, name):
        lr = self.lrig
        if not self.session or (name == lr.setlist and lr.setlist_sure):
            return
        if self._job:
            self.status.set("Please wait, the device is still busy.")
            return
        if lr.dirty:
            how = self.ask_unsaved("Save before switching to setlist “%s”?" % name)
            if how is None:
                return
            if how != "discard":
                self.live_store(how, then=lambda: self.on_pick_setlist(name))
                return
        setlists, discard, ids = lr.setlists, lr.dirty, lr.setlist_ids

        def done(res, err):
            self._rig_list_done(res, err)
            if not err:
                self.live_reload()
        self.run_job(lambda br: L.enter_setlist(br, setlists, name, ids, discard),
                     done, "Switching to setlist “%s” …" % name)

    def live_export_rig(self, rig_id=None, name=None):
        """Rig aus der Datenbank des Geraets als .rig-Datei sichern (ohne Angabe: das gewaehlte
        Rig der Liste, sonst das geladene)."""
        lr = self.lrig
        if rig_id is None:
            i = self.riglist.selected
            if i is not None and i < len(self.live_shown):
                _, name, _, rig_id = self.live_shown[i]
            else:
                rig_id, name = lr.rig_id, L.display_name(lr.name)
        if not rig_id:
            messagebox.showinfo(APP, "No rig is loaded.")
            return
        path = filedialog.asksaveasfilename(title="Back up rig as file", initialfile=name + ".rig",
                                            defaultextension=".rig", filetypes=[("Rig files", "*.rig")])
        if not path:
            return

        def done(row, err):
            if err:
                messagebox.showwarning(APP, err)
                return
            try:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(L.rig_file_json(row))
            except OSError as e:
                messagebox.showerror(APP, str(e))
                return
            self.status.set("Backed up: %s" % path)
        self.run_job(lambda br: L.db_rig(br, rig_id), done, "Reading “%s” from the database …" % name)

    def live_backup_all(self):
        """Alle Rigs, Setlists und Block-Presets aus der Datenbank des Geraets in einen neuen
        Unterordner sichern. Dauert etwa eine Minute; das Geraet bleibt spielbar."""
        if self._job:
            self.status.set("Please wait, the device is still busy.")
            return
        parent = filedialog.askdirectory(title="Choose a folder – the backup is created as a subfolder")
        if not parent:
            return
        folder = os.path.join(parent, time.strftime("MX5-Sicherung %Y-%m-%d %H%M"))
        try:
            os.makedirs(folder, exist_ok=False)
        except OSError as e:
            messagebox.showerror(APP, "Could not create the folder:\n%s" % e)
            return
        progress = lambda txt: self._inbox.put(lambda: self.status.set(txt))

        def done(res, err):
            if err:
                messagebox.showwarning(APP, "Backup incomplete:\n%s\n\nFiles written so far are in\n%s"
                                       % (err, folder))
                self.status.set("Backup aborted: %s" % err)
                return
            self.status.set("Backup done: %d rigs, %d setlists, %d block presets in %.0f s" % (
                res["rigs"], res["setlists"], res["blocks"], res["seconds"]))
            messagebox.showinfo(APP, "Backup done.\n\n%d rigs\n%d setlists\n%d block presets\n\n%s" % (
                res["rigs"], res["setlists"], res["blocks"], folder))
        self.run_job(lambda br: L.backup_all(br, folder, progress), done, "Backup running …")

    def live_import_rigs(self):
        """.rig-Dateien auf das Geraet kopieren: neue Rigs in der aktiven Setlist; gibt es ein Rig
        mit derselben ID schon, wird gefragt (ueberschreiben / Kopie / auslassen)."""
        if not self.can_write():
            return
        if self._job:
            self.status.set("Please wait, the device is still busy.")
            return
        paths = filedialog.askopenfilenames(title="Copy rig files to the MX5",
                                            filetypes=[("MX5-Rig", "*.rig"), ("All files", "*.*")])
        if not paths:
            return
        lr = self.lrig
        sid = lr.setlist_ids.get(lr.setlist) if lr.setlist != L.ALL_RIGS else None

        def decide(present, err):
            if err:
                messagebox.showwarning(APP, err)
                return
            plan = []
            for p in paths:
                try:
                    d = L._read_json_file(p)
                except L.LiveError as e:
                    messagebox.showwarning(APP, str(e))
                    continue
                name = L.rig_name_of_file(d, p)
                mode = "new"
                if d.get("id") in present:
                    r = messagebox.askyesnocancel(APP, "“%s” already exists on the device (same ID).\n\n"
                                                       "Yes = overwrite the rig on the device\n"
                                                       "No = create as a new rig\nCancel = skip" % name)
                    if r is None:
                        continue
                    mode = "replace" if r else "new"
                plan.append((p, mode))
            if not plan:
                return
            replaced = [p for p, m in plan if m == "replace"]
            reload = any(L._read_json_file(p).get("id") == lr.rig_id for p in replaced)

            def work(br):
                out = []
                for p, mode in plan:
                    out.append(L.import_rig_file(br, p, mode=mode, setlist_id=sid if mode == "new" else None))
                return out

            def report(out):
                self.status.set("%d rig file(s) copied to the device (%d new, %d replaced)." % (
                    len(out), sum(1 for _, w in out if w == "neu"), sum(1 for _, w in out if w == "ersetzt")))
            self.db_job(work, "Copying %d rig file(s) to the device …" % len(plan), reload=reload, then=report)
        self.run_job(lambda br: L.db_ids(br, "rigs"), decide, "Checking rigs on the device …")

    def live_restore_all(self):
        """Umkehrung von 'Alles sichern': Rigs, Setlists und Block-Presets aus einem
        Sicherungsordner auf das Geraet; danach App-Neustart, damit neue Setlists sichtbar werden."""
        if not self.can_write():
            return
        if self._job:
            self.status.set("Please wait, the device is still busy.")
            return
        folder = filedialog.askdirectory(title="Choose the backup folder (contains Rigs\\, Setlists\\, Blocks\\)")
        if not folder:
            return
        if not any(os.path.isdir(os.path.join(folder, d)) for d in ("Rigs", "Setlists", "Blocks")):
            messagebox.showwarning(APP, "This folder has no subfolders Rigs, Setlists or Blocks.")
            return
        r = messagebox.askyesnocancel(APP, "Restore everything from\n%s\nto the device?\n\n"
                                           "Rigs, setlists and presets that no longer exist on the device are "
                                           "created. Should existing rigs (same ID) be overwritten with the state "
                                           "of the backup?\n\nYes = overwrite\nNo = only create what is missing\n"
                                           "Cancel\n\n(The device app restarts at the end, about 15 s.)" % folder)
        if r is None:
            return
        progress = lambda txt: self._inbox.put(lambda: self.status.set(txt))

        def report(c):
            text = "%d rigs new, %d replaced, %d already present\n%d setlists new\n%d block presets new" % (
                c["rigs"], c["rigs_ersetzt"], c["rigs_vorhanden"], c["setlists"], c["blocks"])
            if c["fehler"]:
                text += "\n\n%d errors:\n" % len(c["fehler"]) + "\n".join(c["fehler"][:10])
            self.status.set("Restore done: " + text.split("\n")[0])
            messagebox.showinfo(APP, "Restore done.\n\n" + text)
        self.db_job(lambda br: L.restore_all(br, folder, progress, replace=bool(r)),
                    "Restoring backup …", restart=True, then=report)

    def live_load_rig(self, index, name, discard=False):
        rows = self.lrig.rows

        def done(st, err):
            if err:
                messagebox.showwarning(APP, err)
                self.select_current()
                return
            self.status.set("Loaded: %s" % st["name"])
            self.live_reload()
        self.run_job(lambda br: L.load_rig(br, rows, index, discard), done, "Loading “%s” …" % name)

    def live_revert(self):
        if not self.lrig.dirty:
            return
        if not messagebox.askyesno(APP, "Discard all unsaved changes to “%s”?\n"
                                        "The rig is reloaded on the device." % self.lrig.name):
            return
        rows = self.lrig.rows

        def done(st, err):
            if err:
                messagebox.showwarning(APP, err)
                return
            if st["dirty"]:
                messagebox.showinfo(APP, "The rig is still marked as changed on the device.\n"
                                         "Please reload it on the MX5.")
            self.live_reload()
        self.run_job(lambda br: L.reload_rig(br, rows), done, "Reloading “%s” …" % self.lrig.name)

    def live_save(self):
        """Knopf 'Speichern': erst die Wahl 'Speichern' (ueberschreibt) oder 'Als neues Rig', erst
        beim neuen Rig wird nach dem Namen gefragt (live_store)."""
        if not self.lrig.dirty:
            self.status.set("No changes to save.")
            return
        self.focus_set()
        self.update()
        lr = self.lrig
        how = U.ask(self, "Save “%s” on the MX5?" % lr.name,
                    [("Cancel", None, "ghost"), ("Save as new rig …", "new", "default"), ("Save", "save", "primary")],
                    title="Save rig", icon="question",
                    detail="“Save” overwrites the rig on the device, “Save as new rig” creates a new one "
                           "with the current state.")
        if how:
            self.live_store(how)

    def live_store(self, how, then=None):
        """Das geladene Rig speichern: how = 'save' (ueberschreiben) oder 'new' (neues Rig, fragt den
        Namen, save_rig_as legt die Zeile an). then() nach Erfolg."""
        lr = self.lrig
        if how == "new":
            setlist = lr.setlist if lr.setlist != L.ALL_RIGS and lr.setlist in (lr.setlist_ids or {}) else None
            name = self.ask_text("Save as new rig", "Name of the new rig:", L.display_name(lr.name) + " 2",
                                 "The new rig gets the current state%s; “%s” stays unchanged."
                                 % (" and goes into the setlist “%s”" % setlist if setlist else "", lr.name))
            if not name or not name.strip():
                return
            try:
                name = L.check_rig_name(name)
            except L.LiveError as e:
                messagebox.showwarning(APP, str(e))
                return
            sid = lr.setlist_ids.get(setlist) if setlist else None

            def saved(_):
                self.status.set("Saved and loaded as “%s”." % name)
                if then:
                    then()
            self.db_job(lambda br: L.save_rig_as(br, name, setlist_id=sid), "Saving as “%s” …" % name,
                        load_result=True, then=saved)
            return
        if how == "save":
            def done(st, err):
                ok = False
                if err:
                    messagebox.showwarning(APP, err)
                elif st["dirty"]:
                    messagebox.showwarning(APP, "The MX5 still reports the rig as changed.\n"
                                                "Please check the display for an open dialog.")
                else:
                    ok = True
                    self.status.set("“%s” saved on the device." % st["name"])
                self.live_reload(then=then if ok else None)
            self.run_job(L.save_rig, done, "Saving “%s” …" % self.lrig.name)

    # ---- Bloecke ----
    def live_block_types(self, slot, then):
        lr = self.lrig
        if lr.block_types:
            then(lr.block_types)
            return

        def done(res, err):
            if err:
                messagebox.showwarning(APP, "Could not read the block list:\n%s" % err)
                return
            lr.block_types = res
            then(res)
        self.run_job(lambda br: br.entries(lr.slot_path(slot)), done, "Reading block list …")

    def models(self):
        """Amp-/Cab-Modelle fuer die Modell-Auswahl (aus dem Katalog; IR-Dateien nicht, die sind je Geraet)."""
        return {b: self.catalog.choices(b, U.MODEL_PARAM[b][0]) for b in ("Amp", "Cab")}

    def live_presets(self, then):
        """Namen aller Block-Presets einmal aus der Datenbank lesen."""
        lr = self.lrig
        if lr.presets is not None:
            then(lr.presets or {})
            return

        def done(res, err):
            if err:
                self.status.set("Could not read presets: %s" % err)
                res = {}
            lr.presets = res
            then(res)
        self.run_job(L.db_preset_names, done, "Reading block presets …")

    def live_add_block(self, slot, current=None, half=None):
        """Modell-Auswahl: zeigt jeden Blocktyp einmal (Amps und Cabs je Modell) und rechts die
        Presets des gewaehlten Typs; das Geraet fuehrt jeden Typ doppelt ('Amp', 'Amp 2'), gewaehlt
        wird die erste Variante, die noch nicht in der Kette ist. Bei Amp/Cab wird danach das Modell
        (Type/CabType) gesetzt, ein gewaehltes Preset danach geladen."""
        def choose(types, presets):
            names = [t for t in types if t and t != L.EMPTY]
            title = "Choose a block for slot %d" % slot if not half else "Choose model %s for %s" % (half, current)
            res = U.ModelSelector(self, title, names, current, self.models(),
                                  self.model_of(current, half or "A") if current else None,
                                  presets=(lambda base: presets.get(L.preset_type(base))) if presets else None,
                                  nam=self.nam_names()).result
            if res is None:
                return
            pick, model, preset = res
            if current and U.base_name(current) == pick:
                if preset:
                    self.live_load_preset(current, preset, half or "A")
                elif model and model != self.model_of(current, half or "A"):
                    self.live_set_model(current, model, half or "A")
                return
            if half:
                messagebox.showinfo(APP, "For half %s please choose a model of the same block type." % half)
                return
            used = {m for m in self.lrig.slots if m and m != current}
            variants = [t for t in names if U.base_name(t) == pick]
            free = [t for t in variants if t not in used]
            if not free:
                messagebox.showinfo(APP, "“%s” is already %d times in the chain – the MX5 allows no more."
                                    % (self.nam_names().get(pick, pick), len(variants)))
                return
            self.live_set_slot(slot, types.index(free[0]), free[0], model, preset)
        self.live_block_types(slot, lambda types: self.live_presets(lambda presets: choose(types, presets)))

    def live_load_preset(self, module, preset, half="A"):
        """Block-Preset aus der Datenbank in den Block schreiben (Haelfte B: Parameter mit Endung 2)."""
        def done(n, err):
            if err:
                messagebox.showwarning(APP, "Could not load the preset:\n%s" % err)
                return
            self.status.set("%s: preset “%s” loaded (%d values)" % (SPECIAL_LABELS.get(module, module), preset["name"], n))
            self.live_mark_dirty()
            self.lrig.forget_module(module)
            self.live_reload()
        self.run_job(lambda br: L.load_block_preset(br, module, preset, half), done,
                     "Loading preset %s …" % preset["name"])

    def live_set_model(self, module, model, half="A"):
        """Amp-/Cab-Modell eines vorhandenen Blocks setzen (Haelfte B = Parameter mit Endung 2)."""
        param = U.MODEL_PARAM[U.base_name(module)][0] + ("2" if half == "B" else "")
        path = self.lrig.path(module, param)

        def job(br):
            ents = br.entries(path)
            if model not in ents:
                raise L.LiveError("Model not in the list: %s" % model)
            return br.set(path, "index", ents.index(model))

        def done(res, err):
            if err:
                messagebox.showwarning(APP, err)
                return
            self.status.set("%s: %s" % (module, res.get("string")))
            self.live_mark_dirty()
            self.live_reload()
        self.run_job(job, done, "Setting %s to %s …" % (module, model))

    def drop_block(self, slot, module):
        """Block auf den Mülleimer der Kette gezogen: nachfragen und entfernen (offline nur
        ModuleType, die Parameter bleiben wie am Gerät unter dem Blocknamen erhalten).
        True = wird entfernt."""
        if self.session and self._job:
            self.status.set("Please wait, the device is still busy.")
            return False
        if not messagebox.askyesno(APP, "Remove block “%s” from slot %d?" % (module, slot)):
            return False
        if self.session:
            self.live_remove_block(slot, module, ask=False)
            return True
        chain = [m for _, m in self.view.chain()]
        chain[slot - 1] = None
        self.rig.set_chain(chain)
        if self.module == module:
            self.module = None
        self.refresh()
        self.status.set("%s entfernt" % module)
        return True

    def live_remove_block(self, slot, module, ask=True):
        if ask and not messagebox.askyesno(APP, "Remove block “%s” from slot %d?" % (module, slot)):
            return

        def choose(types):
            self.live_set_slot(slot, types.index(L.EMPTY), L.EMPTY)
            if self.module == module:
                self.module = None
        self.live_block_types(slot, choose)

    def live_set_slot(self, slot, index, name, model=None, preset=None):
        path = self.lrig.slot_path(slot)
        # NAM-Block: Drive steht meist auf 50 % - ohne 51 Modelle waere er stumm, darum das erste Modell
        nam_n = len(self.lrig.nam_models or []) if self.is_nam(name) and not preset else 0

        def job(br):
            r = br.set(path, "user", index)
            if not r.get("ok"):
                raise L.LiveError(r.get("err"))
            if model or preset or nam_n:
                time.sleep(0.4)   # der neue Block braucht einen Moment, bis seine Parameter da sind
            if nam_n:
                dpath = L.LiveRig.path(name, "Drive")
                if L.nam_index_of(br.get(dpath)) >= nam_n:
                    br.set(dpath, "unnormalized", 0)
            if model:
                mpath = L.LiveRig.path(name, U.MODEL_PARAM[U.base_name(name)][0])
                ents = br.entries(mpath)
                if model in ents:
                    br.set(mpath, "index", ents.index(model))
            if preset:
                L.load_block_preset(br, name, preset)
            return r

        def done(res, err):
            if err:
                self.status.set("Error: %s" % err)
            else:
                what = res.get("string")
                if preset:
                    what += " – preset " + preset["name"]
                elif model:
                    what += " – " + model
                self.status.set("Slot %d: %s" % (slot, what))
                if preset:
                    self.live_mark_dirty()
                self.live_reload()
        self.run_job(job, done, "Setting slot %d to %s …" % (slot, name))

    # ---- Hardware-Zuweisungen (live) ----
    def hw_set(self, path, field, value, reload=True):
        """Zuweisung schreiben; danach die Hardware-Seite neu lesen, weil sich abhaengige
        Auswahllisten (Funktion, Parameter, Zustaende) mit aendern."""
        lr = self.lrig

        def reply(p, res):
            if not self.session:
                return
            if not res.get("ok"):
                self.status.set("Error at %s: %s" % (p.rsplit("/", 1)[1], res.get("err")))
                return
            self.status.set("%s = %s" % (p.rsplit("/", 1)[1], res.get("string", value)))
            self.live_mark_dirty()
            if reload:
                lr.hw = None
                self.live_load_hw()
        self.write(path, field, value, reply)

    def hw_set_scene(self, n, state, slot, mode):
        lr = self.lrig

        def done(res):
            if not self.session or lr is not self.lrig:
                return
            if isinstance(res, dict) and res.get("ok") is False:
                self.status.set("Error: %s" % res.get("err"))
                return
            eff = "Slot %d" % (slot + 1)
            if lr.hw:
                eff, _, preset = lr.hw["fs"][n]["scenes"][state - 1][slot]
                lr.hw["fs"][n]["scenes"][state - 1][slot] = (eff, res, preset)
            self.status.set("%s: %s = %s" % (self.scene_name(n, state), eff, SCENE_MODES[res]))
            self.live_mark_dirty()
            self.scene_changed(n, state, eff)
        self.session.run(lambda br: L.set_scene_slot(br, n, state, slot, mode), done)

    def hw_set_scene_preset(self, n, state, slot, name):
        """Preset (Name, "" = keins) eintragen, das die Scene in den Block auf Platz slot (0-basiert) laedt."""
        lr = self.lrig

        def done(res):
            if not self.session or lr is not self.lrig:
                return
            if isinstance(res, dict) and res.get("ok") is False:
                self.status.set("Error: %s" % res.get("err"))
                return
            eff = "Slot %d" % (slot + 1)
            if lr.hw:
                eff, mode, _ = lr.hw["fs"][n]["scenes"][state - 1][slot]
                lr.hw["fs"][n]["scenes"][state - 1][slot] = (eff, mode, res)
            self.status.set("%s: %s loads %s" % (
                self.scene_name(n, state), eff, ("preset “%s”" % res) if res else "no preset"))
            self.live_mark_dirty()
            self.scene_changed(n, state, eff)
        self.session.run(lambda br: L.set_scene_preset(br, n, state, slot, name), done)

    def scene_changed(self, n, state, module):
        """Nach einer Scene-Aenderung Signalpfad, Parameterfeld und Hardware-Feld nachziehen."""
        if self.hw_panel:
            self.hw_panel.refresh()
        if self.scene == (n, state):
            self.draw_chain()
            if self.module == module:
                self.draw_params()

    # ---- Parameter (live) ----
    def live_mark_dirty(self):
        """Parameteraenderungen ueber die Bridge setzen das Geaendert-Flag des MX5 nicht
        (wie MIDI-Zuweisungen). Der Editor setzt Rigs/Dirty selbst, damit 'Speichern'
        moeglich ist und das MX5 beim Rig-Wechsel nachfragt."""
        lr = self.lrig
        if lr.dirty or lr.marking_dirty:
            return
        lr.marking_dirty = True

        def reply(path, res):
            if not self.session:
                return
            lr.marking_dirty = False
            if res.get("ok") and res.get("state"):
                lr.dirty = True
                self.refresh_head()
        self.write(L.RIGS + "/Dirty", "state", 1, reply)

    def draw_live_params(self, m, start=0):
        lr = self.lrig
        if m in L.METERS:
            self.draw_meter(m, start)
            start += 1
        if m not in lr.loaded_modules:
            tk.Label(self.params, text="Reading values from the device …", bg=PANEL, fg=MUTED).grid(row=start, column=0, sticky="w")
            return
        if self.is_nam(m):
            self.draw_nam_params(m, start)
            return
        row = start
        known = 0
        for label, p in self.params_for(m):
            info = lr.info(m, p)
            kind = L.kind_of(info)
            if kind is None:
                continue
            known += 1
            self.label(self.params, label, row)
            cell = tk.Frame(self.params, bg=PANEL)
            cell.grid(row=row, column=1, sticky="ew")
            self.live_widget(cell, m, p, info, kind)
            row += 1
        if not known:
            tk.Label(self.params, text="No parameters are known for this block type yet.",
                     bg=PANEL, fg=MUTED).grid(row=start, column=0, columnspan=2, sticky="w")

    def draw_meter(self, m, row):
        """Pegelanzeige oben auf der Input-/Output-Seite; fragt die Meter des Geraets ~25x pro
        Sekunde ab, solange sie zu sehen ist (neben der normalen Abfrage)."""
        lo, hi = L.METER_RANGE[m]
        warn, clip = (-12.0, -3.0) if m == "Input" else (-6.0, 0.0)
        box = tk.Frame(self.params, bg=PANEL)
        box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, px(12)))
        tk.Label(box, text="Input level" if m == "Input" else "Output level", bg=PANEL, fg=MUTED,
                 font=FONT_SMALL, anchor="w").pack(fill="x", pady=(0, px(4)))
        meter = U.LevelMeter(box, [n for n, _ in L.METERS[m]], lo, hi, warn=warn, clip=clip)
        meter.pack(fill="x")
        self._meter = (m, meter)
        self._meter_token += 1
        self.meter_tick(self._meter_token)

    def meter_tick(self, token):
        if token != self._meter_token or not self.session or not self._meter:
            return
        m, meter = self._meter
        if not meter.winfo_exists():
            self._meter = None
            return
        if self._job or self.tuner_open():
            self.after(METER_SLOW_MS, lambda: self.meter_tick(token))
            return

        def reply(res):
            if token != self._meter_token or not meter.winfo_exists():
                return
            ok = isinstance(res, dict) and res.get("ok") is not False
            meter.set(L.meter_parse(m, res) if ok else None)
            self.after(METER_MS if ok else METER_SLOW_MS, lambda: self.meter_tick(token))
        self.session.get_many(L.meter_paths(m), reply)

    def live_widget(self, cell, m, p, info, kind, fmt=None):
        """Regler fuer einen Parameter. fmt(info) -> Anzeigetext statt des Texts des Geraets (Zahlen)."""
        lr, path = self.lrig, self.lrig.path(m, p)
        show = fmt or (lambda i: i.get("string", ""))
        text = tk.StringVar(value=info.get("string", ""))

        def reply(pth, res, text=text):
            if not self.session:
                return
            if res.get("ok"):
                lr.store(pth, res)
                text.set(res.get("string", ""))
                if val is not None:
                    val.set_text(show(res))
                self.status.set("%s / %s = %s" % (m, p, res.get("string", "")))
                mp = U.MODEL_PARAM.get(U.base_name(m), (None,))[0]
                if p in ("On", "Colour") or (mp and p in (mp, mp + "2")):
                    self.draw_chain()
                    self.draw_head()
                    if self.rows_changed():      # anderes Amp-Modell: andere Regler
                        self.after_idle(self.draw_params)
                self.live_mark_dirty()
            else:
                self.status.set("Error at %s/%s: %s" % (m, p, res.get("err")))
        val = None

        if kind == L.L_NUMBER:
            def commit(txt):
                try:
                    v = float(txt.replace(",", "."))
                except ValueError:
                    self.status.set("Invalid number")
                    val.set_text(show(lr.values.get(path, info)))
                    return

                def after_set(pth, res):
                    reply(pth, res)
                    if res.get("ok"):
                        scale.set(float(res.get("value", 0)))
                self.write(path, "unnormalized", v, after_set)
            scale = U.Slider(cell, from_=0.0, to=1.0, value=float(info.get("value", 0)),
                             command=lambda v: self.write(path, "value", round(float(v), 5), reply))
            scale.pack(side="left", fill="x", expand=True, padx=(0, px(8)))
            val = self.editable_value(cell, show(info), commit, width=10)
            val.raw = lambda: fmt(lr.values.get(path, info).get("unnormalized", ""))
            val.pack(side="left")
            default = info.get("defaultValue")
            if default is not None:
                def reset():
                    scale.set(float(default))
                    self.write(path, "value", default, reply)
                U.Btn(cell, "↺", command=reset, kind="ghost", padx=4, pady=0).pack(side="left", padx=(px(2), 0))

            def update(i):
                scale.set(float(i.get("value", 0)))
                val.set_text(show(i))
            self.live_widgets[path] = update
        elif kind == L.L_BOOL:
            tg = U.Toggle(cell, value=bool(info.get("state")),
                          command=lambda on: self.write(path, "state", int(on), reply))
            tg.pack(side="left")
            tk.Label(cell, textvariable=text, bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=px(8))
            self.live_widgets[path] = lambda i: (tg.set(i.get("state")), text.set(i.get("string", "")))
        elif kind == L.L_ENUM:
            n = int(info.get("numEntries", 1))

            def step(d):
                cur = lr.values.get(path, info)
                idx = max(0, min(n - 1, int(cur.get("index", 0)) + d))
                self.write(path, "index", idx, reply)

            def pick_from_list():
                def done(res, err):
                    if err:
                        self.status.set("Could not read the list: %s" % err)
                        return
                    cur = lr.values.get(path, info).get("string")
                    choice = U.ChoiceDialog(self, "%s / %s" % (m, p), [v for v in res if v], cur).result
                    if choice is not None:
                        self.write(path, "index", res.index(choice), reply)
                self.run_job(lambda br: br.entries(path), done, "Reading choice list …")
            U.Btn(cell, "‹", command=lambda: step(-1), kind="ghost", padx=6, pady=0, font=FONT_HEAD).pack(side="left")
            dd = U.Dropdown(cell, [], info.get("string", ""), width=20, on_open=pick_from_list)
            dd.pack(side="left", fill="x", expand=True)
            U.Btn(cell, "›", command=lambda: step(1), kind="ghost", padx=6, pady=0, font=FONT_HEAD).pack(side="left")
            text.trace_add("write", lambda *_: dd.set_text(text.get()))
            self.live_widgets[path] = lambda i: text.set(i.get("string", ""))
        elif self.ir_param(m, p):
            lbl = self.ir_row(cell, m, p, info.get("string", ""))
            self.live_widgets[path] = lambda i: lbl.configure(text=L.ir_label(i.get("string", "")) or "–")
        else:
            tk.Label(cell, textvariable=text, bg=PANEL, fg=MUTED).pack(side="left")
            self.live_widgets[path] = lambda i: text.set(i.get("string", ""))

    # ---- NAM-Mod (Bruecke 0.7 mit NAM gebaut) ----
    def nam_active(self):
        """Laeuft die Geraete-App gerade mit NAM (Anxiety OD spielt NAM-Modelle)?"""
        lr = self.lrig
        return bool(self.session and lr and lr.nam and lr.nam.get("active"))

    def is_nam(self, m):
        return bool(m) and self.nam_active() and m in L.nam_modules(self.lrig.nam)

    def icon_of(self, m):
        """Blockname fuer das Symbol: NAM-Bloecke bekommen ein eigenes (Amp-Topteil mit Netz)."""
        return "NAM" if self.is_nam(m) else m

    def block_title(self, m):
        """Anzeigename eines Blocks: NAM-Bloecke heissen 'NAM' / 'NAM 2' statt 'Anxiety OD'."""
        return L.nam_display(m) if self.is_nam(m) else SPECIAL_LABELS.get(m, m)

    def nam_names(self):
        """{Basisname: Anzeigename} der Blocktypen, die gerade NAM spielen (fuer die Blockauswahl)."""
        if not self.nam_active():
            return {}
        return {U.base_name(m): L.nam_display(U.base_name(m)) for m in L.nam_modules(self.lrig.nam)}

    def nam_model_label(self, idx):
        """'003  Name' fuer Drive-Platz idx; Plaetze ohne Modell sind stumm."""
        models = self.lrig.nam_models if self.lrig else None
        if models is None:
            return "Model %d" % idx
        if 0 <= idx < len(models):
            return "%03d  %s" % (idx, models[idx]["name"])
        return "%03d  – no model (silent)" % idx

    def nam_read(self, then=None):
        """NAM-Zustand und Modellliste im Hintergrund lesen (nach dem Verbinden und nach Aenderungen).
        Laeuft ueber die Warteschlange der Sitzung, nicht als Job - blockiert also nichts."""
        session = self.session
        if not session:
            return

        def job(br):
            st = L.nam_status(br)
            return {"nam": st, "models": L.db_nam_models(br)["models"] if st["installed"] else []}

        def done(res):
            if session is not self.session or not isinstance(res, dict) or res.get("ok") is False:
                return
            lr = self.lrig
            lr.nam, lr.nam_models = res["nam"], res["models"]
            if res["nam"].get("auto_off") and not self._nam_auto_told:
                self._nam_auto_told = True
                messagebox.showwarning(APP, "NAM was switched off automatically: the device app crashed three times "
                                            "in a row right after starting with NAM.\n\nCheck the NAM models "
                                            "(⋯ › NAM models …) and turn NAM on again from the ⋯ menu.")
            if self.view is not None:
                self.draw_chain()
                self.draw_params()
            if then:
                then()
        session.run(job, done)

    def draw_nam_params(self, m, row):
        """Parameterfeld eines NAM-Blocks: Modell (Drive), Eingangs- und Ausgangspegel (Tone/Level)."""
        lr = self.lrig
        models = lr.nam_models or []
        for label, p in NAM_ROWS:
            info = lr.info(m, p)
            if L.kind_of(info) is None:
                continue
            self.label(self.params, label, row)
            cell = tk.Frame(self.params, bg=PANEL)
            cell.grid(row=row, column=1, sticky="ew")
            if p == "Drive":
                self.nam_model_row(cell, m, p, info)
            else:
                self.live_widget(cell, m, p, info, L.L_NUMBER, fmt=lambda i: L.nam_trim_text(i.get("value", 0)))
            row += 1
        nam = lr.nam or {}
        text = ("NAM %s  ·  %d model(s) on the device  ·  Input/Output: 50 %% = unity, above up to +%d dB"
                % (nam.get("ref", ""), len(models), L.NAM_TRIM_DB))
        tk.Label(self.params, text=text, bg=PANEL, fg=DIM, font=FONT_SMALL, anchor="w", justify="left",
                 wraplength=px(380)).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(px(10), 0))
        if self.can_write():
            U.Btn(self.params, "Manage NAM models …" if models else "Add NAM models …", command=self.open_nam_dialog,
                  padx=10, pady=3, font=FONT_SMALL).grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(px(6), 0))

    def nam_model_row(self, cell, m, p, info):
        """Modellwahl: Drive-Platz = Modell in der Reihenfolge des NAM-Ordners (‹ › blaettern)."""
        lr, path = self.lrig, self.lrig.path(m, p)

        def cur():
            return L.nam_index_of(lr.values.get(path, info))

        def update(i):
            if dd.winfo_exists():   # das Parameterfeld kann inzwischen neu gezeichnet sein
                dd.set_text(self.nam_model_label(L.nam_index_of(i)))

        def reply(pth, res):
            if not self.session:
                return
            if res.get("ok"):
                lr.store(pth, res)
                update(res)
                self.status.set("%s: NAM model %s" % (m, self.nam_model_label(L.nam_index_of(res)).strip()))
                self.draw_head()
                self.live_mark_dirty()
            else:
                self.status.set("Error at %s/%s: %s" % (m, p, res.get("err")))

        def set_idx(i):
            self.write(path, "unnormalized", max(0, min(L.NAM_SILENT, i)), reply)

        def step(d):
            n, i = len(lr.nam_models or []), cur()
            if not n:
                return
            i = (n - 1 if d < 0 else 0) if i >= n else max(0, min(n - 1, i + d))
            set_idx(i)

        def pick():
            models = lr.nam_models or []
            if not models:
                if self.can_write() and messagebox.askyesno(APP, "There are no NAM models on the device yet.\n"
                                                                 "Upload some now?"):
                    self.open_nam_dialog()
                return
            if self.nam_browser and self.nam_browser.winfo_exists():
                self.nam_browser.close()
            labels = [self.nam_model_label(i) for i in range(len(models))]
            i = cur()
            self.nam_browser = NAMBrowser(self, "%s · NAM model" % self.block_title(m), labels,
                                          i if i < len(models) else L.NAM_SILENT, set_idx,
                                          audition=self.prefs.get("audition"),
                                          on_manage=self.open_nam_dialog if self.can_write() else None)
        U.Btn(cell, "‹", command=lambda: step(-1), kind="ghost", padx=6, pady=0, font=FONT_HEAD).pack(side="left")
        dd = U.Dropdown(cell, [], self.nam_model_label(L.nam_index_of(info)), width=24, on_open=pick)
        dd.pack(side="left", fill="x", expand=True)
        U.Btn(cell, "›", command=lambda: step(1), kind="ghost", padx=6, pady=0, font=FONT_HEAD).pack(side="left")
        self.live_widgets[path] = update

    def nam_switch(self, on):
        """NAM ein-/ausschalten (Bruecke 0.7): die Geraete-App startet neu, mit bzw. ohne NAM."""
        text = ("Turn NAM on? The device app restarts with NAM (about 15 s); the Anxiety OD then plays "
                "NAM models." if on else
                "Turn NAM off? The device app restarts without NAM (about 15 s); the Anxiety OD is then a "
                "normal overdrive again. The NAM models stay on the device.")
        if not messagebox.askyesno(APP, text):
            return
        self.db_job(lambda br: None, "Turning NAM %s – the device app restarts …" % ("on" if on else "off"),
                    restart=True, restart_action="nam-on" if on else "nam-off",
                    then=lambda _: self.nam_read(then=lambda: self.status.set(
                        "NAM is %s." % ("on" if self.nam_active() else "off"))))

    def open_nam_dialog(self):
        """NAM-Modelle des Geraets verwalten (hochladen, umbenennen, sortieren, loeschen)."""
        if not self.can_write():
            return
        if self.nam_dialog and self.nam_dialog.winfo_exists():
            self.nam_dialog.close()
        nam = self.lrig.nam

        def job(br):
            st = L.nam_status(br)
            return {"nam": st, "models": L.db_nam_models(br)["models"], "usage": L.nam_usage(br, dict(st, active=True))}

        def done(res, err):
            if err:
                messagebox.showwarning(APP, "Could not read the NAM models:\n%s" % err)
                return
            self.lrig.nam, self.lrig.nam_models = res["nam"], res["models"]
            self.nam_dialog = NAMDialog(self, res)
            self.rail_nam.set_active(True)
        if not nam or not nam.get("installed"):
            messagebox.showinfo(APP, "This firmware has no NAM mod (MX5 Bridge 0.7 built with NAM is needed).")
            return
        self.run_job(job, done, "Reading NAM models from the device …")

    def nam_browser_done(self, dlg):
        if self.nam_browser is dlg:
            self.nam_browser = None

    def manage_nam(self):
        """Symbolleiste 'NAM': Modelle verwalten (nur live mit NAM-Firmware)."""
        if self.nam_dialog and self.nam_dialog.winfo_exists():
            self.nam_dialog.raise_()
            return
        if not self.can_write():
            self.status.set("NAM models can be managed only in live mode (MX5 Bridge 0.7 with NAM).")
            return
        self.open_nam_dialog()

    def nam_dialog_done(self, dlg):
        """Beim Schliessen des NAM-Dialogs: wurden Dateien geaendert, die Geraete-App neu starten -
        die Mod liest den NAM-Ordner nur einmal je App-Start."""
        if self.nam_dialog is dlg:
            self.nam_dialog = None
            self.rail_nam.set_active(False)
        if not self.session:
            return
        if not dlg.changed:
            self.nam_read()
            return
        if not self.nam_active():
            self.nam_read(then=lambda: self.status.set("NAM models changed – they are used once NAM is on."))
            return
        if not self.db_job(lambda br: None, "Restarting the device app so it loads the NAM models …", restart=True,
                           then=lambda _: self.nam_read()):
            self.nam_read()
            self.status.set("The MX5 uses the changed NAM models after the next restart of the device app.")

    # ---- Einstellungen ----
    def open_settings(self):
        if self.settings_dialog and self.settings_dialog.winfo_exists():
            self.settings_dialog.raise_()
            return
        self.settings_dialog = settings.SettingsDialog(self)
        self.rail_settings.set_active(True)

    def midi_ports(self):
        return self.prefs["midi_in"], self.prefs["midi_out"]

    def pref_changed(self, key):
        """Einstellung wurde geaendert (settings.SettingsDialog): sofort anwenden, was ohne Neustart geht."""
        if key == "footswitch_bar" and self.session and not self.hw_panel:
            self.show_fsbar(True)

    def settings_done(self, dlg):
        if self.settings_dialog is dlg:
            self.settings_dialog = None
            self.rail_settings.set_active(False)

    # ---- Impulse Responses ----
    def ir_row(self, cell, m, p, value):
        """Zeile des IR-Parameters: 'Ordner / Name' und ein Knopf, der die IR-Auswahl oeffnet."""
        lbl = tk.Label(cell, text=L.ir_label(value) or "–", bg=PANEL, fg=TEXT, anchor="w")
        lbl.pack(side="left", fill="x", expand=True)
        U.Btn(cell, "Choose …", command=lambda: self.open_ir_dialog(m, "B" if p == "IR2" else "A"),
              padx=10, pady=2, font=FONT_SMALL).pack(side="right")
        return lbl

    def open_ir_dialog(self, m=None, half="A"):
        """IR-Auswahl fuer Block m (Haelfte A/B) oder, ohne m, die Verwaltung der IR-Dateien.
        Live kommt die Liste vom Geraet, offline aus 'Impulse Responses'."""
        if self.ir_dialog and self.ir_dialog.winfo_exists():
            self.ir_dialog.close()
        current = None
        if m:
            info = self.param_info(m, "IR2" if half == "B" else "IR")
            current = info.get("string", "") if info else ""
        on_pick = (lambda folder, name: self.ir_set(m, half, folder, name)) if m else None
        if not self.session:
            self.ir_dialog = IRDialog(self, self.irs_offline or L.read_ir_folder(""), current, on_pick)
            self.rail_irs.set_active(True)
            return

        def done(res, err):
            if err:
                messagebox.showwarning(APP, "Could not read the IR files:\n%s" % err)
                return
            self.ir_dialog = IRDialog(self, res, current, on_pick, manage=True, audition=self.prefs.get("audition"))
            self.rail_irs.set_active(True)
        self.run_job(L.db_irs, done, "Reading IR files from the device …")

    def manage_irs(self):
        """Symbolleiste 'IRs': IR-Dateien verwalten (live ab Bruecke 0.3, offline aus dem Ordner)."""
        if self.ir_dialog and self.ir_dialog.winfo_exists():
            self.ir_dialog.raise_()
            return
        if self.session and not getattr(self.session.bridge, "v3", False):
            self.status.set("Managing IR files needs MX5 Bridge 0.3 or newer.")
            return
        self.open_ir_dialog()

    def ir_set(self, m, half, folder, name):
        """IR eines Blocks setzen (live: Feld string, laedt sofort; offline: in die Datei)."""
        value = L.ir_string(folder, name)
        p = "IR2" if half == "B" else "IR"
        if not self.session:
            self.apply(m, p, value)
            self.refresh()
            return
        path = self.lrig.path(m, p)

        def reply(pth, res):
            if not self.session:
                return
            if res.get("ok"):
                self.lrig.store(pth, res)
                self.status.set("%s: %s" % (self.block_title(m), L.ir_label(res.get("string", ""))))
                self.live_mark_dirty()
                if path in self.live_widgets:
                    self.live_widgets[path](res)
                self.draw_chain()
                self.draw_head()
            else:
                self.status.set("Could not set the IR: %s" % res.get("err"))
        self.write(path, "string", value, reply)

    def ir_dialog_done(self, dlg):
        """Beim Schliessen des IR-Dialogs: wurden Dateien geaendert, die Geraete-App neu starten,
        damit das MX5 sie sieht (es liest den Dateibaum nur beim Start)."""
        if self.ir_dialog is dlg:
            self.ir_dialog = None
            self.rail_irs.set_active(False)
        pick = (lambda: dlg.on_pick(*dlg.pick_args)) if (dlg.on_pick and dlg.pick_args) else (lambda: None)
        if not dlg.changed or not self.session:
            pick()
            return
        if not self.can_write():
            messagebox.showinfo(APP, "The MX5 sees the changed IR files only after the next power-up.")
            pick()
            return
        # erst der Neustart (die Auswahl darf eine gerade hochgeladene Datei sein), dann die IR setzen
        self.db_job(lambda br: None, "Restarting the device app so it sees the IR files …", restart=True,
                    then=lambda _: pick())


if __name__ == "__main__":
    if U.Image is None:
        tk.Tk().withdraw()
        messagebox.showerror(APP, "The user interface needs Pillow:\n\npip install pillow")
        sys.exit(1)
    Editor(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()
