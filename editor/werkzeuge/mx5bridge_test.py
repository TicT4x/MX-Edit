#!/usr/bin/env python3
"""MX5 Bridge - PC-Testprogramm 0.10 (inoffiziell)

Voraussetzung:  pip install mido python-rtmidi   (bridge.py im selben Ordner)
Aufruf:         python mx5bridge_test.py            automatischer Test
                python mx5bridge_test.py --shell    interaktiv
                python mx5bridge_test.py --ports    nur MIDI-Ports anzeigen

Ausgaben landen zusaetzlich in mx5bridge_testlog.txt.

Stand nach 0.7:
  - Laden:     /Engine/PresetCtrl/Rigs/ReceivePresetIndex = Programmnummer - 1
  - Speichern: /Engine/RedirCtrl/EditModeSaveRig state=1 -> Dialog
               cancel|save|save_new_rig = FS1|FS2|FS3 ueber RawFootswitches/FSn
Neu in 0.8:
  - Rig-Liste ueber die Bank-Anzeige des Rig-Modus: RigName1-3 lesen,
    NextBank druecken, wiederholen. Laedt dabei hoffentlich kein Rig.
Neu in 0.9:
  - Shell-Befehl sql (Bruecke 0.3): Nur-Lese-Abfragen der Rig-Datenbank,
    z. B.  sql select name, prog_num from rigs order by name
Neu in 0.10:
  - Shell-Befehle write (Bruecke 0.4, schreibend, eine Transaktion) und
    action status|backup|restore|restart (Datenbankdienst),
    z. B.  write update rigs set color = 3 where name = 'MXBRIDGE TEST'
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                    # PC-Test der Bruecke: bridge.py liegt daneben
sys.path.insert(1, os.path.dirname(HERE))   # werkzeuge\ des Editors: bridge.py im Editor-Ordner
try:
    import mido
except ImportError:
    sys.exit("Bitte zuerst installieren:  pip install mido python-rtmidi")
from bridge import Bridge, BridgeError

VERSION = "0.9"
LOG = open("mx5bridge_testlog.txt", "a", encoding="utf-8")
P = "/Engine/Patch"
PC = "/Engine/PresetCtrl"
RIGS = PC + "/Rigs"
RIG_PROPS = ["LoadedID", "LoadedName", "LoadedColor", "Dirty", "LoadedProgNum"]
SAVE = "/Engine/RedirCtrl/EditModeSaveRig"
FS = "/Engine/RedirCtrl/RawFootswitches/FS%d"
BOARD = "/Engine/RedirCtrl/BoardMode"
CHANNEL = "/Engine/MIDICtrl/Channel"
USB = "/media/az01-internal/Evil/usb_mnt"
BANK_PROPS = ["RigName1", "RigName2", "RigName3", "RigColour1", "RigColour2", "RigColour3",
              "SetName1", "SetRigName1", "SetRigName2", "SetRigName3", "CurrentPreset",
              "LoadRig1", "LoadRig2", "LoadRig3", "NextBank", "PrevBank", "NextPreset", "PrevPreset"]


class Abort(Exception):
    pass


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    LOG.write(s + "\n")
    LOG.flush()


def ask(q):
    a = input(q + " [j/n] ").strip().lower()
    log("   ", q, "->", a)
    return a == "j"


def ask_text(q):
    a = input(q + " ").strip()
    log("   ", q, "->", a)
    return a


def step(title, fn):
    log("\n=== %s ===" % title)
    try:
        return fn()
    except BridgeError as e:
        log("  FEHLER:", e)
    except Abort:
        raise
    except Exception as e:
        log("  AUSNAHME:", type(e).__name__, e)


def alive(b):
    try:
        b.ping()
        return True
    except BridgeError:
        log("  Bruecke antwortet nicht mehr. Abbruch, bitte MX5 neu starten.")
        raise Abort()


def connect():
    ins, outs = mido.get_input_names(), mido.get_output_names()
    log("Eingaenge:", ins)
    log("Ausgaenge:", outs)
    try:
        i, o = Bridge.find_ports()
    except BridgeError as e:
        log(e)
        log("Hinweis: Der Port erscheint ca. 10 s nach dem Start des MX5 bzw. nach")
        log("Verlassen des USB-Transfer-Modus.")
        sys.exit(1)
    log("Verwende Eingang '%s', Ausgang '%s'" % (i, o))
    return Bridge(i, o)


def rig_state(b):
    res = b.get_many(["%s/%s" % (RIGS, n) for n in RIG_PROPS])
    return {k.rsplit("/", 1)[1]: v for k, v in res.items()}


def short(v):
    if not v.get("ok"):
        return "(fehlt)"
    keys = ("string", "unnormalized", "index", "state", "numEntries", "maximum")
    return {k: v[k] for k in keys if k in v}


def prog_of(st):
    s = st["LoadedProgNum"].get("string", "-")
    return int(s) if s.isdigit() else None


def press(b, path, hold=0.15):
    b.set(path, "state", 1)
    time.sleep(hold)
    return short(b.set(path, "state", 0))


def bank_names(b):
    res = b.get_many(["%s/RigName%d" % (PC, n) for n in (1, 2, 3)])
    return [res["%s/RigName%d" % (PC, n)].get("string") for n in (1, 2, 3)]


def midi_channel(b):
    try:
        ch = int(b.get(CHANNEL).get("unnormalized", 1))
    except (BridgeError, ValueError, TypeError):
        ch = 1
    return max(0, min(15, ch - 1))


def send_pc(b, program, channel):
    b.out.send(mido.Message("program_change", channel=channel, program=max(0, min(127, program))))


def js_list(expr):
    return ("var l = %s; if (l === undefined || l === null) return 'undefined'; "
            "try { return l.length + ' Eintraege: ' + Array.prototype.slice.call(l, 0, 40).join(' | '); } "
            "catch (e) { return 'kein Array: ' + l; }" % expr)


def js_members(expr):
    return ("var o = %s; if (o === undefined || o === null) return 'undefined'; var r = []; "
            "for (var k in o) { var t; try { t = typeof o[k]; } catch (e) { t = '?'; } r.push(k + ':' + t); } "
            "return r.length + ' Mitglieder: ' + r.join(' ');" % expr)


def browse_banks(b, start_id, limit=60):
    """NextBank druecken, bis sich die erste Dreiergruppe wiederholt. Liefert (liste, geladen_geaendert)."""
    first = bank_names(b)
    seen, banks = [first], 1
    log("  Bank 1: %s" % first)
    for i in range(limit):
        press(b, "%s/NextBank" % PC)
        time.sleep(0.4)
        names = bank_names(b)
        if names == first and i > 0:
            break
        banks += 1
        seen.append(names)
        log("  Bank %d: %s" % (banks, names))
        if names == first:
            break
    now = rig_state(b)["LoadedID"].get("string")
    rigs = [n for grp in seen for n in grp if n]
    return rigs, banks, now != start_id


def autotest(b):
    ver = step("1. PING", lambda: b.ping())
    log("  Antwort:", ver)
    if not b.v2:
        log("Bruecke 0.2 wird benoetigt.")
        return

    def props():
        st = rig_state(b)
        for k, v in st.items():
            log("  Rigs/%s: %s" % (k, short(v)))
        bm = b.get(BOARD)
        log("  BoardMode: %s | Eintraege: %s" % (short(bm), b.entries(BOARD)))
        res = b.get_many(["%s/%s" % (PC, n) for n in BANK_PROPS])
        for n in BANK_PROPS:
            log("  PresetCtrl/%s: %s" % (n, short(res["%s/%s" % (PC, n)])))
        return st, bm
    st, bm = step("2. Rig- und Bank-Eigenschaften", props) or (None, None)
    alive(b)
    if not st:
        return

    def banks():
        if st["Dirty"].get("state"):
            log("  Rig hat ungespeicherte Aenderungen, Test uebersprungen (bitte erst speichern).")
            return
        start_id, start_name = st["LoadedID"].get("string"), st["LoadedName"].get("string")
        if not ask("Baenke durchblaettern (NextBank bis zur ersten Wiederholung)? Bitte aufs Display schauen."):
            log("  uebersprungen")
            return
        rigs, n, changed = browse_banks(b, start_id)
        log("  %d Baenke, %d Rig-Namen: %s" % (n, len(rigs), rigs))
        log("  Geladenes Rig gewechselt: %s (jetzt %s)" % (changed, rig_state(b)["LoadedName"].get("string")))
        ask_text("Was hat sich am Display getan?")
        if len(set(rigs)) <= 3 and ask("Nur eine Bank gesehen. Im Rig-Modus (BoardMode) noch einmal probieren?"):
            old = bm.get("index", 0)
            names = b.entries(BOARD)
            target = next((i for i, s in enumerate(names) if s == "Rig"), None)
            if target is None:
                log("  Kein 'Rig'-Modus in der Liste.")
            else:
                log("  BoardMode -> Rig:", short(b.set(BOARD, "index", target)))
                time.sleep(1.0)
                rigs, n, changed = browse_banks(b, start_id)
                log("  %d Baenke, %d Rig-Namen: %s" % (n, len(rigs), rigs))
                log("  Geladenes Rig gewechselt: %s" % changed)
                ask_text("Was hat sich am Display getan?")
                log("  BoardMode zurueck:", short(b.set(BOARD, "index", old)))
        if rig_state(b)["LoadedID"].get("string") != start_id:
            log("  Bitte '%s' am MX5 wieder laden." % start_name)
    step("3. Rig-Liste ueber die Bank-Anzeige", banks)
    alive(b)

    def load_from_bank():
        st2 = rig_state(b)
        start_name, start_prog = st2["LoadedName"].get("string"), prog_of(st2)
        names = bank_names(b)
        log("  Aktuelle Bank: %s | geladen: %s" % (names, start_name))
        other = next((i for i, n in enumerate(names) if n and n != start_name), None)
        if other is None:
            log("  Kein anderes Rig in der Bank, uebersprungen.")
            return
        if not ask("LoadRig%d druecken (laedt '%s')?" % (other + 1, names[other])):
            log("  uebersprungen")
            return
        log("  LoadRig%d:" % (other + 1), press(b, "%s/LoadRig%d" % (PC, other + 1)))
        time.sleep(2.5)
        log("  geladen:", rig_state(b)["LoadedName"].get("string"))
        if start_prog is not None:
            b.set("%s/ReceivePresetIndex" % RIGS, "unnormalized", start_prog - 1)
            time.sleep(2.5)
            log("  zurueck per Programmnummer %d: geladen ist %s" % (start_prog, rig_state(b)["LoadedName"].get("string")))
        else:
            log("  Bitte '%s' am MX5 wieder laden." % start_name)
    step("4. Rig aus der Bank laden", load_from_bank)


def shell(b):
    log("verbunden:", b.ping())
    print("Befehle: ping | get <pfad> | set <pfad> <feld> <wert> | entries <pfad> | many <pfad>;<pfad>")
    print("         pc <nr> | fs <1-3> | press <pfad> | save | bank | ls <ordner> | members <js> | eval <js>")
    print("         sql <abfrage> (Bruecke 0.3, nur lesend) | write <anweisungen> (0.4, Transaktion)")
    print("         action status|backup|restore|restart (0.4) | sh <shell-zeile> | dir <ordner> (0.3) | quit")
    ch = midi_channel(b)
    while True:
        try:
            line = input("mx5> ").strip()
        except EOFError:
            break
        if not line:
            continue
        log("mx5>", line)
        cmd, _, rest = line.partition(" ")
        try:
            if cmd in ("quit", "exit"):
                break
            elif cmd == "ping":
                log(b.ping())
            elif cmd == "get":
                log(b.get(rest))
            elif cmd == "set":
                parts = rest.rsplit(" ", 2)
                log(b.set(*parts) if len(parts) == 3 else "set <pfad> <feld> <wert>")
            elif cmd == "entries":
                log(b.entries(rest))
            elif cmd == "many":
                for k, v in b.get_many([p.strip() for p in rest.split(";") if p.strip()]).items():
                    log(" ", k, v)
            elif cmd == "pc":
                send_pc(b, int(rest), ch)
                time.sleep(2.0)
                log(short(b.get("%s/LoadedName" % RIGS)))
            elif cmd == "fs":
                log(press(b, FS % int(rest)))
            elif cmd == "press":
                log(press(b, rest))
            elif cmd == "save":
                log(short(b.set(SAVE, "state", 1)))
            elif cmd == "bank":
                log(bank_names(b))
            elif cmd == "ls":
                log(b.eval(js_list("App.entryList('file://%s', ['*'], false)" % (rest or USB))))
            elif cmd == "members":
                log(b.eval(js_members(rest)))
            elif cmd == "eval":
                log(b.eval(rest))
            elif cmd == "sql":
                rows = b.sql(rest)
                log("%d Zeilen" % len(rows))
                for r in rows[:60]:
                    log(" ", json.dumps(r, ensure_ascii=False)[:300])
            elif cmd == "write":
                log("%d Zeilen geaendert" % b.sql_write(rest))
            elif cmd == "action":
                log(json.dumps(b.action(rest.strip()), ensure_ascii=False))
            elif cmd == "sh":
                rc, out = b.shell(rest)
                log("Exit %d" % rc, out.rstrip())
            elif cmd == "dir":
                for name, is_dir, mtime in b.list_dir(rest or "/media/az01-internal/Evil/usb_mnt/Impulse Responses"):
                    log(" ", name + ("/" if is_dir else ""))
            else:
                print("unbekannter Befehl")
        except BridgeError as e:
            log("FEHLER:", e)


if __name__ == "__main__":
    log("\n##### MX5 Bridge Test %s" % VERSION, time.strftime("%Y-%m-%d %H:%M:%S"), "#####")
    if "--ports" in sys.argv:
        log("Eingaenge:", mido.get_input_names())
        log("Ausgaenge:", mido.get_output_names())
        sys.exit()
    bridge = connect()
    try:
        shell(bridge) if "--shell" in sys.argv else autotest(bridge)
    except Abort:
        log("Abgebrochen.")
    finally:
        bridge.close()
    log("Fertig. Log: mx5bridge_testlog.txt")
