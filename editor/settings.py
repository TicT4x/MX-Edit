"""settings.py - Einstellungen des Editors: ablegen in %APPDATA%\\MX5Editor\\einstellungen.json und
die Seite "Settings" (ui.Overlay wie Tuner/IR-Dialog, ueber die Symbolleiste links).

Einstellungen sind ein flaches dict; unbekannte/fehlende Schluessel bekommen die Vorgaben aus
DEFAULTS, eine kaputte Datei wird ignoriert (dann gelten die Vorgaben)."""
import json, os, re, tkinter as tk

import ui as U
from ui import PANEL, LINE, TEXT, MUTED, DIM, px
from ui import FONT_BOLD, FONT_SMALL

DEFAULTS = {
    # IR- und NAM-Auswahl: ein Klick laedt die Datei sofort, die Auswahl bleibt offen (Probehoeren)
    "audition": True,
    # Fussschalter-Leiste unter dem Signalpfad (live); aus = nur ueber das Menue 'Footswitches & pedals'
    "footswitch_bar": True,
    # Groesse der Oberflaeche in Prozent zusaetzlich zur Windows-Skalierung (gilt ab dem naechsten Start)
    "ui_scale": 100,
    # beim Start ohne Ordner gleich mit dem MX5 verbinden
    "auto_connect": True,
    # MIDI-Ports fest waehlen ("" = automatisch ueber die Namenssuche in bridge.py)
    "midi_in": "",
    "midi_out": "",
}

SCALES = [80, 90, 100, 110, 125, 150]
AUTO_PORT = "Automatic"


def path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "MX5Editor", "einstellungen.json")


def load():
    data = dict(DEFAULTS)
    try:
        with open(path(), encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            data.update({k: v for k, v in saved.items() if k in DEFAULTS and type(v) is type(DEFAULTS[k])})
    except (OSError, ValueError):
        pass
    if data["ui_scale"] not in SCALES:
        data["ui_scale"] = DEFAULTS["ui_scale"]
    return data


def save(data):
    p = path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, p)
        return None
    except OSError as e:
        return str(e)


# ---------------- MIDI-Ports ----------------
def port_names():
    """(Eingaenge, Ausgaenge) wie mido sie meldet; ohne mido zwei leere Listen."""
    try:
        import mido
        return mido.get_input_names(), mido.get_output_names()
    except Exception:
        return [], []


def _port_base(name):
    # rtmidi haengt unter Windows eine laufende Nummer an ("HeadRush MX5 1"), die sich aendern kann
    return re.sub(r"\s+\d+$", "", name)


def pick_port(names, wanted):
    """Gespeicherten Portnamen unter den vorhandenen finden: genau, sonst ohne die angehaengte Nummer."""
    if wanted in names:
        return wanted
    hits = [n for n in names if _port_base(n) == _port_base(wanted)]
    if len(hits) == 1:
        return hits[0]
    raise LookupError("MIDI port “%s” not found" % wanted)


def find_ports(want_in, want_out):
    """(Eingang, Ausgang) fuer Bridge(): fest gewaehlte Ports aus den Einstellungen, der Rest automatisch."""
    from bridge import Bridge
    ins, outs = port_names()
    auto = None if (want_in and want_out) else Bridge.find_ports()
    return (pick_port(ins, want_in) if want_in else auto[0],
            pick_port(outs, want_out) if want_out else auto[1])


class SettingsDialog(U.Overlay):
    """Seite 'Settings': jede Aenderung wird sofort gespeichert; Editor.pref_changed wendet sie an,
    soweit das ohne Neustart geht."""

    def __init__(self, editor):
        super().__init__(editor, "Settings", width=600, click_out=True)
        self.ed = editor
        self.closed = False
        b = self.body
        p = editor.prefs

        self.section("BROWSERS")
        self.row("Audition while browsing",
                 "IR and NAM browser: a click loads the file at once, so you can hear it right away. The browser "
                 "stays open until you close it (“Done” keeps the current choice, “Revert” goes back to the one "
                 "you started with). When off, the browser closes after you apply a file.",
                 lambda f: self.toggle(f, "audition"))

        self.section("DISPLAY")
        self.row("Footswitch bar",
                 "The three footswitches below the signal chain (live mode). When hidden, footswitches and pedals "
                 "open from the ⋯ menu (“Footswitches & pedals …”).",
                 lambda f: self.toggle(f, "footswitch_bar"))
        self.lbl_scale = None
        self.row("Interface size",
                 "Scales text and controls on top of the Windows display scaling.", None)
        sf = tk.Frame(b, bg=PANEL)
        sf.pack(fill="x", pady=(0, px(4)))
        U.Segmented(sf, ["%d %%" % v for v in SCALES], SCALES.index(p["ui_scale"]),
                    on_pick=lambda i: self.set_scale(SCALES[i]), padx=8).pack(side="left")
        self.lbl_scale = tk.Label(b, text="", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w")
        self.lbl_scale.pack(fill="x", pady=(0, px(10)))
        self.scale_hint()

        self.section("CONNECTION")
        self.row("Connect on start",
                 "Look for the MX5 as soon as the editor starts. Turn off if you mostly edit .rig files offline – "
                 "“Connect to Device” still connects on demand.",
                 lambda f: self.toggle(f, "auto_connect"))
        self.row("MIDI ports",
                 "“Automatic” finds the MX5 by its port name. Choose the ports yourself if several devices "
                 "match or the name differs. Used for the next connection.", None)
        pf = tk.Frame(b, bg=PANEL)
        pf.pack(fill="x", pady=(0, px(10)))
        self.dd_ports = {}
        for col, (key, label) in enumerate((("midi_in", "Input"), ("midi_out", "Output"))):
            tk.Label(pf, text=label, bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").grid(
                row=0, column=col, sticky="w", padx=(0, px(12)))
            dd = U.Dropdown(pf, [AUTO_PORT], p[key] or AUTO_PORT, width=22, title="MIDI " + label.lower(),
                            on_pick=lambda i, k=key: self.pick_port(k, i), font=FONT_SMALL,
                            on_open=lambda k=key: self.open_ports(k))
            dd.grid(row=1, column=col, sticky="we", padx=(0, px(12)), pady=(px(2), 0))
            pf.columnconfigure(col, weight=1)
            self.dd_ports[key] = dd

        tk.Frame(b, bg=LINE, height=1).pack(fill="x", pady=(px(4), px(8)))
        tk.Label(b, text="Saved in %s" % path(), bg=PANEL, fg=DIM, font=FONT_SMALL, anchor="w", justify="left",
                 wraplength=px(540)).pack(fill="x")
        bf = tk.Frame(b, bg=PANEL)
        bf.pack(fill="x", pady=(px(14), 0))
        U.Btn(bf, "Close", command=self.close, kind="primary").pack(side="right")
        self.bind_keys()

    # ---- Aufbau ----
    def section(self, text):
        tk.Label(self.body, text=text, bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").pack(
            fill="x", pady=(px(4), px(6)))

    def row(self, label, text, control):
        """Zeile mit Titel + Erklaerung links; control(frame) baut rechts das Bedienelement (oder None)."""
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill="x", pady=(0, px(10) if control else px(6)))
        if control:
            control(row).pack(side="right", anchor="n", padx=(px(16), 0), pady=(px(2), 0))
        tf = tk.Frame(row, bg=PANEL)
        tf.pack(side="left", fill="x", expand=True)
        tk.Label(tf, text=label, bg=PANEL, fg=TEXT, font=FONT_BOLD, anchor="w").pack(fill="x")
        tk.Label(tf, text=text, bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w", justify="left",
                 wraplength=px(480)).pack(fill="x", pady=(px(2), 0))

    def toggle(self, parent, key):
        return U.Toggle(parent, self.ed.prefs.get(key), command=lambda v: self.set(key, v), bg=PANEL)

    # ---- Aenderungen ----
    def set(self, key, value):
        self.ed.prefs[key] = value
        err = save(self.ed.prefs)
        self.ed.status.set("Could not save the settings: %s" % err if err else "Settings saved.")
        self.ed.pref_changed(key)

    def set_scale(self, value):
        self.set("ui_scale", value)
        self.scale_hint()

    def scale_hint(self):
        now, want = self.ed.ui_scale, self.ed.prefs["ui_scale"]
        self.lbl_scale.configure(text="" if now == want else
                                 "Takes effect the next time the editor starts (now %d %%)." % now)

    def open_ports(self, key):
        """Liste der Ports erst beim Aufklappen lesen (Geraete koennen inzwischen dazugekommen sein)."""
        ins, outs = port_names()
        names = ins if key == "midi_in" else outs
        cur = self.ed.prefs[key]
        if cur and cur not in names:
            names = names + [cur]   # gespeicherter Port, gerade nicht angeschlossen
        self._ports = [""] + names
        self.dd_ports[key].show([AUTO_PORT] + names)

    def pick_port(self, key, i):
        self.set(key, self._ports[i])

    def cancel(self):
        self.close()

    def close(self, result=None):
        if self.closed:
            return
        self.closed = True
        self.ed.settings_done(self)
        super().close(result)
