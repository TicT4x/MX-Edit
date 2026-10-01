# Installation

You need about 15 minutes, a HeadRush **MX5 on firmware 2.7**, its power supply, a USB cable and
a Windows 10/11 computer.

> ⚠️ **Unofficial firmware, at your own risk.** The patcher only adds files to the official
> firmware, and the steps below have been tested many times. Still, a firmware update can always
> fail. Section 4 explains how to get back to the stock firmware. **Back up your rigs first** (step 1).

## 1. Back up your rigs

Do this with the stock tools before you start. On the MX5, enable *USB transfer mode* (Global
Settings) and copy the `Rigs`, `Setlists`, `Blocks` and `Impulse Responses` folders from the
drive to your computer. (After the bridge is installed, the editor can do this for you:
*⋯ › Back up everything*.)

## 2. Build and install the bridge firmware

You only need two files from the [latest release](../../releases/latest):
**`MX5Bridge_0.7_Patcher.exe`** (firmware) and **`MX5Editor_0.9.exe`** (editor). Nothing has to
be installed, and Python is not needed. Both programs are not code-signed, so Windows SmartScreen
may warn about an unknown publisher. Click *More info › Run anyway*.

1. Put **`MX5Bridge_0.7_Patcher.exe`** into an empty folder, for example `Desktop\MX5Bridge`, and
   double-click it. The patcher window opens.
2. Choose the options, then click **Build updater**:
   - **Use a firmware file I already have:** leave it unticked and the patcher downloads the
     official *HeadRush MX5 2.7 Firmware Updater* (about 60 MB) from `cdn.inmusicbrands.com`.
     Tick it to use a copy you already have: click **Choose …** and select the HeadRush updater
     (the `.exe`, or the `.zip` from HeadRush). Dragging that file onto the patcher's `.exe`
     preselects it.
   - **Also install the NAM mod:** see the next section. Leave it unticked for the bridge only.
   - **Output:** the folder in which the new updater is created (default: next to the patcher).

   The patcher adds the bridge, checks every file it wrote and creates
   **`MX5Bridge_0.7_Updater`**. This takes one to two minutes.
3. Connect the MX5 to its **power supply** and to the computer with **USB**.
4. On the MX5: **Global Settings › ⋯ (more) › Firmware Update**.
5. Click **Start firmware updater** in the patcher (or run `FirmwareUpdater.exe` in
   `MX5Bridge_0.7_Updater`). Its window title must say *"MX5Bridge 0.7"*. Click
   **"Install MX5Bridge 0.7"** and wait. **Do not disconnect** the MX5
   until the update is finished and the device has restarted.

Your rigs, setlists, presets and IRs stay on the device. The update only replaces the system
part, just like an official update.

### Optional: with the NAM mod (Neural Amp Modeler)

The [HeadRush NAM mod by lolgab](https://github.com/lolgab/headrush-nam-mod) turns the
*Anxiety OD* block into a [Neural Amp Modeler](https://www.neuralampmodeler.com) block that plays
`.nam` captures of real amps and pedals. The bridge and the NAM mod can be installed together.
The NAM mod is a separate project and is not included here. Its installer builds its part, and
the bridge patcher adds the bridge on top.

To install it, tick **Also install the NAM mod** in the patcher and click **Build updater**:

1. The patcher downloads the NAM mod's official installer (`headrush-nam-gui`, the newest
   release from its GitHub page) and opens it in a second window.
2. In that window, select **MX5** and the number of NAM instances:
   - **2 instances**: *Anxiety OD* and *Anxiety OD 2* become NAM blocks.
   - **up to 4 instances**: *Anxiety OD V2* and *Anxiety OD V2 2* as well. This uses more of the
     device's processing power.

   Then click **Install NAM Mod** and wait. The NAM installer downloads the official firmware
   itself and builds its part.
3. The patcher notices when the NAM installer is done and continues by itself. You can close the
   NAM installer's window. The patcher creates **`MX5Bridge_0.7_NAM_Updater`**.
4. Continue with steps 3–5 above. The button in the firmware updater is called
   **"Install MX5Bridge 0.7 + NAM"**.

If you already have an updater made by the NAM installer
(`HeadRush MX5 Firmware Updater (NAM mod).exe`), tick both boxes and choose that file instead.
The patcher then does not open the NAM installer. **Never run the "(NAM mod)" updater itself**
if you want the bridge too: it would install NAM without the bridge.

The patcher also keeps `HeadRush MX5 Firmware Updater (stock).exe` next to the new updater. It is
the unmodified official updater, for getting back to the stock firmware (section 4).

**Using NAM with the editor:**

- **Models:** click **NAM** in the editor's left bar to upload `.nam` files, and to rename,
  reorder or delete them. They are stored in the `NAM` folder of the MX5's drive. The device app
  restarts when you close the dialog (about 15 s), because the NAM mod reads its models only at
  start-up.
- **Choosing a model:** in a rig, NAM blocks appear as amps called *NAM* (*NAM 2*, *NAM V2*, …).
  The model picker lists them under *Amp*. In a NAM block, *Model* selects the capture. On the
  device this is the Drive knob: Drive = position in the model list, so up to 101 models.
  *Input* and *Output* are the Tone and Level knobs. When you reorder or delete models, the
  editor updates every rig and NAM preset that uses them.
- **On/off:** *⋯ › Turn NAM off/on* switches NAM without reflashing (the device app restarts).
  With NAM off, the Anxiety OD sounds like the stock pedal again.
- **Safety:** if the device app crashes three times in a row right after starting with NAM, the
  bridge switches NAM off by itself, and the editor tells you. Problems with the NAM mod itself
  belong in [its issue tracker](https://github.com/lolgab/headrush-nam-mod/issues).

Already have NAM installed and want to add the bridge? Do the same: tick **Also install the NAM
mod**, and install the result.

## 3. Start the editor

1. Put **`MX5Editor_0.9.exe`** anywhere, for example on the desktop, and double-click it.
2. If SmartScreen warns, click *More info › Run anyway* (see above).
3. Switch the MX5 on and connect it via USB. About 10 seconds after the device has started, the
   MIDI port **"HeadRush MX5"** appears. The editor connects by itself and reads the current rig.

Tips:

- The editor and the device share the MIDI port. Close other programs that might use
  "HeadRush MX5" (DAWs, MIDI tools).
- While the MX5 is in *USB transfer mode*, the MIDI port is not available. The editor waits and
  reconnects when you leave transfer mode.
- *Settings* (gear icon, bottom left) has the UI size, MIDI port choice, auto-connect and the
  footswitch bar.
- Without a device, use *Folder* in the left bar to open a folder of `.rig` files (for example a
  backup) and edit them offline.

### Run from source (optional)

Both programs are also available as Python source, if you prefer that or the `.exe` files do not
run on your system. Install [Python 3](https://www.python.org/downloads/) (3.9 or newer, tick
*Add python.exe to PATH*).

- Patcher: download `MX5Bridge_0.7_Patcher.zip`, unzip it and double-click `Patch_Firmware.bat`
  (the same window). `python patcher.py [updater]` is a console version without the NAM
  installer step. No extra packages are needed, and it also runs on
  Linux/macOS (Python 3 only). To build the `.exe` yourself from the
  repository: `pip install pyinstaller pillow`, then `python firmware\tools\patcher_exe.py`.
- Editor: see below.

#### Editor from source

Download `MX5Editor_0.9.zip`, unzip it and install the packages once:

```bat
pip install mido python-rtmidi pillow
```

Then double-click `MX5Editor_starten.bat` in the unzipped folder. To build the `.exe` yourself,
run `pip install pyinstaller` and `python werkzeuge\exe_bauen.py`.

### Check the bridge without the editor (optional)

This uses the source zip and the packages from the previous section.

```bat
cd MX5Editor_0.9\werkzeuge
python mx5bridge_test.py --shell
```

At the prompt, `ping` must answer `MX5Bridge-0.7`, and `action status` shows the database size,
the free space and the backup age. `quit` exits.

## 4. Going back to the stock firmware

- **Normal way:** put the MX5 into firmware update mode (*Global Settings › ⋯ › Firmware
  Update*) and run the **official** HeadRush MX5 2.7 updater.
- **If the device no longer starts:** hold **footswitches 1 and 2** while switching it on. This
  is the recovery update mode. Then run the official updater.
- ⚠️ Footswitches **2 and 3** at power-on is a **factory reset**. It erases your own rigs.
  Only use it as a last resort, and restore your backup afterwards.

If the rig database itself is damaged, the bridge's crash guard restores its last automatic
backup after three failed app starts. You can also trigger a restore by hand in the test shell
with `action restore`.

## Troubleshooting

| Problem | What to try |
|---|---|
| Patcher: *"Could not unpack the updater"* | Use patcher v0.9.2 or newer — it unpacks the updater itself (older versions relied on Windows' `tar.exe`, which cannot unpack it on Windows 10). If it still fails, the downloaded file is probably incomplete: delete it next to the patcher and try again |
| Patcher: download fails | Download the official updater yourself from HeadRush (MX5, firmware 2.7, Windows), tick *Use a firmware file I already have* and choose it |
| Patcher: *"The NAM mod installer was closed before it built the MX5 updater"* | Click *Build updater* again. In the NAM installer, choose **MX5** and click *Install NAM Mod*, then wait until it is done |
| Patcher: *"… has unexpected layout"* / *"already patched"* | The input is not the plain official 2.7 updater (or an updater from the NAM mod). Use the official one |
| Editor: *"No MX5 found"* | Wait ~15 s after the device has started. Check the cable. In *Settings*, set both MIDI ports to *Automatic* |
| Editor asks for a newer bridge | The device runs an older bridge or the stock firmware. Install the firmware from step 2 |
| Device shows *"restore last state?"* after an editor action | Some actions restart the device app (creating setlists, uploading IRs, NAM on/off). The editor answers this itself; if it asks you, press **No** |

## Building the firmware on Linux (developers)

`firmware/build.py` is the original build path. It applies the same changes (`bridgepatch.py`)
with `debugfs`, checks the result with `e2fsck` and compresses with `xz`:

```bash
sudo apt install -y e2fsprogs xz-utils gcc-arm-linux-gnueabihf python3
cd firmware
sh tools/build-sqlite3.sh                      # optional: rebuild bin/sqlite3 (static ARM)
python3 build.py <official Update.img> <output Update.img>
```

The official `Update.img` is inside the HeadRush updater, which is a 7-Zip archive
(`7z x "HeadRush MX5 2.7 Firmware Updater - Win.exe"`). `tools/nam-mod.sh` builds the NAM mod
from source and applies it before `build.py` (see the comments in the script).
`tools/daemontest.sh` tests the device-side database service locally with BusyBox.
