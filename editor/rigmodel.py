"""rigmodel.py - Laden, Bearbeiten und Speichern von HeadRush-MX5-.rig-Dateien.

Das Format ist ein JSON-Objekt, dessen Feld "content" einen weiteren JSON-Text
mit dem serialisierten Eigenschaftsbaum enthaelt. Beide Ebenen schreibt das
Geraet kompakt und mit sortierten Schluesseln; genau so wird hier gespeichert
(fuer unveraenderte Dateien byte-identisch).
"""
import json, os, shutil, time, uuid


def base_name(module):
    """Basisname eines Blocks: 'Amp 2' -> 'Amp' (nur die Zweitinstanz mit einstelliger Endung,
    'B Dist 7000' bleibt). Katalog, Presets, Modellbilder und Kategorien benutzen ihn."""
    parts = module.rsplit(" ", 1)
    return parts[0] if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 1 else module

SLOTS = 11
EMPTY = "Empty Slot"
# Knoten-Typen im Eigenschaftsbaum
T_NUMBER, T_BOOL, T_BOOL3, T_ENUM, T_TEXT = 0, 1, 3, 4, 8
HIDDEN_PARAMS = {"PresetName", "PresetName2"}
SPECIAL_MODULES = ["Rig", "Input", "Output"]  # immer vorhanden, nicht Teil der Kette


def _dump(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class RigError(Exception):
    pass


class Rig:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self._raw = f.read()
        try:
            self.outer = json.loads(self._raw)
            self.content = json.loads(self.outer["content"])
            self.patch = self.content["data"]["Patch"]["children"]
        except (ValueError, KeyError, TypeError) as e:
            raise RigError("Not a valid rig file: %s (%s)" % (os.path.basename(path), e))
        self.dirty = False

    # ---------- Lesen ----------
    @property
    def name(self):
        return self.node("Rig", "PresetName").get("string", "")

    def chain(self):
        """Liste der Kettenplaetze [(platz, modulname oder None)]."""
        ch = self.patch.get("Chain", {}).get("children", {})
        out = []
        for i in range(1, SLOTS + 1):
            t = ch.get("ModuleType%d" % i, {}).get("string", EMPTY)
            out.append((i, None if t == EMPTY else t))
        return out

    @property
    def routing(self):
        return self.patch.get("Chain", {}).get("children", {}).get("Routing", {}).get("string", "?")

    def modules(self):
        return [m for _, m in self.chain() if m] + [m for m in SPECIAL_MODULES if m in self.patch]

    def has_module(self, module):
        return module in self.patch

    def params(self, module):
        """Parameternamen in Geraete-Reihenfolge (ohne interne Namensfelder)."""
        node = self.patch.get(module)
        if node is None:
            raise RigError("Module not in the rig: %s" % module)
        children = node.get("children", {})
        order = [k for k in node.get("childorder", []) if k in children]
        order += sorted(k for k in children if k not in order)
        return [k for k in order if k not in HIDDEN_PARAMS]

    def node(self, module, param):
        try:
            return self.patch[module]["children"][param]
        except KeyError:
            raise RigError("Parameter not found: %s/%s" % (module, param))

    def value(self, module, param):
        n = self.node(module, param)
        t = n.get("type")
        if t == T_NUMBER:
            return n.get("value")
        if t in (T_BOOL, T_BOOL3):
            return n.get("state")
        return n.get("string")

    def is_on(self, module):
        try:
            return bool(self.node(module, "On").get("state"))
        except RigError:
            return None

    def colour(self, module):
        try:
            return self.node(module, "Colour").get("string")
        except RigError:
            return None

    # ---------- Schreiben ----------
    def set_value(self, module, param, value):
        n = self.node(module, param)
        t = n.get("type")
        if t == T_NUMBER:
            if isinstance(value, str):
                value = float(value.replace(",", "."))
            if isinstance(value, float) and value.is_integer() and isinstance(n.get("value"), int):
                value = int(value)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise RigError("Number expected for %s/%s" % (module, param))
            changed = n.get("value") != value
            n["value"] = value
        elif t in (T_BOOL, T_BOOL3):
            value = bool(value)
            changed = n.get("state") != value
            n["state"] = value
        elif t in (T_ENUM, T_TEXT):
            value = str(value)
            changed = n.get("string") != value
            n["string"] = value
        else:
            raise RigError("Unknown parameter type %r at %s/%s" % (t, module, param))
        self.dirty |= changed
        return changed

    def set_routing(self, name):
        """Signalweg: 'S', 'SPS-1' oder 'PS-1'."""
        node = self.patch.setdefault("Chain", {}).setdefault("children", {}).setdefault("Routing", {"type": T_ENUM})
        self.dirty |= node.get("string") != name
        node["string"] = name

    def set_chain(self, names):
        """Reihenfolge der Kette setzen: Liste mit Modulname oder None je Platz (die Module
        selbst bleiben unter ihrem Namen erhalten, nur ModuleType1..11 aendern sich)."""
        ch = self.patch.setdefault("Chain", {}).setdefault("children", {})
        for i, name in enumerate(names, start=1):
            node = ch.setdefault("ModuleType%d" % i, {"type": T_ENUM})
            new = name or EMPTY
            self.dirty |= node.get("string") != new
            node["string"] = new

    def rename(self, new_name):
        new_name = new_name.strip()
        if not new_name:
            raise RigError("The name must not be empty")
        if any(c in new_name for c in '\\/:*?"<>|'):
            raise RigError("The name contains invalid characters")
        self.set_value("Rig", "PresetName", new_name)

    def serialize(self):
        outer = dict(self.outer)
        outer["content"] = _dump(self.content)
        return _dump(outer).encode("utf-8")

    def save(self, backup_dir=None):
        data = self.serialize()
        # Sicherheitscheck: Ergebnis muss wieder ladbar sein
        json.loads(json.loads(data)["content"])
        if backup_dir and os.path.exists(self.path):
            os.makedirs(backup_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(self.path, os.path.join(backup_dir, "%s_%s" % (stamp, os.path.basename(self.path))))
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, self.path)
        self._raw = data
        self.dirty = False

    def save_as(self, folder, new_name, backup_dir=None):
        target = os.path.join(folder, new_name.strip() + ".rig")
        if os.path.exists(target):
            raise RigError("File already exists: %s" % os.path.basename(target))
        self.rename(new_name)
        self.outer = dict(self.outer)
        self.outer["id"] = str(uuid.uuid4())
        self.outer["created_at"] = int(time.time())
        self.outer["prog_num"] = -1
        self.outer["readonly"] = False
        self.path = target
        self.save(backup_dir)
        return target

    def revert(self):
        self.__init__(self.path)


class Catalog:
    """Bekannte Wertebereiche und Auswahllisten, gesammelt aus Rigs/Block-Presets."""

    def __init__(self, path):
        self.modules = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.modules = json.load(f).get("modules", {})

    @staticmethod
    def base(module):
        return base_name(module)   # "Amp 2" nutzt denselben Katalogeintrag wie "Amp"

    def param(self, module, param):
        m = self.modules.get(module) or self.modules.get(self.base(module)) or {}
        return m.get("params", {}).get(param, {})

    def choices(self, module, param):
        return [v for v in self.param(module, param).get("values", []) if isinstance(v, str)]

    def range(self, module, param):
        p = self.param(module, param)
        return p.get("min"), p.get("max")
