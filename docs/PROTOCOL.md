# MX5 Bridge protocol (bridge 0.7)

The bridge adds a USB-MIDI function to the MX5's USB gadget. It shows up on the computer as a
MIDI port named like **"HeadRush MX5"**. All communication is SysEx. A reference client is
[`editor/bridge.py`](../editor/bridge.py) (Python, `mido` + `python-rtmidi`):

```python
from bridge import Bridge
br = Bridge.auto()                       # finds the port by name
print(br.ping())                         # 'MX5Bridge-0.7 f_midi'
print(br.get("/Engine/PresetCtrl/Rigs/LoadedName"))
br.set("/Engine/Patch/Amp/Bass", "unnormalized", 6.5)
print(br.sql("select name, prog_num from rigs order by rowid limit 5"))
```

## Framing

Request:

```
F0 7D 48 52 <seq> <cmd> <payload as 7-bit ASCII> F7
```

- `7D` is the non-commercial manufacturer ID, and `48 52` = "HR".
- `<seq>` is 1–127 and is echoed in every reply part.
- Setting bit `0x20` in `<cmd>` requests the **long reply header** (bridge ≥ 0.6, recommended
  for everything except `ping`).

Reply (one or more SysEx messages, at most 380 payload characters each):

```
F0 7D 48 52 <seq> <code> <part> <total> <text> F7                    short header (≤ 127 parts)
F0 7D 48 52 <seq> <code> <part hi> <part lo> <total hi> <total lo> <text> F7   long header (14 bit)
```

Join the parts in order. `<code>` `0x7F` means error, and the text is then the message.

**Characters outside ASCII** (bridge ≥ 0.5): SysEx carries only 7 bits, so every character
other than TAB, LF and 0x20–0x7E travels as byte `0x7F` followed by four uppercase hex digits
(one UTF-16 code unit; characters outside the BMP become surrogate pairs). This applies in
both directions. An escape may be split across two reply parts, so unescape after joining.

## Commands

| cmd | name | payload | reply |
|---|---|---|---|
| `0x01` | PING | – | `MX5Bridge-<version> <gadget name>` |
| `0x02` | GET | property path | `path<TAB>{json info}` |
| `0x03` | SET | `path<TAB>field<TAB>value` | `path<TAB>{json info}` after the write |
| `0x04` | ENTRIES | property path | `path<TAB>[list of enum entries]` |
| `0x05` | GET_MANY | paths separated by LF | one JSON object `{path: info}` |
| `0x07` | EVAL | JavaScript function body | its return value as text |
| `0x08` | SQL | read-only SQL (one result set) | `{"ok", "rows", "err"}` |
| `0x09` | SQLWRITE | SQL statements | `{"ok", "rows": [{"changes": n}], "err"}` |
| `0x0A` | ACTION | `status`, `backup`, `restore`, `restart`, `diag`, `nam-on`, `nam-off` | `{"ok", "rows", "err"}` |
| `0x0B` | SHELL | shell script (runs as root) | `{"ok", "rows": [{"rc", "out"}], "err"}` |

- **Property info** (GET/SET) holds the fields `value` (normalised 0..1), `unnormalized` (real
  value), `state`, `index` (enum), `string`, plus metadata such as `maximum` and `numEntries`.
  Write with the field that fits the property: `value | unnormalized | state | index | string |
  user`.
- **EVAL** runs inside the device's QML MIDI-assignment engine with the objects `App`, `Midi` and
  `device`. `App.getProperty(path).translator` gives access to everything the stock GUI uses.
- **SQLWRITE** runs as one transaction (`pragma foreign_keys=on`), and the first error rolls
  everything back. Before the first write after each boot, the service backs up the database to
  `/media/az01-internal/Evil/mx5bridge/evil.db.mx5bak`.
- **ACTION** `restart`/`restore`/`nam-*` restart the device app (about 10–15 s). The MIDI port
  stays. Afterwards the device asks *"restore last state?"* (footswitch 2 = No).

The SQL and SHELL commands are only reachable from a computer connected by USB. The bridge does
**no** filtering of its own: anything connected to the MIDI port can run commands as root on
the device.

## Rig database

`/media/az01-internal/Evil/evil.db` (SQLite):

- `rigs(id, name, content, show_order, author, is_readonly, color, created_at, prog_num)`.
  `content` is the inner JSON of a `.rig` file. *All Rigs* order = `rowid`. `prog_num` = shown
  number − 1.
- `setlists(id, name, …)`, `setlist_rigs(setlist_id, rig_id, show_order)` (FK cascades).
- `blocks(id, type, name, content, is_readonly)` = block presets.
- `settings(name, value)`.

The device app reads lists, names, colours and program numbers from the database only when a
list is (re-)entered. After a write, re-enter the active list (`RedirCtrl/AccessSet1` or
`AccessRigView`). Creating, renaming or deleting a setlist needs an app restart.

## Useful property paths

| Path | Meaning |
|---|---|
| `/Engine/Patch/Chain/ModuleType1..11` | signal chain. Write field `user` = block name. A block already in the chain is *moved* |
| `/Engine/Patch/Chain/Routing` | `S`, `SPS-1`, `PS-1` |
| `/Engine/Patch/<Block>/<Param>` | block parameters (`On`, `Colour`, `PresetName`, …) |
| `/Engine/PresetCtrl/Rigs/LoadedName`, `LoadedID`, `Dirty` | loaded rig. `Dirty` state 0 before switching = discard without the dialog |
| `/Engine/PresetCtrl/Rigs/ReceivePresetIndex` | load by program number (unnormalized = number − 1) |
| `/Engine/PresetCtrl/NextPreset` | counter. Writing old+n jumps n places in the active list |
| `/Engine/RedirCtrl/EditModeSaveRig` | state 1 opens the save dialog |
| `/Engine/RedirCtrl/RawFootswitches/FS1..3` | press a footswitch (state 1, then 0, ≥ 30 ms each) |
| `/Engine/RedirCtrl/BoardMode` | view: `Edit, Stomp, Rig, Hybrid, Set, SetRig, Looper, Mode, Tuner, FreeText` |
| `/Engine/RedirCtrl/ButtonText1..3` | button labels of an open dialog |
| `/Engine/FootSwitch/…5/6/7` | footswitches 1–3 (`ModeNew`, `ModuleList`, `OperationList`, scene presets `Scene<n>Slot<k>Preset`) |
| `/Engine/Pedal1/…`, `/Engine/Pedal2/…` | expression pedal assignments |
| `/Engine/FFTCtrl/TunerString`, `TunerCents` | tuner (open with `RedirCtrl/AccessTuner`) |
| `/Engine/InputMeter/Current`, `/Engine/OutputMeterL/Current` | level meters (dB) |

Things to avoid: never trigger `PresetCtrl/LoadBlockPreset` (it crashes the app unless the
preset list is open on the display). Never set a scene mode on an empty chain slot. Never call
`App.entryList(..., recursive=true)` (it walks `/` and hangs the device).
