"""hardware.py - Feld "Hardware" unter dem Signalpfad (Fussschalter, Pedale, Tempo).

Eingebettetes Feld im Hauptfenster (kein eigenes Fenster).
  Fussschalter: drei breite Kacheln, die die Schalter des MX5 spiegeln. Kopfzeile je
                Kachel: Modus-Pille (Klick = Scene/Toggle), Beschriftung (Doppelklick =
                aendern), bei Scenes die Zustaende-Pille (Klick = 1 <-> 2 Zustaende).
                Darunter bei Scenes ein Feld je Zustand in seiner Farbe (bei zwei
                Zustaenden waagerecht geteilt): Klick = Scene im Signalpfad bearbeiten
                (Editor.set_scene). Bei Toggle ein Feld mit Block + Funktion: Klick =
                Block im Signalpfad waehlen (Editor.set_assign). Rechtsklick = Menue.
                Unten die Farbpalette fuer den gewaehlten Schalter/Zustand.
  Pedale:       Expression-Pedal 1/2 mit Classic/Advanced und bis zu vier Zuweisungen.
  Tempo:        Rig-Tempo (Fixed/Current, BPM) und MIDI-Programmnummer.

Breite Fenster (ab WIDE logischen Pixeln): Fussschalter und Pedale nebeneinander,
Tempo/Programmnummer in der Kopfzeile, keine Reiter; schmalere: Reiter.
Der Editor ruft refresh() auf, wenn er die Zuweisungen neu vom Geraet gelesen hat
(nach jedem Schreiben), und close() beim Trennen.

FootBar: die zugeklappte Form an derselben Stelle - drei flache Schalter wie auf dem
Display des MX5 (Text und Farbe aus FootSwitchText/FootSwitchColour, ein nicht
leuchtender Schalter ist abgedunkelt), Klick = Druck auf den Schalter am Geraet
(Editor.press_footswitch), rechts der Knopf "Zuweisen", der das Feld aufklappt.
"""
import tkinter as tk

import live as L
import ui as U
from ui import PANEL, CARD, CARD_LO, CARD_HI, ACCENT, TEXT, MUTED, DIM, COLOURS, px
from ui import FONT, FONT_SMALL, FONT_TINY, FONT_BOLD

SCENE_MODES = ["–", "On", "Off"]          # live.SCENE_UNCHANGED / SCENE_ON / SCENE_OFF
TEMPO = L.ENGINE + "/Rig/Tempo"
TEMPO_MODE = L.ENGINE + "/Rig/TempoFromMaster"
FONT_CARD_BIG = ("Segoe UI", 11, "bold")
TABS = ["Footswitches", "Pedals", "Tempo"]


def read_tempo(br):
    """Tempo-Einstellungen des Rigs und die Programmnummer (Reiter Tempo)."""
    r = br.get_many([TEMPO, TEMPO_MODE, L.RIGS + "/LoadedProgNum"])
    return {"tempo": r.get(TEMPO, {}), "mode": r.get(TEMPO_MODE, {}), "prog": r.get(L.RIGS + "/LoadedProgNum", {}),
            "modes": L._entries(br, TEMPO_MODE)}


def scene_summary(slots):
    """Kurzfassung einer Scene: Zahl der geschalteten Bloecke und Presets."""
    on = sum(1 for _, m, _ in slots if m == L.SCENE_ON)
    off = sum(1 for _, m, _ in slots if m == L.SCENE_OFF)
    pre = sum(1 for _, _, p in slots if p)
    parts = []
    if on:
        parts.append("%d on" % on)
    if off:
        parts.append("%d off" % off)
    if pre:
        parts.append("%d Preset%s" % (pre, "" if pre == 1 else "s"))
    return " · ".join(parts) or "switches nothing"


def state_name(d, state):
    """Name eines Scene-Zustands: 'Scene A'/'Scene B' bei zwei Zustaenden, sonst 'Scene'."""
    states = int(d["states"].get("unnormalized", 1) or 1) if d["mode"].get("string") == "Scene" else 1
    return ("Scene A", "Scene B")[state - 1] if states == 2 else "Scene"


def colour_path(n, state):
    """Farb-Property eines Schalters (Toggle / Scene-Zustand 1) bzw. seines Zustands 2."""
    return "%s/%sMacroColour%d" % (L.FSW, "State2" if state == 2 else "", n)


class FootswitchTile(tk.Canvas):
    """Kachel eines Fussschalters (siehe Modulkopf). Regionen: mode, states, label,
    state <k>, toggle. Rueckruf panel.tile_click(n, kind, arg)."""
    HEAD = 30

    def __init__(self, parent, n, panel):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, cursor="hand2",
                         width=px(120), height=px(120))
        self.n, self.panel = n, panel
        self.data, self.sel = None, None       # sel: 1 / 2 (Zustand) oder "toggle" oder None
        self.regions = []                       # (x1, y1, x2, y2, kind, arg)
        self.entry = None                       # Eingabefeld beim Aendern der Beschriftung
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self._click)
        self.bind("<Double-Button-1>", self._double)
        self.bind("<Button-3>", self._menu)

    def set(self, d, sel):
        self.data, self.sel = d, sel
        self.redraw()

    # ---- Zeichnen ----
    def _pill(self, x, y, text, fill, fg, kind, arg=None, anchor="w"):
        tw, th = U.text_size(text, FONT_SMALL)
        w, h = tw + px(18), th + px(8)
        if anchor == "e":
            x -= w
        U.rrect(self, x, y, w, h, px(6), fill)
        self.create_text(x + w / 2, y + h / 2, text=text, fill=fg, font=FONT_SMALL)
        self.regions.append((x, y, x + w, y + h, kind, arg))
        return w

    def _switch(self, x, y, states, kind):
        """Breiter Schalter '1 | 2' (rechtsbuendig an x), die aktive Zahl ist hervorgehoben."""
        cw, h = px(30), px(24)
        x -= 2 * cw
        U.rrect(self, x, y, 2 * cw, h, px(6), CARD_HI)
        for i, n in enumerate((1, 2)):
            active = states == n
            if active:
                U.rrect(self, x + i * cw + px(2), y + px(2), cw - px(4), h - px(4), px(5), ACCENT)
            self.create_text(x + i * cw + cw / 2, y + h / 2, text=str(n), fill=U.ACCENT_TXT if active else MUTED,
                             font=FONT_BOLD)
        self.regions.append((x, y, x + 2 * cw, y + h, kind, None))

    def redraw(self):
        self.delete("all")
        self.regions = []
        W, H = self.winfo_width(), self.winfo_height()
        if W < 20 or H < 20:
            return
        U.rrect(self, 0, 0, W, H, px(8), CARD_LO)
        d = self.data
        if not d:
            self.create_text(W / 2, H / 2, text="…", fill=DIM, font=FONT)
            return
        mode = d["mode"].get("string", "")
        scene = mode == "Scene"
        states = int(d["states"].get("unnormalized", 1) or 1) if scene else 1
        label = d["text"].get("string", "") or ""
        # Kopfzeile: Modus-Pille, Beschriftung, Zustaende-Pille
        y = px(6)
        self._pill(px(6), y, (mode.upper() if mode else "?") + "  ▾", CARD_HI, TEXT, "mode")
        if scene:
            self._switch(W - px(6), y, states, "states")
        ly = px(self.HEAD) + px(14)
        name = label.upper() if label else "Footswitch %d" % (self.n - 4)
        self.create_text(W / 2, ly, text=name, fill=TEXT if label else DIM, font=FONT_CARD_BIG)
        self.regions.append((px(6), px(self.HEAD), W - px(6), ly + px(12), "label", None))
        # Koerper
        y0, y1 = ly + px(14), H - px(6)
        if scene:
            slots = d["scenes"]
            n = states
            gap = px(4)
            hh = (y1 - y0 - gap * (n - 1)) / n
            for k in range(1, n + 1):
                yy = y0 + (k - 1) * (hh + gap)
                col_name = d["colour%d" % k].get("string", "")
                self._field(px(6), yy, W - px(12), hh, col_name, self.sel == k, "state", k,
                            state_name(d, k).upper(), scene_summary(slots[k - 1]))
        else:
            module = d["module"].get("string", "")
            op = d["operation"].get("string", "")
            col_name = d["colour1"].get("string", "")
            assigned = module and module != "Unassigned"
            title = self.panel.ed.block_title(module) if assigned else "not assigned"
            sub = ("Function: %s" % op) if assigned and op else "Click, then choose a block in the signal chain"
            self._field(px(6), y0, W - px(12), y1 - y0, col_name if assigned else "", self.sel == "toggle",
                        "toggle", None, title, sub)

    def _field(self, x, y, w, h, col_name, selected, kind, arg, title, sub):
        colour = COLOURS.get(col_name)
        fill = colour if colour and col_name != "Off" else CARD
        fg = U.text_on(fill) if fill != CARD else MUTED
        U.rrect(self, x, y, w, h, px(6), fill, "#ffffff" if selected else None, 2 if selected else 0)
        lines = U.wrap_words(title, max(8, int(w / px(8))), 2)
        ty = y + h / 2 - px(8) - (len(lines) - 1) * px(7)
        for l in lines:
            self.create_text(x + w / 2, ty, text=l, fill=fg, font=FONT_BOLD)
            ty += px(14)
        self.create_text(x + w / 2, ty + px(2), text=sub, fill=fg, font=FONT_TINY)
        self.regions.append((x, y, x + w, y + h, kind, arg))

    # ---- Maus ----
    def _region(self, x, y):
        for x1, y1, x2, y2, kind, arg in self.regions:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return kind, arg
        return None, None

    def _click(self, e):
        kind, arg = self._region(e.x, e.y)
        if kind and kind != "label":
            self.panel.tile_click(self.n, kind, arg)

    def _double(self, e):
        kind, _ = self._region(e.x, e.y)
        if kind == "label":
            self.edit_label()
            return "break"

    def _menu(self, e):
        self.panel.tile_menu(self, e)

    def edit_label(self):
        """Beschriftung direkt in der Kachel aendern (Enter uebernimmt, Escape bricht ab)."""
        if self.entry or not self.data:
            return
        ent = tk.Entry(self, bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT_BOLD, justify="center")
        ent.insert(0, self.data["text"].get("string", ""))
        ent.select_range(0, "end")
        ent.place(x=px(10), y=px(self.HEAD), width=self.winfo_width() - px(20), height=px(24))
        ent.focus_set()
        self.entry = ent

        def done(commit):
            if self.entry is None:
                return
            text = ent.get().strip()
            self.entry = None
            ent.destroy()
            if commit:
                self.panel.set_label(self.n, text)
        ent.bind("<Return>", lambda e: done(True))
        ent.bind("<Escape>", lambda e: done(False))
        ent.bind("<FocusOut>", lambda e: done(False))


class FootBar(U.Panel):
    """Zugeklapptes Hardware-Feld: die drei Fussschalter wie auf dem Display, rechts 'Zuweisen'."""
    HEIGHT = 58
    SWITCH = 42      # Hoehe eines Schalters (logische Pixel)
    GAP = 8
    DARK = 0.28      # Farbanteil eines nicht leuchtenden Schalters

    def __init__(self, editor, parent):
        super().__init__(parent, fill=PANEL, r=10, height=px(self.HEIGHT))
        self.ed = editor
        self.data = None          # {n: {text, colour, on}} (live.fs_display)
        self.hover = None         # Nummer des Schalters unter der Maus
        f = self.inner
        self.btn_assign = U.Btn(f, "Assign", command=editor.open_hardware, state="disabled")
        self.btn_assign.pack(side="right", padx=(px(12), px(4)))
        self.canvas = tk.Canvas(f, bg=PANEL, highlightthickness=0, cursor="hand2", width=px(300),
                                height=px(self.SWITCH))
        self.canvas.pack(side="left", fill="x", expand=True, padx=(px(4), 0), pady=px((self.HEIGHT - self.SWITCH) // 2))
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda e: self._hover(None))
        self.canvas.bind("<Button-1>", self._click)

    def set(self, data):
        self.data = data
        self.redraw()

    def _switch_at(self, x):
        W = self.canvas.winfo_width()
        w = (W - 2 * px(self.GAP)) / 3
        for i, n in enumerate(L.FS_NUMBERS):
            x0 = i * (w + px(self.GAP))
            if x0 <= x <= x0 + w:
                return n
        return None

    def _motion(self, e):
        self._hover(self._switch_at(e.x))

    def _hover(self, n):
        if n != self.hover:
            self.hover = n
            self.redraw()

    def _click(self, e):
        n = self._switch_at(e.x)
        if n is not None and self.data:
            self.ed.press_footswitch(n - 4)

    def redraw(self):
        c = self.canvas
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 20 or H < 10:
            return
        w = (W - 2 * px(self.GAP)) / 3
        for i, n in enumerate(L.FS_NUMBERS):
            x = i * (w + px(self.GAP))
            d = (self.data or {}).get(n)
            if not d:
                U.rrect(c, x, 0, w, H, px(7), CARD_LO)
                c.create_text(x + w / 2, H / 2, text="FS %d" % (n - 4), fill=DIM, font=FONT_BOLD)
                continue
            colour = COLOURS.get(d["colour"])
            lit = d["on"] and colour and d["colour"] != "Off"
            if lit:
                fill, fg = colour, U.text_on(colour)
            elif colour and d["colour"] != "Off":
                fill, fg = U.blend(colour, PANEL, self.DARK), U.blend(colour, "#ffffff", 0.35)
            else:
                fill, fg = CARD, MUTED
            outline = "#ffffff" if self.hover == n else None
            U.rrect(c, x, 0, w, H, px(7), fill, outline, 1 if outline else 0)
            # kleine LED links wie am Geraet: hell bei leuchtendem, dunkel bei abgedunkeltem Schalter
            led = px(8)
            U.circle(c, x + px(12) + led / 2, H / 2, led,
                     U.blend(colour, "#ffffff", 0.35) if lit else U.blend(colour or CARD_HI, PANEL, 0.1))
            text = (d["text"] or "").upper() or "–"
            lines = U.wrap_words(text, max(6, int((w - px(40)) / px(8))), 1)
            c.create_text(x + px(12) + led + px(8) + (w - px(28) - led) / 2, H / 2, text=lines[0], fill=fg,
                          font=FONT_CARD_BIG)


class HardwarePanel(U.Panel):
    """Feld 'Hardware' im Hauptfenster (unter dem Signalpfad)."""
    HEIGHT = 300
    WIDE = 1180   # ab dieser Breite (logische Pixel) Fussschalter und Pedale nebeneinander

    def __init__(self, editor, parent, tempo):
        super().__init__(parent, fill=PANEL, r=10, height=px(self.HEIGHT))
        self.ed = editor
        self.tempo = tempo
        self.sel = (L.FS_NUMBERS[0], 1)   # Schalter + Zustand, fuer den die Palette gilt
        self.pedal = 1
        self.tab = 0
        self.wide = None
        f = self.inner
        head = tk.Frame(f, bg=PANEL)
        head.pack(fill="x", padx=px(6), pady=(px(8), px(2)))
        tk.Label(head, text="Hardware", bg=PANEL, fg=TEXT, font=FONT_BOLD).pack(side="left", padx=(0, px(14)))
        self.tabs = U.Segmented(head, TABS, 0, on_pick=self.show_tab, padx=10)
        self.head_tempo = tk.Frame(head, bg=PANEL)   # breites Fenster: Tempo in der Kopfzeile
        U.Btn(head, "✕", command=self.close, kind="ghost", padx=6, pady=0, font=("Segoe UI", 12)).pack(side="right")
        self.lbl_info = tk.Label(head, text="", bg=PANEL, fg=DIM, font=FONT_SMALL)
        self.lbl_info.pack(side="right", padx=(0, px(10)))
        self.body = tk.Frame(f, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=px(6), pady=(px(6), px(8)))
        self.tiles = {}
        self.bind("<Configure>", self._resized, add="+")
        self.build()

    def _resized(self, e):
        """Beim Wechsel zwischen breit und schmal neu aufbauen."""
        if self.wide is not None and (e.width >= px(self.WIDE)) != self.wide:
            self.build()

    def close(self):
        self.ed.close_hardware()

    @property
    def hw(self):
        return self.ed.lrig.hw if self.ed.lrig else None

    def show_tab(self, i):
        self.tab = i
        self.tabs.set(i)
        self.build()

    def refresh(self):
        """Nach neu gelesenen Zuweisungen den aktuellen Reiter neu aufbauen (Auswahl bleibt)."""
        if not self.winfo_exists():
            return
        self.build()

    def build(self):
        for w in list(self.body.winfo_children()) + list(self.head_tempo.winfo_children()):
            w.destroy()
        self.tiles = {}
        self.lbl_info.configure(text="")
        self.tabs.pack_forget()
        self.head_tempo.pack_forget()
        width = self.winfo_width()
        self.wide = width >= px(self.WIDE) if width > 1 else False
        if self.wide:
            self.fill_tempo_inline(self.head_tempo)
            self.head_tempo.pack(side="left", padx=(px(6), 0))
            ped = tk.Frame(self.body, bg=PANEL)   # rechts so breit wie noetig, links der Rest
            ped.pack(side="right", fill="y")
            tk.Frame(self.body, bg=U.LINE, width=1).pack(side="right", fill="y", padx=px(14), pady=px(4))
            fs = tk.Frame(self.body, bg=PANEL)
            fs.pack(side="left", fill="both", expand=True)
            self.fill_fs(fs)
            self.fill_pedal(ped, compact=True)
            return
        self.tabs.pack(side="left")
        if self.tab == 0:
            self.fill_fs(self.body)
        elif self.tab == 1:
            self.fill_pedal(self.body)
        else:
            self.fill_tempo(self.body)

    # ---------------- Fussschalter ----------------
    def tile_sel(self, n):
        """Markierung einer Kachel aus dem Editor-Zustand: Zustand 1/2 (Scene) oder 'toggle'."""
        if self.ed.scene and self.ed.scene[0] == n:
            return self.ed.scene[1]
        if self.ed.assign == n:
            return "toggle"
        return None

    def fill_fs(self, body):
        hw = self.hw
        tiles = tk.Frame(body, bg=PANEL)
        tiles.pack(fill="both", expand=True)
        for n in L.FS_NUMBERS:
            t = FootswitchTile(tiles, n, self)
            t.pack(side="left", fill="both", expand=True, padx=(0, px(8) if n != L.FS_NUMBERS[-1] else 0))
            t.set(hw["fs"][n] if hw else None, self.tile_sel(n))
            self.tiles[n] = t
        bottom = tk.Frame(body, bg=PANEL)
        bottom.pack(fill="x", pady=(px(6), 0))
        cell = px(24)
        pal = tk.Canvas(bottom, width=cell * len(U.COLOUR_ORDER) + px(4), height=cell + px(4), bg=PANEL,
                        highlightthickness=0, cursor="hand2")
        pal.pack(side="left")
        n, state = self.sel
        current = hw["fs"][n]["colour%d" % state].get("string", "") if hw else ""
        for i, name in enumerate(U.COLOUR_ORDER):
            sel = name == current
            U.rrect(pal, i * cell + px(2), px(2), cell - px(2), cell - px(2), px(5), COLOURS[name],
                    "#ffffff" if sel else None, 2 if sel else 0)
        pal.bind("<Button-1>", self.pick_colour)
        what = "Footswitch %d" % (n - 4)
        if hw and state_name(hw["fs"][n], state) != "Scene":
            what += " · " + state_name(hw["fs"][n], state)
        tk.Label(bottom, text="Colour for %s" % what if hw else "Reading assignments from the device …", bg=PANEL, fg=DIM,
                 font=FONT_TINY).pack(side="left", padx=(px(10), 0))

    def tile_click(self, n, kind, arg):
        hw = self.hw
        if not hw:
            return
        d = hw["fs"][n]
        fsw = L.FSW
        if kind == "mode":
            m = U.menu(self)
            cur = d["mode"].get("string", "")
            for i, name in enumerate(d["modes"]):
                m.add_command(label=("●  " if name == cur else "○  ") + name,
                              command=lambda i=i: self.ed.hw_set("%s/ModeNew%d" % (fsw, n), "index", i))
            t = self.tiles[n]
            m.tk_popup(t.winfo_rootx() + px(6), t.winfo_rooty() + px(26))
        elif kind == "states":
            states = int(d["states"].get("unnormalized", 1) or 1)
            self.ed.hw_set("%s/SceneNumberOfStates%d" % (fsw, n), "unnormalized", 1 if states == 2 else 2)
        elif kind == "state":
            self.sel = (n, arg)
            self.ed.set_scene(None if self.ed.scene == (n, arg) else (n, arg))
        elif kind == "toggle":
            self.sel = (n, 1)
            self.ed.set_assign(None if self.ed.assign == n else n)

    def tile_menu(self, tile, e):
        hw = self.hw
        if not hw:
            return
        n = tile.n
        d = hw["fs"][n]
        fsw = L.FSW
        m = U.menu(self)
        m.add_command(label="Change label …", command=tile.edit_label)
        cur = d["mode"].get("string", "")
        for i, name in enumerate(d["modes"]):
            m.add_command(label=("●  " if name == cur else "○  ") + "Modus " + name,
                          command=lambda i=i: self.ed.hw_set("%s/ModeNew%d" % (fsw, n), "index", i))
        if cur == "Scene":
            states = int(d["states"].get("unnormalized", 1) or 1)
            m.add_command(label="One scene" if states == 2 else "Two scenes A/B (each press switches)",
                          command=lambda: self.ed.hw_set("%s/SceneNumberOfStates%d" % (fsw, n), "unnormalized",
                                                         1 if states == 2 else 2))
        m.tk_popup(e.x_root, e.y_root)

    def set_label(self, n, text):
        self.ed.hw_set("%s/UserFootSwitchText%d" % (L.FSW, n), "string", text, reload=True)

    def pick_colour(self, e):
        cell = px(24)
        i = int((e.x - px(2)) // cell)
        if 0 <= i < len(U.COLOUR_ORDER) and self.hw:
            n, state = self.sel
            colours = self.hw["fs"][n]["colours"]
            name = U.COLOUR_ORDER[i]
            if name in colours:
                self.ed.hw_set(colour_path(n, state), "index", colours.index(name), reload=True)

    # ---------------- Pedale ----------------
    def fill_pedal(self, body, compact=False):
        """Pedal-Zuweisungen; compact = Wahl von Pedal und Modus in einer Kopfzeile ueber den
        vier Zeilen (breites Fenster, rechte Spalte), sonst links daneben mit Hinweisen."""
        hw = self.hw
        if compact:
            left = tk.Frame(body, bg=PANEL)
            left.pack(fill="x", pady=(0, px(6)))
            tk.Label(left, text="PEDAL", bg=PANEL, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(0, px(6)))
        else:
            left = tk.Frame(body, bg=PANEL)
            left.pack(side="left", fill="y", padx=(0, px(16)))
            tk.Label(left, text="PEDAL", bg=PANEL, fg=MUTED, font=FONT_TINY).pack(anchor="w")
        self.seg_pedal = U.Segmented(left, ["1  (eingebaut)", "2  (extern)"], self.pedal - 1, on_pick=self.pick_pedal, padx=8)
        self.seg_pedal.pack(side="left" if compact else "top", anchor="w")
        self.mode_holder = tk.Frame(left, bg=PANEL)
        if compact:
            self.mode_holder.pack(side="left", padx=(px(14), 0))
        else:
            self.mode_holder.pack(anchor="w", pady=(px(10), 0))
        right = tk.Frame(body, bg=PANEL)
        right.pack(side="left", fill="both", expand=True)
        if not hw:
            tk.Label(right, text="Reading assignments from the device …", bg=PANEL, fg=MUTED).pack(anchor="w")
            return
        d = hw["pedal"][self.pedal]
        base = L.PEDAL % self.pedal
        classic = False
        if d["mode"]:
            modes = d["pedal_modes"]
            cur = d["mode"].get("string", "")
            tk.Label(self.mode_holder, text="MODE", bg=PANEL, fg=MUTED, font=FONT_TINY).pack(
                side="left" if compact else "top", anchor="w", padx=(0, px(6)) if compact else 0)
            U.Segmented(self.mode_holder, modes, modes.index(cur) if cur in modes else 0,
                        on_pick=lambda i: self.ed.hw_set(base + "/PedalMode", "index", i),
                        padx=8 if compact else 10).pack(side="left" if compact else "top", anchor="w")
            classic = cur == "Classic"
            if not compact:
                tk.Label(self.mode_holder, text="Classic: one assignment\nAdvanced: up to four", bg=PANEL, fg=DIM,
                         font=FONT_SMALL, justify="left").pack(anchor="w", pady=(px(4), 0))
        elif not compact:
            tk.Label(self.mode_holder, text="External pedal on the\nEXP jack, up to four\nassignments.", bg=PANEL,
                     fg=DIM, font=FONT_SMALL, justify="left").pack(anchor="w")
        for i, r in enumerate(d["rows"], start=1):
            active = not classic or i == 1
            card = tk.Frame(right, bg=CARD_LO if active else PANEL, padx=px(8), pady=px(4))
            card.pack(fill="x", pady=(0, px(4)))
            tk.Label(card, text="%d" % i, bg=card.cget("bg"), fg=MUTED if active else DIM, font=FONT_SMALL).pack(
                side="left", padx=(0, px(8)))
            if not active:
                tk.Label(card, text="(Advanced mode only)", bg=PANEL, fg=DIM, font=FONT_SMALL).pack(side="left")
                continue
            # Blocknamen wie im Editor (NAM statt Anxiety OD); die Auswahl geht ueber den Index
            shown = dict(r["module"], string=self.ed.block_title(r["module"].get("string", "")))
            self.combo(card, shown, [self.ed.block_title(x) for x in r["modules"]],
                       lambda ix, i=i: self.ed.hw_set("%s/ModuleList%d" % (base, i), "index", ix),
                       width=15, title="Block", font=FONT_SMALL).pack(side="left", padx=(0, px(6)))
            self.combo(card, r["param"], r["params"], lambda ix, i=i: self.ed.hw_set("%s/ParamList%d" % (base, i), "index", ix),
                       width=10, title="Parameter", font=FONT_SMALL).pack(side="left", padx=(0, px(6)))
            for key in ("Min", "Max"):
                tk.Label(card, text=key, bg=CARD_LO, fg=DIM, font=FONT_TINY).pack(side="left", padx=(px(4), px(3)))
                ent = U.Entry(card, width=3, justify="right", font=FONT_SMALL)
                ent.insert(0, str(int(float(r[key.lower()].get("unnormalized", 0) or 0))))
                ent.pack(side="left")
                path = "%s/%s%d" % (base, key, i)

                def commit(_=None, ent=ent, path=path):
                    try:
                        v = max(0, min(100, int(float(ent.get().replace(",", ".")))))
                    except ValueError:
                        return
                    self.ed.hw_set(path, "unnormalized", v, reload=False)
                ent.bind_entry("<Return>", commit)

    def pick_pedal(self, i):
        self.pedal = i + 1
        self.build()

    # ---------------- Reiter Tempo ----------------
    def fill_tempo_inline(self, parent):
        """Tempo und Programmnummer in einer Zeile (Kopfzeile bei breitem Fenster)."""
        modes = self.tempo.get("modes") or ["Fixed", "Current"]
        cur = self.tempo.get("mode", {}).get("string", "")
        tk.Label(parent, text="TEMPO", bg=PANEL, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(0, px(6)))
        self.seg_tempo = U.Segmented(parent, modes, modes.index(cur) if cur in modes else 0, padx=8,
                                     on_pick=lambda i: self.ed.hw_set(TEMPO_MODE, "index", i, reload=False))
        self.seg_tempo.pack(side="left")
        self.ent_bpm = U.Entry(parent, width=4, justify="right", font=FONT_SMALL)
        self.ent_bpm.insert(0, str(int(float(self.tempo.get("tempo", {}).get("unnormalized", 120) or 120))))
        self.ent_bpm.pack(side="left", padx=(px(8), px(4)))
        self.ent_bpm.bind_entry("<Return>", self.set_bpm)
        tk.Label(parent, text="BPM", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left")
        tk.Label(parent, text="MIDI PROG", bg=PANEL, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(px(18), px(6)))
        prog = self.tempo.get("prog", {}).get("string") or "–"
        tk.Label(parent, text=prog, bg=CARD_LO, fg=TEXT, font=FONT_SMALL, padx=px(8), pady=px(2)).pack(side="left")

    def fill_tempo(self, body):
        top = tk.Frame(body, bg=PANEL)
        top.pack(anchor="w", pady=(px(4), 0))
        tk.Label(top, text="TEMPO", bg=PANEL, fg=MUTED, font=FONT_TINY).grid(row=0, column=0, sticky="w")
        modes = self.tempo.get("modes") or ["Fixed", "Current"]
        cur = self.tempo.get("mode", {}).get("string", "")
        self.seg_tempo = U.Segmented(top, modes, modes.index(cur) if cur in modes else 0,
                                     on_pick=lambda i: self.ed.hw_set(TEMPO_MODE, "index", i, reload=False))
        self.seg_tempo.grid(row=1, column=0, sticky="w")
        bpm = tk.Frame(top, bg=PANEL)
        bpm.grid(row=1, column=1, sticky="w", padx=(px(12), 0))
        self.ent_bpm = U.Entry(bpm, width=5, justify="right")
        self.ent_bpm.insert(0, str(int(float(self.tempo.get("tempo", {}).get("unnormalized", 120) or 120))))
        self.ent_bpm.pack(side="left")
        self.ent_bpm.bind_entry("<Return>", self.set_bpm)
        tk.Label(bpm, text="BPM  (Enter applies)", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=(px(6), 0))
        tk.Label(top, text="MIDI PROG", bg=PANEL, fg=MUTED, font=FONT_TINY).grid(row=0, column=2, sticky="w", padx=(px(30), 0))
        prog = self.tempo.get("prog", {}).get("string") or "–"
        tk.Label(top, text=prog, bg=CARD_LO, fg=TEXT, font=FONT_SMALL, padx=px(10), pady=px(3)).grid(
            row=1, column=2, sticky="w", padx=(px(30), 0))
        tk.Label(body, text="Fixed: the rig brings its own tempo (BPM).  Current: the device's current tempo "
                                 "(tap tempo) is kept when switching rigs.\nThe program number is "
                                 "set in the rig list (right-click).",
                 bg=PANEL, fg=DIM, font=FONT_SMALL, justify="left", wraplength=px(600)).pack(anchor="w", pady=(px(14), 0))

    def set_bpm(self, _=None):
        try:
            v = max(40, min(240, int(float(self.ent_bpm.get().replace(",", ".")))))
        except ValueError:
            return
        self.ed.hw_set(TEMPO, "unnormalized", v, reload=False)

    # ---------------- Hilfen ----------------
    def row_label(self, parent, text, row):
        tk.Label(parent, text=text, bg=parent.cget("bg"), fg=TEXT, font=FONT, anchor="w").grid(
            row=row, column=0, sticky="w", padx=(0, px(10)), pady=px(3))

    def combo(self, parent, info, entries, on_pick, width=18, title="Choose", font=FONT):
        return U.Dropdown(parent, entries, info.get("string", ""), on_pick=on_pick, width=width, title=title, font=font)
