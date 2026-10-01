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

### Optional: with the NAM mod

The [HeadRush NAM mod](https://github.com/lolgab/headrush-nam-mod) and the bridge can be used
together:

1. Use the NAM mod's installer (`headrush-nam-gui`, from its releases page) and choose **MX5**.
   It creates a patched HeadRush updater (`.exe`). **Do not run it.**
2. Drag that `.exe` onto `MX5Bridge_0.7_Patcher.exe`. The patcher detects the NAM mod, keeps it, and
   writes `MX5Bridge_0.7_NAM_Updater`.
3. Install that updater as described above (steps 3–5).

With NAM installed, the editor can turn NAM on and off (*⋯ › Turn NAM off/on*; this restarts the
device app) and manage the NAM models (*NAM* button in the left bar). If the device app crashes
three times in a row right after starting with NAM, the bridge switches NAM off by itself.

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
