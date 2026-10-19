#!/usr/bin/env python3
"""regressionstest.py - Regressionstest der Live-Funktionen gegen das echte MX5.

Start:  python werkzeuge\\regressionstest.py            (aus dem Editor-Ordner)
        python werkzeuge\\regressionstest.py --schnell  (ohne Speichern-Test)

Prueft ohne Rueckfragen die Kette Verbinden -> Rig-Liste (Datenbank) -> eigenes
Test-Rig anlegen -> Test-Rig laden -> Parameter schreiben/lesen -> Verwerfen -> Speichern ->
Datenbank schreiben (Farbe + Auffrischen, Als neues Rig + Loeschen; Bruecke 0.4) ->
Hardware-Zuweisungen (inkl. Scene-Preset) -> Scenes + Fussschalter druecken -> Bloecke
verschieben -> Tuner -> Looper -> Pegel -> kompakter Poll -> Datenbank-Export -> EVAL -> Umlaute
(Bruecke 0.5) -> Setlists in der Datenbank -> Import + Wiederherstellen -> IR-Auswahl ->
Dateifunktionen -> NAM-Mod (Bruecke 0.7 mit NAM, sonst uebersprungen) -> Verbindungsverlust
(LiveSession) -> App-Neustart (restart_app) -> Aufraeumen.
Dauer ~60 s, mit --schnell ~30 s (ohne Speichern, Als neues Rig, All Rigs und App-Neustart).
Der App-Neustart zeigt am Display kurz 'restore last state?' - der Test antwortet selbst
(No), bitte nicht am Geraet druecken.

Braucht kein bestimmtes Rig und keine bestimmte Setlist (seit 2026-10-04): Der Test legt sein
Rig 'ZZ MXB REGTEST' aus regtest_rig.rig (neben diesem Skript; Kette mit Luecke, IR-Block,
Scenes) selbst an und setzt es voruebergehend an Platz 1 der gerade aktiven Setlist (in 'All
Rigs' steht es am Ende) - eine eigene Setlist braeuchte zwei App-Neustarts, weil das Geraet die
Setlist-Namen nur beim Start liest. Nur dieses Rig wird veraendert und gespeichert; andere Rigs
werden nur geladen. Zum Schluss (auch nach Fehlern) laedt der Test das Rig von vorher, stellt die
Ansicht wieder her und loescht sein Rig (der Setlist-Eintrag verschwindet mit). Reste eines
abgebrochenen Laufs raeumt der naechste Lauf weg.

Voraussetzungen: MX5 per USB mit Brueckenfirmware 0.5 (wie der Editor), kein Dialog am
Display, keine ungespeicherten Aenderungen am geladenen Rig (sonst bricht der Test ab, statt sie
zu verwerfen), der Editor darf nicht gleichzeitig im Live-Modus laufen (gleicher MIDI-Port).
Ergebnis: Konsole + Anhang an regressionstest_log.txt im aktuellen Ordner,
Exit-Code 0 = alles bestanden, 1 = mindestens ein Fehler.
"""
import json, os, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # Editor-Ordner: bridge.py, live.py, rigmodel.py
from bridge import Bridge, BridgeError
import live as L
from rigmodel import Catalog

TEST_RIG = "ZZ MXB REGTEST"        # wird angelegt und am Ende geloescht
RIG_FILE = os.path.join(HERE, "regtest_rig.rig")
LOG = "regressionstest_log.txt"


class Test:
    def __init__(self, quick=False):
        self.quick = quick
        self.br = None
        self.ok = self.bad = 0
        self.failed = []
        self.res = {}          # Zwischenergebnisse fuer spaetere Schritte
        self.log = open(LOG, "a", encoding="utf-8")
        self.say("##### Regressionstest %s #####" % time.strftime("%Y-%m-%d %H:%M:%S"))

    def say(self, txt):
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(txt.encode(enc, "replace").decode(enc), flush=True)   # Konsole kann kein Emoji
        self.log.write(txt + "\n")
        self.log.flush()

    def step(self, name, fn):
        """Einen Schritt ausfuehren; Ausnahmen werden als Fehler gezaehlt, der Test laeuft weiter."""
        t = time.time()
        try:
            detail = fn()
            self.ok += 1
            self.say("  OK      %-34s %5.1f s  %s" % (name, time.time() - t, detail or ""))
        except Exception as e:
            self.bad += 1
            self.failed.append(name)
            self.say("  FEHLER  %-34s %5.1f s  %s: %s" % (name, time.time() - t, type(e).__name__, e))
            if not isinstance(e, (AssertionError, L.LiveError, BridgeError)):
                self.say("          " + traceback.format_exc().strip().replace("\n", "\n          "))

    def need(self, key):
        if key not in self.res:
            raise AssertionError("Voraussetzung fehlt (Schritt '%s' nicht bestanden)" % key)
        return self.res[key]

    # ---------------- Schritte ----------------
    def t_verbinden(self):
        self.br = Bridge.auto()
        v = self.br.ping()
        assert self.br.vnum >= (0, 5), "Bruecke 0.5 noetig, gefunden: %s" % v
        b = L.dialog_buttons(self.br)
        assert not b, "Am MX5 ist ein Dialog offen (%s), bitte am Display beantworten" % " | ".join(b)
        self.res["version"] = v
        return v

    def t_rigliste(self):
        res = L.read_rig_list(self.br)
        assert res["sure"], "aktive Setlist nur vermutet"
        n = len(res["rows"])
        assert n > 0, "keine Rigs"
        self.res["liste"] = res
        return "%d Rigs in '%s', Setlists %s" % (n, res["setlist"], res["setlists"])

    # ---- eigenes Test-Rig ----
    @property
    def set(self):
        """Die Liste, in der der Test arbeitet: die beim Start aktive Setlist (oder All Rigs)."""
        return self.need("start")["setlist"]

    def _set_id(self):
        return self.need("liste")["setlist_ids"].get(self.set) if self.set != L.ALL_RIGS else None

    def _refresh(self, reload_id=None):
        res = self.need("liste")
        res2 = L.refresh_lists(self.br, res["setlists"], self.set, res["setlist_ids"], reload_id=reload_id)
        self.res["liste"] = dict(res, rows=res2["rows"], status=res2["status"])
        return res2

    def _leftovers(self):
        return self.br.sql("select id, name from rigs where name like 'ZZ MXB REGTEST%'")

    def t_vorbereiten(self):
        """Ausgangszustand merken (geladenes Rig, Ansicht), Reste frueherer Laeufe loeschen, Test-Rig
        aus regtest_rig.rig anlegen, an Platz 1 der aktiven Setlist setzen, Liste auffrischen."""
        res = self.need("liste")
        st = L.rig_status(self.br)
        assert not st["dirty"], ("Das geladene Rig '%s' hat ungespeicherte Aenderungen - bitte am Geraet "
                                 "speichern oder verwerfen, der Test wuerde sie sonst verwerfen" % st["name"])
        left = self._leftovers()
        if any(r["id"] == st["id"] for r in left):    # abgebrochener Lauf: sein Rig ist noch geladen
            other = next((i for i, r in enumerate(res["rows"]) if not r["name"].startswith(TEST_RIG)), None)
            assert other is not None, "nur Test-Rigs in der aktiven Liste"
            st = L.load_rig(self.br, res["rows"], other, discard=True)
        self.res["start"] = {"setlist": res["setlist"], "rig": st["id"], "name": st["name"],
                             "board": self.br.get(L.BOARD)}
        for r in left:
            L.delete_rig(self.br, r["id"])
        d = json.load(open(RIG_FILE, encoding="utf-8"))
        rid = L.create_rig(self.br, TEST_RIG, content=d["content"], color=d.get("color", 9))
        self.res["rig_id"] = rid
        sid = self._set_id()
        if sid:   # vor alle anderen Eintraege - deren show_order bleibt unveraendert
            self.br.sql_write(
                "insert into setlist_rigs (id, setlist_id, rig_id, show_order) select %s, %s, %s, "
                "coalesce(min(show_order), 0) - 1 from setlist_rigs where setlist_id = %s"
                % (L.sql_lit(L.new_id()), L.sql_lit(sid), L.sql_lit(rid), L.sql_lit(sid)))
        res2 = self._refresh()
        ids = [r["id"] for r in res2["rows"]]
        assert rid in ids, "Test-Rig nicht in der Liste '%s'" % self.set
        self.res["index"] = ids.index(rid)
        assert not sid or self.res["index"] == 0, "Test-Rig steht an Platz %d statt 1" % (self.res["index"] + 1)
        assert res2["status"]["id"] == st["id"], "Auffrischen hat ein anderes Rig geladen"
        return "%s angelegt, Platz %d in '%s'%s; Ausgangs-Rig %s" % (
            TEST_RIG, self.res["index"] + 1, self.set, ", %d Rest(e) geloescht" % len(left) if left else "", st["name"])

    def t_anderes_rig(self):
        """Erst ein anderes Rig laden, damit das Laden des Test-Rigs wirklich etwas tut."""
        res = self.need("liste")
        if L.rig_status(self.br)["id"] != self.need("rig_id"):
            return "schon ein anderes Rig geladen (%s)" % L.rig_status(self.br)["name"]
        other = next((i for i, r in enumerate(res["rows"]) if r["id"] != self.need("rig_id")), None)
        assert other is not None, "kein zweites Rig in der Liste"
        st = L.load_rig(self.br, res["rows"], other, discard=True)
        assert st["id"] == res["rows"][other]["id"], "LoadedID %s statt %s" % (st["id"], res["rows"][other]["id"])
        return "geladen: %s (%s, %.1f s)" % (st["name"], L.LAST_LOAD.get("via"), L.LAST_LOAD.get("secs", 0))

    def t_laden(self):
        res, idx = self.need("liste"), self.need("index")
        st = L.load_rig(self.br, res["rows"], idx, discard=True)
        assert st["name"] == TEST_RIG, "geladen ist '%s'" % st["name"]
        assert not st["dirty"], "Rig nach dem Laden als geaendert markiert"
        assert st["id"] == self.need("rig_id"), "LoadedID %s passt nicht zur Datenbank %s" % (st["id"], self.res["rig_id"])
        assert L.LAST_LOAD.get("via") == "jump", "nicht per Sprung geladen: %s" % L.LAST_LOAD
        return "LoadedID %s, per Sprung in %.1f s" % (st["id"][:8], L.LAST_LOAD["secs"])

    def t_kette(self):
        lr = L.LiveRig(None, Catalog(os.path.join(os.path.dirname(HERE), "catalog.json")))
        r = self.br.get_many(lr.overview_paths())
        for p, info in r.items():
            lr.apply_overview(p, info)
        assert lr.name == TEST_RIG, "PresetName '%s'" % lr.name
        blocks = [m for m in lr.slots if m]
        assert blocks, "leere Kette"
        self.res["block"] = blocks[0]
        self.res["params"] = lr.params(blocks[0])
        return "%d Bloecke, Routing %s, erster Block '%s' (%d Parameter im Katalog)" % (
            len(blocks), lr.routing, blocks[0], len(self.res["params"]))

    def _on_path(self):
        return L.LiveRig.path(self.need("block"), "On")

    def _on(self):
        info = self.br.get(self._on_path())
        assert info.get("ok"), info
        return bool(info.get("state"))

    def t_schreiben(self):
        was = self._on()
        self.res["on_orig"] = was
        r = self.br.set(self._on_path(), "state", int(not was))
        assert r.get("ok"), r
        # Direkt nach einem Rig-Wechsel verschluckt das Geraet den ersten set ganz, wenn
        # live.SETTLE zu kurz ist - dieser Schritt prueft genau das (einmal schreiben)
        t = time.time()
        while self._on() != (not was):
            assert time.time() - t < 1.0, "Wert nach 1 s nicht uebernommen (set-Antwort: %s)" % r.get("string")
            time.sleep(0.05)
        delay = time.time() - t
        st = L.rig_status(self.br)
        assert not st["dirty"], "Parameter-Schreiben ueber die Bruecke setzt Dirty (neu?)"
        self.br.set(L.RIGS + "/Dirty", "state", 1)
        assert L.rig_status(self.br)["dirty"], "Rigs/Dirty laesst sich nicht setzen"
        return "'%s' On %s -> %s%s, Dirty gesetzt" % (self.res["block"], was, not was,
                                                     " (nach %.0f ms)" % (delay * 1000) if delay > 0.02 else "")

    def t_zahl(self):
        """Einen Zahlenparameter des ersten Blocks lesen, mit 'value' und 'unnormalized' schreiben."""
        block = self.need("block")
        for p in self.need("params"):
            info = self.br.get(L.LiveRig.path(block, p))
            if L.kind_of(info) == L.L_NUMBER and "unnormalized" in info:
                path = L.LiveRig.path(block, p)
                orig_v, orig_u = info["value"], info["unnormalized"]
                self.br.set(path, "value", 0.25)
                v = self.br.get(path)
                assert abs(v["value"] - 0.25) < 0.02, "value 0.25 -> %s" % v["value"]
                self.br.set(path, "unnormalized", orig_u)
                v = self.br.get(path)
                assert abs(v["value"] - orig_v) < 0.02, "unnormalized %s -> value %s statt %s" % (orig_u, v["value"], orig_v)
                return "%s/%s: value %s, unnormalized %s %s" % (block, p, orig_v, orig_u, info.get("string", ""))
        return "kein Zahlenparameter im ersten Block, uebersprungen"

    def t_verwerfen(self):
        res = self.need("liste")
        st = L.reload_rig(self.br, res["rows"])
        assert st["name"] == TEST_RIG, "nach dem Neuladen: %s" % st["name"]
        assert not st["dirty"], "weiterhin geaendert"
        assert self._on() == self.need("on_orig"), "Wert nach dem Verwerfen nicht zurueck"
        return "Rig neu geladen, On wieder %s" % self.res["on_orig"]

    def t_speichern(self):
        if self.quick:
            return "uebersprungen (--schnell)"
        orig, rig_id = self.need("on_orig"), self.need("rig_id")
        before = L.db_rig(self.br, rig_id)["content"]
        self.br.set(self._on_path(), "state", int(not orig))
        self.br.set(L.RIGS + "/Dirty", "state", 1)
        st = L.save_rig(self.br)
        assert not st["dirty"], "nach Speichern noch geaendert (Dialog offen? %s)" % L.dialog_buttons(self.br)
        assert L.db_rig(self.br, rig_id)["content"] != before, "Datenbankinhalt nach dem Speichern unveraendert"
        # zurueck in den Ausgangszustand und wieder speichern
        self.br.set(self._on_path(), "state", int(orig))
        self.br.set(L.RIGS + "/Dirty", "state", 1)
        st = L.save_rig(self.br)
        assert not st["dirty"] and self._on() == orig, "Ruecksetzen nicht gespeichert"
        after = L.db_rig(self.br, rig_id)["content"]
        same = after == before
        return "zweimal gespeichert, On wieder %s, Datenbankinhalt %s" % (
            orig, "wie vorher" if same else "anders als vorher (%d/%d Zeichen)" % (len(after), len(before)))

    def t_db_farbe(self):
        """Farbe in der Datenbank aendern und die aktive Setlist auffrischen lassen: die
        Bank-Anzeige zeigt die neue Farbe, das geladene Rig bleibt geladen und unveraendert."""
        rig_id, idx = self.need("rig_id"), self.need("index")
        st0 = L.rig_status(self.br)
        colour0 = self.br.sql("select color from rigs where id = %s" % L.sql_lit(rig_id))[0]["color"]
        new = 5 if colour0 != 5 else 3
        L.set_rig_color(self.br, rig_id, new)
        try:
            t = time.time()
            res2 = self._refresh(reload_id=rig_id)
            dauer = time.time() - t
            assert res2["status"] == st0, "Auffrischen hat das geladene Rig veraendert: %s" % (res2["status"],)
            L.goto_bank(self.br, res2["rows"], idx // 3)
            shown = L.read_bank(self.br)[idx % 3]
            assert shown == (TEST_RIG, L.RIG_COLOURS[new]), "Bank zeigt %s" % (shown,)
        finally:
            L.set_rig_color(self.br, rig_id, colour0)
            res2 = self._refresh(reload_id=rig_id)
        L.goto_bank(self.br, res2["rows"], idx // 3)
        assert L.read_bank(self.br)[idx % 3] == (TEST_RIG, L.RIG_COLOURS[colour0]), "Farbe nicht zurueckgesetzt"
        return "Farbe %s in der Bank-Anzeige, Auffrischen %.1f s, Rig blieb geladen" % (L.RIG_COLOURS[new], dauer)

    def t_db_kopie(self):
        """Als neues Rig (save_rig_as): Kopie mit dem Live-Stand anlegen, laden, wieder loeschen."""
        if self.quick:
            return "uebersprungen (--schnell)"
        res, rig_id, orig = self.need("liste"), self.need("rig_id"), self.need("on_orig")
        name = TEST_RIG + " KOPIE"
        assert not L.db_name_taken(self.br, "rigs", name), "Rest von frueher: %s loeschen" % name
        before = L.db_rig(self.br, rig_id)["content"]
        self.br.set(self._on_path(), "state", int(not orig))
        self.br.set(L.RIGS + "/Dirty", "state", 1)
        new_id = L.save_rig_as(self.br, name, setlist_id=self._set_id())
        try:
            assert L.db_rig(self.br, rig_id)["content"] == before, "Originalzeile veraendert"
            copy = json.loads(L.db_rig(self.br, new_id)["content"])["data"]["Patch"]["children"]
            assert copy["Rig"]["children"]["PresetName"]["string"] == name, "innerer Name der Kopie"
            assert copy[self.need("block")]["children"]["On"]["state"] == (not orig), "Kopie ohne Live-Stand"
            res2 = self._refresh(reload_id=new_id)
            assert res2["status"]["id"] == new_id and not res2["status"]["dirty"], res2["status"]
            assert self._on() == (not orig), "geladene Kopie hat nicht den Live-Stand"
            st = L.load_rig(self.br, res2["rows"], [r["id"] for r in res2["rows"]].index(rig_id))
            assert st["id"] == rig_id and not st["dirty"] and self._on() == orig, "Original nicht sauber zurueck"
        finally:
            if L.rig_status(self.br)["id"] == new_id:
                L.load_rig(self.br, res["rows"], self.need("index"), discard=True)
            L.delete_rig(self.br, new_id)
            res2 = self._refresh(reload_id=rig_id)
        assert new_id not in [r["id"] for r in res2["rows"]], "Kopie nicht geloescht"
        assert res2["status"]["id"] == rig_id and not res2["status"]["dirty"]
        return "Kopie %s angelegt, geladen, geloescht; Original unveraendert" % name

    def t_hardware(self):
        hw = L.read_hardware(self.br)
        for n in L.FS_NUMBERS:
            d = hw["fs"][n]
            assert d["mode"].get("ok"), "FootSwitch %d ModeNew nicht lesbar" % n
            assert d["modes"], "FootSwitch %d ohne Modusliste" % n
            assert len(d["scenes"]) == 2 and all(len(s) == L.SLOTS for s in d["scenes"]), "Scene-Plaetze"
        for p in (1, 2):
            assert len(hw["pedal"][p]["rows"]) == 4
        modes = [hw["fs"][n]["mode"].get("string") for n in L.FS_NUMBERS]
        # Scene-Preset (Editor-Scene-Modus): auf einem belegten Platz eines Scene-Schalters ein
        # Preset des Blocktyps eintragen, zuruecklesen, wieder entfernen - setzt kein Dirty
        detail = ""
        for n in L.FS_NUMBERS:
            d = hw["fs"][n]
            if d["mode"].get("string") != "Scene":
                continue
            slot = next((i for i, (eff, _, _) in enumerate(d["scenes"][0]) if eff != L.EMPTY), None)
            if slot is None:
                continue
            eff, mode, before = d["scenes"][0][slot]
            names = [r["name"] for r in L.db_presets_of(self.br, eff)]
            if not names:
                continue
            pick = next((x for x in names if x != before), names[0])
            got = L.set_scene_preset(self.br, n, 1, slot, pick)
            assert got == pick, "Scene-Preset: %r statt %r" % (got, pick)
            assert L.read_scene_slots(self.br, n, 1)[slot] == (eff, mode, pick), "Scene-Preset nicht zurueckgelesen"
            assert L.set_scene_preset(self.br, n, 1, slot, before) == before
            assert L.read_scene_slots(self.br, n, 1)[slot] == (eff, mode, before)
            assert not L.rig_status(self.br)["dirty"], "Scene-Preset hat Dirty gesetzt"
            detail = ", Scene-Preset %s auf %s (FS%d) hin und zurueck" % (pick, eff, n - 4)
            break
        return "FS1-3 %s, Pedal1 %s%s" % (modes, (hw["pedal"][1]["mode"] or {}).get("string"), detail)

    # ---- Hilfen fuer die Schritte ab 0.9 ----
    def _chain(self):
        lr = L.LiveRig(None, None)
        for p, info in self.br.get_many(lr.overview_paths()).items():
            lr.apply_overview(p, info)
        return list(lr.slots)

    def _scene_map(self):
        """{(Schalter, Zustand, Block): (Modus, Preset)} aller belegten Scene-Plaetze."""
        out = {}
        for n in L.FS_NUMBERS:
            for st in (1, 2):
                for eff, mode, preset in L.read_scene_slots(self.br, n, st):
                    if eff != L.EMPTY:
                        out[(n, st, eff)] = (mode, preset)
        return out

    def _discard(self):
        """Test-Rig frisch laden (Aenderungen verwerfen) und pruefen, dass es sauber ist."""
        st = L.reload_rig(self.br, self.need("liste")["rows"])
        assert st["name"] == TEST_RIG and not st["dirty"], "Verwerfen: %s dirty=%s" % (st["name"], st["dirty"])

    def t_scenes(self):
        """Scene-Modus eines belegten Platzes setzen und zuruecksetzen, leeren Platz verweigern,
        dann FS1 in der Stomp-Ansicht druecken: die Bloecke folgen der Scene; danach verwerfen."""
        chain = self._chain()
        hw = L.read_hardware(self.br)
        n = next((k for k in L.FS_NUMBERS if hw["fs"][k]["mode"].get("string") == "Scene"), None)
        if n is None:
            return "uebersprungen (kein Scene-Schalter im Test-Rig)"
        scene = hw["fs"][n]["scenes"][0]
        slot = next(i for i, (eff, _, _) in enumerate(scene) if eff != L.EMPTY)
        eff, mode0, _ = scene[slot]
        new = L.SCENE_ON if mode0 != L.SCENE_ON else L.SCENE_OFF
        assert L.set_scene_slot(self.br, n, 1, slot, new) == new
        assert L.read_scene_slots(self.br, n, 1)[slot][1] == new, "Modus nicht zurueckgelesen"
        assert L.set_scene_slot(self.br, n, 1, slot, mode0) == mode0
        empty = next((i for i, m in enumerate(chain) if m is None), None)
        if empty is not None:
            try:
                L.set_scene_slot(self.br, n, 1, empty, L.SCENE_ON)
                raise AssertionError("Modus auf leerem Platz %d wurde nicht verweigert" % (empty + 1))
            except L.LiveError:
                pass
            assert L.read_scene_slots(self.br, n, 1)[empty][1] == 0, "leerer Platz hat einen Modus"
        # Fuer das Ausloesen den Block in der Scene schalten lassen (sonst prueft der Druck nichts);
        # das Test-Rig wird danach ohnehin verworfen
        L.set_scene_slot(self.br, n, 1, slot, new)
        # Ausloesen: Board-Modus kurz auf Stomp (press_footswitch verlangt ihn), danach zurueck
        board = self.br.get(L.BOARD)
        modes = L._entries(self.br, L.BOARD)
        want = {eff: m for eff, m, _ in L.read_scene_slots(self.br, n, 1) if eff != L.EMPTY and m}
        try:
            if board.get("string") != "Stomp":
                self.br.set(L.BOARD, "index", modes.index("Stomp"))
                time.sleep(0.3)
            disp = L.press_footswitch(self.br, n)
            time.sleep(0.3)
            on = {m: bool(self.br.get(L.LiveRig.path(m, "On")).get("state")) for m in want}
            wrong = [m for m, md in want.items() if on[m] != (md == L.SCENE_ON)]
            assert not wrong, "Bloecke folgen der Scene nicht: %s" % wrong
            assert disp.get("%s/FootSwitch%d" % (L.FSW, n), {}).get("state"), "Schalter leuchtet nicht"
        finally:
            if board.get("string") != "Stomp" and "index" in board:
                self.br.set(L.BOARD, "index", board["index"])
                time.sleep(0.3)
            self._discard()
        assert self.br.get(L.BOARD).get("string") == board.get("string"), "Board-Modus nicht zurueck"
        return "FS%d: Modus %s auf %s hin und zurueck, leerer Platz verweigert, Druck schaltet %d Bloecke" % (
            n - 4, new, eff, len(want))

    def t_verschieben(self):
        """Bloecke per move_chain verschieben (in eine Luecke, auf einen belegten Platz) - Parameter
        und Scene-Eintraege bleiben; zurueckschieben, dann verwerfen."""
        orig = self._chain()
        types = L._entries(self.br, L.LiveRig.slot_path(1))
        blocks = [m for m in orig if m]
        if len(blocks) < 2 or None not in orig:
            return "uebersprungen (Kette braucht zwei Bloecke und eine Luecke)"
        scenes0 = self._scene_map()
        src = orig.index(blocks[1]) + 1
        gap = max(i for i, m in enumerate(orig) if m is None) + 1
        probe = L.LiveRig.path(blocks[1], "Colour")
        colour0 = self.br.get(probe).get("string")
        try:
            want = L.plan_block_move(orig, src, gap)                          # in die Luecke
            r = L.move_chain(self.br, want, types)
            assert r["chain"] == want and self._chain() == want, "Kette nach Zug 1: %s" % r["chain"]
            assert self.br.get(probe).get("string") == colour0, "Farbe ging beim Verschieben verloren"
            last = max(i for i, m in enumerate(want) if m) + 1
            want2 = L.plan_block_move(want, last, 1)                           # auf belegten Platz 1
            r2 = L.move_chain(self.br, want2, types)
            assert self._chain() == want2, "Kette nach Zug 2: %s" % self._chain()
            assert self._scene_map() == scenes0, "Scene-Eintraege nach Blockname veraendert"
            assert L.rig_status(self.br)["dirty"], "Verschieben setzt Dirty nicht"
            L.move_chain(self.br, orig, types)
            assert self._chain() == orig and self._scene_map() == scenes0, "Rueckweg"
        finally:
            self._discard()
        assert self._chain() == orig, "Kette nach dem Verwerfen: %s" % self._chain()
        return "%s: Platz %d -> %d, dann Platz %d -> 1 (%d Schreibzugriffe), zurueck; Scenes und Farbe erhalten" % (
            blocks[1], src, gap, last, r2["writes"])

    def t_tuner(self):
        """Tuner aus zwei Ansichten oeffnen und schliessen - danach steht das Geraet wieder in der
        Ansicht von vorher (ExitTuner allein fuehrt immer nach Hybrid)."""
        board = self.br.get(L.BOARD)
        modes = L._entries(self.br, L.BOARD)
        starts = [board["string"], "Stomp" if board["string"] != "Stomp" else "Hybrid"]
        seen = []
        try:
            for start in starts:
                if self.br.get(L.BOARD).get("string") != start:
                    self.br.set(L.BOARD, "index", modes.index(start))
                    time.sleep(0.3)
                t = L.tuner_open(self.br)
                assert t["active"], "Tuner-Seite nicht offen"
                assert t["ref"] and L.TUNER_REF_MIN <= t["ref"] <= L.TUNER_REF_MAX, "Kammerton %s" % t["ref"]
                t0 = time.time()
                for _ in range(20):
                    L.tuner_parse(self.br.get_many(L.TUNER_PATHS))
                ms = (time.time() - t0) / 20 * 1000
                L.tuner_close(self.br)
                now = self.br.get(L.BOARD).get("string")
                assert now == start, "nach dem Tuner %s statt %s" % (now, start)
                seen.append(start)
        finally:
            if self.br.get(L.BOARD).get("string") == "Tuner":
                L.tuner_close(self.br)
            L.restore_board(self.br, board)
        assert self.br.get(L.BOARD).get("string") == board["string"]
        return "Tuner auf/zu aus %s, jeweils zurueck; Kammerton %d Hz, Ablesung %.0f ms" % (" und ".join(seen), t["ref"], ms)

    def t_looper(self):
        """Looper-Ansicht oeffnen, Stille aufnehmen (Loop schliessen, Overdub = 2. Ebene), Peel,
        Geschwindigkeit, Rueckwaerts, Loeschen, Ansicht schliessen. Ein vorhandener Loop des
        Benutzers wird nicht angefasst (Schritt uebersprungen)."""
        board = self.br.get(L.BOARD)
        first = L.looper_open(self.br, None, show=False)
        if first["start"] != "Empty" or first["rec"] == "Rec":
            return "uebersprungen: am Geraet laeuft ein Loop (%s)" % first["state"]
        try:
            st = L.looper_open(self.br, None)
            assert st["board"] == "Looper", "Looper-Ansicht nicht offen (%s)" % st["board"]
            st = L.looper_action(self.br, "record")
            assert st["rec"] == "Rec" and st["start"] == "Empty", "Aufnahme: %s/%s" % (st["start"], st["rec"])
            time.sleep(1.0)
            st = L.looper_action(self.br, "record")
            assert st["start"] == "Playing" and st["rec"] == "OverReady", "Loop schliessen: %s/%s" % (st["start"], st["rec"])
            length = st["length"]
            L.looper_action(self.br, "record")
            time.sleep(1.6)   # eine Overdub-Ebene zaehlt erst, wenn sie ueber den Loop-Anfang laeuft
            st = L.looper_action(self.br, "record")
            for _ in range(10):   # die Ebene zaehlt manchmal erst einen Moment spaeter
                if st["layers"] == 2:
                    break
                time.sleep(0.1)
                st = L.looper_parse(self.br.get_many(L.LOOPER_PATHS))
            assert st["layers"] == 2, "Overdub: %d Ebenen" % st["layers"]
            st = L.looper_action(self.br, "undo")
            assert st["layers"] == 1 and st["start"] == "Playing", "Peel: %d Ebenen, %s" % (st["layers"], st["start"])
            st = L.looper_action(self.br, "double_speed")
            assert st["speed"] == "x 2", "Speed %s" % st["speed"]
            st = L.looper_action(self.br, "reverse")
            assert st["reverse"], "nicht rueckwaerts"
            st = L.looper_action(self.br, "reverse")
            pos = [L.looper_parse(self.br.get_many(L.LOOPER_PATHS))["pos"] for _ in range(3) if not time.sleep(0.1)]
            st = L.looper_action(self.br, "play")
            assert st["start"] == "Stopped", "Stop: %s" % st["start"]
        finally:
            st = L.looper_parse(self.br.get_many(L.LOOPER_PATHS))
            if st["start"] != "Empty" or st["rec"] == "Rec":
                st = L.looper_action(self.br, "clear")
            L.looper_close(self.br)
            L.restore_board(self.br, board)
        assert st["start"] == "Empty" and st["speed"] == "x 1", "nach Clear %s, %s" % (st["start"], st["speed"])
        now = self.br.get(L.BOARD).get("string")
        assert now == board["string"], "nach dem Looper %s statt %s" % (now, board["string"])
        return "Aufnahme %s, Overdub + Peel, x2, rueckwaerts, Position %s, geloescht; Ansicht %s" % (
            length, "/".join("%d" % p for p in pos), now)

    def t_pegel(self):
        out = []
        for m in ("Input", "Output"):
            vals = L.meter_parse(m, self.br.get_many(L.meter_paths(m)))
            for name, cur, peak in vals:
                assert cur is not None and peak is not None, "%s/%s nicht lesbar" % (m, name)
                assert -121 <= cur <= 7 and -121 <= peak <= 7, "%s/%s ausserhalb: %s %s" % (m, name, cur, peak)
                out.append("%s %.0f dB" % (name, cur))
        return ", ".join(out)

    def t_kompakt(self):
        """Kompakter Poll (get_compact) liefert dieselben Werte wie get_many."""
        chain = [m for m in self._chain() if m]
        lr = L.LiveRig(None, None)
        paths = lr.overview_paths() + L.fs_display_paths() + ["/Engine/Patch/GibtEsNicht/X"]
        for m in chain:
            paths += [lr.path(m, "On"), lr.path(m, "Colour")]
        paths += [lr.path(self.need("block"), p) for p in self.need("params")]
        full, comp = self.br.get_many(paths), L.get_compact(self.br, paths)
        bad = [p for p in dict.fromkeys(paths) if full[p].get("ok") != comp[p].get("ok")
               or any(full[p].get(k) != comp[p].get(k) for k in L.COMPACT_FIELDS)]
        assert not bad, "Abweichungen: %s" % bad[:5]
        t0 = time.time()
        for _ in range(5):
            L.get_compact(self.br, paths)
        return "%d Pfade gleich, %.0f ms je Abfrage" % (len(set(paths)), (time.time() - t0) / 5 * 1000)

    def t_setlists(self):
        """Setlist in der Datenbank anlegen, befuellen, umsortieren, umbenennen, loeschen
        (ohne App-Neustart - die Set-Anzeige erfaehrt davon nichts, die Setlist ist danach weg)."""
        rig_id = self.need("rig_id")
        name, name2 = "ZZ MXB REGTEST", "ZZ MXB REGTEST 2"
        for nm in (name, name2):
            assert not L.db_name_taken(self.br, "setlists", nm), "Rest von frueher: Setlist %s loeschen" % nm
        sid = L.create_setlist(self.br, name, [rig_id])
        try:
            L.setlist_add(self.br, sid, rig_id)
            assert L.db_setlist_members(self.br).get(sid) == [rig_id, rig_id], "Anhaengen"
            L.setlist_set_order(self.br, sid, [None, rig_id])
            assert L.db_setlist_rig_ids(self.br, sid) == [None, rig_id], "Umsortieren mit Leerplatz"
            assert L.rename_setlist(self.br, sid, name2.lower()) == name2
            assert dict(L.db_setlists(self.br)).get(sid) == name2, "Umbenennen"
        finally:
            L.delete_setlist(self.br, sid)
        assert sid not in dict(L.db_setlists(self.br)), "Setlist nicht geloescht"
        assert sid not in L.db_setlist_members(self.br), "Eintraege nicht mitgeloescht (Cascade)"
        return "angelegt, 2 Eintraege, umsortiert (mit Leerplatz), umbenannt, geloescht"

    def t_import(self):
        """.rig-Datei des Test-Rigs als neues Rig importieren und loeschen; 'Alles wiederherstellen'
        mit vorhandenen Dateien (Rig, Setlist, Preset) darf nichts anlegen."""
        import tempfile, shutil
        rig_id = self.need("rig_id")
        row = L.db_rig(self.br, rig_id)
        folder = tempfile.mkdtemp(prefix="mx5reg_")
        try:
            for d in ("Rigs", "Setlists", os.path.join("Blocks", "X")):
                os.makedirs(os.path.join(folder, d))
            path = os.path.join(folder, "Rigs", TEST_RIG + ".rig")
            L._write(path, L.rig_file_json(row))
            name = TEST_RIG + " IMPORT"
            assert not L.db_name_taken(self.br, "rigs", name), "Rest von frueher: %s loeschen" % name
            new_id, what = L.import_rig_file(self.br, path, name=name, mode="new")
            try:
                assert what == "neu" and new_id != rig_id
                copy = L.db_rig(self.br, new_id)
                assert copy["name"] == name and copy["content"] == L.content_with_name(row["content"], name), "Inhalt"
            finally:
                L.delete_rig(self.br, new_id)
            assert not L.db_name_taken(self.br, "rigs", name), "Import nicht geloescht"
            # irgendeine vorhandene Setlist (die aktive, sonst die erste) - keine: ohne Setlist-Datei
            sls = [s for s, _ in L.db_setlist_rows(self.br)]
            sl = next((s for s in sls if s["name"] == self.set), sls[0] if sls else None)
            if sl:
                rr = [(r, "") for r in L.db_setlist_rig_ids(self.br, sl["id"])]
                L._write(os.path.join(folder, "Setlists", L.safe_filename(sl["name"]) + ".setlist"),
                         L.setlist_file_json(sl, rr))
            bid = self.br.sql("select id from blocks order by id limit 1")[0]["id"]
            blk = L._exact_row(self.br, "blocks", ["id", "type", "name", "content", "is_readonly"], "id", bid)
            L._write(os.path.join(folder, "Blocks", "X", L.safe_filename(blk["name"]) + ".block"), L.block_file_json(blk))
            c = L.restore_all(self.br, folder)
            assert c["rigs"] == 0 and c["rigs_vorhanden"] == 1 and c["setlists"] == 0 and c["blocks"] == 0, c
            assert not c["fehler"], c["fehler"]
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        return "Import als neues Rig + geloescht; Wiederherstellen mit vorhandenen Dateien legte nichts an"

    def t_verbindung(self):
        """LiveSession: eine einzelne verlorene Antwort ist kein Abbruch; antwortet das Geraet gar
        nicht mehr (Nachrichten gehen ins Leere), meldet die Sitzung den Verlust (on_lost)."""
        br = self.br
        def session(lost):
            return L.LiveSession(br, dispatch=lambda f: f(), on_lost=lambda: lost.append(time.time()))
        def stop(s):   # Worker beenden, ohne die Bridge zu schliessen
            with s._cv:
                s._stop = True
                s._cv.notify()
            s._thread.join(timeout=10)
        def wait(results, n, secs):
            end = time.time() + secs
            while len(results) < n and time.time() < end:
                time.sleep(0.05)
        real = br.out.send
        # 1) eine verschluckte Nachricht: Zeitueberschreitung, Ping klappt -> weiter verbunden
        lost, res = [], []
        s = session(lost)
        dropped = []
        br.out.send = lambda m: dropped.append(m) if not dropped else real(m)
        try:
            s.run(lambda b: b.eval("return 1"), res.append)
            s.run(lambda b: b.eval("return 2"), res.append)
            wait(res, 2, 10)
        finally:
            del br.out.send
            stop(s)
        assert not lost and len(res) == 2 and res[1] == "2", "einzelne verlorene Antwort: lost=%s res=%s" % (lost, res)
        # 2) Geraet stumm: Verlust wird gemeldet, der Worker endet
        lost, res = [], []
        s = session(lost)
        br.out.send = lambda m: None
        t0 = time.time()
        try:
            s.run(lambda b: b.eval("return 1"), res.append)
            wait(lost, 1, 10)
        finally:
            del br.out.send
            stop(s)
        assert lost and s.lost, "Verlust nicht erkannt"
        took = lost[0] - t0
        br._drain()
        # 3) dasselbe ueber get_many (wiederholt eine ausgebliebene Antwort erst nach einem Ping)
        lost, res = [], []
        s = session(lost)
        dropped = []
        br.out.send = lambda m: dropped.append(m) if not dropped else real(m)
        try:
            s.get_many([L.RIGS + "/LoadedName"], res.append)
            wait(res, 1, 10)
        finally:
            del br.out.send
        assert not lost and res and (L.RIGS + "/LoadedName") in res[0], "get_many nach verlorener Antwort: %s" % res
        br.out.send = lambda m: None
        t0 = time.time()
        try:
            s.get_many([L.RIGS + "/LoadedName"], res.append)
            wait(lost, 1, 12)
        finally:
            del br.out.send
            stop(s)
        assert lost and s.lost, "Verlust ueber get_many nicht erkannt"
        took2 = lost[0] - t0
        assert took2 < 5.5, "Verlust ueber get_many erst nach %.1f s erkannt" % took2
        br._drain()
        assert br.ping().startswith("MX5Bridge"), "Bridge danach nicht mehr ansprechbar"
        return "verlorene Antwort ueberbrueckt, stummes Geraet nach %.1f s (eval) / %.1f s (get_many) erkannt" % (took, took2)

    def _zahl_param(self):
        """Pfad und Info eines Zahlenparameters des ersten Blocks (oder None)."""
        block = self.need("block")
        for p in self.need("params"):
            path = L.LiveRig.path(block, p)
            info = self.br.get(path)
            if L.kind_of(info) == L.L_NUMBER and "unnormalized" in info:
                return path, info
        return None

    def t_neustart(self):
        """restart_app mit keep_edits: ungespeicherte Aenderung am Test-Rig, Geraete-App neu starten,
        Dialog mit No beantworten, Setlist + Test-Rig laden - die Aenderung muss noch da sein, das Rig
        als geaendert markiert und seine Datenbankzeile unveraendert. Danach wird verworfen."""
        if self.quick:
            return "uebersprungen (--schnell)"
        t0 = time.time()
        rid = self.need("rig_id")
        st = L.rig_status(self.br)
        if st["id"] != rid:
            res = self.need("liste")
            L.load_rig(self.br, res["rows"], [r["id"] for r in res["rows"]].index(rid), discard=True)
        saved = L.db_rig(self.br, rid)["content"]
        par = self._zahl_param()
        assert par, "kein Zahlenparameter im ersten Block"
        path, info = par
        edit = 0.81 if abs(info["value"] - 0.81) > 0.05 else 0.23
        self.br.set(path, "value", edit)
        self.br.set(L.RIGS + "/Dirty", "state", 1)
        board = self.br.get(L.BOARD).get("string")
        res = L.restart_app(self.br, rig_id=rid, setlist=self.set, keep_edits=True)
        now = self.br.get(L.BOARD).get("string")
        assert now == board, "Ansicht nach dem Neustart %s statt %s" % (now, board)
        st = L.rig_status(self.br)
        assert st["id"] == rid, "nach dem Neustart geladen: %s" % (st,)
        assert res["setlist"] == self.set, "Setlist %s" % res["setlist"]
        assert not L.dialog_buttons(self.br), "Dialog offen: %s" % L.dialog_buttons(self.br)
        assert res.get("edits_kept") and not res.get("edits_lost"), "Aenderungen nicht behalten: %s" % res.get("edits_lost")
        assert st["dirty"], "Rig nach dem Neustart nicht als geaendert markiert"
        v = self.br.get(path)["value"]
        assert abs(v - edit) < 0.02, "%s nach dem Neustart %s statt %s" % (path, v, edit)
        assert L.db_rig(self.br, rid)["content"] == saved, "Datenbankzeile des Test-Rigs wurde veraendert"
        # verwerfen: Dirty weg, frisch laden -> wieder der gespeicherte Wert
        L.drop_changes(self.br)
        L.reload_rig(self.br, res["rows"])
        v2 = self.br.get(path)["value"]
        assert abs(v2 - info["value"]) < 0.02, "nach dem Verwerfen %s statt %s" % (v2, info["value"])
        assert not L.rig_status(self.br)["dirty"], "nach dem Verwerfen noch geaendert"
        self.res["liste"] = res
        return "App neu gestartet, %s in %s geladen (%s), Aenderung %s = %.2f behalten, %.0f s" % (
            TEST_RIG, self.set, L.LAST_LOAD.get("via"), path.rsplit("/", 2)[-2] + "/" + path.rsplit("/", 1)[-1], edit,
            time.time() - t0)

    def t_all_rigs(self):
        """All Rigs: ein Rig mit doppeltem Anzeigenamen (zweites Vorkommen) und das zuletzt angelegte
        (Ende der rowid-Reihenfolge) ueber ihre Position laden, an der LoadedID pruefen. Die Rigs
        werden nur geladen; danach wieder die Ausgangsliste mit dem Test-Rig."""
        if self.quick:
            return "uebersprungen (--schnell)"
        res = self.need("liste")
        board = self.br.get(L.BOARD)
        allr = L.enter_setlist(self.br, res["setlists"], L.ALL_RIGS, res["setlist_ids"])
        rows = allr["rows"]
        assert len(rows) == self.br.sql("select count(*) n from rigs")[0]["n"], "All Rigs unvollstaendig"
        names = [L.display_name(r["name"]) for r in rows]
        dup = next((i for i, n in enumerate(names) if names.index(n) != i), None)
        picks = ([dup] if dup is not None else []) + [len(rows) - 1]
        done = []
        try:
            for i in picks:   # doppelter Name ueber die Bank-Anzeige (Rueckfall), das neueste per Sprung
                t = time.time()
                st = L.load_rig(self.br, rows, i, discard=True, fast=(i != dup))
                assert st["id"] == rows[i]["id"], "%s: LoadedID %s statt %s" % (names[i], st["id"], rows[i]["id"])
                done.append("%s (Platz %d, %s, %.1f s)" % (names[i], i + 1, "Bank" if i == dup else "Sprung",
                                                           time.time() - t))
        finally:
            back = L.enter_setlist(self.br, res["setlists"], self.set, res["setlist_ids"], discard=True)
            idx = [r["id"] for r in back["rows"]].index(self.need("rig_id"))
            st = L.load_rig(self.br, back["rows"], idx, discard=True)
            L.restore_board(self.br, board)
            self.res["liste"] = back
        assert st["id"] == self.need("rig_id") and not st["dirty"], "Test-Rig nicht zurueck"
        return "geladen: %s; zurueck in %s" % (", ".join(done), self.set)

    def t_datenbank(self):
        row = L.db_rig(self.br, self.need("rig_id"))
        assert row["name"] == TEST_RIG
        d = json.loads(L.rig_file_json(row))
        content = json.loads(d["content"])
        assert isinstance(d["readonly"], bool) and "id" in d and isinstance(content, dict)
        exact = L._sql_text(self.br, "content", "rigs where id = %s" % L.sql_lit(row["id"]), size=5000)
        assert exact == row["content"], "stueckweises Lesen liefert anderen Inhalt"
        sets = {sl["name"]: rr for sl, rr in L.db_setlist_rows(self.br)}
        if self.set != L.ALL_RIGS:
            assert any(i == row["id"] for i, _ in sets.get(self.set, [])), "Test-Rig nicht in %s" % self.set
        blocks = self.br.sql("select count(*) n from blocks")[0]["n"]
        settings = L.db_settings(self.br)
        assert "RigVersion" in settings
        return "%d Zeichen content, %d Setlists, %d Block-Presets, RigVersion %s" % (
            len(row["content"]), len(sets), blocks, settings["RigVersion"])

    def t_eval(self):
        r = self.br.eval("return String(1 + 1) + '/' + typeof App.getProperty;")
        assert r == "2/function", r
        return r

    def t_umlaute(self):
        """Bruecke 0.5: Nicht-ASCII-Zeichen in beiden Richtungen (eval, set/get string, SQL)."""
        text = "Grüße € 😀 ÄÖÜ"
        r = self.br.eval("return %s;" % json.dumps(text, ensure_ascii=False))
        assert r == text, "eval: %r" % r
        r = self.br.sql("select 'Grüße' || char(8364) as t, hex('ü') as h")   # Umlaute roh in der Anfrage
        assert r and r[0]["t"] == "Grüße€" and r[0]["h"] == "C3BC", "SQL: %r" % r
        # Text-Property ohne Pruefung und ohne Dirty: Scene-Preset des ersten Kettenplatzes von FS1
        path = L.scene_preset_path(5, 1, 0)
        orig = self.br.get(path).get("string")
        try:
            got = self.br.set(path, "string", text).get("string")
            assert got == text, "set: %r" % got
            assert self.br.get_many([path])[path].get("string") == text, "get_many"
        finally:
            self.br.set(path, "string", orig or L.NO_SCENE_PRESET)
        assert self.br.get(path).get("string") == (orig or L.NO_SCENE_PRESET)
        return "eval, SQL (UTF-8 in der Datenbank-Anfrage) und set/get string mit %r" % text

    def t_ir(self):
        """IR-Block des Test-Rigs: IR-Liste vom Geraet, IR ueber Feld string umschalten
        (IRNotFound bleibt aus), auf den Ausgangswert zurueck."""
        lr = L.LiveRig(None, Catalog(os.path.join(os.path.dirname(HERE), "catalog.json")))
        r = self.br.get_many(lr.overview_paths())
        for p, info in r.items():
            lr.apply_overview(p, info)
        mods = [m for m in lr.slots if m and (m[:-2] if m.endswith(" 2") else m) in L.IR_MODULES]
        if not mods:
            return "uebersprungen (kein IR-Block im Test-Rig)"
        m = mods[0]
        irs = L.db_irs(self.br)
        total = sum(len(v) for v in irs["files"].values())
        assert total > 0 and irs["folders"], "keine IR-Dateien gelesen"
        path = L.LiveRig.path(m, "IR")
        orig = self.br.get(path)["string"]
        d0, n0 = L.parse_ir(orig)
        assert d0 is not None, "IR-Text unerwartet: %s" % orig
        # eine andere IR aus einem anderen Ordner als die aktuelle
        other = next(((f, n) for f in irs["folders"] for n, _ in irs["files"][f] if f != d0), None)
        assert other, "keine zweite IR"
        lite = "Lite" if "1024" in m else ""
        sec = "2" if m.endswith(" 2") else ""
        nf = "/Engine/PresetCtrl/Resources/IRNotFound%s%s" % (lite, sec)
        try:
            self.br.set(path, "string", L.ir_string(*other))
            time.sleep(0.5)
            info = self.br.get(L.LiveRig.path(m, "IRInfoString"))["string"]
            assert info == "%s / %s" % other, "IRInfoString %s" % info
            assert not self.br.get(nf).get("state"), "IRNotFound gesetzt fuer %s" % (other,)
        finally:
            self.br.set(path, "string", orig)
            time.sleep(0.3)
        assert self.br.get(path)["string"] == orig
        return "%d IRs in %d Ordnern, %s: %s -> %s / %s -> zurueck" % (total, len(irs["folders"]), m, n0, other[0], other[1])

    def t_dateien(self):
        """Dateifunktionen der Bruecke (Lesekanal): schreiben, lesen, auflisten, Shell - in /tmp."""
        d = "/tmp/mx5bridge/regtest"
        data = bytes(range(256)) * 100 + "Umlaut äöü".encode("utf-8")
        self.br.make_dir(d)
        n = self.br.write_file(d + "/probe.bin", data, chunk=7000)
        assert n == len(data)
        assert self.br.read_file(d + "/probe.bin", page=9000) == data, "gelesen != geschrieben"
        self.br.write_file(d + "/Tést.txt", b"x")
        names = sorted(name for name, is_dir, _ in self.br.list_dir(d))
        assert names == ["Tést.txt", "probe.bin"], names
        rc, out = self.br.shell("ls %s | wc -l" % d)
        assert rc == 0 and out.strip() == "2", (rc, out)
        rc, _ = self.br.shell("rm -r %s" % d)
        assert rc == 0 and all(nm != "regtest" for nm, _, _ in self.br.list_dir("/tmp/mx5bridge")), "nicht geloescht"
        return "%d Bytes hin und zurueck, Umlaut-Name, Shell ok" % len(data)

    def t_nam(self):
        """NAM-Mod (Bruecke 0.7 mit NAM): Zustand, Modellliste, Verwendung und das Nachziehen der
        Drive-Werte an einem voruebergehenden Preset '998 - ...' - keine Dateien, kein Neustart."""
        import uuid
        nam = L.nam_status(self.br)
        if not nam["installed"]:
            return "uebersprungen (Firmware ohne NAM-Mod)"
        models = L.db_nam_models(self.br)["models"]
        assert [m["index"] for m in models] == list(range(len(models)))
        test = dict(nam, active=True)
        use = L.nam_usage(self.br, test)
        pid = str(uuid.uuid4())
        name = "998 - ZZ MXB REGTEST"
        content = json.dumps({"data": {"Anxiety OD": {"childorder": ["Drive"], "children": {"Drive": {"type": 0, "value": 7}}}},
                              "info": {"version": "1.0.9"}}, sort_keys=True, separators=(",", ":"))
        drive = "select json_extract(content, '$.data.\"Anxiety OD\".children.Drive.value') v from blocks where id = %s" \
                % L.sql_lit(pid)
        try:
            self.br.sql_write("insert into blocks (id, type, name, content, is_readonly) values (%s, 'ANXIETY OD', %s, %s, 0)"
                              % (L.sql_lit(pid), L.sql_lit(name), L.sql_lit(content)))
            assert "Preset %s (ANXIETY OD)" % name in L.nam_usage(self.br, test).get(7, []), "Verwendung ohne Preset"
            assert L.nam_remap(self.br, test, {7: 3, 99: 98}) >= 1
            assert self.br.sql(drive)[0]["v"] == 3, "Drive nicht nachgezogen"
            row = self.br.sql("select content from blocks where id = %s" % L.sql_lit(pid))[0]["content"]
            assert row == content.replace('"value":7', '"value":3'), "Inhalt ausser Drive veraendert: %s" % row
        finally:
            self.br.sql_write("delete from blocks where id = %s" % L.sql_lit(pid))
        assert L.nam_usage(self.br, test) == use, "Verwendung nach dem Test anders"
        return "NAM %s %s, %d Modell(e), %d Platz/Plaetze belegt; Preset-Drive 7 -> 3 nachgezogen, Inhalt sonst gleich" % (
            nam["ref"], "an" if nam["active"] else "aus", len(models), len(use))

    def t_ende(self):
        """Laeuft immer (auch nach Fehlern): Ausgangsliste betreten, das Rig von vorher laden
        (Aenderungen am Test-Rig verwerfen), Test-Rigs loeschen, Liste auffrischen, Ansicht zurueck."""
        v = self.br.ping()
        start = self.need("start")
        res = self.need("liste")
        back = L.enter_setlist(self.br, res["setlists"], start["setlist"], res["setlist_ids"], discard=True)
        ids = [r["id"] for r in back["rows"]]
        assert start["rig"] in ids, "Ausgangs-Rig %s nicht mehr in '%s'" % (start["name"], start["setlist"])
        if L.rig_status(self.br)["id"] != start["rig"]:
            L.load_rig(self.br, back["rows"], ids.index(start["rig"]), discard=True)
        left = self._leftovers()
        for r in left:
            L.delete_rig(self.br, r["id"])
        L.refresh_lists(self.br, res["setlists"], start["setlist"], res["setlist_ids"])
        L.restore_board(self.br, start["board"])
        st = L.rig_status(self.br)
        assert st["id"] == start["rig"] and not st["dirty"], "Endzustand: %s dirty=%s" % (st["name"], st["dirty"])
        assert not self._leftovers(), "Test-Rig nicht geloescht"
        assert not L.dialog_buttons(self.br), "Dialog am Display offen"
        now = self.br.get(L.BOARD).get("string")
        assert now == start["board"].get("string"), "Ansicht %s statt %s" % (now, start["board"].get("string"))
        return "%s; wieder %s in '%s', Ansicht %s, %d Test-Rig(s) geloescht" % (
            v, start["name"], start["setlist"], now, len(left))

    # ---------------- Ablauf ----------------
    def run(self):
        steps = [("Verbinden", self.t_verbinden), ("Rig-Liste (Datenbank)", self.t_rigliste),
                 ("Test-Rig anlegen", self.t_vorbereiten), ("Anderes Rig laden", self.t_anderes_rig),
                 ("Test-Rig laden", self.t_laden), ("Kette lesen", self.t_kette),
                 ("Schalter schreiben + Dirty", self.t_schreiben), ("Zahlenparameter", self.t_zahl),
                 ("Verwerfen (neu laden)", self.t_verwerfen), ("Speichern", self.t_speichern),
                 ("DB: Farbe + Auffrischen", self.t_db_farbe), ("DB: Als neues Rig + Loeschen", self.t_db_kopie),
                 ("Hardware-Zuweisungen", self.t_hardware), ("Scenes + Fussschalter", self.t_scenes),
                 ("Bloecke verschieben", self.t_verschieben), ("Tuner", self.t_tuner), ("Looper", self.t_looper),
                 ("Pegel", self.t_pegel),
                 ("Kompakter Poll", self.t_kompakt), ("All Rigs: Laden per Position", self.t_all_rigs),
                 ("Datenbank-Export", self.t_datenbank),
                 ("EVAL", self.t_eval), ("Umlaute (Bruecke 0.5)", self.t_umlaute),
                 ("DB: Setlists", self.t_setlists), ("DB: Import + Wiederherstellen", self.t_import),
                 ("IR-Auswahl", self.t_ir), ("Dateien (Bruecke)", self.t_dateien), ("NAM-Mod (Bruecke 0.7)", self.t_nam),
                 ("Verbindungsverlust", self.t_verbindung), ("App-Neustart", self.t_neustart),
                 ("Aufraeumen + Endzustand", self.t_ende)]
        t0 = time.time()
        for name, fn in steps:
            if self.br is None and fn != self.t_verbinden:
                self.bad += 1
                self.failed.append(name)
                self.say("  -       %-34s        keine Verbindung" % name)
                continue
            self.step(name, fn)
        self.say("Ergebnis: %d bestanden, %d fehlgeschlagen, %.0f s%s" % (
            self.ok, self.bad, time.time() - t0, ("  -> " + ", ".join(self.failed)) if self.failed else ""))
        if self.br:
            self.br.close()
        self.log.close()
        return self.bad == 0


if __name__ == "__main__":
    ok = Test(quick="--schnell" in sys.argv).run()
    sys.exit(0 if ok else 1)
