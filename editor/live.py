"""live.py - Live-Verbindung zum MX5 ueber die MX5 Bridge.

Alle Anfragen laufen in einem Hintergrund-Thread. Schreibanfragen auf denselben
Parameter werden zusammengefasst (nur der letzte Wert wird gesendet), damit
Regelbewegungen das Geraet nicht mit Nachrichten fluten. Ergebnisse werden
ueber `dispatch` (z. B. tk.after) im GUI-Thread zugestellt.

Braucht die Brueckenfirmware 0.5 (Datenbank lesen und schreiben, Umlaute).

Geraetefunktionen (am Geraet verifiziert):
  Rig-Liste   Datenbankzeilen (db_rigs) in Geraete-Reihenfolge: All Rigs nach rowid,
              Setlists nach setlist_rigs.show_order (geprueft 2026-09-30, 330 Rigs).
              Ein Rig ist ueber seine ID bestimmt, Namen sind nicht eindeutig.
  Rig laden   Ueber die Position: Bank anfahren (NextBank/PrevBank, die gezeigte Bank
              RigName1-3 muss genau zur Liste passen), dann LoadRig1-3 "druecken";
              schneller ueber ReceivePresetIndex = Programmnummer - 1 (nur Rigs der
              aktiven Liste). Geprueft wird immer an der LoadedID.
  Setlists    Set-Modus: SetName1 zeigt eine Setlist, NextSetBank/PrevSetBank
              blaettern, AccessSet1 betritt die gezeigte Setlist (das MX5 laedt
              dabei deren erstes Rig). AccessRigView wechselt zu "All Rigs",
              ohne ein Rig zu laden. "All Rigs" steht nicht in der Set-Liste.
  Dialoge     Fragt das MX5 nach ungespeicherten Aenderungen (Global Settings
              "Confirm Dirty"), steht BoardMode auf "FreeText" und ButtonText1-3
              auf Cancel|Save|Discard; die Buttons sind die Fussschalter FS1-3.
              Verwerfen geht ohne Dialog: Rigs/Dirty = 0 vor dem Wechsel, dann
              fragt das MX5 nicht (drop_changes; geprueft 2026-09-29, auch LoadRig
              auf das geladene Rig laedt es dann frisch).
  Speichern   EditModeSaveRig oeffnet den Dialog cancel|save|save_new_rig,
              dessen Buttons an den Fussschaltern FS1|FS2|FS3 haengen.
  Tastendruck state 1, mindestens 30 ms halten, state 0, danach mindestens
              30 ms Pause - sonst wird ein Druck verschluckt oder doppelt gezaehlt.
"""
import collections, json, os, threading, time
from bridge import BridgeError, NoReply, sh_quote, sql_lit
from rigmodel import base_name


ENGINE = "/Engine/Patch"
PC = "/Engine/PresetCtrl"
RIGS = PC + "/Rigs"
RC = "/Engine/RedirCtrl"
SAVE = RC + "/EditModeSaveRig"
FS = RC + "/RawFootswitches/FS%d"
BOARD = RC + "/BoardMode"
BTN = RC + "/ButtonText%d"
ALL_RIGS = "All Rigs"
SLOTS = 11
EMPTY = "Empty Slot"
EMPTY_RIG = "[EMPTY]"
SPECIAL_MODULES = ["Rig", "Input", "Output"]
HIDDEN_PARAMS = {"PresetName", "PresetName2"}
MAX_BANKS = 200
MAX_SETLISTS = 50
HOLD = 0.05           # Taste halten (gemessen: ab 30 ms zuverlaessig)
BANK_WAIT = 0.05      # Pause nach dem Loslassen (unter 30 ms zaehlt der naechste Druck doppelt)
LOAD_WAIT = 3.0
SETTLE = 0.5          # nach dem Laden: Kette und Parameter fertig werden lassen. Mit 0,3 s
                      # verschluckte das MX5 den ersten set danach in ~20 % der Faelle
                      # (gemessen 30.09.2026: +0,1 s reichte schon, 0 von 30)
RELOAD_WAIT = 0.4     # LoadRig auf das geladene Rig (ohne Dirty): gemessen 0,2 s bis zum frischen Stand

# Knotentypen im Live-Modus
L_NUMBER, L_BOOL, L_ENUM, L_TEXT = "number", "bool", "enum", "text"


class LiveError(Exception):
    pass


def kind_of(info):
    if not info or not info.get("ok"):
        return None
    if info.get("valueType") == "TwoStateValue":
        return L_BOOL
    if "numEntries" in info:
        return L_ENUM
    if "maximum" in info or "unnormalized" in info:
        return L_NUMBER
    return L_TEXT


COMPACT_FIELDS = ("value", "unnormalized", "state", "index", "string")
COMPACT_GROUP = 300   # Pfade je eval (~60 Zeichen Antwort je Wert, Grenze ~48 KB)
_COMPACT_JS = ('var P = %s, F = %s, o = []; '
               'function f(t, k) { try { var v = t[k], y = typeof v; '
               '  return y == "number" || y == "boolean" || y == "string" ? v : null; } catch (e) { return null; } } '
               'for (var i = 0; i < P.length; i++) { var p = App.getProperty(P[i]), t = p && p.translator; '
               '  if (!t) { o.push(0); continue; } var r = []; '
               '  for (var k = 0; k < F.length; k++) r.push(f(t, F[k])); o.push(r); } '
               'return JSON.stringify(o);')


def get_compact(br, paths):
    """Wie Bridge.get_many, aber nur die Felder COMPACT_FIELDS (ohne numEntries, maximum,
    defaultValue, valueType, editable) - etwa ein Drittel der Antwort, fuer den laufenden Abgleich
    (95 -> 55 ms bei 86 Werten). Fehlende Pfade -> {"ok": False}; wie bei infoOf fehlen Felder,
    die das Property nicht hat. Die Werte also in vorhandene Eintraege einmischen, nicht ersetzen."""
    paths = list(dict.fromkeys(paths))
    out = {}
    for i in range(0, len(paths), COMPACT_GROUP):
        group = paths[i:i + COMPACT_GROUP]
        for p, v in zip(group, json.loads(br.eval(_COMPACT_JS % (json.dumps(group), json.dumps(COMPACT_FIELDS))))):
            if not v:
                out[p] = {"ok": False, "err": "keine Eigenschaft: " + p}
                continue
            d = {"ok": True}
            for k, x in zip(COMPACT_FIELDS, v):
                if x is not None:
                    d[k] = x
            out[p] = d
    return out


LOST_PING = 1.0   # s: Ping nach einem Transportfehler; bleibt er aus, gilt die Verbindung als verloren


def transport_error(e):
    """True, wenn die Ausnahme auf eine gestoerte Verbindung deutet (keine/unvollstaendige Antwort,
    MIDI-Port weg) - nicht bei Fehlermeldungen des Geraets oder des Editors (LiveError)."""
    if isinstance(e, LiveError):
        return False
    if isinstance(e, BridgeError):
        return str(e).startswith(("Keine Antwort", "Antwort unvollstaendig", "MIDI-Port"))
    return True


class LiveSession:
    def __init__(self, bridge, dispatch, on_lost=None):
        self.bridge = bridge
        self.dispatch = dispatch
        self.on_lost = on_lost    # im GUI-Thread, einmal, wenn das Geraet nicht mehr antwortet
        self._cv = threading.Condition()
        self._sets = collections.OrderedDict()   # path -> (field, value, callback)
        self._jobs = collections.deque()          # (fn(bridge) -> result, callback)
        self._stop = False
        self.lost = False         # Verbindung verloren: der Worker nimmt keine Auftraege mehr an
        self.running = False      # ein Auftrag laeuft gerade auf der Bridge
        self.errors = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def close(self):
        with self._cv:
            self._stop = True
            self._cv.notify()
        self._thread.join(timeout=5)
        try:
            self.bridge.close()
        except Exception:
            pass

    def idle(self):
        with self._cv:
            return not self._sets and not self._jobs and not self.running

    def run(self, fn, callback=None):
        """fn(bridge) im Hintergrund ausfuehren; callback(result) im GUI-Thread.
        Wirft fn eine Ausnahme, bekommt callback ein {"ok": False, "err": ...}."""
        with self._cv:
            self._jobs.append((fn, callback))
            self._cv.notify()

    def get(self, path, callback):
        self.run(lambda br: br.get(path), lambda r: callback(path, r))

    def get_many(self, paths, callback):
        """callback(dict pfad -> info)"""
        self.run(lambda br: br.get_many(paths), callback)

    def set(self, path, field, value, callback=None):
        with self._cv:
            self._sets.pop(path, None)
            self._sets[path] = (field, value, callback)
            self._cv.notify()

    def _run(self):
        while True:
            with self._cv:
                while not self._stop and not self._sets and not self._jobs:
                    self._cv.wait()
                if self._stop or self.lost:
                    return
                if self._sets:  # Schreiben hat Vorrang
                    path, (field, value, cb) = self._sets.popitem(last=False)
                    fn = lambda br, p=path, f=field, v=value: br.set(p, f, v)
                    cb = (lambda r, cb=cb, p=path: cb(p, r)) if cb else None
                else:
                    fn, cb = self._jobs.popleft()
                self.running = True
            broken = False
            try:
                result = fn(self.bridge)
            except LiveError as e:
                result = {"ok": False, "err": str(e)}
            except Exception as e:  # der Worker darf nie sterben
                self.errors += 1
                result = {"ok": False, "err": "%s: %s" % (type(e).__name__, e)}
                broken = transport_error(e) and (isinstance(e, NoReply) or not self._alive())
            finally:
                self.running = False
            if cb:
                self.dispatch(lambda cb=cb, r=result: cb(r))
            if broken:
                self.lost = True
                if self.on_lost:
                    self.dispatch(self.on_lost)
                return

    def _alive(self):
        """Kurzer Ping nach einem Transportfehler: einzelne verlorene Antworten sind kein Abbruch."""
        try:
            self.bridge._drain()
            self.bridge.request(0x01, timeout=LOST_PING)
            return True
        except Exception:
            return False


# ---------------- Geraetefunktionen (laufen im Worker, bekommen die Bridge) ----------------

def press(br, path, hold=HOLD, wait=BANK_WAIT):
    """Taste 'druecken': state 1, kurz halten, state 0, kurze Pause."""
    br.set(path, "state", 1)
    time.sleep(hold)
    br.set(path, "state", 0)
    time.sleep(wait)


def strings(br, paths):
    """Mehrere Textwerte lesen; eine unvollstaendige Antwort wird einmal wiederholt."""
    r = br.get_many(paths)
    if any(p not in r for p in paths):
        r = br.get_many(paths)
    return [(r.get(p) or {}).get("string", "") or "" for p in paths]


def read_bank(br):
    """Die drei Rigs der aktuell angezeigten Bank: [(name, farbe)]."""
    v = strings(br, ["%s/RigName%d" % (PC, n) for n in (1, 2, 3)] + ["%s/RigColour%d" % (PC, n) for n in (1, 2, 3)])
    return [(v[i], v[i + 3][:-2] if v[i + 3].endswith("_D") else v[i + 3]) for i in range(3)]


def _step(br, path, read, before):
    """Taste druecken und neu lesen. Aendert sich nichts, wird nach einer Pause
    noch einmal gedrueckt (kurz nach einem Rig-Wechsel verschluckt das MX5
    Tastendruecke). Liefert (geaendert, anzeige)."""
    press(br, path)
    cur = read(br)
    if cur != before:
        return True, cur
    time.sleep(0.2)
    cur = read(br)
    if cur != before:
        return True, cur
    press(br, path)
    cur = read(br)
    return cur != before, cur


def _to_start(br, read, prev_path, limit):
    """prev_path druecken, bis sich die Anzeige nicht mehr aendert; liefert den ersten Eintrag."""
    cur = read(br)
    for _ in range(limit):
        changed, cur = _step(br, prev_path, read, cur)
        if not changed:
            break
    return cur


def read_set_cursor(br):
    return strings(br, ["%s/SetName1" % PC])[0]


def rig_status(br):
    r = br.get_many(["%s/LoadedName" % RIGS, "%s/LoadedID" % RIGS, "%s/Dirty" % RIGS, "%s/LoadedProgNum" % RIGS])
    pn = r["%s/LoadedProgNum" % RIGS].get("string", "-")
    return {"name": r["%s/LoadedName" % RIGS].get("string"), "id": r["%s/LoadedID" % RIGS].get("string"),
            "dirty": bool(r["%s/Dirty" % RIGS].get("state")), "prog": int(pn) if pn.isdigit() else None}


def dialog_buttons(br):
    """Beschriftung der drei Fussschalter, wenn am MX5 ein Dialog offen ist, sonst None."""
    v = strings(br, [BOARD] + [BTN % n for n in (1, 2, 3)])
    return v[1:] if v[0] == "FreeText" else None


def discard_dialog(br):
    """Den Dialog 'Cancel | Save | Discard' (ungespeicherte Aenderungen) mit Discard beantworten.
    Liefert True, wenn ein solcher Dialog offen war."""
    b = dialog_buttons(br)
    if not b:
        return False
    if b[2].strip().lower() != "discard":
        raise LiveError("A dialog is open on the MX5 (%s). Please answer it on the display." % " | ".join(b))
    press(br, FS % 3)
    return True


def drop_changes(br, st=None):
    """Das geladene Rig als unveraendert markieren (Rigs/Dirty = 0), damit der naechste
    Wechsel ohne 'Cancel | Save | Discard'-Dialog verwirft - statt FS3 zu druecken.
    Liefert True, wenn das Rig geaendert war (fuer keep_changes)."""
    if st is None:
        st = rig_status(br)
    if not st["dirty"]:
        return False
    br.set("%s/Dirty" % RIGS, "state", 0)
    return True


def keep_changes(br):
    """Gegenstueck zu drop_changes, wenn der Wechsel doch nicht stattfand: das geladene
    Rig traegt seine Aenderungen noch, also wieder als geaendert markieren."""
    br.set("%s/Dirty" % RIGS, "state", 1)


def wait_for(br, cond, timeout=LOAD_WAIT, discard=False):
    """Rig-Status abfragen, bis cond(status) gilt. Mit discard=True wird ein
    'Confirm Dirty'-Dialog des MX5 dabei mit Discard beantwortet (Rueckfall; normalerweise
    verhindert drop_changes den Dialog schon vorher)."""
    end = time.time() + timeout
    while True:
        st = rig_status(br)
        if cond(st):
            time.sleep(SETTLE)
            return st
        if discard and discard_dialog(br):
            discard = False
            end = time.time() + timeout
        if time.time() >= end:
            return st
        time.sleep(0.1)


def _seek(br, items, target, read, next_path, prev_path, limit, what):
    """Anzeige Schritt fuer Schritt auf den Eintrag 'target' blaettern. items gibt nur die
    vermutete Richtung vor (Datenbank-Reihenfolge); nach jedem Druck wird gelesen, am Ende
    der Liste wird umgekehrt - so stimmt das Ergebnis auch bei abweichender Reihenfolge."""
    cur = read(br)
    if cur == target:
        return
    forward = target not in items or cur not in items or items.index(target) > items.index(cur)
    for path in ((next_path, prev_path) if forward else (prev_path, next_path)):
        for _ in range(limit):
            changed, cur = _step(br, path, read, cur)
            if cur == target:
                return
            if not changed:
                break
    raise LiveError("'%s' not found in the %s, please reread." % (target, what))


def seek_setlist(br, setlists, name):
    """Set-Anzeige (SetName1) auf die Setlist 'name' stellen."""
    _seek(br, setlists, name, read_set_cursor, "%s/NextSetBank" % PC, "%s/PrevSetBank" % PC,
          MAX_SETLISTS, "setlist list")


def _bank_names(br):
    return [n for n, _ in read_bank(br)]


def bank_names(rows, bank):
    """Namen der Bank 'bank' (0-basiert) der Rig-Liste rows, wie die Bank-Anzeige sie zeigt:
    ohne Werks-Nummer, freie Plaetze der letzten Bank als '[EMPTY]'."""
    names = [display_name(r["name"]) for r in rows[bank * 3:bank * 3 + 3]]
    return names + [EMPTY_RIG] * (3 - len(names))


def bank_count(rows):
    return max(1, (len(rows) + 2) // 3)


def goto_bank(br, rows, target):
    """Bank-Anzeige auf die Bank 'target' der Liste rows stellen und pruefen, dass sie genau deren
    Namen zeigt. Wo die Anzeige steht, verraet die gezeigte Bank (Datenbank- = Geraete-
    Reihenfolge); ist das nicht eindeutig, wird erst an den Anfang geblaettert. Zeigt die Anzeige
    danach etwas anderes, weicht die Liste am Geraet ab (LiveError: neu lesen)."""
    want = bank_names(rows, target)
    banks = [bank_names(rows, b) for b in range(bank_count(rows))]
    for _ in range(3):   # kurz nach einem Rig-Wechsel verschluckt das MX5 Tastendruecke
        cur = _bank_names(br)
        if cur == want:
            return
        hits = [b for b, names in enumerate(banks) if names == cur]
        if len(hits) == 1:
            pos = hits[0]
        else:
            if _to_start(br, _bank_names, "%s/PrevBank" % PC, MAX_BANKS) != banks[0]:
                break
            pos = 0
        path = "%s/%s" % (PC, "NextBank" if target > pos else "PrevBank")
        for _ in range(abs(target - pos)):
            press(br, path)
        time.sleep(0.1)
    cur = _bank_names(br)
    if cur != want:
        raise LiveError("The rig list on the MX5 differs from the editor's (bank %d shows %s) - "
                        "please reread the rig list." % (target + 1, " | ".join(cur)))


def _prog(row):
    """Anzeige-Programmnummer einer Rig-Zeile (Datenbank zaehlt ab 0, -1 = keine) oder None."""
    p = row.get("prog_num")
    return int(p) + 1 if p is not None and int(p) >= 0 else None


JUMP = PC + "/NextPreset"   # Zaehler: Schreiben springt um (neu - alt) Plaetze der aktiven Liste
JUMP_MAX = 16000000         # Wertebereich bis 16777216; darueber wird rueckwaerts gerechnet
LAST_LOAD = {}              # letzter load_rig: {"via": "jump"|"prog"|"bank", "secs": Dauer} (Tests, Fehlersuche)


def jump(br, rows, index, before):
    """rows[index] per NextPreset laden: das Geraet springt um die Differenz zum vorigen Wert
    (negativ = rueckwaerts, ringfoermig ueber das Listenende; eine volle Listenlaenge laedt das
    aktuelle Rig frisch) - ein Schreibzugriff, ~0,06 s, ohne die Bank-Anzeige zu blaettern
    (am Geraet geprueft 2026-09-30, auch 100 Plaetze in All Rigs). Braucht die eindeutige
    Position des Geraete-Zeigers: nach eigenem Laden die geladene Position, nach dem Betreten
    einer Liste Platz 0 - auch wenn das geladene Rig woanders steht (geprueft 2026-09-30); das
    merkt sich die Verbindung (br.cursor = (LoadedID, Platz); read_rig_list setzt ihn beim
    Verbinden). Hat das Geraet selbst ein anderes Rig geladen (LoadedID weicht ab), steht der
    Zeiger auf dessen Position, wenn sie eindeutig ist. Ohne bekannten Zeiger wird nicht geraten
    (ein falsch geladenes Rig waere hoerbar): False, dann laedt load_rig anders."""
    ids = [r["id"] for r in rows]
    n = len(rows)
    cur = getattr(br, "cursor", None)
    if not cur:
        return False
    if cur[0] == before["id"] and 0 <= cur[1] < n:
        pos = cur[1]
    elif before["id"] and ids.count(before["id"]) == 1:
        pos = ids.index(before["id"])
    else:
        return False   # nichts geladen oder das Rig steht mehrfach in der Setlist
    delta = (index - pos) % n or n
    old = int(br.get(JUMP).get("unnormalized") or 0)
    new = old + delta if old + delta <= JUMP_MAX else old - (n - delta if delta < n else n)
    br.set(JUMP, "unnormalized", new)
    return True


def load_rig(br, rows, index, discard=False, fast=True):
    """Rig rows[index] der aktiven Liste laden (rows = Datenbankzeilen in Geraete-Reihenfolge).
    Per Sprung (jump), sonst ueber die Programmnummer, zuletzt ueber die Bank-Anzeige; ob das
    richtige Rig geladen ist, entscheidet die LoadedID. discard=True: Aenderungen am geladenen
    Rig ohne Rueckfrage am Geraet verwerfen (drop_changes). Ist rows[index] das geladene Rig,
    wird es frisch geladen. fast=False: nur ueber die Bank (Test des Rueckfalls).
    Liefert den Rig-Status danach."""
    target = rows[index]
    rid = target["id"]
    before = rig_status(br)
    same = before["id"] == rid
    loaded = lambda s: s["id"] == rid and (not same or not s["dirty"])
    dropped = discard and drop_changes(br, before)   # kein Discard-Dialog am Geraet
    prog = _prog(target)
    t0 = time.time()
    via = lambda how: LAST_LOAD.update(via=how, secs=time.time() - t0)
    try:
        if fast and jump(br, rows, index, before):
            if same:   # Neuladen desselben Rigs: am Status nicht zu erkennen
                time.sleep(RELOAD_WAIT)
            st = wait_for(br, loaded, timeout=1.0, discard=discard and before["dirty"])
            if loaded(st):
                via("jump")
                br.cursor = (rid, index)
                return st
            br.cursor = None   # anderes Rig gelandet (Zeiger/Liste am Geraet anders): ueber die Bank weiter
        if prog and not same and fast:   # ReceivePresetIndex auf das geladene Rig tut nichts
            br.set("%s/ReceivePresetIndex" % RIGS, "unnormalized", prog - 1)
            st = wait_for(br, loaded, timeout=1.0, discard=discard and before["dirty"])
            if loaded(st):
                via("prog")
                br.cursor = (rid, index) if [r["id"] for r in rows].count(rid) == 1 else None
                return st
        goto_bank(br, rows, index // 3)
        press(br, "%s/LoadRig%d" % (PC, index % 3 + 1))
        if same:   # Neuladen desselben Rigs: am Status erst spaet zu erkennen
            time.sleep(RELOAD_WAIT)
        st = wait_for(br, loaded, discard=discard and before["dirty"])
        via("bank")
        br.cursor = (rid, index) if loaded(st) else None
    except Exception:
        if dropped and not same and rig_status(br)["id"] == before["id"]:
            keep_changes(br)
        raise
    if not loaded(st):
        if dropped and not same and st["id"] == before["id"]:
            keep_changes(br)
        if before["dirty"]:
            raise LiveError("The MX5 did not switch. Is it asking on the display about unsaved "
                            "changes? Then confirm there.")
        raise LiveError("Rig '%s' was not loaded (loaded is '%s')." % (display_name(target["name"]), st["name"]))
    return st


def reload_rig(br, rows):
    """Geladenes Rig frisch laden (Aenderungen verwerfen), ueber seine Position in rows (per ID):
    Sprung um eine volle Listenlaenge, sonst LoadRig in seiner Bank. Dirty wird vorher geloescht,
    dann laedt das Geraet ohne Discard-Dialog (geprueft 2026-09-29/30)."""
    ids = [r["id"] for r in rows]
    st = rig_status(br)
    if st["id"] not in ids:
        raise LiveError("The loaded rig is not in the current list - please reread the rig list.")
    return load_rig(br, rows, ids.index(st["id"]), discard=True)


# ---- Setlists ----

def enter_setlist(br, setlists, name, setlist_ids, discard=False, active=False):
    """Setlist 'name' (oder ALL_RIGS) am Geraet aktivieren; liefert die Liste wie read_rig_list.
    Beim Wechsel in eine andere Setlist laedt das MX5 deren erstes Rig (discard=True: ohne
    Rueckfrage verwerfen); 'All Rigs' laedt nichts, ein geaendertes Rig bleibt geaendert. Das
    Betreten liest die Liste (Namen, Farben, Programmnummern) neu aus der Datenbank - auch die
    schon aktive Setlist, und dann laedt es nichts, das geladene Rig bleibt samt seinen
    Aenderungen (am Geraet geprueft 2026-09-17). active=True sagt das vorab, damit nicht auf ein
    Laden gewartet wird - so dient es nach Datenbankaenderungen als Auffrischen."""
    if name != ALL_RIGS and name not in setlist_ids:
        raise LiveError("Setlist '%s' not found." % name)
    rows = db_rigs(br, None if name == ALL_RIGS else setlist_ids[name])   # vorab: welches Rig laedt das Betreten
    before = rig_status(br)
    mode = br.get(BOARD)   # Ansicht (AccessSet1/AccessRigView schalten sie um)
    if name == ALL_RIGS:
        press(br, "%s/AccessRigView" % RC)
        time.sleep(SETTLE)
        st = rig_status(br)
    else:
        seek_setlist(br, setlists, name)
        first = rows[0]["id"] if rows else None
        # Wird sicher ein anderes Rig geladen, Dirty vorher loeschen: dann fragt das MX5 nicht
        # (sonst Discard-Dialog -> FS3). Die schon aktive Setlist laedt nichts - dort nicht.
        dropped = discard and not active and first and first != before["id"] and drop_changes(br, before)
        press(br, "%s/AccessSet1" % RC)
        time.sleep(SETTLE)
        if active:
            st = rig_status(br)
        else:
            if first and first != before["id"]:
                # das Laden des ersten Rigs abwarten (LoadedID wechselt erst nach einer Weile)
                st = wait_for(br, lambda s: s["id"] == first and not s["dirty"], discard=discard and before["dirty"])
            else:
                st = wait_for(br, lambda s: not s["dirty"], discard=discard and before["dirty"])
            if dropped and st["id"] == before["id"]:   # nichts geladen: Aenderungen sind noch da
                keep_changes(br)
                st = rig_status(br)
            if st["dirty"]:
                raise LiveError("The MX5 did not switch the setlist. Is it asking on the display about "
                                "unsaved changes? Then confirm there.")
            for _ in range(10):   # Name und ID werden nacheinander aktualisiert
                st2 = rig_status(br)
                if st2 == st:
                    break
                st = st2
                time.sleep(0.1)
    _wait_stable(br, read_bank)   # die Bank-Anzeige wird verzoegert umgestellt
    restore_board(br, mode)
    br.cursor = (st["id"], 0)   # Geraete-Zeiger fuer jump: erster Platz, auch wenn das Rig woanders steht
    return {"setlists": setlists, "setlist": name, "sure": True, "status": st, "rows": rows,
            "setlist_ids": setlist_ids}


# ---- Rig-Datenbank (Bruecke 0.3: SQL-Befehl, nur lesend) ----
#
# Tabellen: rigs(id, name, content, show_order, author, is_readonly, color, created_at,
# prog_num), setlists(id, name, ...), setlist_rigs(setlist_id, rig_id, show_order),
# settings(name, value). 'content' ist der Rig-Inhalt wie in einer .rig-Datei.

RIG_COLOURS = ["Off", "Green", "Dark Green", "Yellow", "Orange", "Red", "Pink", "Purple", "Blue",
               "Light Blue", "White", "Grey", "Turquoise", "Black"]   # rigs.color -> Anzeigename
RIG_FIELDS = "id, name, color, prog_num, show_order"


# Antwortgrenze: bis Bruecke 0.5 ca. 48 KB (127 Teile), ab 0.6 mit langem Antwortkopf bis ca. 6 MB.
# Seiten werden ab 0.6 um PAGE_FACTOR groesser (~1 MB je Antwort, ~7 s bei ~140 KB/s).
PAGE_FACTOR = 20


def _page(br, rows):
    """Seitengroesse (Zeilen oder Zeichen) fuer eine Bruecke: rows gilt fuer die 48-KB-Grenze."""
    return rows * PAGE_FACTOR if getattr(br, "long", False) else rows


def db_setlists(br):
    """[(id, name)] aller Setlists."""
    return [(r["id"], r["name"]) for r in br.sql("select id, name from setlists order by name collate nocase")]


def db_rigs(br, setlist_id=None):
    """Rigs der Setlist (oder alle) in Geraete-Reihenfolge: [{id, name, color, prog_num, show_order}].
    Setlists: nach setlist_rigs.show_order. 'All Rigs': nach rowid - die App fragt ohne ORDER BY
    ab; die ersten Rigs wurden einmal nach Namen sortiert eingefuegt (Werks-DB/USB-Import), neuere
    haengen hinten an (am Geraet geprueft 2026-09-30, alle 330 Rigs). Die Werks-Rigs heissen
    '003 MODERN PLEXI' usw., die Anzeige laesst die Nummer weg (display_name). prog_num in der DB =
    Anzeige-Programmnummer - 1, -1 = keine."""
    if setlist_id:
        q = ("select r.id, r.name, r.color, r.prog_num, s.show_order from setlist_rigs s "
             "join rigs r on r.id = s.rig_id where s.setlist_id = %s order by s.show_order" % sql_lit(setlist_id))
    else:
        q = "select %s from rigs order by rowid" % RIG_FIELDS
    # Antworten sind (bis 0.5) auf ca. 48 KB begrenzt -> seitenweise lesen
    rows, page = [], _page(br, 150)
    while True:
        part = br.sql("%s limit %d offset %d" % (q, page, len(rows)))
        rows += part
        if len(part) < page:
            return rows


def display_name(name):
    """Rig-Name wie in der Bank-Anzeige: Werks-Nummer ('003 ') am Anfang entfaellt."""
    if len(name) > 4 and name[:3].isdigit() and name[3] == " ":
        return name[4:]
    return name


def _sql_text(br, column, where, size=15000):
    """Lange Textspalte einer Zeile stueckweise lesen (eine Antwort fasst ca. 48 KB, ab 0.6 mehr)."""
    out, pos, size = [], 1, _page(br, size)
    while True:
        rows = br.sql("select substr(%s, %d, %d) t from %s" % (column, pos, size, where))
        piece = (rows[0]["t"] or "") if rows else ""
        out.append(piece)
        if len(piece) < size:
            return "".join(out)
        pos += size


def _exact_row(br, table, cols, key, keyval):
    """Eine Zeile lesen (Spalten cols) oder None."""
    rows = br.sql("select %s from %s where %s = %s" % (", ".join(cols), table, key, sql_lit(keyval)))
    return rows[0] if rows else None


SETTINGS_INLINE = 4000   # laengere Texte (State_Last ~34000 Zeichen) sprengen sonst die Antwortgrenze


def db_settings(br):
    """Tabelle settings als {name: value}. Kurze Werte kommen in der ersten Abfrage mit, lange
    werden je Zeile stueckweise ueber _sql_text nachgeladen."""
    big = "typeof(value) = 'text' and length(value) > %d" % _page(br, SETTINGS_INLINE)
    rows = br.sql("select name, %s as big, case when %s then null else value end as value from settings" % (big, big))
    return {r["name"]: _sql_text(br, "value", "settings where name = %s" % sql_lit(r["name"])) if r["big"] else r["value"]
            for r in rows}


RIG_ROW = ["id", "name", "content", "show_order", "author", "is_readonly", "color", "created_at", "prog_num"]


def db_rig(br, rig_id):
    """Vollstaendige Zeile eines Rigs (mit content) fuer den Export als .rig-Datei."""
    row = _exact_row(br, "rigs", RIG_ROW, "id", rig_id)
    if row is None:
        raise LiveError("Rig not found in the database.")
    return row


def rig_file_json(row):
    """Zeile der rigs-Tabelle als .rig-Datei (gleiche Form wie der USB-Export des Geraets)."""
    d = {"author": row.get("author", ""), "color": row.get("color", 0), "content": row["content"],
         "created_at": row.get("created_at", 0), "id": row["id"], "order": row.get("show_order", 0),
         "prog_num": row.get("prog_num", -1), "readonly": bool(row.get("is_readonly", 0))}
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)   # am Geraet byte-identisch geprueft


# ---- Komplettsicherung (Rigs, Setlists, Block-Presets als Dateien wie im USB-Transfer-Modus) ----
#
# Der USB-Modus zeigt Rigs\<Name>.rig, Setlists\<Name>.setlist und Blocks\<Typ>\<Name>.block.
# Alle drei Formen lassen sich aus den Tabellen rigs, setlists(+setlist_rigs) und blocks
# byte-identisch nachbauen (am Geraet gegen einen USB-Export geprueft). Die Sicherung legt
# die gleiche Ordnerstruktur an, damit sie im USB-Modus zurueckkopiert werden koennte.

_BAD_CHARS = '<>:"/\\|?*'
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def safe_filename(name):
    """Name als Windows-taugliche Datei: verbotene Zeichen -> '_', kein Punkt/Leerzeichen am Ende."""
    s = "".join("_" if c in _BAD_CHARS or ord(c) < 32 else c for c in str(name)).rstrip(" .")
    if not s or s.upper() in _RESERVED:
        s = "_" + s
    return s


def _unique_path(folder, name, ext, used):
    """Pfad in folder, der noch nicht vergeben ist (Windows unterscheidet keine Gross-/Kleinschreibung)."""
    base = safe_filename(name)
    cand, n = base, 1
    while (cand + ext).lower() in used:
        n += 1
        cand = "%s (%d)" % (base, n)
    used.add((cand + ext).lower())
    return os.path.join(folder, cand + ext)


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def db_setlist_rows(br):
    """Alle Setlists mit ihren Rigs in Reihenfolge: [(setlist_row, [(rig_id, rig_name)])]."""
    out = []
    for sl in br.sql("select id from setlists order by name collate nocase"):
        sl = _exact_row(br, "setlists", ["id", "name", "author", "is_readonly", "created_at"], "id", sl["id"])
        rr = br.sql("select s.rig_id, r.name from setlist_rigs s join rigs r on r.id = s.rig_id "
                    "where s.setlist_id = %s order by s.show_order" % sql_lit(sl["id"]))
        out.append((sl, [(r["rig_id"], r["name"]) for r in rr]))
    return out


def setlist_file_json(sl, rigs):
    """Setlist-Zeile + Rigs als .setlist-Datei (gleiche Form wie der USB-Export)."""
    d = {"author": sl.get("author", ""), "created_at": sl.get("created_at", 0), "id": sl["id"],
         "readonly": bool(sl.get("is_readonly", 0)), "rig_names": [n for _, n in rigs],
         "rigs": [i for i, _ in rigs], "version": "1.0.0"}
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def db_blocks(br, page=25):
    """Alle Block-Presets [{id, type, name, content, is_readonly}]; ca. 1 KB pro Zeile,
    darum in Seiten (Antwortgrenze ca. 48 KB, ab 0.6 mehr)."""
    rows, page = [], _page(br, page)
    while True:
        part = br.sql("select id, type, name, content, is_readonly from blocks "
                      "order by type, name limit %d offset %d" % (page, len(rows)))
        rows += part
        if len(part) < page:
            return rows


def block_file_json(row):
    """Zeile der blocks-Tabelle als .block-Datei (gleiche Form wie der USB-Export)."""
    d = {"content": row["content"], "id": row["id"], "readonly": bool(row.get("is_readonly", 0)),
         "type": row["type"]}
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---- Block-Presets ----
#
# Die Presets eines Blocktyps (am Geraet: Block-Menue > Preset) liegen in der Tabelle blocks:
# type = Basisname des Blocks in Grossbuchstaben ('GREEN JRC-OD', 'AMP', 'IR (1024)', 'MIX' fuer
# die Parallelwege), name = Presetname (Werkspresets beginnen mit '+'), content = JSON
# {"data": {"<Block>": {"childorder": [...], "children": {Param: Knoten}}}, "info": {...}} mit
# denselben Knoten wie in .rig-Dateien (type 0 value = unnormalized, 1/3 state, 4/8 string).
# Ohne On, Colour, Doubling, PresetName. Geladen wird durch Schreiben der Werte; das Geraet setzt
# dabei Rigs/Dirty nicht (wie bei allen Bridge-Schreibzugriffen), der Editor markiert selbst.
# PresetCtrl/LoadBlockPreset (mit SelectedBlockIndex/CurrentBlockPresetIndex) NICHT ausloesen:
# ohne die Preset-Liste am Display stuerzt die Geraete-App ab (Neustart, 'letzten Zustand
# wiederherstellen?'). Speichern/Umbenennen/Loeschen (SaveBlockPresetConfirmed usw.) ist
# ungetestet - die Bruecke kann die Datenbank nur lesen.
PRESET_SKIP = {"DoubleStates"}      # Action: state 1 kopiert A -> B, gehoert nicht zum Klang
PRESET_MODULE = {"Chain": "Mix"}    # Pseudo-Modul der Parallelwege: /Engine/Patch/Mix spiegelt Chain/Para*
                                    # und traegt den Presetnamen (Chain/PresetName gibt es nicht)


def preset_type(module):
    """blocks.type zu einem Modulnamen ('Green JRC-OD 2' -> 'GREEN JRC-OD')."""
    return _base_module(module).upper()


def _preset_rows(rows):
    return [{"id": r["id"], "type": r["type"], "name": r["name"], "readonly": bool(r.get("is_readonly", 0))}
            for r in rows]


def db_preset_names(br, page=150):
    """Namen aller Block-Presets: {TYP: [{id, type, name, readonly}]} in Geraete-Reihenfolge
    (nach Name; Werkspresets '+...' zuerst). ~720 Zeilen, seitenweise (Antwortgrenze ca. 48 KB)."""
    rows, page = [], _page(br, page)
    while True:
        part = br.sql("select id, type, name, is_readonly from blocks "
                      "order by type, name limit %d offset %d" % (page, len(rows)))
        rows += _preset_rows(part)
        if len(part) < page:
            break
    out = {}
    for r in rows:
        out.setdefault(r["type"], []).append(r)
    return out


def db_presets_of(br, module):
    """Presets eines Blocktyps [{id, type, name, readonly}]."""
    rows = br.sql("select id, type, name, is_readonly from blocks where type = %s "
                  "order by name" % sql_lit(preset_type(module)))
    return _preset_rows(rows)


def db_preset_content(br, preset_id):
    row = _exact_row(br, "blocks", ["id", "name", "content"], "id", preset_id)
    if row is None:
        raise LiveError("Preset not found in the database.")
    return row


def preset_name_path(module, half="A"):
    """Pfad des Presetnamens eines Blocks (Haelfte B eines doppelten Blocks: PresetName2)."""
    return LiveRig.path(PRESET_MODULE.get(module, module), "PresetName" + ("2" if half == "B" else ""))


def preset_writes(module, content, half="A"):
    """Schreibvorgaenge [(pfad, feld, wert)] zum Laden eines Presets in den Block 'module'
    (Haelfte B eines doppelten Blocks: Parameter mit Endung 2)."""
    data = json.loads(content)["data"] if isinstance(content, str) else content["data"]
    node = next(iter(data.values()), {})
    children = node.get("children", {})
    order = [k for k in node.get("childorder", []) if k in children]
    order += sorted(k for k in children if k not in order)
    module = PRESET_MODULE.get(module, module)
    out = []
    for p in order:
        if p in PRESET_SKIP:
            continue
        n = children[p]
        t = n.get("type")
        if t == 0:
            field, value = "unnormalized", n.get("value")
        elif t in (1, 3):
            field, value = "state", int(bool(n.get("state")))
        else:
            field, value = "string", n.get("string", "")
        if value is None:
            continue
        out.append((LiveRig.path(module, p + ("2" if half == "B" else "")), field, value))
    return out


def load_block_preset(br, module, preset, half="A"):
    """Preset {id, name} in den Block laden: Werte schreiben und den Presetnamen setzen.
    Liefert die Zahl der geschriebenen Parameter."""
    row = db_preset_content(br, preset["id"])
    writes = preset_writes(module, row["content"], half)
    if not writes:
        raise LiveError("Preset '%s' contains no parameters." % preset["name"])
    done = 0
    for path, field, value in writes:
        try:
            r = br.set(path, field, value)
        except BridgeError as e:
            if "no property" in str(e):   # z.B. TremSync hat keinen Zwilling TremSync2 in Haelfte B
                continue
            raise
        if not r.get("ok"):
            raise LiveError("%s: %s" % (path.rsplit("/", 1)[1], r.get("err")))
        done += 1
    if not done:
        raise LiveError("None of the parameters of preset '%s' exists on the device." % preset["name"])
    br.set(preset_name_path(module, half), "string", preset["name"])
    return done


RIG_BATCH = 20   # Rigs je Anfrage in backup_all ab Bruecke 0.6 (Rig-Inhalt ~25 KB)


def backup_all(br, folder, progress=None):
    """Alle Rigs, Setlists und Block-Presets aus der Datenbank des Geraets nach folder
    schreiben (Rigs\\, Setlists\\, Blocks\\<Typ>\\ + Sicherung.txt). progress(text) meldet
    den Fortschritt. Liefert {"rigs", "setlists", "blocks", "folder", "seconds"}.
    Dauer: ca. 8 MB Rig-Inhalt bei ~100 KB/s -> gut eine Minute."""
    t0 = time.time()

    def say(txt):
        if progress:
            progress(txt)
    say("Reading rig list …")
    rigs = db_rigs(br)
    rig_dir, set_dir, blk_dir = (os.path.join(folder, d) for d in ("Rigs", "Setlists", "Blocks"))
    for d in (rig_dir, set_dir, blk_dir):
        os.makedirs(d, exist_ok=True)
    used = set()
    if getattr(br, "long", False):
        # ab 0.6: RIG_BATCH Rigs je Anfrage (~0,5 MB), Namen kommen exakt (Zeichen-Escapes)
        done = 0
        while True:
            part = br.sql("select %s from rigs order by rowid limit %d offset %d"
                          % (", ".join(RIG_ROW), RIG_BATCH, done), timeout=60)
            for row in part:
                done += 1
                say("Backing up rig %d of %d: %s" % (done, len(rigs), display_name(row["name"])))
                _write(_unique_path(rig_dir, row["name"], ".rig", used), rig_file_json(row))
            if len(part) < RIG_BATCH:
                break
        if done != len(rigs):
            raise LiveError("Backup: %d rigs read, but the list has %d - please try again." % (done, len(rigs)))
    else:
        for n, r in enumerate(rigs, 1):
            say("Backing up rig %d of %d: %s" % (n, len(rigs), display_name(r["name"])))
            row = db_rig(br, r["id"])   # liefert auch den exakten Namen (Umlaute)
            _write(_unique_path(rig_dir, row["name"], ".rig", used), rig_file_json(row))
    say("Backing up setlists …")
    setlists = db_setlist_rows(br)
    used = set()
    for sl, rr in setlists:
        _write(_unique_path(set_dir, sl["name"], ".setlist", used), setlist_file_json(sl, rr))
    say("Backing up block presets …")
    blocks = db_blocks(br)
    used = {}
    for b in blocks:
        tdir = os.path.join(blk_dir, safe_filename(b["type"]))
        os.makedirs(tdir, exist_ok=True)
        _write(_unique_path(tdir, b["name"], ".block", used.setdefault(tdir, set())), block_file_json(b))
    settings = {}
    try:
        settings = db_settings(br)
        _write(os.path.join(folder, "Einstellungen.json"),
               json.dumps(settings, sort_keys=True, indent=1, ensure_ascii=False))
    except Exception:
        pass   # nur Beiwerk, die Rigs sind das Wichtige
    secs = time.time() - t0
    info = ["MX5 Editor - backup of %s" % time.strftime("%d.%m.%Y %H:%M"),
            "Bridge: %s" % getattr(br, "version", "?"),
            "Database: db_version %s, RigVersion %s" % (settings.get("db_version", "?"), settings.get("RigVersion", "?")),
            "",
            "%d rigs in Rigs\\, %d setlists in Setlists\\, %d block presets in Blocks\\<type>\\" % (
                len(rigs), len(setlists), len(blocks)),
            "Einstellungen.json: table settings (GlobalSettings, State_Last, ...)",
            "",
            "The files have the same form as the MX5's export in USB transfer mode",
            "(Rigs\\, Setlists\\, Blocks\\ on the MX5 drive). Restore: in the editor with",
            "'Restore everything' (bridge 0.4), or put the MX5 into USB transfer mode and copy the folders.",
            "Whether the MX5 takes over copied-back files on sync (especially overwritten,",
            "already existing ones) is untested - try it with a single rig first.",
            "Backup duration: %.0f s" % secs]
    _write(os.path.join(folder, "Sicherung.txt"), "\r\n".join(info) + "\r\n")
    return {"rigs": len(rigs), "setlists": len(setlists), "blocks": len(blocks), "folder": folder, "seconds": secs}


def read_rig_list(br):
    """Setlists und die Rig-Liste der aktiven Liste aus der Datenbank: {setlists, setlist, sure,
    rows, setlist_ids, status}. Welche Liste aktiv ist, meldet das Geraet nicht (settings.State_Last
    traegt sie, wird aber nur beim Beenden der App geschrieben - geprueft 2026-09-30); sie wird
    erkannt, indem die gerade gezeigte Bank in allen Listen gesucht wird (sure=False: nicht
    eindeutig, geraten). Die Set-Anzeige wird nicht durchgeblaettert: ihre Reihenfolge ist die
    Namensreihenfolge der Datenbank, und seek_setlist findet eine Setlist auch sonst. Ist die
    aktive Liste erkannt, wird sie neu betreten (enter_setlist active=True), damit der Zeiger fuer
    jump bekannt ist."""
    cursor = read_set_cursor(br)
    sets = db_setlists(br)
    names = [n for _, n in sets]
    ids = {n: i for i, n in sets}
    lists = [(ALL_RIGS, db_rigs(br))] + [(n, db_rigs(br, i)) for i, n in sets]
    shown = _bank_names(br)
    exact, close = [], []
    for name, rows in lists:
        banks = [bank_names(rows, b) for b in range(bank_count(rows))]
        if shown in banks:
            exact.append(name)
        elif any(len(set(shown) & set(b) - {EMPTY_RIG}) >= 2 for b in banks):
            close.append(name)
    if len(exact) == 1:
        active, sure = exact[0], True
    elif not exact and len(close) == 1:
        active, sure = close[0], True
    else:
        active = cursor if cursor in names else ALL_RIGS
        sure = not names
    if sure:
        # die aktive Liste einmal neu betreten (~1 s, laedt nichts, das Rig behaelt seine Aenderungen):
        # danach steht der Geraete-Zeiger fuer jump bekannt auf Platz 0
        return enter_setlist(br, names, active, ids, active=True)
    br.cursor = None
    return {"setlists": names, "setlist": active, "sure": sure, "rows": dict(lists)[active],
            "status": rig_status(br), "setlist_ids": ids}


def _wait_stable(br, read, gap=0.2, tries=15):
    """Warten, bis zwei Lesungen im Abstand 'gap' gleich sind."""
    prev = read(br)
    for _ in range(tries):
        time.sleep(gap)
        cur = read(br)
        if cur == prev:
            return cur
        prev = cur
    return prev


def open_save_dialog(br, timeout=2.0):
    """Speichern-Dialog (cancel | save | save_new_rig) am Geraet oeffnen und warten, bis er steht.
    Erscheint er nach der halben Zeit nicht (zweimal beobachtet 2026-09-30, jeweils im Lauf direkt
    nach einem App-Neustart, gezielt nicht nachstellbar), wird er einmal erneut angefordert - nur
    ohne offenen Dialog. Kommt er gar nicht, wird noch kurz nachgesehen: ein verspaetet
    aufgegangener Speichern-Dialog wird mit Cancel geschlossen, damit das Geraet nicht mit offenem
    Dialog stehen bleibt (sonst scheitern alle folgenden Aktionen)."""
    br.set(SAVE, "state", 1)
    end = time.time() + timeout
    retry = time.time() + timeout / 2
    while True:
        b = dialog_buttons(br)
        if b and b[1].strip().lower().startswith("save"):
            return b
        if retry and time.time() >= retry and not b:
            retry = None
            br.set(SAVE, "state", 1)
        if time.time() >= end:
            break
        time.sleep(0.05)
    for _ in range(20):   # 2 s nachsehen
        time.sleep(0.1)
        late = dialog_buttons(br)
        if late and late[1].strip().lower().startswith("save"):
            press(br, FS % 1)   # Cancel
            break
    raise LiveError("The save dialog did not appear on the MX5 in time%s - nothing was saved."
                    % (" (open: %s)" % " | ".join(b) if b else ""))


def save_rig(br):
    """Speichern-Dialog oeffnen und 'save' (FS2) druecken. Liefert den Rig-Status."""
    open_save_dialog(br)
    press(br, FS % 2)
    return wait_for(br, lambda s: not s["dirty"])


def cancel_dialog(br):
    press(br, FS % 1)


# ---- Rig-Datenbank schreiben (Bruecke 0.4) ----
#
# Rigs, Setlists und Programmnummern werden direkt in evil.db geschrieben (eine
# Transaktion je Aufruf, Rollback beim ersten Fehler; der Datenbankdienst sichert
# die Datenbank vor dem ersten Schreiben nach dem Einschalten). Die Geraete-App
# liest Listen, Farben, Namen und Programmnummern aber nur beim Betreten einer
# Liste neu (AccessRigView / AccessSet1) - darum nach jedem Schreiben refresh_lists
# (betritt die aktive Liste erneut, laedt dabei nichts, ca. 1 s). Das geladene Rig
# behaelt seinen Zustand im Speicher; wird seine Zeile geaendert, muss es neu geladen
# werden (refresh_lists reload_row=True). Eine andere als die aktive Liste braucht
# kein Auffrischen - das Geraet liest sie beim naechsten Betreten ohnehin frisch.
# Am Geraet verifiziert 2026-09-17: anlegen (Kopie), umbenennen, Farbe, Programm-
# nummer, Setlist-Eintrag, loeschen (Cascade auf setlist_rigs), Als neues Rig
# (save_rig_as).

RIG_AUTHOR = "UserName"     # so tragen vom Geraet gespeicherte Rigs ihren Autor ein
MAX_PROG = 128


def new_id():
    import uuid
    return str(uuid.uuid4())


def check_rig_name(name):
    """Rig-Namen wie das Geraet begrenzen (Grossbuchstaben, ASCII, max. 32 Zeichen)."""
    name = " ".join(name.split())
    if not name:
        raise LiveError("The name must not be empty.")
    if len(name) > 32:
        raise LiveError("The name may be at most 32 characters long.")
    if any(not 0x20 <= ord(c) <= 0x7E for c in name):
        raise LiveError("ASCII characters only (no umlauts) - like names entered on the MX5.")
    return name.upper()


def db_name_taken(br, table, name, except_id=None):
    """True, wenn es in table schon eine Zeile mit diesem Namen gibt (ohne Gross/Klein)."""
    where = "name = %s collate nocase" % sql_lit(name)
    if except_id:
        where += " and id <> %s" % sql_lit(except_id)
    return bool(br.sql("select 1 from %s where %s limit 1" % (table, where)))


def db_prognum_owner(br, prog, except_id=None):
    """Name des Rigs, das die Programmnummer (Anzeige 1..128) schon hat, sonst None."""
    where = "prog_num = %d" % (prog - 1)
    if except_id:
        where += " and id <> %s" % sql_lit(except_id)
    rows = br.sql("select name from rigs where %s limit 1" % where)
    return rows[0]["name"] if rows else None


def content_with_name(content, name):
    """Rig-Inhalt (JSON-Text wie in der Datenbank / .rig-Datei) mit neuem Rig/PresetName.
    Der Inhalt ist kompaktes JSON mit sortierten Schluesseln (am Geraet verifiziert), darum
    bleibt alles andere byte-identisch."""
    try:
        c = json.loads(content)
        c["data"]["Patch"]["children"]["Rig"]["children"]["PresetName"]["string"] = name
    except (ValueError, KeyError, TypeError) as e:
        raise LiveError("Rig content not readable (%s)." % e)
    return json.dumps(c, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def create_rig(br, name, src_id=None, content=None, color=0, prog=None, setlist_id=None):
    """Neues Rig anlegen: Kopie von src_id (Inhalt aus der Datenbank) oder mit content
    (Inhaltstext einer .rig-Datei); der innere Rig/PresetName wird auf name gesetzt.
    prog = Anzeige-Programmnummer oder None. setlist_id: ausserdem ans Ende dieser Setlist
    haengen. Liefert die neue ID. (Anfragen bis 100 KB kommen durch, Rigs sind < 30 KB.)"""
    name = check_rig_name(name)
    if db_name_taken(br, "rigs", name):
        raise LiveError("There is already a rig called '%s'." % name)
    if prog is not None:
        owner = db_prognum_owner(br, prog)
        if owner:
            raise LiveError("Program number %d already belongs to rig '%s'." % (prog, owner))
    if src_id:
        content = db_rig(br, src_id)["content"]
    elif content is None:
        raise LiveError("create_rig needs src_id or content.")
    content = content_with_name(content, name)
    rid = new_id()
    pn = -1 if prog is None else prog - 1
    sql = ("insert into rigs (id, name, content, show_order, author, is_readonly, color, created_at, prog_num) "
           "values (%s, %s, %s, 0, %s, 0, %d, strftime('%%s','now'), %d)"
           % (sql_lit(rid), sql_lit(name), sql_lit(content), sql_lit(RIG_AUTHOR), color, pn))
    if setlist_id:
        sql += "; " + _setlist_append_sql(setlist_id, rid)
    if br.sql_write(sql) < 1:
        raise LiveError("The rig was not created (source not found?).")
    return rid


def rename_rig(br, rig_id, name):
    name = check_rig_name(name)
    if db_name_taken(br, "rigs", name, rig_id):
        raise LiveError("There is already a rig called '%s'." % name)
    content = content_with_name(db_rig(br, rig_id)["content"], name)   # auch der innere PresetName
    br.sql_write("update rigs set name = %s, content = %s where id = %s"
                 % (sql_lit(name), sql_lit(content), sql_lit(rig_id)))
    return name


def set_rig_color(br, rig_id, color):
    br.sql_write("update rigs set color = %d where id = %s" % (int(color), sql_lit(rig_id)))


def set_rig_prognum(br, rig_id, prog):
    """Programmnummer (Anzeige 1..128) setzen, None = keine. Eine belegte Nummer wird
    dem anderen Rig weggenommen (wie am Geraet)."""
    if prog is None:
        pn = -1
    else:
        if not 1 <= int(prog) <= MAX_PROG:
            raise LiveError("Program numbers go from 1 to %d." % MAX_PROG)
        pn = int(prog) - 1
    sql = "update rigs set prog_num = %d where id = %s" % (pn, sql_lit(rig_id))
    if pn >= 0:
        sql = "update rigs set prog_num = -1 where prog_num = %d and id <> %s; " % (pn, sql_lit(rig_id)) + sql
    br.sql_write(sql)


def delete_rig(br, rig_id):
    """Rig loeschen (Setlist-Eintraege verschwinden mit). Nicht fuer das geladene Rig."""
    if rig_status(br)["id"] == rig_id:
        raise LiveError("The loaded rig cannot be deleted - load another one first.")
    return br.sql_write("delete from rigs where id = %s" % sql_lit(rig_id))


def save_rig_as(br, name, setlist_id=None, prog=None):
    """Das geladene Rig mit seinem aktuellen Stand (auch ungespeicherte Aenderungen) als
    neues Rig anlegen (Bruecke 0.4) - Ersatz fuer 'save_new_rig', dessen Namenseingabe nur
    am Touchscreen geht. Weg: gespeicherten Inhalt der Zeile merken, am Geraet speichern
    (die Zeile traegt dann den Live-Stand), diesen als neue Zeile mit neuem Namen kopieren
    und die alte Zeile zuruecksetzen - beides in einer Transaktion. Danach ist das alte Rig
    geladen und sauber (im Speicher mit dem Live-Stand, in der Datenbank wie zuvor); der
    Aufrufer laedt das neue Rig (refresh_lists). setlist_id: ausserdem ans Ende dieser
    Setlist haengen. Liefert die neue ID."""
    name = check_rig_name(name)
    if db_name_taken(br, "rigs", name):
        raise LiveError("There is already a rig called '%s'." % name)
    if prog is not None:
        owner = db_prognum_owner(br, prog)
        if owner:
            raise LiveError("Program number %d already belongs to rig '%s'." % (prog, owner))
    st = rig_status(br)
    if not st["id"]:
        raise LiveError("No rig is loaded on the MX5.")
    old = db_rig(br, st["id"])
    st = save_rig(br)
    if st["dirty"]:
        raise LiveError("The MX5 did not save. Is a dialog open on the display?")
    content = content_with_name(db_rig(br, old["id"])["content"], name)
    rid = new_id()
    sql = ("insert into rigs (id, name, content, show_order, author, is_readonly, color, created_at, prog_num) "
           "values (%s, %s, %s, 0, %s, 0, %d, strftime('%%s','now'), %d); "
           "update rigs set content = %s where id = %s"
           % (sql_lit(rid), sql_lit(name), sql_lit(content), sql_lit(RIG_AUTHOR), int(old.get("color") or 0),
              -1 if prog is None else prog - 1, sql_lit(old["content"]), sql_lit(old["id"])))
    if setlist_id:
        sql += "; " + _setlist_append_sql(setlist_id, rid)
    try:
        br.sql_write(sql)
    except BridgeError as e:
        raise LiveError("'%s' was saved under its old name, the copy '%s' was not created: %s"
                        % (old["name"], name, e))
    return rid


def _setlist_append_sql(setlist_id, rig_id):
    return ("insert into setlist_rigs (id, setlist_id, rig_id, show_order) "
            "select %s, %s, %s, coalesce(max(show_order), -1) + 1 from setlist_rigs where setlist_id = %s"
            % (sql_lit(new_id()), sql_lit(setlist_id), sql_lit(rig_id), sql_lit(setlist_id)))


def create_setlist(br, name, rig_ids=()):
    name = check_rig_name(name)
    if db_name_taken(br, "setlists", name):
        raise LiveError("There is already a setlist called '%s'." % name)
    sid = new_id()
    sql = ("insert into setlists (id, name, author, is_readonly, created_at) values (%s, %s, %s, 0, strftime('%%s','now'))"
           % (sql_lit(sid), sql_lit(name), sql_lit(RIG_AUTHOR)))
    for n, rid in enumerate(rig_ids):
        sql += "; insert into setlist_rigs (id, setlist_id, rig_id, show_order) values (%s, %s, %s, %d)" % (
            sql_lit(new_id()), sql_lit(sid), sql_lit(rid), n)
    br.sql_write(sql)
    return sid


def rename_setlist(br, setlist_id, name):
    name = check_rig_name(name)
    if db_name_taken(br, "setlists", name, setlist_id):
        raise LiveError("There is already a setlist called '%s'." % name)
    br.sql_write("update setlists set name = %s where id = %s" % (sql_lit(name), sql_lit(setlist_id)))
    return name


def delete_setlist(br, setlist_id):
    """Setlist loeschen; die Rigs bleiben erhalten."""
    return br.sql_write("delete from setlists where id = %s" % sql_lit(setlist_id))


def setlist_add(br, setlist_id, rig_id):
    """Rig ans Ende der Setlist haengen (ein Rig darf mehrfach vorkommen, wie am Geraet)."""
    br.sql_write(_setlist_append_sql(setlist_id, rig_id))


def setlist_set_order(br, setlist_id, rig_ids):
    """Setlist komplett neu befuellen: rig_ids in dieser Reihenfolge (entfernen, sortieren,
    einfuegen in einem Schritt)."""
    sql = "delete from setlist_rigs where setlist_id = %s" % sql_lit(setlist_id)
    for n, rid in enumerate(rig_ids):   # None = Platz eines fehlenden Rigs (rig_id NULL, wie am Geraet)
        sql += "; insert into setlist_rigs (id, setlist_id, rig_id, show_order) values (%s, %s, %s, %d)" % (
            sql_lit(new_id()), sql_lit(setlist_id), "null" if rid is None else sql_lit(rid), n)
    br.sql_write(sql)


def db_setlist_rig_ids(br, setlist_id):
    return [r["rig_id"] for r in br.sql("select rig_id from setlist_rigs where setlist_id = %s order by show_order"
                                        % sql_lit(setlist_id))]


def db_setlist_members(br):
    """Alle Setlists mit ihren Rig-IDs in Reihenfolge: {setlist_id: [rig_id oder None]}
    (seitenweise, die Antwort waere bei vielen Eintraegen sonst zu gross)."""
    q = "select setlist_id, rig_id from setlist_rigs order by setlist_id, show_order"
    out, rows, page = {}, [], _page(br, 400)
    while True:
        part = br.sql("%s limit %d offset %d" % (q, page, len(rows)))
        rows += part
        if len(part) < page:
            break
    for r in rows:
        out.setdefault(r["setlist_id"], []).append(r.get("rig_id"))
    return out


def set_rig_prognums(br, pairs):
    """Mehrere Programmnummern in einer Transaktion setzen: pairs = [(rig_id, Anzeige-Nummer)].
    Wer eine der Nummern schon hat, verliert sie (wie set_rig_prognum)."""
    sql = []
    for rid, prog in pairs:
        if not 1 <= int(prog) <= MAX_PROG:
            raise LiveError("Program numbers go from 1 to %d." % MAX_PROG)
        pn = int(prog) - 1
        sql.append("update rigs set prog_num = -1 where prog_num = %d and id <> %s" % (pn, sql_lit(rid)))
        sql.append("update rigs set prog_num = %d where id = %s" % (pn, sql_lit(rid)))
    if sql:
        br.sql_write("; ".join(sql))


# ---- Block-Preset speichern (Bruecke 0.4) ----
#
# Ein Nutzerpreset ist der Block-Teilbaum des Rigs (data.Patch.children.<Block>) ohne
# PresetName/PresetName2/Doubling/On/Colour und ohne die Parameter der Haelfte B (Endung 2),
# in der Reihenfolge des Rigs, unter dem Basisnamen des Blocks, mit info.version 1.0.9
# (aus 10 Nutzerpresets des Geraets abgeleitet). Die Werte kommen live vom Geraet, damit
# auch ungespeicherte Aenderungen im Preset landen.

PRESET_OMIT = {"PresetName", "PresetName2", "Doubling", "On", "Colour"}
PRESET_VERSION = "1.0.9"


def _base_module(module):
    return base_name(PRESET_MODULE.get(module, module))


def preset_content_from_rig(content, module, half="A"):
    """Preset-Inhalt (JSON-Text) fuer den Block 'module' aus einem Rig-Inhalt; half='B' nimmt
    die Parameter mit Endung 2 (ohne Endung gespeichert)."""
    try:
        patch = json.loads(content)["data"]["Patch"]["children"]
    except (ValueError, KeyError, TypeError) as e:
        raise LiveError("Rig content not readable (%s)." % e)
    key = PRESET_MODULE.get(module, module)
    if key not in patch:
        raise LiveError("Block '%s' is not in the saved rig - please save first." % module)
    node = patch[key]
    children = node.get("children", {})
    order, out = [], {}
    for p in node.get("childorder", []) + sorted(k for k in children if k not in node.get("childorder", [])):
        if p in PRESET_OMIT or p not in children:
            continue
        is_b = len(p) > 1 and p.endswith("2") and p[:-1] in children and p[:-1] not in PRESET_OMIT
        if half == "B":
            if not is_b:
                continue
            name = p[:-1]
        else:
            if is_b:
                continue
            name = p
        if name in out:
            continue
        order.append(name)
        out[name] = dict(children[p])
    if not out:
        raise LiveError("Block '%s' has no parameters for a preset." % module)
    return json.dumps({"data": {_base_module(module): {"childorder": order, "children": out}},
                       "info": {"version": PRESET_VERSION}}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def preset_content_live(br, content, module, half="A"):
    """Wie preset_content_from_rig, aber mit den aktuellen Werten vom Geraet."""
    text = preset_content_from_rig(content, module, half)
    d = json.loads(text)
    blk = next(iter(d["data"].values()))
    mod = PRESET_MODULE.get(module, module)
    suffix = "2" if half == "B" else ""
    paths = {LiveRig.path(mod, p + suffix): p for p in blk["childorder"] if p not in PRESET_SKIP}
    info = br.get_many(list(paths))
    for path, p in paths.items():
        i = info.get(path) or {}
        if not i.get("ok"):
            continue
        n = blk["children"][p]
        t = n.get("type")
        if t == 0 and i.get("unnormalized") is not None:
            v = i["unnormalized"]
            n["value"] = int(v) if float(v).is_integer() else v
        elif t in (1, 3) and i.get("state") is not None:
            n["state"] = bool(i["state"])
        elif t in (4, 8) and i.get("string") is not None:
            n["string"] = i["string"]
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def save_block_preset(br, rig_id, module, name, half="A", live=True, replace=False):
    """Preset des Blocks 'module' des Rigs rig_id unter 'name' in der Datenbank anlegen
    (Bruecke 0.4). live=True: aktuelle Werte vom Geraet, sonst die des gespeicherten Rigs.
    replace=True: ein eigenes Preset gleichen Namens ueberschreiben. Setzt danach den
    Presetnamen des Blocks am Geraet. Liefert (preset_id, 'neu'|'ersetzt')."""
    name = " ".join(name.split())   # Presetnamen duerfen Kleinbuchstaben haben (wie am Geraet)
    if not name:
        raise LiveError("The preset name must not be empty.")
    if name.startswith("+"):
        raise LiveError("Names starting with '+' are reserved for factory presets.")
    typ = preset_type(module)
    content = db_rig(br, rig_id)["content"]
    text = preset_content_live(br, content, module, half) if live else preset_content_from_rig(content, module, half)
    rows = br.sql("select id, is_readonly from blocks where type = %s and name = %s collate nocase"
                  % (sql_lit(typ), sql_lit(name)))
    if rows:
        if rows[0].get("is_readonly") or not replace:
            raise LiveError("There is already a preset '%s' for %s." % (name, typ))
        pid = rows[0]["id"]
        br.sql_write("update blocks set content = %s where id = %s" % (sql_lit(text), sql_lit(pid)))
        what = "ersetzt"
    else:
        pid = new_id()
        br.sql_write("insert into blocks (id, type, name, content, is_readonly) values (%s, %s, %s, %s, 0)"
                     % (sql_lit(pid), sql_lit(typ), sql_lit(name), sql_lit(text)))
        what = "neu"
    br.set(preset_name_path(module, half), "string", name)
    return pid, what


def delete_block_preset(br, preset_id):
    rows = br.sql("select is_readonly from blocks where id = %s" % sql_lit(preset_id))
    if rows and rows[0].get("is_readonly"):
        raise LiveError("Factory presets cannot be deleted.")
    return br.sql_write("delete from blocks where id = %s" % sql_lit(preset_id))


# ---- Dateien auf das Geraet (Umkehrung von backup_all) ----

def _read_json_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise LiveError("%s: not readable (%s)" % (os.path.basename(path), e))


def rig_name_of_file(d, path):
    """Name eines Rigs aus einer .rig-Datei: innerer PresetName, sonst Dateiname."""
    try:
        return json.loads(d["content"])["data"]["Patch"]["children"]["Rig"]["children"]["PresetName"]["string"]
    except (KeyError, ValueError, TypeError):
        return os.path.splitext(os.path.basename(path))[0]


def db_ids(br, table, page=500):
    ids, page = set(), _page(br, page)
    while True:
        part = br.sql("select id from %s limit %d offset %d" % (table, page, len(ids)))
        ids.update(r["id"] for r in part)
        if len(part) < page:
            return ids


def import_rig_file(br, path, name=None, mode="new", setlist_id=None, keep_prog=False):
    """Eine .rig-Datei auf das Geraet bringen. mode: 'new' = neues Rig mit neuer ID (Name aus
    der Datei oder name), 'replace' = Rig mit der ID aus der Datei ueberschreiben (Inhalt,
    Farbe), 'restore' = mit der ID aus der Datei anlegen, falls es sie noch nicht gibt (sonst
    nichts tun). keep_prog: Programmnummer der Datei uebernehmen, wenn sie frei ist.
    Liefert (rig_id, 'neu'|'ersetzt'|'vorhanden')."""
    d = _read_json_file(path)
    if "content" not in d:
        raise LiveError("%s is not a .rig file." % os.path.basename(path))
    name = name or rig_name_of_file(d, path)
    # Namen aus Dateien so lassen, wie das Geraet sie geschrieben hat (auch Umlaute: sql_lit
    # kodiert sie hex); nur ein frei gewaehlter Name wird wie am Geraet geprueft
    name = check_rig_name(name) if mode == "new" else (" ".join(name.split()) or os.path.basename(path))
    color = int(d.get("color") or 0)
    prog = int(d.get("prog_num", -1)) + 1 if keep_prog and int(d.get("prog_num", -1)) >= 0 else None
    if prog and db_prognum_owner(br, prog):
        prog = None
    fid = d.get("id") or new_id()
    exists = bool(br.sql("select 1 from rigs where id = %s" % sql_lit(fid)))
    if mode == "replace" and exists:
        content = content_with_name(d["content"], name)
        sql = "update rigs set content = %s, color = %d" % (sql_lit(content), color)
        if prog is not None:
            sql += ", prog_num = %d" % (prog - 1)
        br.sql_write(sql + " where id = %s" % sql_lit(fid))
        return fid, "ersetzt"
    if mode == "restore":
        if exists:
            return fid, "vorhanden"
        if db_name_taken(br, "rigs", name):
            name = _free_name(br, "rigs", name)
        content = content_with_name(d["content"], name)
        pn = -1 if prog is None else prog - 1
        sql = ("insert into rigs (id, name, content, show_order, author, is_readonly, color, created_at, prog_num) "
               "values (%s, %s, %s, %d, %s, 0, %d, %d, %d)"
               % (sql_lit(fid), sql_lit(name), sql_lit(content), int(d.get("order") or 0),
                  sql_lit(d.get("author") or RIG_AUTHOR), color, int(d.get("created_at") or time.time()), pn))
        if setlist_id:
            sql += "; " + _setlist_append_sql(setlist_id, fid)
        br.sql_write(sql)
        return fid, "neu"
    if db_name_taken(br, "rigs", name):
        name = _free_name(br, "rigs", name)
    rid = create_rig(br, name, content=d["content"], color=color, prog=prog, setlist_id=setlist_id)
    return rid, "neu"


def _free_name(br, table, name):
    """'NAME' -> 'NAME 2', 'NAME 3', ... bis der Name frei ist."""
    base = name[:29]
    for n in range(2, 100):
        cand = "%s %d" % (base, n)
        if not db_name_taken(br, table, cand):
            return cand
    raise LiveError("No free name for '%s'." % name)


def import_setlist_file(br, path, rig_ids_present):
    """Eine .setlist-Datei anlegen, falls die ID fehlt. Rigs, die es nicht gibt, werden
    wie am Geraet leere Plaetze (rig_id NULL). Liefert 'neu'|'vorhanden'."""
    d = _read_json_file(path)
    if "rigs" not in d:
        raise LiveError("%s is not a .setlist file." % os.path.basename(path))
    sid = d.get("id") or new_id()
    if br.sql("select 1 from setlists where id = %s" % sql_lit(sid)):
        return "vorhanden"
    name = os.path.splitext(os.path.basename(path))[0]
    if db_name_taken(br, "setlists", name):
        name = _free_name(br, "setlists", name)
    sql = ("insert into setlists (id, name, author, is_readonly, created_at) values (%s, %s, %s, 0, %d)"
           % (sql_lit(sid), sql_lit(name), sql_lit(d.get("author") or RIG_AUTHOR), int(d.get("created_at") or time.time())))
    for n, rid in enumerate(d["rigs"]):
        sql += "; insert into setlist_rigs (id, setlist_id, rig_id, show_order) values (%s, %s, %s, %d)" % (
            sql_lit(new_id()), sql_lit(sid), sql_lit(rid) if rid in rig_ids_present else "NULL", n)
    br.sql_write(sql)
    return "neu"


def import_block_file(br, path):
    """Eine .block-Datei (Block-Preset) anlegen, falls ID und (Typ, Name) frei sind.
    Der Presetname ist der Dateiname. Liefert 'neu'|'vorhanden'."""
    d = _read_json_file(path)
    if "content" not in d or "type" not in d:
        raise LiveError("%s is not a .block file." % os.path.basename(path))
    bid = d.get("id") or new_id()
    name = os.path.splitext(os.path.basename(path))[0]
    if br.sql("select 1 from blocks where id = %s or (type = %s and name = %s)"
              % (sql_lit(bid), sql_lit(d["type"]), sql_lit(name))):
        return "vorhanden"
    br.sql_write("insert into blocks (id, type, name, content, is_readonly) values (%s, %s, %s, %s, 0)"
                 % (sql_lit(bid), sql_lit(d["type"]), sql_lit(name), sql_lit(d["content"])))
    return "neu"


def restore_all(br, folder, progress=None, replace=False):
    """Umkehrung von backup_all: Rigs\\, Setlists\\, Blocks\\ aus folder auf das Geraet.
    Rigs und Presets, die es (nach ID) schon gibt, bleiben unangetastet - mit replace=True
    werden vorhandene Rigs ueberschrieben. Setlists werden nur angelegt, wenn ihre ID fehlt.
    Danach ist ein App-Neustart noetig (restart_app), damit das Geraet neue Setlists sieht.
    Liefert Zaehler und Fehlerliste."""
    say = progress or (lambda t: None)
    counts = {"rigs": 0, "rigs_ersetzt": 0, "rigs_vorhanden": 0, "setlists": 0, "blocks": 0, "fehler": []}
    rig_dir, set_dir, blk_dir = (os.path.join(folder, d) for d in ("Rigs", "Setlists", "Blocks"))
    rig_files = sorted(f for f in os.listdir(rig_dir) if f.lower().endswith(".rig")) if os.path.isdir(rig_dir) else []
    present = db_ids(br, "rigs")
    for n, f in enumerate(rig_files, 1):
        say("Rig %d of %d: %s" % (n, len(rig_files), f[:-4]))
        try:
            d = _read_json_file(os.path.join(rig_dir, f))
            mode = "replace" if replace and d.get("id") in present else "restore"
            rid, what = import_rig_file(br, os.path.join(rig_dir, f), mode=mode, keep_prog=True)
            counts["rigs" if what == "neu" else "rigs_" + what] += 1
            present.add(rid)
        except LiveError as e:
            counts["fehler"].append(str(e))
    if os.path.isdir(set_dir):
        for f in sorted(os.listdir(set_dir)):
            if not f.lower().endswith(".setlist"):
                continue
            say("Setlist %s" % f[:-8])
            try:
                if import_setlist_file(br, os.path.join(set_dir, f), present) == "neu":
                    counts["setlists"] += 1
            except LiveError as e:
                counts["fehler"].append(str(e))
    if os.path.isdir(blk_dir):
        files = [os.path.join(r, f) for r, _, fs in os.walk(blk_dir) for f in fs if f.lower().endswith(".block")]
        for n, p in enumerate(sorted(files), 1):
            if n % 10 == 1:
                say("Block preset %d of %d" % (n, len(files)))
            try:
                if import_block_file(br, p) == "neu":
                    counts["blocks"] += 1
            except LiveError as e:
                counts["fehler"].append(str(e))
    return counts


def restart_app(br, rig_id=None, setlist=None, progress=None, timeout=90, action="restart"):
    """Geraete-App neu starten (Bruecke 0.4). Noetig nach Setlist-Aenderungen: die Set-
    Anzeige (SetName1) liest die Setlists nur beim App-Start. Dauert ca. 10 s; ungesicherte
    Aenderungen am geladenen Rig gehen verloren. Den 'letzten Zustand wiederherstellen?'-
    Dialog beantwortet die Funktion mit No (FS2): danach ist nichts geladen und All Rigs
    aktiv - ein definierter Zustand. (Yes stellte einen aelteren Stand wieder her: ein
    anderes, als geaendert markiertes Rig, das beim naechsten Wechsel nachfragt.) Dann wird
    setlist betreten und rig_id geladen. Liefert das Ergebnis wie read_rig_list. action: die
    Aktion, die neu startet (restart; nam-on/nam-off schalten vorher NAM um, Bruecke 0.7)."""
    say = progress or (lambda t: None)
    say("Restarting the device app ...")
    board = br.get(BOARD)   # Ansicht am Geraet; nach dem Neustart landet es sonst in SetRig (2026-09-30)
    br.action(action)
    end = time.time() + timeout
    time.sleep(3)
    while True:   # die Bruecke ist erst mit der neuen App wieder da
        try:
            br.ping()
            break
        except BridgeError:
            if time.time() > end:
                raise LiveError("The device app is not reachable after the restart.")
            time.sleep(1)
    say("App is running again, waiting for the dialog ...")
    while time.time() < end:
        if br.get(BOARD).get("string") == "FreeText" and "Yes" in dialog_buttons(br):
            press(br, FS % 2)   # No = nichts wiederherstellen
            for _ in range(20):
                if br.get(BOARD).get("string") != "FreeText":
                    break
                time.sleep(0.1)
            break
        time.sleep(0.5)
    time.sleep(SETTLE)
    res = read_rig_list(br)
    if setlist and setlist != res["setlist"] and (setlist == ALL_RIGS or setlist in res["setlist_ids"]):
        say("Entering setlist %s ..." % setlist)
        res = enter_setlist(br, res["setlists"], setlist, res["setlist_ids"], discard=True)
    ids = [r["id"] for r in res["rows"]]
    if rig_id in ids and rig_status(br)["id"] != rig_id:
        say("Loading the rig again ...")
        res["status"] = load_rig(br, res["rows"], ids.index(rig_id), discard=True)
    restore_board(br, board)
    return res


VIEW_MODES = ("Stomp", "Rig", "Hybrid", "Set", "SetRig", "Looper")   # BoardMode-Ansichten ohne Dialog/Tuner


def restore_board(br, before):
    """Ansicht am Geraet (BoardMode, Antwort von get) wiederherstellen, wenn eine Aktion sie
    umgestellt hat - nur zwischen normalen Ansichten, nie in einen Dialog oder den Tuner."""
    if not before or before.get("string") not in VIEW_MODES or "index" not in before:
        return
    for _ in range(20):   # ein Dialog oder der Tuner schliesst gerade noch
        now = br.get(BOARD).get("string")
        if now in VIEW_MODES:
            break
        time.sleep(0.1)
    else:
        return
    if now != before["string"]:
        br.set(BOARD, "index", before["index"])


def refresh_lists(br, setlists, setlist, setlist_ids, reload_id=None, reload_row=False):
    """Nach Datenbankaenderungen die aktive Liste am Geraet neu lesen lassen (Setlist bzw.
    All Rigs wieder betreten - laedt nichts, ca. 1 s). Andere Listen liest das Geraet ohnehin
    frisch, sobald sie betreten werden. reload_id: dieses Rig danach laden - ein anderes als
    das geladene (save_rig_as) oder mit reload_row=True das geladene selbst, weil seine Zeile
    geaendert wurde (Name, Farbe, Programmnummer stehen im Speicher des Geraets; ueber die
    Bank, denn ReceivePresetIndex auf das geladene Rig tut nichts). Liefert das Ergebnis
    wie enter_setlist."""
    if setlist == ALL_RIGS or setlist not in (setlist_ids or {}):
        setlist = ALL_RIGS
    res = enter_setlist(br, setlists, setlist, setlist_ids, active=True)
    ids = [r["id"] for r in res["rows"]]
    st = res["status"]
    if reload_id in ids and (st["id"] != reload_id or reload_row):
        res["status"] = load_rig(br, res["rows"], ids.index(reload_id), discard=st["id"] == reload_id or st["dirty"])
    return res


# ---- Impulse Responses (IR-Dateien) ----
#
# Die IR-Dateien liegen dauerhaft im USB-Abbild des Geraets (usb.img, im Betrieb
# unter IR_DIR eingehaengt, vfat, utf8): <Ordner>/<Name>.wav, eine Ordnerebene; die
# Werks-IRs aus /usr/Evil/Content werden dorthin kopiert. Der IR-Block traegt die
# Datei als Text '[directory](<Ordner>)[name](<Name ohne Endung>)' in IR/IR (Haelfte
# B: IR2, Blocktypen IR und IR (1024)); Schreiben ueber Feld string laedt die IR
# sofort (PresetCtrl/Resources/IRNotFound[Lite][2][_B] state 1 = Datei fehlt), setzt
# aber Dirty nicht. Ordner '[IR ROOT]' = Suche ueber alle Ordner (erste Datei mit dem
# Namen), '[USER]' = Ordner USER. Das Geraet liest den Dateibaum nur beim App-Start
# (und nach dem USB-Abgleich): nach jeder Aenderung an Dateien ist restart_app
# noetig, bevor neue Dateien ladbar sind - auch in bestehenden Ordnern (verifiziert
# 2026-09-17). Dateizugriffe laufen ueber Bridge.read_file/write_file/list_dir/shell
# (Bruecke 0.3).

IR_DIR = "/media/az01-internal/Evil/usb_mnt/Impulse Responses"
IR_ROOT, IR_USER = "[IR ROOT]", "[USER]"
IR_EXT = (".wav", ".mp3")         # so filtert die Geraete-App (\.(wav|mp3)$)
IR_MODULES = ("IR", "IR (1024)")
IR_MAX_KB = 2048                  # groessere Dateien lehnt der Editor ab (das Geraet nutzt ohnehin nur den Anfang)


def ir_string(folder, name):
    return "[directory](%s)[name](%s)" % (folder, name)


def parse_ir(s):
    """'[directory](Ordner)[name](Name)' -> (Ordner, Name); anderer Text -> (None, Text)."""
    s = s or ""
    if s.startswith("[directory](") and "[name](" in s and s.endswith(")"):
        d, _, n = s[len("[directory]("):-1].partition(")[name](")
        return d, n
    return None, s


def ir_label(s, folder=True):
    """Anzeige wie IRInfoString: 'Ordner / Name' (folder=False: nur der Name)."""
    d, n = parse_ir(s)
    if d is None:
        return n
    return "%s / %s" % (d, n) if folder and d else n


def ir_folder_path(folder):
    if folder == IR_ROOT or not folder:
        return IR_DIR
    return IR_DIR + "/" + ("USER" if folder == IR_USER else folder)


def ir_file_path(folder, filename):
    return ir_folder_path(folder) + "/" + filename


def _ir_folder_name(dirname):
    return IR_USER if dirname == "USER" else dirname


def check_ir_name(name, what="Name"):
    """Fehlertext, wenn name als Datei-/Ordnername auf dem Geraet nicht taugt, sonst None."""
    if not name or name != name.strip() or name.endswith("."):
        return "%s must not be empty and must not start/end with a space or dot." % what
    bad = [c for c in name if c in _BAD_CHARS or ord(c) < 32]
    if bad:
        return "%s contains forbidden characters: %s" % (what, " ".join(sorted(set(bad))))
    if name.startswith("[") and name.endswith("]"):
        return "%s must not be in square brackets (reserved)." % what
    if len(name.encode("utf-8")) > 120:
        return "%s is too long." % what
    return None


def db_irs(br):
    """Alle IR-Dateien des Geraets: {'folders': [Ordner], 'files': {Ordner: [(Name, Dateiname)]}}.
    Ordner in der Reihenfolge des Geraets ([IR ROOT] nur, wenn Dateien direkt im Wurzelordner
    liegen), Dateien alphabetisch ohne Gross-/Kleinschreibung. Eine Abfrage, ca. 0,3 s."""
    return _ir_index((rel, is_dir) for rel, is_dir, _ in br.list_dir(IR_DIR, recursive=True))


def _ir_index(entries):
    """IR-Verzeichnis aus [(relativer Pfad mit '/', ist Ordner)] -> Form von db_irs
    (eine Ordnerebene, nur .wav)."""
    files, folders = {}, set()
    for rel, is_dir in entries:
        parts = rel.split("/")
        if is_dir:
            if len(parts) == 1:
                folders.add(_ir_folder_name(parts[0]))
            continue
        if len(parts) > 2 or not rel.lower().endswith(IR_EXT):
            continue
        folder = _ir_folder_name(parts[0]) if len(parts) == 2 else IR_ROOT
        fn = parts[-1]
        files.setdefault(folder, []).append((fn[:fn.rfind(".")], fn))
    for lst in files.values():
        lst.sort(key=lambda t: t[0].lower())
    order = sorted(folders | set(files), key=lambda f: (f not in (IR_ROOT, IR_USER), f))
    return {"folders": order, "files": {f: files.get(f, []) for f in order}}


def ir_filename(irs, folder, name):
    """Dateiname (mit Endung) zu Ordner/Name aus db_irs, sonst None."""
    for n, fn in irs["files"].get(folder, []):
        if n == name:
            return fn
    return None


def wav_info(data):
    """(Kanaele, Abtastrate, Bits, Laenge in Frames) einer WAV-Datei oder None."""
    if len(data) < 36 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos, fmt, size = 12, None, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        ln = int.from_bytes(data[pos + 4:pos + 8], "little")
        if cid == b"fmt " and ln >= 16:
            ch = int.from_bytes(data[pos + 10:pos + 12], "little")
            rate = int.from_bytes(data[pos + 12:pos + 16], "little")
            bits = int.from_bytes(data[pos + 22:pos + 24], "little")
            fmt = (ch, rate, bits)
        elif cid == b"data":
            size = min(ln, len(data) - pos - 8)
        pos += 8 + ln + (ln & 1)
    if not fmt:
        return None
    ch, rate, bits = fmt
    frames = size // max(1, ch * max(bits, 8) // 8) if size is not None else 0
    return ch, rate, bits, frames


def ir_create_folder(br, folder):
    err = check_ir_name(folder, "Folder name")
    if err:
        raise LiveError(err)
    if folder in (IR_ROOT, IR_USER):
        raise LiveError("This folder already exists.")
    br.make_dir(ir_folder_path(folder))


def ir_upload(br, folder, path, name=None, replace=False):
    """Lokale IR-Datei (.wav/.mp3) nach <folder>/<name>.<endung> auf das Geraet schreiben.
    Liefert (Name, Dateiname). Ohne replace ist eine vorhandene Datei ein Fehler."""
    base, ext = os.path.splitext(os.path.basename(path))
    ext = ext.lower()
    if ext not in IR_EXT:
        raise LiveError("Only .wav or .mp3 files: %s" % os.path.basename(path))
    name = (name or base).strip()
    err = check_ir_name(name)
    if err:
        raise LiveError(err)
    data = open(path, "rb").read()
    if len(data) > IR_MAX_KB * 1024:
        raise LiveError("%s is too large (%d KB, at most %d KB)." % (os.path.basename(path), len(data) // 1024, IR_MAX_KB))
    if ext == ".wav" and wav_info(data) is None:
        raise LiveError("%s is not a WAV file." % os.path.basename(path))
    target = ir_file_path(folder, name + ext)
    if not replace:
        taken = {os.path.splitext(n)[0].lower() for n, d, _ in br.list_dir(ir_folder_path(folder)) if not d}
        if name.lower() in taken:
            raise LiveError("Folder %s already has an IR called %s." % (folder, name))
    br.write_file(target, data)
    return name, name + ext


def ir_download(br, folder, filename, local_path):
    data = br.read_file(ir_file_path(folder, filename))
    with open(local_path, "wb") as f:
        f.write(data)
    return len(data)


def _sh(br, cmd):
    rc, out = br.shell(cmd)
    if rc != 0:
        raise LiveError("Device command failed: %s" % (out.strip() or cmd))


def ir_delete(br, folder, filename):
    _sh(br, "rm -f %s" % sh_quote(ir_file_path(folder, filename)))


def ir_rename(br, folder, filename, new_name):
    """Datei umbenennen (Endung bleibt); liefert den neuen Dateinamen."""
    err = check_ir_name(new_name)
    if err:
        raise LiveError(err)
    new_fn = new_name + os.path.splitext(filename)[1]
    _sh(br, "mv -n %s %s" % (sh_quote(ir_file_path(folder, filename)), sh_quote(ir_file_path(folder, new_fn))))
    return new_fn


def ir_delete_folder(br, folder):
    if folder in (IR_ROOT, IR_USER):
        raise LiveError("This folder cannot be deleted.")
    _sh(br, "rm -r %s" % sh_quote(ir_folder_path(folder)))


def ir_rename_folder(br, folder, new_name):
    if folder in (IR_ROOT, IR_USER):
        raise LiveError("This folder cannot be renamed.")
    err = check_ir_name(new_name, "Folder name")
    if err:
        raise LiveError(err)
    _sh(br, "mv -n %s %s" % (sh_quote(ir_folder_path(folder)), sh_quote(ir_folder_path(new_name))))


def db_rigs_using_ir(br, folder, name):
    """Namen der Rigs, deren Inhalt diese IR nennt (auch als Haelfte B)."""
    needle = ir_string(folder, name)
    rows = br.sql("select name from rigs where instr(content, %s) > 0 order by name" % sql_lit(needle))
    return [r["name"] for r in rows]


def read_ir_folder(folder):
    """Offline: 'Impulse Responses' eines USB-Exports -> wie db_irs (leer, wenn es den Ordner nicht gibt)."""
    entries = []
    if os.path.isdir(folder):
        for entry in os.listdir(folder):
            p = os.path.join(folder, entry)
            entries.append((entry, os.path.isdir(p)))
            if os.path.isdir(p):
                entries += [(entry + "/" + fn, os.path.isdir(os.path.join(p, fn))) for fn in os.listdir(p)]
    return _ir_index(entries)


# ---- NAM-Mod (Bruecke 0.7, mit NAM gebaut) ----
#
# Die NAM-Mod von lolgab (github.com/lolgab/headrush-nam-mod) ersetzt die Klangverarbeitung
# des Anxiety OD (beide Instanzen 'Anxiety OD', 'Anxiety OD 2'; mit 4 Instanzen auch
# 'Anxiety OD V2' [2]) durch Neural Amp Modeler. Regler (verifiziert am Quelltext v0.1.6,
# patch/nam_hook.cpp): Drive waehlt das Modell - unnormalized 0..100 = Platz in der nach
# Dateiname (Bytes) sortierten Liste der .nam-Dateien in NAM_DIR; Plaetze ohne Datei sind
# stumm. Tone = Eingangs-, Level = Ausgangspegel: unter 50 % linear leiser bis stumm, ab 50 %
# 0 bis +12 dB. Hi-Lo tut nichts. Das Geraet liest den Ordner nur einmal je App-Start (und
# ueberspringt Dateien, die es nicht laden kann - dann verschieben sich alle folgenden
# Plaetze); nach jeder Aenderung an den Dateien ist restart_app noetig. Die Konvention der
# Mod: Dateinamen 'NNN - Name.nam' mit lueckenloser Nummer = Platz. Rigs speichern den Platz
# als Drive-Wert - wer Modelle verschiebt oder loescht, muss die Rigs nachziehen (nam_remap).
# Die Bruecke startet die App nur mit NAM, wenn es eingeschaltet ist (Aktionen nam-on/-off).

NAM_DIR = "/media/az01-internal/Evil/usb_mnt/NAM"
NAM_INFO = "/usr/Evil/Scripts/mx5bridge-nam.txt"
NAM_EXT = ".nam"
NAM_STEPS = 101                  # Drive 0..100 %, je Prozent ein Modell
NAM_SILENT = NAM_STEPS - 1       # Platz fuer 'kein Modell' (belegt erst beim 101. Modell)
NAM_V1 = ("Anxiety OD", "Anxiety OD 2")
NAM_V2 = ("Anxiety OD V2", "Anxiety OD V2 2")
NAM_PRESET_TYPES = {"Anxiety OD": "ANXIETY OD", "Anxiety OD V2": "ANXIETY OD V2"}
NAM_MAX_MB = 30                  # groessere Dateien lehnt der Editor ab (A1/A2-Modelle sind 0,1..5 MB)
NAM_TRIM_DB = 12.0               # Tone/Level ueber 50 %: bis zu +12 dB (NAM_TRIM_MAX_DB der Mod)


def nam_status(br):
    """NAM-Zustand des Geraets: {installed, on, active, auto_off, ref, instances}. installed=False
    fuer Firmware ohne NAM oder Bruecke vor 0.7. on = beim naechsten App-Start, active = die
    laufende App wurde mit NAM gestartet."""
    off = {"installed": False, "on": False, "active": False, "auto_off": False, "ref": "", "instances": 0}
    if br.vnum < (0, 7):
        return off
    st = br.action("status")
    if not st.get("nam_installed"):
        return off
    rc, out = br.shell("cat %s 2>/dev/null" % sh_quote(NAM_INFO))
    info = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    try:
        inst = int(info.get("nam_instanzen", 2))
    except ValueError:
        inst = 2
    return {"installed": True, "on": bool(st.get("nam_on")), "active": bool(st.get("nam_active")),
            "auto_off": bool(st.get("nam_auto_off")), "ref": st.get("nam_ref") or info.get("nam_mod_ref", ""),
            "instances": inst}


def nam_modules(nam):
    """Blocknamen, die NAM spielen (leer, wenn NAM in der laufenden App nicht aktiv ist)."""
    if not nam or not nam.get("active"):
        return ()
    return NAM_V1 + (NAM_V2 if nam.get("instances", 2) >= 4 else ())


NAM_NAMES = {"Anxiety OD": "NAM", "Anxiety OD V2": "NAM V2"}   # Anzeige im Editor (Basisname -> Name)


def nam_display(m):
    """Anzeigename eines NAM-Blocks: 'Anxiety OD 2' -> 'NAM 2', 'Anxiety OD V2' -> 'NAM V2'."""
    base = base_name(m)
    return NAM_NAMES.get(base, base) + m[len(base):]


def nam_base(fn):
    """Anzeigename einer Modelldatei: ohne 'NNN - ' und ohne .nam."""
    n = fn[:-len(NAM_EXT)] if fn.lower().endswith(NAM_EXT) else fn
    if len(n) > 6 and n[:3].isdigit() and n[3:6] == " - ":
        n = n[6:]
    return n


def nam_filename(index, name):
    return "%03d - %s%s" % (index, name, NAM_EXT)


def _nam_index(files):
    """[(Dateiname, Bytes)] -> Modelle in der Reihenfolge des Geraets: nur *.nam (ohne '._'-
    Begleitdateien von macOS), sortiert nach den Bytes des Namens wie std::sort der Mod.
    Jedes Modell: {file, name, size, index}; index = Drive-Wert, der es waehlt."""
    ok = [(fn, size) for fn, size in files
          if fn.lower().endswith(NAM_EXT) and not fn.startswith("._")]
    ok.sort(key=lambda t: t[0].encode("utf-8"))
    return [{"file": fn, "name": nam_base(fn), "size": size, "index": i} for i, (fn, size) in enumerate(ok)]


def db_nam_models(br):
    """NAM-Modelle auf dem Geraet: {'exists': Ordner vorhanden, 'models': [...] wie _nam_index}."""
    q = sh_quote(NAM_DIR)
    rc, out = br.shell("[ -d %s ] || { echo NODIR; exit 0; }\ncd %s || exit 1\n"
                       "for f in * .[!.]*; do [ -f \"$f\" ] && printf '%%s\\t%%s\\n' \"$(wc -c < \"$f\")\" \"$f\"; done; true"
                       % (q, q))
    if rc != 0:
        raise LiveError("Could not read the NAM folder: %s" % out.strip())
    if out.strip() == "NODIR":
        return {"exists": False, "models": []}
    files = []
    for line in out.splitlines():
        size, _, fn = line.partition("\t")
        if fn and size.strip().isdigit():
            files.append((fn, int(size)))
    return {"exists": True, "models": _nam_index(files)}


def check_nam_name(name):
    """Fehlertext fuer einen Modellnamen (ohne Nummer/Endung), sonst None."""
    err = check_ir_name(name)
    if err:
        return err
    if len(name.encode("utf-8")) > 200:
        return "Name is too long."
    return None


def check_nam_data(data, what="The file"):
    """Prueft eine .nam-Datei wie die Mod beim Laden (JSON mit architecture/config/weights).
    Liefert eine kurze Beschreibung ('WaveNet, 13 KB weights') oder wirft LiveError - eine
    Datei, die das Geraet nicht laden kann, wuerde alle folgenden Plaetze verschieben."""
    try:
        j = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise LiveError("%s is not a NAM model (no JSON: %s)." % (what, e))
    if not isinstance(j, dict) or "architecture" not in j or "weights" not in j and "config" not in j:
        raise LiveError("%s is not a NAM model (architecture/weights missing)." % what)
    arch = str(j.get("architecture"))
    meta = j.get("metadata") if isinstance(j.get("metadata"), dict) else {}
    extra = meta.get("name") or meta.get("gear_make") or ""
    return arch + (" · " + str(extra) if extra else "")


def nam_download(br, fn, local_path):
    data = br.read_file(NAM_DIR + "/" + fn)
    with open(local_path, "wb") as f:
        f.write(data)
    return len(data)


def nam_rename_files(br, renames, delete=()):
    """Dateien loeschen und umbenennen, in einem Shell-Skript und ueber Zwischennamen (ein
    neuer Name kann der alte Name einer anderen Datei sein). Prueft vorher, dass kein Ziel
    einer Datei gehoert, die bleibt."""
    if not renames and not delete:
        return
    d = sh_quote(NAM_DIR)
    lines = ["cd %s || exit 1" % d]
    lines += ["rm -f -- %s || exit 1" % sh_quote(fn) for fn in delete]
    lines += ["mv -- %s %s || exit 1" % (sh_quote(old), sh_quote(".mx5b_tmp_%d" % i)) for i, (old, _) in enumerate(renames)]
    lines += ["[ -e %s ] && { echo exists: %s; exit 1; }; mv -- %s %s || exit 1"
              % (sh_quote(new), sh_quote(new), sh_quote(".mx5b_tmp_%d" % i), sh_quote(new))
              for i, (_, new) in enumerate(renames)]
    rc, out = br.shell("\n".join(lines))
    if rc != 0:
        raise LiveError("Renaming the NAM models failed: %s\n(Check the NAM folder; temporary files are "
                        "called .mx5b_tmp_*.)" % out.strip())


def _nam_value_sql(json_path):
    return "cast(round(json_extract(content, %s)) as integer)" % sql_lit(json_path)


def _nam_paths(nam):
    """(Tabelle, JSON-Pfad des Drive-Werts, Anzeige, Zusatzbedingung) fuer Rigs und Block-Presets
    der NAM-Bloecke. Presets nur mit Namen 'NNN - ...' (Konvention der Mod, so legt sie auch
    der Editor an): die Werks-Presets des Anxiety OD (BRIGHT, SMOOTH ...) sind Overdrive-
    Einstellungen und in der Datenbank nicht als schreibgeschuetzt markiert."""
    out = []
    for m in nam_modules(nam):
        out.append(("rigs", '$.data.Patch.children."%s".children.Drive.value' % m, m, ""))
    for base in sorted({base_name(m) for m in nam_modules(nam)}):
        t = NAM_PRESET_TYPES[base]
        out.append(("blocks", '$.data."%s".children.Drive.value' % base, t,
                    " and type = %s and name glob '[0-9][0-9][0-9] - *'" % sql_lit(t)))
    return out


def nam_usage(br, nam):
    """Wer welchen Platz benutzt: {Platz: ['Rig NAME (Block)', 'Preset NAME'...]} ueber alle Rigs
    und Block-Presets der NAM-Bloecke (ein Blick in den Inhalt, ca. 0,5 s)."""
    usage = {}
    for table, path, what, cond in _nam_paths(nam):
        rows = br.sql("select name, %s as v from %s where json_extract(content, %s) is not null%s"
                      % (_nam_value_sql(path), table, sql_lit(path), cond))
        for r in rows:
            label = "%s (%s)" % (r["name"], what) if table == "rigs" else "Preset %s (%s)" % (r["name"], what)
            usage.setdefault(int(r["v"]), []).append(label)
    return usage


def nam_remap(br, nam, mapping):
    """Drive-Werte in Rigs und Block-Presets der NAM-Bloecke nach mapping {alt: neu} umschreiben
    (eine Transaktion, json_set laesst den restlichen Inhalt unveraendert). Liefert die Zahl
    der geaenderten Zeilen. Das geladene Rig liest das Geraet erst beim naechsten Laden neu."""
    if not mapping:
        return 0
    stmts = []
    for table, path, what, cond in _nam_paths(nam):
        v = _nam_value_sql(path)
        case = "case %s %s end" % (v, " ".join("when %d then %d" % (a, b) for a, b in sorted(mapping.items())))
        stmts.append("update %s set content = json_set(content, %s, %s) where json_extract(content, %s) is not null "
                     "and %s in (%s)%s;" % (table, sql_lit(path), case, sql_lit(path), v,
                                            ",".join(str(a) for a in sorted(mapping)), cond))
    return br.sql_write("\n".join(stmts))


def nam_apply(br, nam, old, final, delete=(), replace=None, progress=None):
    """Den NAM-Ordner in einem Zug umbauen. old: Dateinamen vorher (Reihenfolge des Geraets).
    final: [(Quelle, Anzeigename)] in der neuen Reihenfolge - Quelle ist ein vorhandener
    Dateiname aus old oder ein lokaler Pfad (hochladen). delete: Dateien aus old, die wegfallen.
    replace: {Datei aus old: lokaler Pfad} - Inhalt ersetzen, Platz und Name bleiben.
    Laedt neue Dateien unter Zwischennamen ohne .nam hoch (das Geraet sieht sie so nie halb),
    benennt dann alles lueckenlos 'NNN - Name.nam', loescht und schreibt die Drive-Werte der
    Rigs/Presets nach (nam_remap), damit jedes Rig sein Modell behaelt. Liefert
    {'files': Anzahl, 'remapped': geaenderte Rigs/Presets}."""
    say = progress or (lambda t: None)
    if len(final) > NAM_STEPS:
        raise LiveError("At most %d NAM models are reachable (Drive 0–100 %%)." % NAM_STEPS)
    seen = set()
    for _, name in final:
        err = check_nam_name(name)
        if err:
            raise LiveError("%s: %s" % (name, err))
        if name.lower() in seen:
            raise LiveError("The name “%s” is used twice." % name)
        seen.add(name.lower())
    oldset = set(old)
    replace = {fn: p for fn, p in (replace or {}).items() if fn in oldset}
    ups = [(i, src) for i, (src, _) in enumerate(final) if src not in oldset] + [(None, p) for p in replace.values()]
    for _, src in ups:   # erst alles pruefen, dann schreiben
        if not os.path.isfile(src):
            raise LiveError("File not found: %s" % src)
        if os.path.getsize(src) > NAM_MAX_MB * 1024 * 1024:
            raise LiveError("%s is too large (at most %d MB)." % (os.path.basename(src), NAM_MAX_MB))
        with open(src, "rb") as f:
            check_nam_data(f.read(), os.path.basename(src))
    _sh(br, "mkdir -p %s" % sh_quote(NAM_DIR))
    cur = {}
    for k, (i, src) in enumerate(ups):
        say("Uploading %s (%d/%d) …" % (os.path.basename(src), k + 1, len(ups)))
        tmp = ".mx5b_up_%d" % k
        with open(src, "rb") as f:
            br.write_file(NAM_DIR + "/" + tmp, f.read())
        cur[src] = tmp
    if replace:
        _sh(br, "\n".join("mv -f %s %s" % (sh_quote(NAM_DIR + "/" + cur[p]), sh_quote(NAM_DIR + "/" + fn))
                          for fn, p in replace.items()))
    renames = []
    for i, (src, name) in enumerate(final):
        now, new = cur.get(src, src), nam_filename(i, name)
        if now != new:
            renames.append((now, new))
    say("Renaming models …")
    nam_rename_files(br, renames, [fn for fn in delete if fn in oldset])
    pos = {src: i for i, (src, _) in enumerate(final)}
    mapping = {i: pos.get(fn, NAM_SILENT) for i, fn in enumerate(old) if pos.get(fn, NAM_SILENT) != i}
    n = 0
    if mapping:
        say("Updating rigs and presets …")
        n = nam_remap(br, nam, mapping)
    return {"files": len(final), "remapped": n}


def nam_trim_text(v):
    """Tone/Level (normiert 0..1) als Pegel wie die Mod ihn anwendet."""
    import math
    v = float(v)
    if v <= 0:
        return "mute"
    if v < 0.5:
        return "%.1f dB" % (20 * math.log10(v / 0.5))
    return "+%.1f dB" % ((v - 0.5) * 2 * NAM_TRIM_DB) if v > 0.5 else "0.0 dB"


def nam_index_of(info):
    """Drive-Info -> Platz 0..100."""
    try:
        return int(round(float(info.get("unnormalized", 0))))
    except (TypeError, ValueError):
        return 0


# ---- Tuner (verifiziert 2026-09-17) ----
# RedirCtrl/AccessTuner "druecken" oeffnet die Tuner-Seite am Geraet (BoardMode -> "Tuner",
# AudioCtrl/Input/TunerOn -> On), ExitTuner schliesst sie wieder (auch ein Fussschalter am Geraet).
# FFTCtrl/TunerString ist der Notenname ("" = kein Ton), FFTCtrl/TunerCents unnormalized die
# Abweichung in Cents (-100..100, das Geraet zeigt -50..+50), aktualisiert alle ~35 ms; eine
# get_many-Abfrage der Tuner-Werte dauert ~5 ms, der Editor fragt daher ~30x pro Sekunde ab.
# TunerRef = Kammerton 410..480 Hz (IntegerValue), TunerMuting = Ausgang stumm im Tuner.
FFT = "/Engine/FFTCtrl"
TUNER_NOTE = FFT + "/TunerString"
TUNER_CENTS = FFT + "/TunerCents"
TUNER_REF = FFT + "/TunerRef"
TUNER_MUTE = "/Engine/AudioCtrl/Input/TunerMuting"
TUNER_ON = "/Engine/AudioCtrl/Input/TunerOn"
TUNER_PATHS = [TUNER_NOTE, TUNER_CENTS, TUNER_REF, TUNER_MUTE, BOARD]
TUNER_REF_MIN, TUNER_REF_MAX = 410, 480
TUNER_OK = 6.0        # |Cents| darunter gilt als gestimmt (Schwelle der Geraeteanzeige)


def tuner_open(br):
    """Tuner-Seite am Geraet oeffnen; liefert die erste Ablesung (tuner_parse). Die Ansicht davor
    merkt sich die Bridge-Verbindung fuer tuner_close (ExitTuner fuehrt sonst immer nach Hybrid)."""
    board = br.get(BOARD) or {}
    if board.get("string") != "Tuner":
        br.tuner_board = board
        press(br, RC + "/AccessTuner")
        for _ in range(20):
            if (br.get(BOARD) or {}).get("string") == "Tuner":
                break
            time.sleep(0.05)
        else:
            raise LiveError("Tuner not opened on the device (BoardMode stays %s)" % (br.get(BOARD) or {}).get("string"))
    return tuner_parse(br.get_many(TUNER_PATHS))


def tuner_close(br):
    """Tuner-Seite verlassen (nichts tun, wenn das Geraet sie schon verlassen hat) und die Ansicht
    von vorher wiederherstellen."""
    if (br.get(BOARD) or {}).get("string") == "Tuner":
        press(br, RC + "/ExitTuner")
        restore_board(br, getattr(br, "tuner_board", None))
    br.tuner_board = None
    return True


def tuner_parse(res):
    """get_many-Antwort der TUNER_PATHS -> {note, cents, ref, mute, active}."""
    note = (res.get(TUNER_NOTE) or {}).get("string") or ""
    cents = (res.get(TUNER_CENTS) or {}).get("unnormalized")
    ref = (res.get(TUNER_REF) or {}).get("unnormalized")
    mute = (res.get(TUNER_MUTE) or {}).get("state")
    board = (res.get(BOARD) or {}).get("string")
    return {"note": note, "cents": float(cents) if cents is not None else 0.0,
            "ref": int(ref) if ref is not None else None, "mute": None if mute is None else bool(mute),
            "active": board == "Tuner", "ok": bool(res.get("ok", True)) and TUNER_CENTS in res}


# ---- Pegelanzeige (verifiziert 2026-09-30) ----
# /Engine/InputMeter/Current|Peak (unnormalized dB, -120..0) und /Engine/OutputMeterL|R/Current|Peak
# (-60..+6) sind die Pegelanzeigen der Input-/Output-Seite am Geraet. Laufend aktualisiert, Peak
# haelt den Hoechstwert eine Weile und faellt dann langsam; get_many der Werte dauert ~5 ms.
METERS = {"Input": [("IN", "/Engine/InputMeter")],
          "Output": [("L", "/Engine/OutputMeterL"), ("R", "/Engine/OutputMeterR")]}
METER_RANGE = {"Input": (-60.0, 0.0), "Output": (-60.0, 6.0)}   # angezeigter Bereich in dB


def meter_paths(module):
    return [p + s for _, p in METERS.get(module, []) for s in ("/Current", "/Peak")]


def meter_parse(module, res):
    """get_many-Antwort -> [(name, current_db, peak_db)] (None, wenn ein Wert fehlt)."""
    out = []
    for name, p in METERS.get(module, []):
        cur = (res.get(p + "/Current") or {}).get("unnormalized")
        peak = (res.get(p + "/Peak") or {}).get("unnormalized")
        out.append((name, None if cur is None else float(cur), None if peak is None else float(peak)))
    return out


# ---- Hardware-Zuweisungen (Fussschalter, Scenes, Expression-Pedale) ----
#
# Fussschalter 1-3 des MX5 sind /Engine/FootSwitch/...5, 6, 7. Je Schalter:
#   ModeNew (Toggle|Scene), UserFootSwitchText (Beschriftung), im Toggle-Modus
#   ModuleList/OperationList (Auswahllisten, setzen Module/Operation), im
#   Scene-Modus SceneNumberOfStates (1-2), MacroColour/State2MacroColour und
#   Scene/State2Scene mit slot(0..10) = {effect, mode}; mode 0 = unveraendert,
#   1 = an, 2 = aus. Nur belegte Kettenplaetze setzen - ein Zustand auf einem
#   leeren Platz hat beim Ausloesen die Geraete-App abstuerzen lassen.
#   Dazu je Platz das Text-Property Scene<n>Slot<k>Preset (Zustand 2:
#   State2Scene<n>Slot<k>Preset): Name eines Block-Presets (Tabelle blocks,
#   Typ des Blocks), das beim Ausloesen der Scene in den Block geladen wird;
#   "No Preset" = keins, leere Plaetze liefern "". Das Geraet prueft den Namen
#   nicht (am Geraet 2026-09-17 geprueft: Preset WARM wurde per Fussschalter
#   geladen, PresetName und Parameter des Blocks folgten).
# Pedal1 (eingebaut) / Pedal2 (extern): je 4 Zuweisungen ModuleList/ParamList
#   (setzen Module/Param), Min/Max in Prozent; Pedal1 hat PedalMode Classic|Advanced.
# Zuweisungsaenderungen setzen Rigs/Dirty am Geraet selbst.
# Anzeige der Schalter wie auf dem Display (am Geraet 2026-09-17 geprueft): FootSwitchText<n>
#   = gezeigter Text (Beschriftung, sonst Blockname), FootSwitchColour<n> = gezeigte Farbe
#   (folgt bei zwei Zustaenden dem aktiven, SceneState<n> = 0/1), FootSwitch<n> state = leuchtet
#   (zuletzt ausgeloeste Scene bzw. Block an). Ein Druck geht in der Stomp-Ansicht ueber
#   RedirCtrl/RawFootswitches/FS1-3 (press_footswitch).

HW_FS, HW_PEDAL = "Footswitches", "Pedals"
HW_MODULES = [HW_FS, HW_PEDAL]
FSW = "/Engine/FootSwitch"
PEDAL = "/Engine/Pedal%d"
FS_NUMBERS = (5, 6, 7)
SCENE_UNCHANGED, SCENE_ON, SCENE_OFF = 0, 1, 2
NO_SCENE_PRESET = "No Preset"
FS_DISPLAY = ("FootSwitchText%d", "FootSwitchColour%d", "FootSwitch%d")


def fs_display_paths():
    """Die neun Anzeige-Properties der drei Fussschalter (Text, Farbe, leuchtet)."""
    return ["%s/%s" % (FSW, k % n) for n in FS_NUMBERS for k in FS_DISPLAY]


def fs_display(values):
    """Anzeige der Schalter aus gelesenen Werten: {n: {text, colour, on}}; None, solange nichts gelesen ist."""
    out = {}
    for n in FS_NUMBERS:
        t, c, o = ((values.get("%s/%s" % (FSW, k % n)) or {}) for k in FS_DISPLAY)
        if not t and not c and not o:
            continue
        out[n] = {"text": t.get("string") or "", "colour": c.get("string") or "", "on": bool(o.get("state"))}
    return out or None


def press_footswitch(br, k):
    """Fussschalter k (1-3) am Geraet druecken wie ein Tritt auf den Schalter - nur in der
    Stomp-Ansicht, sonst wuerde der Druck einen Dialogknopf treffen. Liefert die neue Anzeige."""
    board = (br.get(BOARD) or {}).get("string")
    if board != "Stomp":
        raise LiveError("The device currently shows '%s', not the stomp view." % board)
    press(br, FS % k, hold=0.06, wait=0.2)
    return br.get_many(fs_display_paths())


def scene_path(n, state):
    return "%s/%sScene%d" % (FSW, "State2" if state == 2 else "", n)


def scene_preset_path(n, state, slot):
    """Preset-Property eines Kettenplatzes (0-basiert) einer Scene."""
    return "%s/%sScene%dSlot%dPreset" % (FSW, "State2" if state == 2 else "", n, slot + 1)


def read_scene_slots(br, n, state):
    """[(blockname, mode, preset)] der 11 Kettenplaetze einer Scene; preset "" = keins."""
    js = ('var t = App.getProperty("%s").translator; var o = []; for (var i = 0; i < %d; i++) '
          '{ var s = t.slot(i); o.push([s.effect, s.mode]); } return JSON.stringify(o);' % (scene_path(n, state), SLOTS))
    slots = [(e, int(m)) for e, m in json.loads(br.eval(js))]
    paths = [scene_preset_path(n, state, i) for i in range(SLOTS)]
    r = br.get_many(paths)
    out = []
    for i, (e, m) in enumerate(slots):
        name = (r.get(paths[i]) or {}).get("string") or ""
        out.append((e, m, "" if name == NO_SCENE_PRESET else name))
    return out


def set_scene_slot(br, n, state, slot, mode):
    """mode eines Kettenplatzes (0-basiert) setzen; leere Plaetze werden verweigert."""
    js = ('var s = App.getProperty("%s").translator.slot(%d); if (s.effect === "%s") return "leer"; '
          's.mode = %d; return String(s.mode);' % (scene_path(n, state), slot, EMPTY, mode))
    r = br.eval(js)
    if r == "leer":
        raise LiveError("Slot %d is empty." % (slot + 1))
    return int(r)


def set_scene_preset(br, n, state, slot, name):
    """Preset (Name, "" = keins) eintragen, das die Scene in den Block auf Platz slot (0-basiert)
    laedt. Liefert den eingetragenen Namen ("" = keins)."""
    r = br.set(scene_preset_path(n, state, slot), "string", name or NO_SCENE_PRESET)
    if not r.get("ok"):
        raise LiveError("Preset not set: %s" % r.get("err"))
    got = r.get("string") or ""
    return "" if got == NO_SCENE_PRESET else got


def _entries(br, path):
    try:
        return br.entries(path)
    except Exception:
        return []


FS_KEYS = {"mode": "ModeNew%d", "text": "UserFootSwitchText%d", "module": "ModuleList%d",
           "operation": "OperationList%d", "states": "SceneNumberOfStates%d",
           "colour1": "MacroColour%d", "colour2": "State2MacroColour%d"}
FS_LISTS = {"modes": "ModeNew%d", "modules": "ModuleList%d", "operations": "OperationList%d",
            "colours": "MacroColour%d"}
PEDAL_KEYS = {"module": "ModuleList%d", "param": "ParamList%d", "min": "Min%d", "max": "Max%d"}
PEDAL_LISTS = {"modules": "ModuleList%d", "params": "ParamList%d"}

# Liest alles fuer read_hardware in einem eval (vorher ~55 Einzelanfragen, 250 ms). V = Pfade fuer
# infoOf, E = Pfade fuer entriesOf (fehlt die Liste: []), S = Scene-Pfade (slot 0..10),
# P = Scene-Preset-Pfade (nur der Text).
_HW_JS = ('var V = %s, E = %s, S = %s, P = %s, o = {v: {}, e: {}, s: {}, p: {}}; '
          'for (var i = 0; i < V.length; i++) o.v[V[i]] = device.infoOf(V[i]); '
          'for (var i = 0; i < E.length; i++) { try { o.e[E[i]] = device.entriesOf(E[i]); } catch (x) { o.e[E[i]] = []; } } '
          'for (var i = 0; i < S.length; i++) { var t = device.translatorOf(S[i]), l = []; '
          '  for (var k = 0; k < %d; k++) { var x = t.slot(k); l.push([x.effect, x.mode]); } o.s[S[i]] = l; } '
          'for (var i = 0; i < P.length; i++) { try { o.p[P[i]] = device.translatorOf(P[i]).string; } catch (x) { } } '
          'return JSON.stringify(o);')


def read_hardware(br):
    """Alle Hardware-Zuweisungen des aktiven Rigs lesen (Werte, Auswahllisten, Scenes) - in
    einem eval statt ~55 Einzelanfragen."""
    vals, lists, scenes = [], [], []
    for n in FS_NUMBERS:
        vals += ["%s/%s" % (FSW, k % n) for k in FS_KEYS.values()]
        lists += ["%s/%s" % (FSW, k % n) for k in FS_LISTS.values()]
        scenes += [scene_path(n, 1), scene_path(n, 2)]
    for p in (1, 2):
        base = PEDAL % p
        for i in (1, 2, 3, 4):
            vals += ["%s/%s" % (base, k % i) for k in PEDAL_KEYS.values()]
            lists += ["%s/%s" % (base, k % i) for k in PEDAL_LISTS.values()]
        vals.append(base + "/PedalMode")
        lists.append(base + "/PedalMode")
    presets = [scene_preset_path(n, st, i) for n in FS_NUMBERS for st in (1, 2) for i in range(SLOTS)]
    r = json.loads(br.eval(_HW_JS % (json.dumps(vals), json.dumps(lists), json.dumps(scenes), json.dumps(presets), SLOTS)))
    v, e, s, pr = r["v"], r["e"], r["s"], r["p"]

    def scene(n, st):
        out = []
        for i, (eff, mode) in enumerate(s[scene_path(n, st)]):
            name = pr.get(scene_preset_path(n, st, i)) or ""
            out.append((eff, int(mode), "" if name == NO_SCENE_PRESET else name))
        return out

    hw = {"fs": {}, "pedal": {}}
    for n in FS_NUMBERS:
        d = {name: v.get("%s/%s" % (FSW, k % n), {}) for name, k in FS_KEYS.items()}
        d.update({name: e.get("%s/%s" % (FSW, k % n), []) for name, k in FS_LISTS.items()})
        d["scenes"] = [scene(n, 1), scene(n, 2)]
        hw["fs"][n] = d
    for p in (1, 2):
        base = PEDAL % p
        rows = []
        for i in (1, 2, 3, 4):
            row = {name: v.get("%s/%s" % (base, k % i), {}) for name, k in PEDAL_KEYS.items()}
            row.update({name: e.get("%s/%s" % (base, k % i), []) for name, k in PEDAL_LISTS.items()})
            rows.append(row)
        mode = v.get(base + "/PedalMode", {})
        hw["pedal"][p] = {"rows": rows, "mode": mode if mode.get("ok") else None,
                          "pedal_modes": e.get(base + "/PedalMode", []) if mode.get("ok") else []}
    return hw


# ---- Bloecke verschieben (am Geraet 2026-09-29 geprueft) ----
#
# Die Original-Oberflaeche (BlockMove.js im Evil-Binary) setzt nur ModuleType<k>.index:
# ein Typ, der schon auf einem anderen Platz steht, wandert dorthin (Parameter bleiben).
# Ein belegtes Ziel wird dabei *ersetzt* - aber jeder Blocktyp ist eine feste Instanz:
# wird er spaeter wieder eingesetzt, sind Parameter, An/Aus, Farbe und Pedal-Zuweisung
# wieder da. Verloren gehen nur seine Scene-Eintraege (Modus/Preset je Fussschalter),
# darum sichert move_chain sie vorher und stellt sie danach nach Blockname wieder her.
# Aendern per index setzt Rigs/Dirty nicht (die Oberflaeche setzt es selbst).

def plan_block_move(chain, src, dst):
    """Kette nach dem Ziehen von Platz src auf dst (1-basiert) - wie am Geraet: ist dst frei,
    wandert der Block dorthin; sonst ruecken die Bloecke ab dst bis zur naechsten Luecke
    (Richtung src bzw. nach hinten) einen Platz auf; ohne Luecke werden die beiden getauscht."""
    c = list(chain)
    i, j = src - 1, dst - 1
    m = c[i]
    if i == j or m is None:
        return c
    if c[j] is None:
        c[i], c[j] = None, m
        return c
    rng = range(j + 1, i) if i > j else range(j + 1, len(c))
    gap = next((k for k in rng if c[k] is None), None)
    if gap is None:
        c[i], c[j] = c[j], m
    else:
        c[j + 1:gap + 1] = c[j:gap]
        c[i], c[j] = None, m
    return c


def chain_writes(cur, desired):
    """Schreibfolge [(platz, name)] von cur nach desired (gleiche Bloecke, andere Plaetze).
    Bevorzugt Zuege auf freie Plaetze; nur ohne freien Platz wird ein Block verdraengt und
    spaeter wieder eingesetzt."""
    work, out, writes = list(cur), set(), []
    assert sorted(m for m in cur if m) == sorted(m for m in desired if m), "andere Bloecke"
    while work != desired:
        progressed = False
        for k, name in enumerate(desired):
            if name and work[k] is None and (name in work or name in out):
                if name in work:
                    work[work.index(name)] = None
                out.discard(name)
                work[k] = name
                writes.append((k + 1, name))
                progressed = True
        if progressed:
            continue
        k0 = next(k for k in range(len(work)) if desired[k] and work[k] != desired[k])
        free = [k for k in range(len(work)) if work[k] is None]
        if free:   # Block von k0 auf einen freien Platz parken
            work[free[0]], work[k0] = work[k0], None
            writes.append((free[0] + 1, work[free[0]]))
        else:      # Kette voll: Ziel ueberschreiben, der dortige Block kommt spaeter wieder
            name = desired[k0]
            if name in work:
                work[work.index(name)] = None
            out.add(work[k0])
            work[k0] = name
            writes.append((k0 + 1, name))
    return writes


_JS_TR = ('function tr(p) { return App.getProperty(p).translator; } '
          'function sc(n, s) { return tr("%(F)s/" + (s == 2 ? "State2" : "") + "Scene" + n); } '
          'function pp(n, s, i) { return tr("%(F)s/" + (s == 2 ? "State2" : "") + "Scene" + n + "Slot" + (i + 1) + "Preset"); } '
          'function chain() { var o = []; for (var i = 1; i <= %(N)d; i++) o.push(tr("%(C)s" + i).string); return o; } '
          'var FS = %(FS)s; ')


def _move_js(body, **kw):
    kw.update(F=FSW, N=SLOTS, C=ENGINE + "/Chain/ModuleType", FS=json.dumps(list(FS_NUMBERS)))
    return (_JS_TR % kw) + body


def move_chain(br, desired, types):
    """Kette am Geraet in die Reihenfolge desired bringen (Blocknamen, None = leer), ohne
    Parameter oder Scene-Eintraege zu verlieren. types = Auswahlliste von ModuleType.
    Liefert {"chain": [...], "writes": n, "fixed": n} (fixed = wiederhergestellte Eintraege)."""
    snap = json.loads(br.eval(_move_js(
        'var c = chain(), k = {}; '
        'for (var a = 0; a < FS.length; a++) for (var s = 1; s <= 2; s++) { var t = sc(FS[a], s); '
        '  for (var i = 0; i < c.length; i++) if (c[i] != "%s") { var x = t.slot(i); '
        '    k[FS[a] + "/" + s + "/" + c[i]] = [x.mode, pp(FS[a], s, i).string]; } } '
        'return JSON.stringify({chain: c, keep: k});' % EMPTY)))
    cur = [None if m == EMPTY else m for m in snap["chain"]]
    writes = chain_writes(cur, list(desired))
    if not writes:
        return {"chain": cur, "writes": 0, "fixed": 0}
    idx = [[k, types.index(name)] for k, name in writes]
    br.eval(_move_js('var W = %s; for (var i = 0; i < W.length; i++) tr("%s/Chain/ModuleType" + W[i][0]).index = W[i][1]; '
                     'tr("%s/Dirty").state = true; return "";' % (json.dumps(idx), ENGINE, RIGS)))
    time.sleep(0.1)   # die Engine zieht die Scene-Eintraege verschobener Bloecke selbst nach
    # Scene-Eintraege nach Blockname wiederherstellen: nur belegte Plaetze bekommen einen Modus,
    # leere werden auf 0 gesetzt (ein Modus auf leerem Platz kann die App abstuerzen lassen)
    res = json.loads(br.eval(_move_js(
        'var K = %s, c = chain(), fixed = 0; '
        'for (var a = 0; a < FS.length; a++) for (var s = 1; s <= 2; s++) { var t = sc(FS[a], s); '
        '  for (var i = 0; i < c.length; i++) { var x = t.slot(i); '
        '    if (c[i] == "%s") { if (x.mode != 0) { x.mode = 0; fixed++; } continue; } '
        '    var w = K[FS[a] + "/" + s + "/" + c[i]] || [0, "%s"]; '
        '    if (x.mode != w[0]) { x.mode = w[0]; fixed++; } '
        '    var p = pp(FS[a], s, i), ps = p.string || "%s", ws = w[1] || "%s"; '
        '    if (ps != ws) { p.string = ws; fixed++; } } } '
        'return JSON.stringify({chain: c, fixed: fixed});'
        % (json.dumps(snap["keep"]), EMPTY, NO_SCENE_PRESET, NO_SCENE_PRESET, NO_SCENE_PRESET))))
    got = [None if m == EMPTY else m for m in res["chain"]]
    if got != list(desired):
        raise LiveError("Chain on the device: %s" % [g or "-" for g in got])
    return {"chain": got, "writes": len(writes), "fixed": res["fixed"]}


class LiveRig:
    """Abbild des aktiven Rigs am Geraet (Zwischenspeicher der gelesenen Werte)."""

    def __init__(self, session, catalog):
        self.session = session
        self.catalog = catalog
        self.values = {}          # voller Pfad -> letzte Antwort
        self.slots = [None] * SLOTS
        self.name = "?"
        self.rig_id = None
        self.routing = "?"
        self.dirty = False
        self.marking_dirty = False   # Rigs/Dirty wird gerade gesetzt
        self.loaded_modules = set()
        self.setlists = []        # Namen der Setlists am Geraet (ohne ALL_RIGS)
        self.setlist = None       # aktive Setlist oder ALL_RIGS
        self.setlist_sure = False # False = nur vermutet (Geraet meldet die aktive Setlist nicht)
        self.setlist_ids = None   # Setlist-Name -> Datenbank-ID
        self.rows = []            # Datenbankzeilen der aktiven Rig-Liste in Geraete-Reihenfolge
        self.block_types = None   # Auswahlliste fuer ModuleType (einmal gelesen)
        self.presets = None       # Block-Presets {TYP: [{id, type, name, readonly}]} (db_preset_names), None = ungelesen
        self.hw = None            # Hardware-Zuweisungen (read_hardware), None = nicht gelesen
        self.hw_loading = False
        self.nam = None           # NAM-Zustand (nam_status), None = ungelesen
        self.nam_models = None    # NAM-Modelle in Geraete-Reihenfolge (db_nam_models()['models']), None = ungelesen

    def apply_rig_list(self, res):
        """Ergebnis von read_rig_list / enter_setlist / refresh_lists uebernehmen."""
        self.setlists = res["setlists"]
        self.setlist = res["setlist"]
        self.setlist_sure = res["sure"]
        self.setlist_ids = res["setlist_ids"]
        self.rows = res["rows"]

    def setlist_choices(self):
        return [ALL_RIGS] + self.setlists

    # ---- Pfade ----
    @staticmethod
    def path(module, param):
        return "%s/%s/%s" % (ENGINE, module, param)

    @staticmethod
    def slot_path(slot):
        return "%s/Chain/ModuleType%d" % (ENGINE, slot)

    # ---- Kopfdaten ----
    def overview_paths(self):
        paths = ["%s/Rig/PresetName" % ENGINE, "%s/Chain/Routing" % ENGINE, "%s/Dirty" % RIGS, "%s/LoadedID" % RIGS]
        paths += [self.slot_path(i) for i in range(1, SLOTS + 1)]
        return paths

    def apply_overview(self, path, info):
        """Gibt True zurueck, wenn sich Rig oder Kette geaendert haben."""
        if not info.get("ok"):
            return False
        s = info.get("string", "")
        if path.endswith("/Rig/PresetName"):
            changed = s != self.name
            self.name = s
            return changed
        if path.endswith("/Rigs/LoadedID"):
            changed = self.rig_id is not None and s != self.rig_id
            self.rig_id = s
            return changed
        if path.endswith("/Rigs/Dirty"):
            self.dirty = bool(info.get("state"))
            return False
        if path.endswith("/Chain/Routing"):
            self.routing = s
            return False
        n = int(path.rsplit("ModuleType", 1)[1])
        new = None if s == EMPTY else s
        changed = self.slots[n - 1] != new
        self.slots[n - 1] = new
        return changed

    def chain(self):
        return [(i + 1, m) for i, m in enumerate(self.slots)]

    def modules(self):
        """Bloecke der Kette plus Rig/Eingang/Ausgang (ohne die Hardware-Seiten)."""
        return [m for m in self.slots if m] + SPECIAL_MODULES

    def has_module(self, module):
        return module in self.slots or module in SPECIAL_MODULES or module in HW_MODULES

    # ---- Rig-Liste ----
    def rigs(self):
        """[(index, Anzeigename, Farbname, ID)] der aktiven Liste."""
        return [(i, display_name(r["name"]), RIG_COLOURS[int(r.get("color") or 0)]
                 if 0 <= int(r.get("color") or 0) < len(RIG_COLOURS) else "Off", r["id"])
                for i, r in enumerate(self.rows)]

    def row(self, rig_id):
        """Datenbankzeile eines Rigs der aktiven Liste (erstes Vorkommen) oder None."""
        return next((r for r in self.rows if r["id"] == rig_id), None)

    def prog_of(self, rig_id):
        r = self.row(rig_id)
        return _prog(r) if r else None

    # ---- Parameter ----
    def params(self, module):
        """Parameternamen aus dem Katalog (Geraete-Reihenfolge, soweit bekannt)."""
        entry = self.catalog.modules.get(module) or self.catalog.modules.get(self.catalog.base(module)) or {}
        order = list(entry.get("order", []))
        order += sorted(k for k in entry.get("params", {}) if k not in order)
        if module in SPECIAL_MODULES or entry:
            return [p for p in order if p not in HIDDEN_PARAMS]
        return ["On", "Colour"]  # unbekannter Blocktyp: wenigstens die Grundfunktionen

    def info(self, module, param):
        return self.values.get(self.path(module, param))

    def store(self, path, info):
        if info.get("ok"):
            self.values[path] = info

    def forget_module(self, module):
        prefix = "%s/%s/" % (ENGINE, module)
        for k in [k for k in self.values if k.startswith(prefix)]:
            del self.values[k]
        self.loaded_modules.discard(module)

    def is_on(self, module):
        i = self.info(module, "On")
        return None if i is None else bool(i.get("state"))

    def fs_display(self):
        """Anzeige der drei Fussschalter (fs_display), None solange nicht gelesen."""
        return fs_display(self.values)

    def colour(self, module):
        i = self.info(module, "Colour")
        return None if i is None else i.get("string")
