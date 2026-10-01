"""setlists.py - Setlist-Manager des Editors (Bruecke 0.4).

Eigene Ansicht an Stelle von Rig-Liste, Signalkette und Parameterfeld: links die Quelle
(All Rigs oder eine andere Setlist), in der Mitte die bearbeitete Setlist in Baenken zu
drei Rigs (so wie das Geraet sie auf die Fussschalter legt), rechts das gewaehlte Rig mit
Name, Farbe und Programmnummer.

Bedienung: Rigs aus der Quelle in die Setlist ziehen (Doppelklick = anhaengen), in der
Setlist verschieben, aus ihr heraus auf die Quelle ziehen (oder Entf) = entfernen.
Strg/Umschalt-Klick waehlt mehrere Rigs, die zusammen gezogen bzw. gefaerbt werden.

Jede Aenderung geht sofort in die Datenbank (ein kurzer Schreibauftrag, ca. 80 ms, alle
ueber den einen Worker der Sitzung, also in Reihenfolge). Das Geraet liest Listen aber nur
beim Betreten neu und die Set-Auswahl nur beim App-Start - darum merkt sich der Manager,
was betroffen ist (effects()), und der Editor frischt beim Schliessen einmal auf bzw.
startet die App neu (Editor.close_setlists).
"""
import tkinter as tk
from tkinter import ttk

import live as L
import ui as U
from ui import BG, PANEL, CARD, CARD_HI, CARD_LO, ACCENT, ACCENT_TXT, TEXT, MUTED, DIM, DANGER, COLOURS, px
from ui import FONT, FONT_SMALL, FONT_BOLD, FONT_HEAD, FONT_TINY, messagebox

MISSING = "– missing rig –"
APP = "MX5 Editor"   # Titel der Meldungen (wird im Overlay nicht angezeigt)


def rig_colour(index):
    """rigs.color (Index in RIG_COLOURS) -> Anzeigefarbe."""
    try:
        return COLOURS.get(L.RIG_COLOURS[int(index)], COLOURS["Off"])
    except (ValueError, TypeError, IndexError):
        return COLOURS["Off"]


class RigRows(tk.Canvas):
    """Zeilenliste des Managers. items = [{id, name, colour, prog, mark}]. numbered=True:
    die bearbeitete Setlist, mit Bank-Spalte links (je drei Rigs eine Bank).
    Auswahl: Klick, Strg+Klick, Umschalt+Klick; Ziehen meldet sich beim Manager."""

    DRAG_PX = 6

    def __init__(self, parent, mgr, numbered=False):
        super().__init__(parent, bg=PANEL, highlightthickness=0, width=px(120), takefocus=1)
        self.mgr, self.numbered = mgr, numbered
        self.row = px(30)
        self.gutter = px(46) if numbered else 0
        self.items = []
        self.sel = set()
        self.anchor = None
        self.hover = None
        self.drop = None          # Einfuegeposition 0..n, solange etwas ueber diese Liste gezogen wird
        self.drop_text = None     # ganze Liste als Ablage hervorheben (Text, z. B. 'entfernen')
        self.empty_text = ""
        self._press = None        # (zeile, x, y, modifiziert)
        self._dragging = False
        self.configure(yscrollincrement=self.row)
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self._down)
        self.bind("<B1-Motion>", self._motion_drag)
        self.bind("<ButtonRelease-1>", self._up)
        self.bind("<Double-Button-1>", self._double)
        self.bind("<Button-3>", self._rclick)
        self.bind("<Motion>", lambda e: self._set_hover(self.row_at(e.y)))
        self.bind("<Leave>", lambda e: self._set_hover(None))

    # ---- Geometrie ----
    def row_at(self, y):
        i = int(self.canvasy(y) // self.row)
        return i if 0 <= i < len(self.items) else None

    def insert_at(self, y_root):
        """Einfuegeposition (0..n) fuer einen Bildschirmpunkt."""
        y = self.canvasy(y_root - self.winfo_rooty())
        return max(0, min(len(self.items), int((y + self.row / 2) // self.row)))

    def contains(self, x_root, y_root):
        x, y = x_root - self.winfo_rootx(), y_root - self.winfo_rooty()
        return 0 <= x < self.winfo_width() and 0 <= y < self.winfo_height()

    def scroll_wheel(self, step):
        self.yview_scroll(step, "units")

    # ---- Maus ----
    def _down(self, e):
        self.focus_set()
        i = self.row_at(e.y)
        self._dragging = False
        if i is None:
            self._press = None
            if not e.state & 0x0005:
                self.set_selection(set())
                self.mgr.selected(self)
            return
        ctrl, shift = bool(e.state & 0x0004), bool(e.state & 0x0001)
        self._press = (i, e.x, e.y, ctrl or shift)
        if shift and self.anchor is not None:
            a, b = sorted((self.anchor, i))
            self.set_selection(set(range(a, b + 1)) | (self.sel if ctrl else set()))
        elif ctrl:
            self.set_selection(self.sel ^ {i})
            self.anchor = i
        elif i not in self.sel:   # auf eine schon gewaehlte Zeile: erst beim Loslassen einzeln waehlen (Ziehen mehrerer)
            self.set_selection({i})
            self.anchor = i
        self.mgr.selected(self)

    def _motion_drag(self, e):
        if not self._press:
            return
        i, x0, y0, _ = self._press
        if not self._dragging:
            if abs(e.x - x0) < self.DRAG_PX and abs(e.y - y0) < self.DRAG_PX:
                return
            if i not in self.sel:
                self.set_selection({i})
            self._dragging = True
            self.mgr.drag_begin(self, sorted(self.sel))
        self.mgr.drag_move(e.x_root, e.y_root)

    def _up(self, e):
        press, dragging = self._press, self._dragging
        self._press, self._dragging = None, False
        if dragging:
            self.mgr.drag_end(e.x_root, e.y_root)
            return
        if press and not press[3] and press[0] in self.sel and len(self.sel) > 1:
            self.set_selection({press[0]})
            self.anchor = press[0]
            self.mgr.selected(self)

    def _double(self, e):
        i = self.row_at(e.y)
        if i is not None:
            self.mgr.double(self, i)

    def _rclick(self, e):
        self.focus_set()
        i = self.row_at(e.y)
        if i is None:
            return
        if i not in self.sel:
            self.set_selection({i})
            self.anchor = i
            self.mgr.selected(self)
        self.mgr.menu(self, e)

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.redraw()

    # ---- Inhalt ----
    def set_items(self, items, selection=None):
        self.items = list(items)
        if selection is not None:
            self.sel = set(selection)
        self.sel = {i for i in self.sel if i < len(self.items)}
        if self.anchor is not None and self.anchor >= len(self.items):
            self.anchor = None
        self.redraw()

    def set_selection(self, sel, see=False):
        self.sel = {i for i in sel if 0 <= i < len(self.items)}
        self.redraw()
        if see and self.sel:
            self.see(min(self.sel))

    def see(self, i):
        top, h = i * self.row, self.winfo_height()
        total = max(1, len(self.items) * self.row)
        y0 = self.canvasy(0)
        if top < y0 or top + self.row > y0 + h:
            self.yview_moveto(max(0, top - h / 3) / total)

    def set_drop(self, k, text=None):
        if (k, text) != (self.drop, self.drop_text):
            self.drop, self.drop_text = k, text
            self.redraw()

    def redraw(self):
        self.delete("all")
        w = max(self.winfo_width(), 2)
        R, G = self.row, self.gutter
        n = len(self.items)
        if self.numbered:   # Baenke: abwechselnd hinterlegt, Banknummer mittig in der linken Spalte
            for b in range((n + 2) // 3):
                y0, rows = b * 3 * R, min(3, n - b * 3)
                if b % 2 == 0:
                    U.rrect(self, px(2), y0 + px(1), w - px(4), rows * R - px(2), px(8), CARD_LO)
                self.create_text(G / 2, y0 + rows * R / 2 - px(6), text=str(b + 1), fill=MUTED, font=FONT_BOLD)
                self.create_text(G / 2, y0 + rows * R / 2 + px(9), text="BANK", fill=DIM, font=FONT_TINY)
        for i, it in enumerate(self.items):
            y = i * R
            cy = y + R / 2
            fg = TEXT if it["id"] else DIM
            if i in self.sel:
                U.rrect(self, G + px(4), y + px(2), w - G - px(8), R - px(4), px(6), ACCENT)
                fg = ACCENT_TXT
            elif i == self.hover:
                U.rrect(self, G + px(4), y + px(2), w - G - px(8), R - px(4), px(6), CARD_HI)
            x = G + px(14)
            U.rrect(self, x, cy - px(6), px(12), px(12), px(3), it["colour"])
            right = w - px(12)
            if it.get("prog"):
                t = "PC %d" % it["prog"]
                tw = U.text_size(t, FONT_SMALL)[0]
                U.rrect(self, right - tw - px(12), cy - px(9), tw + px(12), px(18), px(9),
                        U.blend(ACCENT, PANEL, 0.35) if i in self.sel else CARD)
                self.create_text(right - px(6), cy, text=t, anchor="e", font=FONT_SMALL,
                                 fill=ACCENT_TXT if i in self.sel else MUTED)
                right -= tw + px(18)
            if it.get("mark"):
                self.create_text(right, cy, text="✓", anchor="e", font=FONT_BOLD,
                                 fill=ACCENT_TXT if i in self.sel else ACCENT)
                right -= px(18)
            name = it["name"]
            while name and U.text_size(name, FONT)[0] > right - x - px(24):
                name = name[:-2] + "…"
            self.create_text(x + px(22), cy, text=name, anchor="w", fill=fg, font=FONT)
        if not n and self.empty_text:
            self.create_text(w / 2, px(60), text=self.empty_text, fill=MUTED, font=FONT, justify="center",
                             width=w - px(40))
        if self.drop is not None:
            y = self.drop * R
            y = max(px(2), min(y, max(n * R, px(4)) - px(2))) if n else px(4)
            self.create_line(G + px(6), y, w - px(6), y, fill=ACCENT, width=px(3), capstyle="round")
            U.circle(self, G + px(6), y, px(9), ACCENT)
        if self.drop_text:
            h = max(self.winfo_height(), 2)
            y0 = self.canvasy(0)
            U.rrect(self, px(4), y0 + px(4), w - px(8), h - px(8), px(10), None, DANGER, px(2))
            bw = U.text_size(self.drop_text, FONT_BOLD)[0] + px(32)
            U.rrect(self, w / 2 - bw / 2, y0 + h / 2 - px(20), bw, px(40), px(8), DANGER)
            self.create_text(w / 2, y0 + h / 2, text=self.drop_text, fill=TEXT, font=FONT_BOLD)
        # mindestens so hoch wie die Flaeche, sonst laesst sich eine kurze Liste nach unten verschieben
        self.configure(scrollregion=(0, 0, w, max(n * R, self.winfo_height(), 1)))


def hint(parent, text):
    """Grauer Hinweis am unteren Rand, bricht mit der Breite um."""
    lbl = tk.Label(parent, text=text, bg=PANEL, fg=DIM, font=FONT_SMALL, anchor="w", justify="left")
    lbl.pack(side="bottom", fill="x", padx=px(4), pady=(0, px(8)))
    lbl.bind("<Configure>", lambda e: lbl.configure(wraplength=max(50, e.width - px(4))))
    return lbl


class SwatchGrid(tk.Canvas):
    """Die 14 Rig-Farben als Kaestchen (7 x 2); on_pick(index in RIG_COLOURS)."""

    COLS = 7

    def __init__(self, parent, on_pick, on_hover=None):
        self.s, self.gap = px(30), px(6)
        rows = (len(L.RIG_COLOURS) + self.COLS - 1) // self.COLS
        super().__init__(parent, bg=PANEL, highlightthickness=0, cursor="hand2",
                         width=self.COLS * (self.s + self.gap), height=rows * (self.s + self.gap))
        self.on_pick, self.on_hover = on_pick, on_hover
        self.current, self.hover, self.enabled = None, None, False
        self.bind("<Button-1>", lambda e: self._pick(self._at(e.x, e.y)))
        self.bind("<Motion>", lambda e: self._set_hover(self._at(e.x, e.y)))
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.redraw()

    def _at(self, x, y):
        c, r = int(x // (self.s + self.gap)), int(y // (self.s + self.gap))
        i = r * self.COLS + c
        return i if 0 <= c < self.COLS and 0 <= i < len(L.RIG_COLOURS) else None

    def _pick(self, i):
        if i is not None and self.enabled:
            self.on_pick(i)

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.redraw()
            if self.on_hover:
                self.on_hover(i if self.enabled else None)

    def set(self, current, enabled=True):
        self.current, self.enabled = current, enabled
        self.redraw()

    def redraw(self):
        self.delete("all")
        for i, name in enumerate(L.RIG_COLOURS):
            r, c = divmod(i, self.COLS)
            x, y = c * (self.s + self.gap) + px(2), r * (self.s + self.gap) + px(2)
            col = COLOURS.get(name, COLOURS["Off"]) if self.enabled else U.blend(COLOURS.get(name, COLOURS["Off"]), PANEL, 0.7)
            ring = None
            if self.enabled and i == self.current:
                ring = TEXT
            elif self.enabled and i == self.hover:
                ring = MUTED
            U.rrect(self, x, y, self.s - px(4), self.s - px(4), px(6), col, ring, px(2) if ring else 0)
            if name == "Off":   # "keine Farbe": diagonaler Strich
                self.create_line(x + px(7), y + self.s - px(11), x + self.s - px(11), y + px(7),
                                 fill=MUTED if self.enabled else DIM, width=px(2))


class SetlistManager(tk.Frame):
    """Setlist-Manager (siehe Modulbeschreibung). ed = Editor (Sitzung, Statuszeile, Dialoge)."""

    def __init__(self, ed, parent):
        super().__init__(parent, bg=BG)
        self.ed = ed
        self.rows = {}          # rig_id -> {id, name, color, prog_num}
        self.all_ids = []       # All Rigs in Geraete-Reihenfolge
        self.sets = []          # [(id, name)] nach Name
        self.members = {}       # setlist_id -> [rig_id oder None]
        self.target = None      # bearbeitete Setlist (id)
        self.source = None      # Quelle: None = All Rigs, sonst setlist_id
        self.src_view = []      # sichtbare Quellzeilen -> rig_id
        self.focus_list = None  # Liste, deren Auswahl das Detailfeld zeigt
        self.undo_stack = []    # [(setlist_id, [rig_ids])]
        self.pending = 0        # laufende Schreibauftraege
        self.loaded = False
        self._drag = None       # (Quellliste, [Indizes], [rig_ids])
        self._ghost = None
        self._scroll_job = None
        self._pointer = (0, 0)
        # was beim Schliessen am Geraet aufzufrischen ist
        self.fx_lists, self.fx_rows = set(), set()
        self.fx_renamed, self.fx_deleted, self.fx_created = {}, set(), set()
        self._build()

    # ================= Aufbau =================
    def _build(self):
        # Quelle (links)
        lp = U.Panel(self, width=px(330))
        lp.pack(side="left", fill="y")
        lp.pack_propagate(False)
        left = lp.inner
        head = tk.Frame(left, bg=PANEL)
        head.pack(fill="x", padx=px(4), pady=(px(12), px(4)))
        tk.Label(head, text="SOURCE", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left")
        self.lbl_src_count = tk.Label(head, text="", bg=PANEL, fg=MUTED, font=FONT_SMALL)
        self.lbl_src_count.pack(side="right")
        self.dd_source = U.Dropdown(left, [], L.ALL_RIGS, on_pick=self.pick_source, width=24, title="Source",
                                    font=FONT_BOLD)
        self.dd_source.pack(fill="x", padx=px(4), pady=(0, px(8)))
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.fill_source())
        self.search = U.Entry(left, textvariable=self.filter, placeholder="Search …")
        self.search.pack(fill="x", padx=px(4), pady=(0, px(8)))
        hint(left, "Drag into the setlist · double-click or Enter = append · Ctrl/Shift+click selects several")
        sf = tk.Frame(left, bg=PANEL)
        sf.pack(fill="both", expand=True, pady=(0, px(6)))
        self.src = RigRows(sf, self)
        sb = ttk.Scrollbar(sf, command=self.src.yview)
        self.src.configure(yscrollcommand=sb.set)
        self.src.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Detailfeld (rechts)
        rp = U.Panel(self, width=px(340))
        rp.pack(side="right", fill="y", padx=(px(8), 0))
        rp.pack_propagate(False)
        self._build_details(rp.inner)

        # bearbeitete Setlist (Mitte)
        cp = U.Panel(self)
        cp.pack(side="left", fill="both", expand=True, padx=(px(8), 0))
        mid = cp.inner
        top = tk.Frame(mid, bg=PANEL)
        top.pack(fill="x", padx=px(4), pady=(px(12), px(4)))
        tk.Label(top, text="SETLIST", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left")
        self.lbl_saving = tk.Label(top, text="", bg=PANEL, fg=MUTED, font=FONT_SMALL)
        self.lbl_saving.pack(side="right")
        bar = tk.Frame(mid, bg=PANEL)
        bar.pack(fill="x", padx=px(4), pady=(0, px(8)))
        U.Btn(bar, "Done", command=self.ed.close_setlists, kind="primary").pack(side="right")
        U.Btn(bar, "⋯", command=self.setlist_menu, kind="ghost", padx=8,
              font=("Segoe UI", 13, "bold")).pack(side="right", padx=(0, px(4)))
        self.btn_undo = U.Btn(bar, "Undo", command=self.undo, kind="ghost", state="disabled")
        self.btn_undo.pack(side="right", padx=(0, px(2)))
        U.Btn(bar, "New …", command=self.new_setlist).pack(side="right", padx=(0, px(6)))
        self.dd_target = U.Dropdown(bar, [], "", on_pick=self.pick_target, width=26, title="Setlist", font=FONT_HEAD)
        self.dd_target.pack(side="left", fill="x", expand=True, padx=(0, px(10)))
        self.lbl_count = tk.Label(mid, text="", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w")
        self.lbl_count.pack(fill="x", padx=px(4), pady=(0, px(6)))
        hint(mid, "Drag to reorder · drag back onto the source list or press Del to remove · Ctrl+Z = undo")
        tf = tk.Frame(mid, bg=PANEL)
        tf.pack(fill="both", expand=True, pady=(0, px(6)))
        self.tgt = RigRows(tf, self, numbered=True)
        tsb = ttk.Scrollbar(tf, command=self.tgt.yview)
        self.tgt.configure(yscrollcommand=tsb.set)
        self.tgt.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.tgt.empty_text = "Reading setlists from the device …"
        for w in (self.src, self.tgt):
            w.bind("<Delete>", lambda e: self.remove_selected())
            w.bind("<BackSpace>", lambda e: self.remove_selected())
            w.bind("<Control-z>", lambda e: self.undo())
            w.bind("<Control-a>", lambda e, w=w: (w.set_selection(set(range(len(w.items)))), self.selected(w)))
            w.bind("<Return>", lambda e, w=w: self.append_selected() if w is self.src else None)
            w.bind("<Up>", lambda e, w=w: self.step_selection(w, -1, e.state & 0x0004))
            w.bind("<Down>", lambda e, w=w: self.step_selection(w, 1, e.state & 0x0004))

    def _build_details(self, p):
        tk.Label(p, text="RIG", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x", padx=px(4),
                                                                                      pady=(px(12), px(4)))
        self.lbl_rig = tk.Label(p, text="No rig selected", bg=PANEL, fg=TEXT, font=FONT_HEAD, anchor="w",
                                wraplength=px(300), justify="left")
        self.lbl_rig.pack(fill="x", padx=px(4), pady=(0, px(12)))
        self.detail_body = tk.Frame(p, bg=PANEL)
        self.detail_body.pack(fill="both", expand=True, padx=px(4))
        b = self.detail_body

        tk.Label(b, text="Name", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x")
        self.name_var = tk.StringVar()
        self.ent_name = U.Entry(b, textvariable=self.name_var)
        self.ent_name.pack(fill="x", pady=(px(2), px(2)))
        self.ent_name.bind_entry("<Return>", lambda e: self.apply_name())
        self.ent_name.bind_entry("<Escape>", lambda e: self.show_details())
        tk.Label(b, text="Enter renames the rig (ASCII, shown in upper case).", bg=PANEL, fg=DIM,
                 font=FONT_SMALL, anchor="w").pack(fill="x", pady=(0, px(14)))

        crow = tk.Frame(b, bg=PANEL)
        crow.pack(fill="x")
        tk.Label(crow, text="Colour", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left")
        self.lbl_colour = tk.Label(crow, text="", bg=PANEL, fg=TEXT, font=FONT_SMALL)
        self.lbl_colour.pack(side="right")
        self.swatches = SwatchGrid(b, self.apply_colour, on_hover=self._colour_hover)
        self.swatches.pack(anchor="w", pady=(px(4), px(14)))

        tk.Label(b, text="Program number (MIDI PC)", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x")
        prow = tk.Frame(b, bg=PANEL)
        prow.pack(fill="x", pady=(px(2), px(2)))
        self.prog_var = tk.StringVar()
        self.ent_prog = U.Entry(prow, textvariable=self.prog_var, width=6, justify="center")
        self.ent_prog.pack(side="left")
        self.ent_prog.bind_entry("<Return>", lambda e: self.apply_prog())
        self.ent_prog.bind_entry("<Escape>", lambda e: self.show_details())
        self.btn_prog = U.Btn(prow, "Set", command=self.apply_prog)
        self.btn_prog.pack(side="left", padx=(px(6), 0))
        self.btn_prog_clear = U.Btn(prow, "None", command=lambda: self.apply_prog(clear=True), kind="ghost")
        self.btn_prog_clear.pack(side="left", padx=(px(2), 0))
        self.lbl_prog = tk.Label(b, text="", bg=PANEL, fg=DIM, font=FONT_SMALL, anchor="w", justify="left",
                                 wraplength=px(300))
        self.lbl_prog.pack(fill="x", pady=(0, px(14)))

        tk.Label(b, text="In setlists", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x")
        self.lbl_in = tk.Label(b, text="", bg=PANEL, fg=TEXT, font=FONT_SMALL, anchor="w", justify="left",
                               wraplength=px(300))
        self.lbl_in.pack(fill="x", pady=(px(2), px(14)))
        self.btn_action = U.Btn(b, "", command=self.detail_action)
        self.btn_action.pack(anchor="w")

    # ================= Daten =================
    def load(self, keep=True):
        """Rigs, Setlists und Belegung aus der Datenbank lesen (ca. 0,5 s)."""
        def read(br):
            return {"rigs": L.db_rigs(br), "sets": L.db_setlists(br), "members": L.db_setlist_members(br)}

        def done(res):
            if not self.winfo_exists():
                return
            if isinstance(res, dict) and res.get("ok") is False:
                self.tgt.empty_text = "Could not read the setlists: %s" % res.get("err")
                self.tgt.redraw()
                return
            self.rows = {r["id"]: r for r in res["rigs"]}
            self.all_ids = [r["id"] for r in res["rigs"]]
            self.sets = list(res["sets"])
            self.members = {sid: list(res["members"].get(sid, [])) for sid, _ in self.sets}
            self.loaded = True
            ids = [s for s, _ in self.sets]
            if not (keep and self.target in ids):
                lr = self.ed.lrig
                active = (lr.setlist_ids or {}).get(lr.setlist) if lr else None
                self.target = active if active in ids else (ids[0] if ids else None)
            if self.source is not None and self.source not in ids:
                self.source = None
            self.refresh_all()
            self.ed.status.set("Setlist manager: %d setlists, %d rigs." % (len(self.sets), len(self.all_ids)))
        self.ed.session.run(read, done)

    def set_name(self, sid):
        return next((n for s, n in self.sets if s == sid), "?")

    def item(self, rid, mark=False):
        r = self.rows.get(rid)
        if r is None:
            return {"id": None, "name": MISSING, "colour": COLOURS["Off"], "prog": None, "mark": False}
        pn = r.get("prog_num")
        prog = int(pn) + 1 if pn is not None and int(pn) >= 0 else None
        return {"id": rid, "name": L.display_name(r["name"]), "colour": rig_colour(r.get("color")), "prog": prog,
                "mark": mark}

    def target_ids(self):
        return self.members.get(self.target, []) if self.target else []

    # ================= Anzeige =================
    def refresh_all(self):
        names = [n for _, n in self.sets]
        self.dd_target.set_values(names)
        self.dd_target.set_text(self.set_name(self.target) if self.target else "No setlist yet")
        self.dd_source.set_values([L.ALL_RIGS] + [n for s, n in self.sets if s != self.target])
        self.dd_source.set_text(L.ALL_RIGS if self.source is None else self.set_name(self.source))
        self.tgt.empty_text = ("Drag rigs from the source list here." if self.target else
                               "There is no setlist on the device yet.\nCreate one with “New …”.")
        self.fill_target()
        self.fill_source()
        self.show_details()

    def fill_target(self, selection=None):
        ids = self.target_ids()
        self.tgt.set_items([self.item(r) for r in ids], selection)
        n = len(ids)
        self.lbl_count.configure(text="%d rig%s · %d bank%s" % (n, "" if n == 1 else "s", (n + 2) // 3,
                                                               "" if (n + 2) // 3 == 1 else "s") if self.target else "")
        self.btn_undo.configure(state="normal" if any(s == self.target for s, _ in self.undo_stack) else "disabled")

    def fill_source(self, keep_ids=None):
        if keep_ids is None:
            keep_ids = {self.src_view[i] for i in self.src.sel if i < len(self.src_view)}
        ids = self.all_ids if self.source is None else self.members.get(self.source, [])
        q = self.filter.get().strip().lower()
        inside = set(self.target_ids())
        self.src_view = [r for r in ids if r is not None and r in self.rows
                         and q in L.display_name(self.rows[r]["name"]).lower()]
        sel = {i for i, r in enumerate(self.src_view) if r in keep_ids}
        self.src.set_items([self.item(r, r in inside) for r in self.src_view], sel)
        self.lbl_src_count.configure(text="%d rigs" % len(self.src_view))

    def redraw_rows(self):
        """Nach Aenderungen an Namen/Farben/Nummern beide Listen neu aufbauen, Auswahl bleibt."""
        self.fill_target(self.tgt.sel)
        self.fill_source()
        self.show_details()

    def pick_target(self, i):
        sid = self.sets[i][0]
        if sid == self.target:
            return
        self.target = sid
        if self.source == sid:
            self.source = None
        self.tgt.set_selection(set())
        self.tgt.yview_moveto(0)
        self.focus_list = None
        self.refresh_all()

    def pick_source(self, i):
        name = self.dd_source.values[i]
        self.source = None if name == L.ALL_RIGS else next((s for s, n in self.sets if n == name), None)
        self.src.set_selection(set())
        self.src.yview_moveto(0)
        self.fill_source(set())
        if self.focus_list is self.src:
            self.focus_list = None
        self.show_details()

    def _saving(self, delta):
        self.pending += delta
        self.lbl_saving.configure(text="Saving …" if self.pending else "All changes saved",
                                  fg=ACCENT if self.pending else MUTED)

    # ================= Auswahl und Detailfeld =================
    def selected(self, lst):
        self.focus_list = lst
        other = self.tgt if lst is self.src else self.src
        if lst.sel and other.sel:
            other.set_selection(set())
        self.show_details()

    def sel_ids(self, lst=None):
        lst = lst or self.focus_list
        if lst is None:
            return []
        view = self.src_view if lst is self.src else self.target_ids()
        out = []
        for i in sorted(lst.sel):
            if i < len(view) and view[i] is not None and view[i] not in out:
                out.append(view[i])
        return out

    def step_selection(self, lst, d, extend=False):
        if not lst.items:
            return
        cur = max(lst.sel) if d > 0 and lst.sel else (min(lst.sel) if lst.sel else -1)
        i = max(0, min(len(lst.items) - 1, cur + d))
        lst.set_selection((lst.sel | {i}) if extend else {i}, see=True)
        lst.anchor = i
        self.selected(lst)

    def show_details(self):
        ids = [r for r in self.sel_ids() if r in self.rows]
        one = self.rows[ids[0]] if len(ids) == 1 else None
        state = "normal" if one else "disabled"
        if not ids:
            self.lbl_rig.configure(text="No rig selected" if self.loaded else "")
        elif one:
            self.lbl_rig.configure(text=L.display_name(one["name"]))
        else:
            self.lbl_rig.configure(text="%d rigs selected" % len(ids))
        self.name_var.set(one["name"] if one else "")
        self.ent_name.set_enabled(bool(one))
        cols = {int(self.rows[r].get("color") or 0) for r in ids}
        self.swatches.set(cols.pop() if len(cols) == 1 else None, enabled=bool(ids))
        self._colour_hover(None)
        pn = one.get("prog_num") if one else None
        self.prog_var.set(str(int(pn) + 1) if pn is not None and int(pn) >= 0 else "")
        self.ent_prog.set_enabled(bool(one))
        self.btn_prog.configure(state=state)
        self.btn_prog_clear.configure(state=state)
        self.lbl_prog.configure(text="If another rig has the number, it loses it." if one else
                                ("Program numbers can be set per rig or with ⋯ › Number by position."
                                 if ids else ""))
        if ids:
            names = []
            for sid, n in self.sets:
                c = sum(1 for r in self.members.get(sid, []) if r in ids)
                if c:
                    names.append(n if len(ids) == 1 and c == 1 else "%s (%d×)" % (n, c))
            self.lbl_in.configure(text=", ".join(names) or "none")
        else:
            self.lbl_in.configure(text="")
        if self.focus_list is self.tgt and ids:
            self.btn_action.configure(text="Remove from setlist", state="normal")
        elif ids and self.target:
            self.btn_action.configure(text="Append to “%s”" % self.set_name(self.target), state="normal")
        else:
            self.btn_action.configure(text="Append to setlist", state="disabled")

    def _colour_hover(self, i):
        if i is not None:
            self.lbl_colour.configure(text=L.RIG_COLOURS[i], fg=TEXT)
            return
        cur = self.swatches.current
        self.lbl_colour.configure(text=L.RIG_COLOURS[cur] if cur is not None and self.swatches.enabled else "",
                                  fg=MUTED)

    def detail_action(self):
        if self.focus_list is self.tgt:
            self.remove_selected()
        else:
            self.append_selected()

    # ================= Schreiben =================
    def write(self, fn, text, done=None):
        """fn(br) im Worker der Sitzung; bei Fehler Meldung und alles neu lesen."""
        if not self.ed.session:
            return
        self._saving(+1)
        self.ed.status.set(text)

        def cb(res):
            failed = isinstance(res, dict) and res.get("ok") is False
            if not self.winfo_exists():   # Manager schon geschlossen
                if failed:
                    self.ed.status.set("%s failed: %s" % (text.rstrip(" …."), res.get("err")))
                return
            self._saving(-1)
            if failed:
                messagebox.showwarning(APP, "%s\n\n%s\n\nThe lists are read again from the device."
                                       % (text.rstrip(" …."), res.get("err")))
                self.load()
                return
            if done:
                done(res)
            elif not self.pending:
                self.ed.status.set("Saved.")
        self.ed.session.run(fn, cb)

    def set_order(self, ids, text, selection=None):
        """Neue Reihenfolge der bearbeiteten Setlist: sofort anzeigen und schreiben."""
        sid = self.target
        old = list(self.members.get(sid, []))
        if ids == old:
            return
        self.undo_stack.append((sid, old))
        del self.undo_stack[:-50]
        self.members[sid] = list(ids)
        self.fx_lists.add(sid)
        self.fill_target(selection)
        self.fill_source()
        self.show_details()
        new = list(ids)
        self.write(lambda br: L.setlist_set_order(br, sid, new), text)

    def undo(self):
        for k in range(len(self.undo_stack) - 1, -1, -1):
            sid, ids = self.undo_stack[k]
            if sid == self.target:
                del self.undo_stack[k]
                self.members[sid] = list(ids)
                self.fx_lists.add(sid)
                self.tgt.set_selection(set())
                self.refresh_all()
                self.write(lambda br: L.setlist_set_order(br, sid, list(ids)), "Undoing the last change …")
                return

    def insert_ids(self, rig_ids, pos=None):
        if not self.target:
            messagebox.showinfo(APP, "Create a setlist first (“New …”).")
            return
        ids = list(self.target_ids())
        pos = len(ids) if pos is None else pos
        dup = [r for r in rig_ids if r in ids]
        new = ids[:pos] + list(rig_ids) + ids[pos:]
        n = len(rig_ids)
        what = "“%s”" % L.display_name(self.rows[rig_ids[0]]["name"]) if n == 1 else "%d rigs" % n
        self.set_order(new, "Adding %s to “%s” …" % (what, self.set_name(self.target)),
                       selection=set(range(pos, pos + n)))
        self.tgt.see(pos + n - 1)
        self.focus_list = self.tgt
        self.src.set_selection(set())
        self.show_details()
        if dup:
            self.ed.status.set("Note: %s now in the setlist more than once (the device allows that)."
                               % ("“%s” is" % L.display_name(self.rows[dup[0]]["name"]) if len(dup) == 1
                                  else "%d rigs are" % len(dup)))

    def append_selected(self):
        ids = self.sel_ids(self.src)
        if ids:
            self.insert_ids(ids)

    def move_rows(self, indices, k):
        ids = list(self.target_ids())
        moving = [ids[i] for i in indices]
        rest = [r for j, r in enumerate(ids) if j not in set(indices)]
        k -= sum(1 for i in indices if i < k)
        new = rest[:k] + moving + rest[k:]
        n = len(moving)
        what = "“%s”" % self.tgt.items[indices[0]]["name"] if n == 1 else "%d rigs" % n
        self.set_order(new, "Moving %s to position %d …" % (what, k + 1), selection=set(range(k, k + n)))

    def remove_rows(self, indices):
        if not indices or not self.target:
            return
        ids = [r for j, r in enumerate(self.target_ids()) if j not in set(indices)]
        n = len(indices)
        what = "“%s”" % self.tgt.items[indices[0]]["name"] if n == 1 else "%d rigs" % n
        self.set_order(ids, "Removing %s from “%s” …" % (what, self.set_name(self.target)), selection=set())
        self.focus_list = None
        self.show_details()

    def remove_selected(self):
        if self.focus_list is self.tgt:
            self.remove_rows(sorted(self.tgt.sel))

    def double(self, lst, i):
        if lst is self.src:
            lst.set_selection({i})
            self.append_selected()

    # ---- Eigenschaften der Rigs (gelten ueberall, nicht nur in dieser Setlist) ----
    def apply_colour(self, c):
        ids = [r for r in self.sel_ids() if r in self.rows]
        ids = [r for r in ids if int(self.rows[r].get("color") or 0) != c]
        if not ids:
            return
        for r in ids:
            self.rows[r]["color"] = c
        self.fx_rows.update(ids)
        self.redraw_rows()
        what = "“%s”" % L.display_name(self.rows[ids[0]]["name"]) if len(ids) == 1 else "%d rigs" % len(ids)

        def fn(br):
            for r in ids:
                L.set_rig_color(br, r, c)
        self.write(fn, "Colour of %s: %s …" % (what, L.RIG_COLOURS[c]))

    def apply_name(self):
        ids = self.sel_ids()
        if len(ids) != 1 or ids[0] not in self.rows:
            return
        rid = ids[0]
        try:
            name = L.check_rig_name(self.name_var.get())
        except L.LiveError as e:
            messagebox.showwarning(APP, str(e))
            return
        if name == self.rows[rid]["name"]:
            return
        if any(r["name"].lower() == name.lower() for i, r in self.rows.items() if i != rid):
            messagebox.showwarning(APP, "There is already a rig called “%s”." % name)
            return
        self.rows[rid]["name"] = name
        # All Rigs sortiert nach Name wie das Geraet (Namensende hinter jedem Zeichen)
        self.all_ids.sort(key=lambda r: self.rows[r]["name"] + "\x7f")
        self.fx_rows.add(rid)
        self.redraw_rows()
        self.write(lambda br: L.rename_rig(br, rid, name), "Renaming to “%s” …" % name)

    def apply_prog(self, clear=False):
        ids = self.sel_ids()
        if len(ids) != 1 or ids[0] not in self.rows:
            return
        rid = ids[0]
        txt = "" if clear else self.prog_var.get().strip()
        if txt and (not txt.isdigit() or not 1 <= int(txt) <= L.MAX_PROG):
            messagebox.showwarning(APP, "Please enter a number from 1 to %d." % L.MAX_PROG)
            return
        prog = int(txt) if txt else None
        pn = -1 if prog is None else prog - 1
        if int(self.rows[rid].get("prog_num") if self.rows[rid].get("prog_num") is not None else -1) == pn:
            self.show_details()
            return
        owner = next((i for i, r in self.rows.items() if i != rid and pn >= 0 and r.get("prog_num") == pn), None)
        if owner and not messagebox.askyesno(APP, "Program number %d belongs to “%s”.\nMove it to “%s”?"
                                             % (prog, L.display_name(self.rows[owner]["name"]),
                                                L.display_name(self.rows[rid]["name"]))):
            self.show_details()
            return
        if owner:
            self.rows[owner]["prog_num"] = -1
            self.fx_rows.add(owner)
        self.rows[rid]["prog_num"] = pn
        self.fx_rows.add(rid)
        self.redraw_rows()
        self.write(lambda br: L.set_rig_prognum(br, rid, prog),
                   "Program number of “%s”: %s …" % (L.display_name(self.rows[rid]["name"]), prog or "none"))

    def number_by_position(self):
        ids = []
        for r in self.target_ids():
            if r is not None and r in self.rows and r not in ids:
                ids.append(r)
        if not ids:
            return
        txt = self.ed.ask_text("Number by position", "First program number for “%s”:" % self.set_name(self.target),
                               "1", "The rigs get consecutive numbers in setlist order (%d rigs). Rigs outside "
                                    "the setlist that already have one of these numbers lose it." % len(ids))
        if txt is None:
            return
        txt = txt.strip()
        if not txt.isdigit() or not 1 <= int(txt) or int(txt) + len(ids) - 1 > L.MAX_PROG:
            messagebox.showwarning(APP, "The numbers must stay within 1 to %d." % L.MAX_PROG)
            return
        start = int(txt)
        pairs = [(r, start + n) for n, r in enumerate(ids)]
        wanted = {p - 1 for _, p in pairs}
        losers = [i for i, r in self.rows.items() if i not in ids and r.get("prog_num") in wanted]
        if losers and not messagebox.askyesno(
                APP, "%d other rig%s lose%s %s program number:\n%s\n\nContinue?"
                % (len(losers), "" if len(losers) == 1 else "s", "s" if len(losers) == 1 else "",
                   "its" if len(losers) == 1 else "their",
                   ", ".join(L.display_name(self.rows[i]["name"]) for i in losers[:8]) + (" …" if len(losers) > 8 else ""))):
            return
        for i in losers:
            self.rows[i]["prog_num"] = -1
        for r, p in pairs:
            self.rows[r]["prog_num"] = p - 1
        self.fx_rows.update(losers)
        self.fx_rows.update(ids)
        self.redraw_rows()
        self.write(lambda br: L.set_rig_prognums(br, pairs),
                   "Numbering “%s” from %d …" % (self.set_name(self.target), start))

    def sort_by_name(self):
        ids = list(self.target_ids())
        new = sorted(ids, key=lambda r: (self.rows[r]["name"] + "\x7f") if r in self.rows else "￿")
        self.set_order(new, "Sorting “%s” by name …" % self.set_name(self.target))

    # ---- Setlists (Anlegen/Umbenennen/Loeschen braucht beim Schliessen einen App-Neustart) ----
    def _check_setlist_name(self, text, except_id=None):
        try:
            name = L.check_rig_name(text)
        except L.LiveError as e:
            messagebox.showwarning(APP, str(e))
            return None
        if any(n.lower() == name.lower() for s, n in self.sets if s != except_id):
            messagebox.showwarning(APP, "There is already a setlist called “%s”." % name)
            return None
        return name

    def new_setlist(self):
        if not self.loaded:
            return
        text = self.ed.ask_text("New setlist", "Name of the new setlist:", "",
                                "The device shows new setlists after its app restarts – the editor does that "
                                "once when you close the setlist manager.")
        if not text:
            return
        name = self._check_setlist_name(text)
        if not name:
            return

        def done(sid):
            self.fx_created.add(sid)
            self.sets.append((sid, name))
            self.sets.sort(key=lambda s: s[1].lower())
            self.members[sid] = []
            self.target = sid
            self.tgt.set_selection(set())
            self.focus_list = None
            self.refresh_all()
            self.ed.status.set("Setlist “%s” created – drag rigs into it." % name)
        self.write(lambda br: L.create_setlist(br, name), "Creating setlist “%s” …" % name, done)

    def rename_setlist(self):
        sid = self.target
        if not sid:
            return
        text = self.ed.ask_text("Rename setlist", "New name for “%s”:" % self.set_name(sid), self.set_name(sid),
                                "The device app restarts once when you close the setlist manager.")
        if not text:
            return
        name = self._check_setlist_name(text, sid)
        if not name or name == self.set_name(sid):
            return
        self.sets = sorted([(s, name if s == sid else n) for s, n in self.sets], key=lambda s: s[1].lower())
        if sid not in self.fx_created:   # neu angelegte stehen ohnehin mit dem neuen Namen in der Datenbank
            self.fx_renamed[sid] = name
        self.refresh_all()
        self.write(lambda br: L.rename_setlist(br, sid, name), "Renaming setlist to “%s” …" % name)

    def delete_setlist(self):
        sid = self.target
        if not sid:
            return
        name = self.set_name(sid)
        if not messagebox.askyesno(APP, "Delete setlist “%s” from the device?\nThe rigs are kept.\n\n"
                                                "The device app restarts once when you close the setlist manager."
                                                % name):
            return
        self.sets = [(s, n) for s, n in self.sets if s != sid]
        self.members.pop(sid, None)
        self.undo_stack = [u for u in self.undo_stack if u[0] != sid]
        if sid in self.fx_created:   # in dieser Sitzung angelegt und wieder geloescht: kein Neustart noetig
            self.fx_created.discard(sid)
        else:
            self.fx_deleted.add(sid)
        self.fx_renamed.pop(sid, None)
        self.fx_lists.discard(sid)
        if self.source == sid:
            self.source = None
        self.target = self.sets[0][0] if self.sets else None
        self.tgt.set_selection(set())
        self.focus_list = None
        self.refresh_all()
        self.write(lambda br: L.delete_setlist(br, sid), "Deleting setlist “%s” …" % name)

    def setlist_menu(self):
        m = U.menu(self)
        on = "normal" if self.target else "disabled"
        m.add_command(label="New setlist …", command=self.new_setlist)
        m.add_command(label="Rename setlist …", command=self.rename_setlist, state=on)
        m.add_command(label="Delete setlist …", command=self.delete_setlist, state=on)
        m.add_separator()
        m.add_command(label="Number by position …", command=self.number_by_position, state=on)
        m.add_command(label="Sort by name", command=self.sort_by_name, state=on)
        m.add_separator()
        m.add_command(label="Read again from the device", command=self.load)
        m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def menu(self, lst, e):
        ids = [r for r in self.sel_ids(lst) if r in self.rows]
        m = U.menu(self)
        if lst is self.src:
            m.add_command(label="Append to “%s”" % self.set_name(self.target) if self.target else "Append to setlist",
                          command=self.append_selected, state="normal" if self.target and ids else "disabled")
        else:
            sel = sorted(lst.sel)
            m.add_command(label="Move to top", command=lambda: self.move_rows(sel, 0))
            m.add_command(label="Move to bottom", command=lambda: self.move_rows(sel, len(lst.items)))
            m.add_command(label="Remove from setlist", command=self.remove_selected)
        if ids:
            m.add_separator()
            cm = U.menu(self)
            for ci, cname in enumerate(L.RIG_COLOURS):
                cm.add_command(label=cname, command=lambda c=ci: self.apply_colour(c),
                               swatch=COLOURS.get(cname, COLOURS["Off"]))
            m.add_cascade(label="Colour", menu=cm)
            if len(ids) == 1:
                m.add_command(label="Rename …", command=self.focus_name)
                m.add_command(label="Program number …", command=self.focus_prog)
        m.tk_popup(e.x_root, e.y_root)

    def focus_name(self):
        self.ent_name.focus_entry()
        self.ent_name.select_all()

    def focus_prog(self):
        self.ent_prog.focus_entry()
        self.ent_prog.select_all()

    # ================= Ziehen und Ablegen =================
    def drag_begin(self, lst, indices):
        view = self.src_view if lst is self.src else self.target_ids()
        ids = [view[i] for i in indices if i < len(view)]
        if lst is self.src:
            ids = [r for r in ids if r is not None]
        if not ids:
            return
        self._drag = (lst, list(indices), ids)
        g = tk.Toplevel(self)
        g.overrideredirect(True)
        try:
            g.attributes("-topmost", True)
            g.attributes("-alpha", 0.92)
        except tk.TclError:
            pass
        first = lst.items[indices[0]]
        text = first["name"] if len(ids) == 1 else "%s  + %d more" % (first["name"], len(ids) - 1)
        f = tk.Frame(g, bg=ACCENT, padx=px(10), pady=px(5))
        f.pack()
        tk.Label(f, text="■", bg=ACCENT, fg=first["colour"], font=FONT).pack(side="left", padx=(0, px(6)))
        tk.Label(f, text=text, bg=ACCENT, fg=ACCENT_TXT, font=FONT_BOLD).pack(side="left")
        self._ghost = g
        lst.configure(cursor="fleur")

    def _over(self, xr, yr):
        if self.tgt.contains(xr, yr) and self.target:
            return "target"
        if self.src.contains(xr, yr) or self._in(self.src.master.master, xr, yr):
            return "source"
        return None

    @staticmethod
    def _in(w, xr, yr):
        x, y = xr - w.winfo_rootx(), yr - w.winfo_rooty()
        return 0 <= x < w.winfo_width() and 0 <= y < w.winfo_height()

    def drag_move(self, xr, yr):
        if not self._drag:
            return
        self._pointer = (xr, yr)
        if self._ghost:
            self._ghost.geometry("+%d+%d" % (xr + px(14), yr + px(8)))
        where = self._over(xr, yr)
        src = self._drag[0]
        self.tgt.set_drop(self.tgt.insert_at(yr) if where == "target" else None)
        self.src.set_drop(None, "Release to remove from the setlist"
                          if where == "source" and src is self.tgt else None)
        if where == "target" and self._scroll_job is None:
            self._autoscroll()

    def _autoscroll(self):
        """Beim Ziehen am oberen/unteren Rand der Setlist weiterblaettern."""
        self._scroll_job = None
        if not self._drag:
            return
        xr, yr = self._pointer
        if not self.tgt.contains(xr, yr):
            return
        y, h, edge = yr - self.tgt.winfo_rooty(), self.tgt.winfo_height(), px(28)
        step = -1 if y < edge else (1 if y > h - edge else 0)
        if step:
            self.tgt.yview_scroll(step, "units")
            self.tgt.set_drop(self.tgt.insert_at(yr))
            self._scroll_job = self.after(70, self._autoscroll)

    def drag_end(self, xr, yr):
        drag, self._drag = self._drag, None
        if self._ghost:
            self._ghost.destroy()
            self._ghost = None
        if self._scroll_job:
            self.after_cancel(self._scroll_job)
            self._scroll_job = None
        self.tgt.set_drop(None)
        self.src.set_drop(None, None)
        if not drag:
            return
        lst, indices, ids = drag
        lst.configure(cursor="")
        where = self._over(xr, yr)
        if where == "target":
            k = self.tgt.insert_at(yr)
            if lst is self.src:
                self.insert_ids(ids, k)
            else:
                self.move_rows(indices, k)
        elif where == "source" and lst is self.tgt:
            self.remove_rows(indices)

    # ================= Schliessen =================
    def effects(self):
        return {"lists": set(self.fx_lists), "rows": set(self.fx_rows), "renamed": dict(self.fx_renamed),
                "deleted": set(self.fx_deleted),
                "restart": bool(self.fx_created or self.fx_renamed or self.fx_deleted)}
