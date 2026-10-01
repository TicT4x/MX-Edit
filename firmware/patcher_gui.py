#!/usr/bin/env python3
"""MX5 Bridge firmware patcher - window version (tkinter, look of the MX5 Editor).

Aufruf:  python patcher_gui.py [Datei]     (Datei = vorausgewaehlte eigene Firmware, z. B. per
                                           Drag & Drop auf die EXE)
Optionen: eigene Firmware-Datei statt Download (offizieller Updater .exe/.zip oder ein Updater
des NAM-Installers) und NAM-Mod gefuehrt mitinstallieren (naminstaller.py). Die Arbeit laeuft in
einem Thread (patcher.build); Ausgaben kommen ueber patcher.LOG/PROGRESS und eine Queue in die
Oberflaeche. Die Konsolenversion bleibt patcher.py."""
import os, queue, subprocess, sys, threading, time, webbrowser
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import patcher, naminstaller, bridgepatch, ext4

BG, PANEL, CARD, LINE = "#0b0b0e", "#141519", "#1c1d23", "#2a2b33"
TEXT, MUTED, DIM = "#e8e8ea", "#9a9ba3", "#5f6069"
ACCENT, ACCENT_HI, ACCENT_TXT, DANGER = "#1fc9a1", "#43dcb8", "#07110e", "#e5484d"
NAM_URL = "https://github.com/lolgab/headrush-nam-mod"
VERSION = bridgepatch.VERSION


def dpi_aware():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class Check(tk.Frame):
    """Haken mit Beschriftung im dunklen Stil (tk.Checkbutton sieht dort fremd aus)."""

    def __init__(self, parent, text, command=None, bg=PANEL):
        super().__init__(parent, bg=bg)
        self.value = False
        self.command = command
        self.enabled = True
        s = self.size = int(20 * parent.winfo_toplevel().scale)
        self.box = tk.Canvas(self, width=s, height=s, bg=bg, highlightthickness=0, cursor="hand2")
        self.box.pack(side="left", anchor="n", pady=(2, 0))
        self.lbl = tk.Label(self, text=text, bg=bg, fg=TEXT, font=("Segoe UI", 11), cursor="hand2",
                            anchor="w", justify="left")
        self.lbl.pack(side="left", padx=(10, 0), fill="x")
        for w in (self.box, self.lbl):
            w.bind("<Button-1>", lambda e: self.toggle())
        self.draw()

    def draw(self):
        c, s = self.box, self.size
        c.delete("all")
        on = self.value
        col = ACCENT if on else (DIM if self.enabled else LINE)
        c.create_rectangle(1, 1, s - 2, s - 2, outline=col, width=2, fill=ACCENT if on else CARD)
        if on:
            c.create_line(s * .25, s * .52, s * .43, s * .7, s * .76, s * .3, fill=ACCENT_TXT, width=max(2, s // 8),
                          capstyle="round", joinstyle="round")
        self.lbl.configure(fg=TEXT if self.enabled else DIM)

    def toggle(self):
        if not self.enabled:
            return
        self.set(not self.value)
        if self.command:
            self.command()

    def set(self, v):
        self.value = bool(v)
        self.draw()

    def enable(self, on):
        self.enabled = on
        self.box.configure(cursor="hand2" if on else "arrow")
        self.lbl.configure(cursor="hand2" if on else "arrow")
        self.draw()


class Btn(tk.Label):
    """Flache Schaltflaeche (primary = Akzentfarbe)."""

    def __init__(self, parent, text, command, primary=False, bg=PANEL):
        self.colors = (ACCENT, ACCENT_HI, ACCENT_TXT) if primary else (CARD, LINE, TEXT)
        super().__init__(parent, text=text, bg=self.colors[0], fg=self.colors[2], cursor="hand2",
                         font=("Segoe UI", 11, "bold" if primary else "normal"), padx=18, pady=7)
        self.command = command
        self.enabled = True
        self.bind("<Enter>", lambda e: self.enabled and self.configure(bg=self.colors[1]))
        self.bind("<Leave>", lambda e: self.configure(bg=self.colors[0] if self.enabled else CARD))
        self.bind("<Button-1>", lambda e: self.enabled and self.command())

    def enable(self, on):
        self.enabled = on
        self.configure(bg=self.colors[0] if on else CARD, fg=self.colors[2] if on else DIM,
                       cursor="hand2" if on else "arrow")


class PatcherApp(tk.Tk):
    def __init__(self, preset=None):
        dpi_aware()
        super().__init__()
        self.scale = self.winfo_fpixels("1i") / 96.0
        px = lambda v: int(v * self.scale)
        self.px = px
        self.title("MX5 Bridge %s – Firmware Patcher" % VERSION)
        self.configure(bg=BG)
        self.geometry("%dx%d" % (px(720), px(820)))
        self.minsize(px(600), px(640))
        ico = os.path.join(HERE, "patcher.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(default=ico)
            except tk.TclError:
                pass
        self.q = queue.Queue()
        self.busy = False
        self.cancel = False
        self.file = None
        self.out_parent = patcher.BASE
        self.result = None
        self._build()
        if preset and os.path.exists(preset):
            self.file = os.path.abspath(preset)
            self.chk_file.set(True)
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(50, self.pump)
        self.after(10, self.dark_title)
        if os.environ.get("MX5B_AUTOSTART") == "1":     # nur fuer Tests der EXE: gleich bauen
            self.after(500, self.start)

    def dark_title(self):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            on = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
            self.withdraw()       # Titelleiste neu zeichnen lassen
            self.deiconify()
        except Exception:
            pass

    # ---------------- Aufbau ----------------
    def card(self, parent, title):
        f = tk.Frame(parent, bg=PANEL, padx=self.px(20), pady=self.px(16))
        f.pack(fill="x", pady=(0, self.px(12)))
        tk.Label(f, text=title.upper(), bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        return f

    def note(self, parent, text="", fg=MUTED, link=None):
        l = tk.Label(parent, text=text, bg=PANEL, fg=fg, font=("Segoe UI", 10), anchor="w", justify="left",
                     wraplength=self.px(620))
        l.pack(fill="x", pady=(self.px(6), 0))
        if link:
            l.configure(fg=ACCENT, cursor="hand2")
            l.bind("<Button-1>", lambda e: webbrowser.open(link))
        return l

    def _build(self):
        px = self.px
        root = tk.Frame(self, bg=BG, padx=px(20), pady=px(16))
        root.pack(fill="both", expand=True)
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", pady=(0, px(14)))
        tk.Label(head, text="MX5", bg=BG, fg=ACCENT, font=("Segoe UI", 22, "bold")).pack(side="left")
        tk.Label(head, text="  Bridge %s · Firmware Patcher" % VERSION, bg=BG, fg=TEXT,
                 font=("Segoe UI", 16)).pack(side="left", pady=(px(4), 0))
        tk.Label(root, text="Builds a firmware updater for the HeadRush MX5 (firmware 2.7) with the MX5 Bridge "
                            "from the official HeadRush updater. Unofficial – use at your own risk.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10), anchor="w", justify="left",
                 wraplength=px(660)).pack(fill="x", pady=(0, px(14)))

        # Optionen in einem eigenen Rahmen: nach dem Erfolg ersetzt der Ergebniskasten sie
        self.opts = tk.Frame(root, bg=BG)
        self.opts.pack(fill="x")
        c = self.card(self.opts, "Firmware")
        self.chk_file = Check(c, "Use a firmware file I already have", command=self.refresh)
        self.chk_file.pack(fill="x", pady=(px(10), 0))
        self.file_row = tk.Frame(c, bg=PANEL)
        self.lbl_file = tk.Label(self.file_row, text="", bg=CARD, fg=TEXT, font=("Segoe UI", 10), anchor="w", width=1,
                                 padx=px(10), pady=px(6))
        self.lbl_file.pack(side="left", fill="x", expand=True)
        self.btn_file = Btn(self.file_row, "Choose …", self.choose_file)
        self.btn_file.pack(side="left", padx=(px(8), 0))
        self.note_file = self.note(c)

        c = self.card(self.opts, "NAM mod")
        self.chk_nam = Check(c, "Also install the NAM mod (Neural Amp Modeler)", command=self.refresh)
        self.chk_nam.pack(fill="x", pady=(px(10), 0))
        self.note_nam = self.note(c)
        self.note(c, "NAM mod by lolgab (GPLv3) · github.com/lolgab/headrush-nam-mod", link=NAM_URL)

        c = self.card(self.opts, "Output")
        row = tk.Frame(c, bg=PANEL)
        row.pack(fill="x", pady=(px(10), 0))
        self.lbl_out = tk.Label(row, text="", bg=CARD, fg=TEXT, font=("Segoe UI", 10), anchor="w", width=1,
                                padx=px(10), pady=px(6))
        self.lbl_out.pack(side="left", fill="x", expand=True)
        self.btn_out = Btn(row, "Change …", self.choose_out)
        self.btn_out.pack(side="left", padx=(px(8), 0))

        bar = self.bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", pady=(px(4), px(10)))
        self.btn_go = Btn(bar, "Build updater", self.start, primary=True, bg=BG)
        self.btn_go.pack(side="left")
        self.btn_cancel = Btn(bar, "Cancel", self.do_cancel, bg=BG)
        self.status = tk.Label(bar, text="", bg=BG, fg=MUTED, font=("Segoe UI", 10), anchor="w")
        self.status.pack(side="left", padx=(px(14), 0), fill="x", expand=True)

        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("MX.Horizontal.TProgressbar", troughcolor=CARD, background=ACCENT, bordercolor=CARD,
                     lightcolor=ACCENT, darkcolor=ACCENT, thickness=px(6))
        self.prog = ttk.Progressbar(root, style="MX.Horizontal.TProgressbar", mode="determinate", maximum=100)
        self.prog.pack(fill="x")

        self.root_frame = root
        self.done = None
        logf = self.logf = tk.Frame(root, bg=PANEL, padx=px(2), pady=px(2))
        logf.pack(fill="both", expand=True, pady=(px(10), 0))
        self.log = tk.Text(logf, bg=PANEL, fg=MUTED, font=("Consolas", 9), relief="flat", wrap="word",
                           height=8, padx=px(10), pady=px(8), insertbackground=TEXT, state="disabled",
                           highlightthickness=0)
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("err", foreground=DANGER)
        self.log.tag_configure("ok", foreground=ACCENT)

    # ---------------- Zustand ----------------
    def refresh(self):
        px = self.px
        use_file, nam = self.chk_file.value, self.chk_nam.value
        if use_file:
            self.file_row.pack(fill="x", pady=(px(8), 0), before=self.note_file)
            self.lbl_file.configure(text=self.file or "No file chosen", fg=TEXT if self.file else DIM)
            if nam:
                txt = ("Choose the “HeadRush MX5 Firmware Updater (NAM mod).exe” that the NAM installer made. "
                       "To let the patcher run the NAM installer instead, untick this box.")
            else:
                txt = ("Choose the official “HeadRush MX5 2.7 Firmware Updater” (.exe or the .zip from HeadRush). "
                       "An updater made by the NAM installer works too – NAM is then kept.")
        else:
            self.file_row.pack_forget()
            txt = ("The NAM installer downloads the official firmware itself." if nam else
                   "The official HeadRush MX5 2.7 updater is downloaded from inMusic (about 60 MB).")
        self.note_file.configure(text=txt)
        if nam and not use_file:
            self.note_nam.configure(text="The NAM mod's own installer is downloaded from GitHub and opens in a "
                                         "second window. Choose MX5 and the number of instances there and click "
                                         "“Install NAM Mod” – the patcher then continues by itself.")
        elif nam:
            self.note_nam.configure(text="The chosen file must already contain the NAM mod.")
        else:
            self.note_nam.configure(text="Without the NAM mod the Anxiety OD stays the stock pedal. "
                                         "You can add NAM later by running the patcher again.")
        self.lbl_out.configure(text=self.out_parent)
        ready = not self.busy and (not use_file or bool(self.file))
        self.btn_go.enable(ready)
        for w in (self.chk_file, self.chk_nam):
            w.enable(not self.busy)
        self.btn_file.enable(not self.busy)
        self.btn_out.enable(not self.busy)

    def choose_file(self):
        p = filedialog.askopenfilename(
            parent=self, title="Choose the firmware updater",
            filetypes=[("HeadRush firmware updater", "*.exe *.zip"), ("Update.img", "*.img"), ("All files", "*.*")])
        if p:
            self.file = os.path.normpath(p)
            self.refresh()

    def choose_out(self):
        p = filedialog.askdirectory(parent=self, title="Folder for the new updater", initialdir=self.out_parent)
        if p:
            self.out_parent = os.path.normpath(p)
            self.refresh()

    # ---------------- Ausgabe aus dem Arbeits-Thread ----------------
    def post(self, kind, *a):
        self.q.put((kind, a))

    def pump(self):
        try:
            while True:
                kind, a = self.q.get_nowait()
                if kind == "log":
                    self.write(*a)
                elif kind == "progress":
                    got, total = a
                    self.prog.stop()
                    self.prog.configure(mode="determinate", value=got * 100 / total)
                    self.status.configure(text="Downloading … %d of %d MB" % (got >> 20, total >> 20))
                elif kind == "busy":
                    self.prog.configure(mode="indeterminate")
                    self.prog.start(15)
                    self.status.configure(text=a[0])
                elif kind == "finished":
                    self.finished(*a)
        except queue.Empty:
            pass
        self.after(50, self.pump)

    def write(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")
        line = text.strip().splitlines()[0] if text.strip() else ""
        if line and tag != "err":
            self.status.configure(text=line[:90])

    # ---------------- Ablauf ----------------
    def start(self):
        if self.busy:
            return
        self.busy, self.cancel, self.result = True, False, None
        self.status.configure(fg=MUTED)
        if self.done:
            self.done.destroy()
            self.done = None
        if not self.opts.winfo_ismapped():
            self.opts.pack(fill="x", before=self.bar)
        if not self.logf.winfo_ismapped():
            self.logf.pack(fill="both", expand=True, pady=(self.px(10), 0))
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        if self.chk_nam.value and not self.chk_file.value:
            self.btn_cancel.pack(side="left", padx=(self.px(8), 0), after=self.btn_go)
        self.refresh()
        args = (self.file if self.chk_file.value else None, self.chk_nam.value, self.out_parent)
        threading.Thread(target=self.work, args=args, daemon=True).start()

    def do_cancel(self):
        self.cancel = True
        self.status.configure(text="Cancelling …")

    def work(self, src, nam, out_parent):
        patcher.LOG[0] = lambda text: self.post("log", text)
        patcher.PROGRESS[0] = lambda got, total: self.post("progress", got, total)
        log = lambda text: self.post("log", text)
        stock = None
        try:
            log("MX5 Bridge %s firmware patcher" % VERSION)
            if nam and not src:
                self.post("busy", "Getting the NAM mod installer …")
                exe, tag, page = naminstaller.fetch(patcher.BASE, log, patcher.PROGRESS[0])
                self.post("busy", "Waiting for the NAM mod installer …")
                workdir = os.path.join(patcher.BASE, "NAM installer", "output")
                src, stock = naminstaller.run(exe, workdir, log, lambda: self.cancel)
            self.post("busy", "Building the updater …")
            out, found_nam, missing = patcher.build(src, need_nam=nam, out_parent=out_parent)
            kept = naminstaller.keep_stock(stock, out_parent)
            self.post("finished", True, out, found_nam, missing, kept)
        except (patcher.Fail, bridgepatch.PatchError, ext4.Ext4Error, naminstaller.NamError) as e:
            self.post("finished", False, str(e))
        except Exception as e:     # Netz, Dateien ... - dem Nutzer zeigen statt still zu sterben
            self.post("finished", False, "%s: %s" % (type(e).__name__, e))

    def finished(self, ok, *a):
        self.busy = False
        self.prog.stop()
        self.btn_cancel.pack_forget()
        px = self.px
        if not ok:
            self.prog.configure(mode="determinate", value=0)
            self.write("ERROR: " + a[0], "err")
            self.status.configure(text="Failed – see the messages below.", fg=DANGER)
            self.refresh()
            return
        out, nam, missing, kept = a
        self.result = out
        self.prog.configure(mode="determinate", value=100)
        self.write("Done: " + out, "ok")
        if kept:
            self.write("Kept the unmodified official updater for emergencies: " + kept)
        self.status.configure(text="Done.", fg=ACCENT)
        for w in (self.logf, self.opts, self.bar, self.prog):     # Ergebnisansicht statt Optionen
            w.pack_forget()
        self.done = tk.Frame(self.root_frame, bg=BG)
        self.done.pack(fill="x")
        box = tk.Frame(self.done, bg=PANEL, padx=px(20), pady=px(14))
        box.pack(fill="x")
        tk.Label(box, text="Updater ready%s" % (" (with NAM)" if nam else ""), bg=PANEL, fg=ACCENT,
                 font=("Segoe UI", 12, "bold"), anchor="w").pack(fill="x")
        steps = ("1. Connect the MX5 to its power supply and to this computer via USB.\n"
                 "2. On the MX5: Global Settings › ⋯ (more) › Firmware Update.\n"
                 "3. Click “Start firmware updater” and then “Install MX5Bridge %s%s”.\n"
                 "    Do not disconnect the MX5 until it has finished and restarted."
                 % (VERSION, " + NAM" if nam else ""))
        if kept:
            steps += "\nKeep “%s” – the unmodified official updater, for emergencies." % os.path.basename(kept)
        if missing:
            steps = ("Copy these files from the official updater into the folder first: %s\n\n" % ", ".join(missing)) + steps
        tk.Label(box, text="Saved in " + out, bg=PANEL, fg=MUTED, font=("Segoe UI", 9), anchor="w",
                 justify="left", wraplength=px(620)).pack(fill="x", pady=(px(2), 0))
        tk.Label(box, text=steps, bg=PANEL, fg=TEXT, font=("Segoe UI", 10), anchor="w", justify="left",
                 wraplength=px(620)).pack(fill="x", pady=(px(6), px(10)))
        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x")
        upd = os.path.join(out, "FirmwareUpdater.exe")
        b = Btn(row, "Start firmware updater", lambda: self.launch(upd, out), primary=True)
        b.pack(side="left")
        b.enable(os.path.exists(upd))
        Btn(row, "Open folder", lambda: os.startfile(out)).pack(side="left", padx=(px(8), 0))
        Btn(row, "Show details", self.toggle_details).pack(side="right")
        Btn(row, "Change options", self.show_options).pack(side="right", padx=(0, px(8)))
        self.refresh()
        self.fit_height()

    def fit_height(self):
        """Fenster so weit vergroessern, dass der Ergebniskasten ganz zu sehen ist (hoechstens bis
        zur Bildschirmhoehe); verkleinert nie."""
        self.update_idletasks()
        need = self.root_frame.winfo_reqheight()
        have = self.winfo_height()
        top = self.winfo_rooty() - self.winfo_y()      # Hoehe der Titelleiste
        room = self.winfo_screenheight() - self.winfo_y() - top - self.px(60)
        if need > have:
            self.geometry("%dx%d" % (self.winfo_width(), min(need, max(have, room))))

    def show_options(self):
        """Zurueck zu den Optionen (Ergebniskasten weg, Protokoll wieder da)."""
        if self.done:
            self.done.destroy()
            self.done = None
        for w in (self.opts, self.bar, self.prog, self.logf):
            w.pack_forget()
        self.opts.pack(fill="x")
        self.bar.pack(fill="x", pady=(self.px(4), self.px(10)))
        self.prog.pack(fill="x")
        self.logf.pack(fill="both", expand=True, pady=(self.px(10), 0))
        self.status.configure(text="", fg=MUTED)
        self.prog.configure(mode="determinate", value=0)

    def toggle_details(self):
        if self.logf.winfo_ismapped():
            self.logf.pack_forget()
        else:
            self.logf.pack(fill="both", expand=True, pady=(self.px(10), 0))

    def launch(self, exe, cwd):
        try:
            subprocess.Popen([exe], cwd=cwd)
        except OSError as e:
            messagebox.showerror("MX5 Bridge", "Could not start the updater:\n%s" % e, parent=self)

    def on_close(self):
        if self.busy and not messagebox.askyesno(
                "MX5 Bridge", "The patcher is still working. Quit anyway?", parent=self):
            return
        self.destroy()
        os._exit(0)     # laufende Arbeits-Threads (Download, Komprimieren) nicht abwarten


def main():
    PatcherApp(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()


if __name__ == "__main__":
    main()
