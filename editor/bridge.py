"""bridge.py - Client fuer die MX5 Bridge (SysEx ueber USB-MIDI).

Unterstuetzt Firmware-Bruecke 0.1 (einteilige Antworten), 0.2
(Antworten in Teilen: <cmd> <teil> <teile> <text>), 0.3 (SQL-Abfragen
der Rig-Datenbank, nur lesend) und 0.4 (schreibende SQL-Transaktionen und
Aktionen des Datenbankdienstes: status, backup, restore, restart) und 0.5
(Zeichen ausserhalb von ASCII in beiden Richtungen als Escape 0x7F + vier
Hex-Ziffern statt '?'; bridge.py kodiert/dekodiert das selbst, Aufrufer sehen
normalen Text) und 0.6 (langer Antwortkopf mit 14-Bit-Teilezaehler, angefordert
ueber das Bit 0x20 im Befehl - Antworten bis ca. 6 MB statt 48 KB; Befehl 0x0B
SHELL; der SQL-Lesekanal ist wirklich nur lesend).

Dateien auf dem Geraet (read_file, write_file, make_dir, list_dir, shell): ab
Bruecke 0.6 ueber den Befehl SHELL (Daten base64); 0.3 bis 0.5 ueber den
SQL-Lesekanal, dessen sqlite3-Shell readfile()/writefile()/fsdir() und den
Punktbefehl .system (eine Shell-Zeile als root) kennt.
"""
import base64, json, re, time

HDR = [0x7D, 0x48, 0x52]
_ESCAPED = re.compile("\x7f([0-9A-Fa-f]{4})")
KEYWORDS = ["mx5", "headrush", "gadget", "f_midi", "midi function"]
MAX_REPLY = 40000   # geschaetzte Antwortgroesse je Sammelabfrage (Grenze der Bruecke: 127 x 380 Zeichen)
PER_VALUE = 220     # Antwortzeichen je Wert zusaetzlich zum Pfad (gemessen ~130-160)


class BridgeError(Exception):
    pass


class NoReply(BridgeError):
    """Keine Antwort, und auch ein kurzer Ping danach blieb aus: das Geraet ist weg."""


class Bridge:
    def __init__(self, in_name, out_name):
        import mido
        self.mido = mido
        self.in_name, self.out_name = in_name, out_name
        self.inp = mido.open_input(in_name)
        self.out = mido.open_output(out_name)
        self.seq = 0
        self.v2 = None      # None = unbekannt, per ping() ermittelt
        self.v3 = False     # Datenbankdienst (SQL) vorhanden
        self.v4 = False     # Datenbankdienst schreibt (SQL-Transaktionen, Aktionen)
        self.unicode = False  # Bruecke 0.5: Nicht-ASCII-Zeichen kommen unbeschaedigt durch
        self.long = False     # Bruecke 0.6: langer Antwortkopf (14-Bit-Teilezaehler), Befehl SHELL
        self.version = ""
        self.vnum = (0, 0)  # Versionsnummer aus dem Ping, z. B. (0, 5)
        self._drain()

    @staticmethod
    def find_ports():
        import mido
        def pick(names):
            hits = [n for n in names if any(k in n.lower() for k in KEYWORDS)]
            if len(hits) != 1:
                raise BridgeError("MX5-MIDI-Port nicht eindeutig gefunden: %s" % names)
            return hits[0]
        return pick(mido.get_input_names()), pick(mido.get_output_names())

    @classmethod
    def auto(cls):
        return cls(*cls.find_ports())

    def close(self):
        for p in (self.inp, self.out):
            try:
                p.close()
            except Exception:
                pass

    def _drain(self):
        for _ in self.inp.iter_pending():
            pass

    # ---------- Transport ----------
    def _is_chunk(self, d):
        if self.v2 is False:
            return False
        return len(d) >= 7 and d[5] < d[6] <= 127 and (self.v2 or (d[5] == 0 and d[6] >= 1))

    def request(self, cmd, text="", timeout=3.0):
        if self.inp.closed or self.out.closed:   # send() auf geschlossenem rtmidi-Port stuerzt ab
            raise BridgeError("MIDI-Port geschlossen")
        self.seq = self.seq % 127 + 1
        long_hdr = self.long and cmd != 0x01   # der Ping antwortet immer kurz (Version noch unbekannt)
        data = HDR + [self.seq, cmd | (0x20 if long_hdr else 0)] + \
            [ord(c) & 0x7F for c in (escape(text) if self.unicode else text)]
        self.out.send(self.mido.Message("sysex", data=data))
        parts, total = {}, None
        deadline = time.time() + timeout
        while time.time() < deadline:
            for m in self.inp.iter_pending():
                if m.type != "sysex":
                    continue
                d = list(m.data)
                if d[:3] != HDR or len(d) < 5 or d[3] != self.seq:
                    continue
                code = d[4]
                if long_hdr and len(d) >= 9:   # <teil hi> <teil lo> <teile hi> <teile lo>
                    total = d[7] << 7 | d[8]
                    parts[d[5] << 7 | d[6]] = "".join(chr(b) for b in d[9:])
                    deadline = time.time() + timeout
                    if len(parts) < total:
                        continue
                    body = "".join(parts[i] for i in range(total))
                elif not long_hdr and self._is_chunk(d):
                    total = d[6]
                    parts[d[5]] = "".join(chr(b) for b in d[7:])
                    deadline = time.time() + timeout
                    if len(parts) < total:
                        continue
                    body = "".join(parts[i] for i in range(total))
                else:
                    body = "".join(chr(b) for b in d[5:])
                if self.unicode:
                    body = unescape(body)
                if code == 0x7F:
                    raise BridgeError(body)
                return code, body
            time.sleep(0.002)
        if parts:
            raise BridgeError("Antwort unvollstaendig (%d von %d Teilen)" % (len(parts), total))
        raise BridgeError("Keine Antwort vom Geraet")

    RETRY_PING = 1.0   # s: Ping vor dem Wiederholen einer ausgebliebenen Antwort

    def _retry(self, fn, *a):
        """Einmal wiederholen, wenn eine Antwort ausblieb oder unvollstaendig war. Blieb sie ganz
        aus, wird erst kurz gepingt: antwortet das Geraet auch darauf nicht, kommt sofort NoReply
        (Verlust nach ~4 s erkannt statt nach zwei vollen Zeitlimits)."""
        try:
            return fn(*a)
        except BridgeError as e:
            if "unvollstaendig" not in str(e) and "Keine Antwort" not in str(e):
                raise
            self._drain()
            if "Keine Antwort" in str(e):
                try:
                    self.request(0x01, timeout=self.RETRY_PING)
                except BridgeError:
                    raise NoReply("Keine Antwort vom Geraet (auch nicht auf einen Ping)")
                self._drain()
            return fn(*a)

    # ---------- Befehle ----------
    def ping(self):
        self.v2 = None
        code, body = self.request(0x01)   # Antwort 'MX5Bridge-0.5 f_midi' ist reines ASCII
        self.version = body
        m = re.match(r"MX5Bridge-(\d+)\.(\d+)", body)
        self.vnum = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        self.v2 = self.vnum >= (0, 2)
        self.v3 = self.vnum >= (0, 3)
        self.v4 = self.vnum >= (0, 4)
        self.unicode = self.vnum >= (0, 5)
        self.long = self.vnum >= (0, 6)
        return body

    def get(self, path):
        code, body = self._retry(self.request, 0x02, path)
        return json.loads(body.split("\t", 1)[1])

    def set(self, path, field, value):
        if isinstance(value, bool):
            value = int(value)
        code, body = self.request(0x03, "%s\t%s\t%s" % (path, field, value))
        return json.loads(body.split("\t", 1)[1])

    def entries(self, path):
        self._need_v2("Auswahllisten")
        code, body = self._retry(self.request, 0x04, path)
        return json.loads(body.split("\t", 1)[1])

    def get_many(self, paths):
        """Mehrere Werte lesen; bei Bruecke 0.1 einzeln. Aufgeteilt wird nach der geschaetzten
        Antwortgroesse; ist eine Antwort doch zu gross, wird die Gruppe halbiert."""
        if not self.v2:
            return {p: self.get(p) for p in paths}
        result, group, size = {}, [], 0
        for p in list(paths) + [None]:
            if p is None or (group and size + len(p) + PER_VALUE > MAX_REPLY):
                if group:
                    result.update(self._get_group(group))
                group, size = [], 0
            if p is not None:
                group.append(p)
                size += len(p) + PER_VALUE
        return result

    def _get_group(self, group):
        try:
            code, body = self._retry(self.request, 0x05, "\n".join(group))
        except BridgeError as e:
            if "zu gross" not in str(e) or len(group) < 2:
                raise
            half = len(group) // 2
            return dict(self._get_group(group[:half]), **self._get_group(group[half:]))
        return json.loads(body)

    def eval(self, js):
        self._need_v2("EVAL")
        return self.request(0x07, js)[1]

    def sql(self, query, timeout=20.0):
        """Nur-Lese-Abfrage der Rig-Datenbank (Bruecke 0.3). Liefert die Zeilen als
        Liste von dicts; Fehler der Datenbank kommen als BridgeError."""
        if not self.v3:
            raise BridgeError("SQL-Abfragen benoetigen die Firmware-Bruecke 0.3")
        return self._db(0x08, query, timeout)

    def sql_write(self, statements, timeout=30.0):
        """Schreibende SQL-Anweisungen (Bruecke 0.4). Der Dienst fuehrt sie als eine
        Transaktion aus (foreign_keys an); beim ersten Fehler wird nichts geschrieben
        und ein BridgeError geworfen. Vor dem ersten Schreiben seit dem Einschalten
        sichert der Dienst die Datenbank auf dem Geraet. Liefert die Zahl der
        geaenderten Zeilen."""
        if not self.v4:
            raise BridgeError("Schreiben in die Datenbank benoetigt die Firmware-Bruecke 0.4")
        rows = self._db(0x09, statements, timeout)
        return rows[0].get("changes", 0) if rows else 0

    def action(self, name, timeout=60.0):
        """Aktion des Datenbankdienstes (Bruecke 0.4): status, backup, restore, restart.
        restore/restart beenden die Geraete-App; sie startet nach ca. 15 s neu, die
        Bridge ist solange weg (neu verbinden)."""
        if not self.v4:
            raise BridgeError("Aktionen benoetigen die Firmware-Bruecke 0.4")
        rows = self._db(0x0A, name, timeout)
        return rows[0] if rows else {}

    def _db(self, cmd, text, timeout):
        code, body = self.request(cmd, text, timeout=timeout)
        r = json.loads(body)
        if not r.get("ok"):
            raise BridgeError("SQL: %s" % (r.get("err") or "unbekannter Fehler"))
        return r.get("rows") or []

    # ---------- Dateien auf dem Geraet (Bruecke 0.3, SQL-Lesekanal) ----------
    def _need_v3(self, what):
        if not self.v3:
            raise BridgeError("%s benoetigen die Firmware-Bruecke 0.3" % what)

    # ---------- Dateien und Shell ab Bruecke 0.6 (Befehl SHELL, Daten base64) ----------
    SQLITE = "/usr/Evil/Scripts/mx5bridge-sqlite3"
    FILE_PAGE = 192 * 1024      # Bytes je Lese-Anfrage (base64 ~256 KB Antwort, ~1,5 s)
    FILE_CHUNK = 48 * 1024      # Bytes je Schreib-Anfrage (base64 64 KB Anfrage)

    def _shell6(self, script, timeout=70.0):
        """Shell-Skript (auch mehrzeilig) per Befehl SHELL: (Exit-Code, Ausgabe inkl. stderr)."""
        rows = self._db(0x0B, script, timeout)
        r = rows[0] if rows else {}
        return int(r.get("rc", -1)), r.get("out") or ""

    def _check6(self, rc, out, what):
        if rc != 0:
            raise BridgeError("%s (Exit-Code %d): %s" % (what, rc, out.strip()[:300]))
        return out

    def _read_file6(self, path):
        q = sh_quote(path)
        size = int(self._check6(*self._shell6("wc -c < %s" % q), what="Datei nicht lesbar: %s" % path).strip())
        out = bytearray()
        for k in range((size + self.FILE_PAGE - 1) // self.FILE_PAGE):
            rc, b64 = self._shell6("dd if=%s bs=%d skip=%d count=1 2>/dev/null | base64 -w 0"
                                   % (q, self.FILE_PAGE, k))
            out += base64.b64decode(self._check6(rc, b64, "Lesen fehlgeschlagen: %s" % path).strip())
        if len(out) != size:
            raise BridgeError("Datei unvollstaendig gelesen (%d statt %d Bytes): %s" % (len(out), size, path))
        return bytes(out)

    def _write_file6(self, path, data):
        q = sh_quote(path)
        for off in range(0, max(len(data), 1), self.FILE_CHUNK):
            part = base64.b64encode(data[off:off + self.FILE_CHUNK]).decode("ascii")
            self._check6(*self._shell6("printf '%%s' '%s' | base64 -d %s %s" % (part, ">" if off == 0 else ">>", q)),
                         what="Schreiben fehlgeschlagen: %s" % path)
        n = int(self._check6(*self._shell6("wc -c < %s" % q), what="Datei nicht lesbar: %s" % path).strip())
        if n != len(data):
            raise BridgeError("Datei unvollstaendig geschrieben (%s statt %d Bytes): %s" % (n, len(data), path))
        return n

    def _list_dir6(self, path, recursive):
        # fsdir der sqlite3-Shell (als eigener Prozess, nicht im Lesekanal): Namen kommen dank der
        # Zeichen-Escapes (0.5) unveraendert, eine Antwort fasst alles (langer Kopf)
        cond = "" if recursive else " and name not glob %s" % sql_lit(path + "/*/*")
        sql = ("select name, (mode & 61440) = 16384 as d, mtime from fsdir(%s) where name <> %s%s order by name"
               % (sql_lit(path), sql_lit(path), cond))
        out = self._check6(*self._shell6("%s -json :memory: %s" % (self.SQLITE, sh_quote(sql))),
                           what="Ordner nicht lesbar: %s" % path)
        rows = json.loads(out) if out.strip() else []
        return [(r["name"][len(path) + 1:], bool(r.get("d")), r.get("mtime")) for r in rows]

    def read_file(self, path, page=20000):
        """Datei vom Geraet lesen (Bytes); seitenweise als Hex, weil eine Antwort
        hoechstens ca. 48 KB fasst (ab 0.6 ueber SHELL, base64)."""
        if self.long:
            return self._read_file6(path)
        self._need_v3("Dateizugriffe")
        rows = self.sql("select length(readfile(%s)) as n" % sql_lit(path))
        size = rows[0].get("n") if rows else None
        if size is None:
            raise BridgeError("Datei nicht lesbar: %s" % path)
        out = bytearray()
        for off in range(0, size, page):
            rows = self.sql("select hex(substr(readfile(%s), %d, %d)) as h" % (sql_lit(path), off + 1, page))
            out += bytes.fromhex(rows[0]["h"])
        return bytes(out)

    def write_file(self, path, data, chunk=30000):
        """Datei auf dem Geraet schreiben (ueberschreibt); in Stuecken, die an die Datei
        angehaengt werden. Liefert die geschriebene Laenge."""
        if self.long:
            return self._write_file6(path, data)
        self._need_v3("Dateizugriffe")
        lit = sql_lit(path)
        first = True
        for off in range(0, max(len(data), 1), chunk):
            part = data[off:off + chunk].hex()
            if first:
                q = "select writefile(%s, unhex('%s')) as n" % (lit, part)
            else:
                q = "select writefile(%s, readfile(%s) || unhex('%s')) as n" % (lit, lit, part)
            rows = self.sql(q, timeout=30.0)
            if not rows or rows[0].get("n") is None:
                raise BridgeError("Schreiben fehlgeschlagen: %s" % path)
            first = False
        rows = self.sql("select length(readfile(%s)) as n" % lit)
        n = rows[0].get("n") if rows else None
        if n != len(data):
            raise BridgeError("Datei unvollstaendig geschrieben (%s statt %d Bytes): %s" % (n, len(data), path))
        return n

    def make_dir(self, path):
        """Ordner anlegen (bestehender Ordner ist kein Fehler)."""
        if self.long:
            self._check6(*self._shell6("mkdir -p %s" % sh_quote(path)), what="Ordner nicht anlegbar: %s" % path)
            return
        self._need_v3("Dateizugriffe")
        self.sql("select writefile(%s, null, 16877) as n" % sql_lit(path))   # 040755

    def list_dir(self, path, recursive=False):
        """Eintraege eines Ordners: [(name, ist_ordner, mtime)], Namen relativ zu path
        (rekursiv mit Unterpfaden). Namen mit Nicht-ASCII-Zeichen kommen als Hex, weil
        der SysEx-Weg nur 7 Bit traegt (bis 0.4)."""
        if self.long:
            return self._list_dir6(path, recursive)
        self._need_v3("Dateizugriffe")
        lit = sql_lit(path)
        cond = "" if recursive else " and name not glob %s" % sql_lit(path + "/*/*")
        out, page, off = [], 300, 0
        while True:
            rows = self.sql("select case when name glob '*[^ -~]*' then hex(name) else name end as n, "
                            "name glob '*[^ -~]*' as h, (mode & 61440) = 16384 as d, mtime from fsdir(%s) "
                            "where name <> %s%s order by name limit %d offset %d"
                            % (lit, lit, cond, page, off))
            for r in rows:
                name = bytes.fromhex(r["n"]).decode("utf-8", "replace") if r.get("h") else r["n"]
                out.append((name[len(path) + 1:], bool(r.get("d")), r.get("mtime")))
            if len(rows) < page:
                return out
            off += page

    def shell(self, cmd, timeout=30.0):
        """Eine Shell-Zeile auf dem Geraet ausfuehren (als root). Liefert (Exit-Code, Ausgabe);
        cmd darf keinen Zeilenumbruch enthalten (ab 0.6 schon: Befehl SHELL). Nicht-ASCII-Zeichen
        in Pfaden ueber sh_quote()."""
        if self.long:
            return self._shell6(cmd, timeout=max(timeout, 70.0))
        self._need_v3("Shell-Befehle")
        if "\n" in cmd or "\r" in cmd:
            raise BridgeError("Shell-Befehl darf nur eine Zeile sein")
        out, rc = "/tmp/mx5bridge/sh.out", "/tmp/mx5bridge/sh.rc"
        rows = self.sql(".system { %s ; } > %s 2>&1; echo $? > %s\n"
                        "select cast(readfile('%s') as text) as out, cast(readfile('%s') as text) as rc"
                        % (cmd, out, rc, out, rc), timeout=timeout)
        r = rows[0] if rows else {}
        try:
            code = int((r.get("rc") or "").strip() or -1)
        except ValueError:
            code = -1
        return code, r.get("out") or ""

    def _need_v2(self, what):
        if self.v2 is False:
            raise BridgeError("%s benoetigen die Firmware-Bruecke 0.2" % what)


def escape(text):
    """Text fuer die Leitung (Bruecke 0.5): alles ausser Tab, LF und 0x20..0x7E als 0x7F + 4 Hex-Ziffern
    je UTF-16-Einheit (Zeichen ausserhalb der BMP also als Surrogatpaar)."""
    if all(c in "\t\n" or " " <= c <= "~" for c in text):
        return text
    out = []
    for c in text:
        if c in "\t\n" or " " <= c <= "~":
            out.append(c)
        else:
            units = c.encode("utf-16-be")
            out += ["\x7f%04X" % int.from_bytes(units[i:i + 2], "big") for i in range(0, len(units), 2)]
    return "".join(out)


def unescape(text):
    """Gegenstueck zu escape: Escapes aufloesen, Surrogatpaare zusammenfuegen."""
    if "\x7f" not in text:
        return text
    s = _ESCAPED.sub(lambda m: chr(int(m.group(1), 16)), text)
    return s.encode("utf-16", "surrogatepass").decode("utf-16", "surrogatepass")


def sql_lit(s):
    """SQL-Stringliteral; Nicht-ASCII-Text als Hex (cast(x'..' as text)), weil SysEx nur
    7 Bit traegt (bis Bruecke 0.4; ab 0.5 ginge auch der Klartext)."""
    s = str(s)
    if all(" " <= c <= "~" for c in s):
        return "'" + s.replace("'", "''") + "'"
    return "cast(x'%s' as text)" % s.encode("utf-8").hex()


def sh_quote(s):
    """Shell-Argument fuer Bridge.shell(): einfach gequotet, Nicht-ASCII ueber printf-Oktalfolgen."""
    if all(" " <= c <= "~" for c in s):
        return "'" + s.replace("'", "'\\''") + "'"
    return '"$(printf \'%s\')"' % "".join(chr(c) if 32 <= c <= 126 and chr(c) not in "'\\%" else "\\%03o" % c
                                          for c in s.encode("utf-8"))
