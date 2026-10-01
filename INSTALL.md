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

1. Put **`MX5Bridge_0.7_Patcher.exe`** into an empty folder, for example `Desktop\MX5Bridge`.
2. Double-click it. A console window opens, and the patcher:
   - downloads the official *HeadRush MX5 2.7 Firmware Updater* (about 60 MB) from
     `cdn.inmusicbrands.com`;
   - adds the bridge to the firmware and checks every file it wrote;
   - creates the folder **`MX5Bridge_0.7_Updater`** next to the patcher.

   This takes one to two minutes. Press Enter to close the window afterwards. If you already
   have the official updater (the `.zip` or the `.exe`), drag it onto the patcher and nothing is
   downloaded.
3. Connect the MX5 to its **power supply** and to the computer with **USB**.
4. On the MX5: **Global Settings › ⋯ (more) › Firmware Update**.
5. In `MX5Bridge_0.7_Updater`, run **`FirmwareUpdater.exe`**. Its window title must say
   *"MX5Bridge 0.7"*. Click **"Install MX5Bridge 0.7"** and wait. **Do not disconnect** the MX5
   until the update is finished and the device has restarted.

Your rigs, setlists, presets and IRs stay on the device. The update only replaces the system
part, just like an official update.

### Optional: with the NAM mod (Neural Amp Modeler)

The [HeadRush NAM mod by lolgab](https://github.com/lolgab/headrush-nam-mod) turns the
*Anxiety OD* block into a [Neural Amp Modeler](https://www.neuralampmodeler.com) block that plays
`.nam` captures of real amps and pedals. The bridge and the NAM mod can be installed together.
The NAM mod is a separate project and is not included here. Its installer builds its part, and
the bridge patcher adds the bridge on top.

Instead of steps 1–2 above:

1. Download the NAM mod's installer for Windows (`headrush-nam-gui`, a `.zip`) from its
   [releases page](https://github.com/lolgab/headrush-nam-mod/releases). Unzip it and keep the
   `.exe` together with its `.dll` files.
2. Start it, select **MX5** and the number of NAM instances:
   - **2 instances**: *Anxiety OD* and *Anxiety OD 2* become NAM blocks.
   - **up to 4 instances**: *Anxiety OD V2* and *Anxiety OD V2 2* as well. This uses more of the
     device's processing power.

   Click **Install NAM Mod**. It downloads the official updater and writes two files into its
   folder: **`HeadRush MX5 Firmware Updater (NAM mod).exe`** and
   `HeadRush MX5 Firmware Updater (stock).exe`.
3. **Do not run the "(NAM mod)" updater.** Drag it onto **`MX5Bridge_0.7_Patcher.exe`** instead.
   The patcher shows *"NAM mod found"* and creates the folder
   **`MX5Bridge_0.7_NAM_Updater`**.
4. Continue with steps 3–5 above, using `FirmwareUpdater.exe` from `MX5Bridge_0.7_NAM_Updater`.
   The button is called **"Install MX5Bridge 0.7 + NAM"**.

Keep the "(stock)" updater. It is the unmodified official updater for getting back to the stock
firmware (section 4).

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

Already have NAM installed and want to add the bridge? Do the same: the NAM mod's installer
creates a new "(NAM mod)" updater each time. Drag that onto the bridge patcher and install the
result.

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
  (or run `python patcher.py [updater]`). No extra packages are needed. It also runs on
  Linux/macOS when `7z` or `bsdtar` is installed. To build the `.exe` yourself from the
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
| Patcher: *"Could not unpack the updater"* | Windows 10 (1803+) / 11 has `tar.exe` built in. On older systems install [7-Zip](https://www.7-zip.org) and make sure `7z` is on the PATH |
| Patcher: download fails | Download the official updater yourself from HeadRush (MX5, firmware 2.7, Windows) and drag the `.zip` onto the patcher |
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
