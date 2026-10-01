"""irs.py - Dialog "Impulse Responses": IR-Datei fuer einen IR-Block waehlen und die
IR-Dateien des Geraets verwalten (hochladen, herunterladen, umbenennen, loeschen,
Ordner anlegen) - ohne USB-Transfermodus, ueber die Dateifunktionen der Bruecke 0.3.

Links die Ordner, rechts die Dateien des gewaehlten Ordners (wie am Geraet: Folder /
IR File). Darunter Ordner und Name als Eingabefelder, damit sich auch eine IR eintragen
laesst, die der Editor nicht kennt (offline ohne Export-Ordner). Der Dialog ist eine
Ebene ueber dem Fenster (ui.Overlay wie der Tuner), nicht modal: Geraeteaktionen laufen ueber
editor.run_job, Rueckfragen legen sich als weitere Ebene darueber. Nach Aenderungen an den Dateien
muss die Geraete-App neu starten (das MX5 liest den Dateibaum nur beim Start) - der
Editor stoesst das beim Schliessen bzw. vor dem Uebernehmen an (ir_dialog_done).

Probehoeren (Einstellung "audition", nur live): ein Klick auf eine Datei setzt sie sofort im Block,
der Dialog bleibt offen; "Done"/x behaelt die gerade gehoerte IR, "Revert" setzt die IR vom Oeffnen
zurueck. Sind Dateien geaendert, kennt das Geraet sie erst nach dem Neustart - dann wird die
Auswahl wie bisher erst beim Schliessen (nach dem Neustart) gesetzt.
"""
import os, tkinter as tk
from tkinter import ttk, filedialog

import live as L
import ui as U
from ui import PANEL, CARD, ACCENT, ACCENT_TXT, TEXT, MUTED, px
from ui import FONT, FONT_SMALL
from ui import messagebox   # Meldungen als Overlay im Stil der Oberflaeche


class IRDialog(U.Overlay):
    """irs: Ergebnis von live.db_irs / live.read_ir_folder. current: IR-Text des Blocks.
    on_pick(folder, name): Auswahl uebernehmen (None = nur verwalten). manage: Dateien
    aendern erlaubt (live, Bruecke 0.3)."""

    def __init__(self, editor, irs, current=None, on_pick=None, manage=False, title=None, audition=False):
        self._title = title or ("Choose IR" if on_pick else "Manage impulse responses")
        self.audition = bool(audition and on_pick)
        self.original = L.parse_ir(current or "")   # (Ordner, Name) beim Oeffnen, fuer "Revert"
        self.heard = None                           # zuletzt probegehoerte (Ordner, Name)
        super().__init__(editor, self._title, width=820, height=560)
        self.ed = editor
        self.closed = False
        self.irs = irs
        self.on_pick = on_pick
        self.manage = manage
        self.changed = False          # Dateien geaendert -> Neustart der Geraete-App noetig
        self.pick_args = None         # (Ordner, Name) nach Uebernehmen; der Editor setzt die IR
        self.var_folder = tk.StringVar()
        self.var_name = tk.StringVar()
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.fill_files())
        self.folder = None
        self.build()
        d, n = L.parse_ir(current or "")
        if d is not None:
            self.var_folder.set(d)
            self.var_name.set(n)
        self.fill_folders(d if d in self.irs["folders"] else None, n)
        self.bind_keys()   # Escape auch in Eingabefeldern und Listen
        if self.audition:  # Pfeiltasten blaettern durch die Dateien und laden sie
            self.lb_files.focus_set()

    def title(self):
        return self._title   # fuer Rueckfragen (wie Toplevel.title())

    def cancel(self):
        self.close()

    def close(self, result=None):
        if self.closed:
            return
        self.closed = True
        self.ed.ir_dialog_done(self)
        super().close(result)

    # ---------------- Aufbau ----------------
    def build(self):
        b = self.body
        self.lbl_info = tk.Label(b, text="", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w")
        self.lbl_info.pack(fill="x", pady=(0, px(6)))
        mid = tk.Frame(b, bg=PANEL)
        mid.pack(fill="both", expand=True)
        left = tk.Frame(mid, bg=PANEL, width=px(240))
        left.pack(side="left", fill="y", padx=(0, px(12)))
        left.pack_propagate(False)
        tk.Label(left, text="FOLDER", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x", pady=(0, px(4)))
        self.lb_folders = self._listbox(left)
        self.lb_folders.bind("<<ListboxSelect>>", lambda e: self.on_folder())
        right = tk.Frame(mid, bg=PANEL)
        right.pack(side="left", fill="both", expand=True)
        top = tk.Frame(right, bg=PANEL)
        top.pack(fill="x", pady=(0, px(4)))
        tk.Label(top, text="IR FILE", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").pack(side="left")
        U.Entry(top, textvariable=self.filter, placeholder="Search …", width=22, font=FONT_SMALL).pack(side="right")
        self.lb_files = self._listbox(right)
        self.lb_files.bind("<<ListboxSelect>>", lambda e: self.on_file())
        if self.audition:
            self.lb_files.bind("<Return>", lambda e: self.close())
        elif self.on_pick:
            self.lb_files.bind("<Double-Button-1>", lambda e: self.apply())
        # Eingabefelder: Ordner / Name (auch fuer IRs, die der Editor nicht kennt)
        row = tk.Frame(b, bg=PANEL)
        row.pack(fill="x", pady=(px(10), 0))
        tk.Label(row, text="Folder", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left")
        U.Entry(row, textvariable=self.var_folder, width=22, font=FONT_SMALL).pack(side="left", padx=(px(6), px(14)))
        tk.Label(row, text="Name", bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(side="left")
        e_name = U.Entry(row, textvariable=self.var_name, width=34, font=FONT_SMALL)
        e_name.pack(side="left", padx=(px(6), 0), fill="x", expand=True)
        if self.audition:   # getippte IR: Enter laedt sie, ohne zu schliessen
            e_name.bind_entry("<Return>", lambda e: self.apply())
        # Knoepfe
        bf = self.bf = tk.Frame(b, bg=PANEL)
        bf.pack(fill="x", side="bottom", pady=(px(12), 0))
        if self.audition:
            U.Btn(bf, "Done", command=self.close, kind="primary").pack(side="right")
            self.btn_revert = U.Btn(bf, "Revert", command=self.revert, kind="ghost")
            self.btn_revert.pack(side="right", padx=px(8))
            self.btn_revert.configure(state="disabled")
        elif self.on_pick:
            U.Btn(bf, "Apply", command=self.apply, kind="primary").pack(side="right")
            U.Btn(bf, "Cancel", command=self.close, kind="ghost").pack(side="right", padx=px(8))
        else:
            U.Btn(bf, "Close", command=self.close, kind="primary").pack(side="right")
        if self.manage:
            U.Btn(bf, "Upload …", command=self.upload, padx=10, pady=4, font=FONT_SMALL).pack(side="left")
            U.Btn(bf, "New folder …", command=self.new_folder, padx=10, pady=4, font=FONT_SMALL).pack(side="left", padx=(px(6), 0))
            self.btn_rename = U.Btn(bf, "Rename …", command=self.rename, padx=10, pady=4, font=FONT_SMALL)
            self.btn_rename.pack(side="left", padx=(px(6), 0))
            self.btn_delete = U.Btn(bf, "Delete …", command=self.delete_selected, kind="danger", padx=10, pady=4, font=FONT_SMALL)
            self.btn_delete.pack(side="left", padx=(px(6), 0))
            self.btn_download = U.Btn(bf, "Download …", command=self.download, padx=10, pady=4, font=FONT_SMALL)
            self.btn_download.pack(side="left", padx=(px(6), 0))
        self.lbl_restart = tk.Label(b, text="", bg=PANEL, fg=ACCENT, font=FONT_SMALL, anchor="w", wraplength=px(760),
                                    justify="left")   # erst bei einer Aenderung gezeigt (mark_changed)

    @staticmethod
    def _listbox(parent):
        f = tk.Frame(parent, bg=PANEL)
        f.pack(fill="both", expand=True)
        lb = tk.Listbox(f, activestyle="none", exportselection=False, bg=CARD, fg=TEXT, selectbackground=ACCENT,
                        selectforeground=ACCENT_TXT, bd=0, highlightthickness=0, font=FONT, width=10)
        sb = ttk.Scrollbar(f, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return lb

    # ---------------- Listen ----------------
    def set_irs(self, irs, folder=None, name=None):
        self.irs = irs
        self.fill_folders(folder or self.folder, name)

    def fill_folders(self, select=None, name=None):
        lb = self.lb_folders
        lb.delete(0, "end")
        folders = self.irs["folders"]
        for f in folders:
            n = len(self.irs["files"].get(f, []))
            lb.insert("end", "%s  (%d)" % (f, n) if n else f)
        total = sum(len(v) for v in self.irs["files"].values())
        if not folders:
            self.lbl_info.configure(text="No IR files known – enter folder and name below."
                                    if not self.manage else "No IR files on the device.")
        else:
            hint = (" – a click loads the IR, “Done” keeps it" if self.audition else
                    " – double-click applies" if self.on_pick else "")
            self.lbl_info.configure(text="%d IR files in %d folders%s" % (total, len(folders), hint))
        if select not in folders:
            select = folders[0] if folders else None
        self.folder = select
        if select:
            i = folders.index(select)
            lb.selection_set(i)
            lb.see(i)
        self.fill_files(name)

    def fill_files(self, select=None):
        lb = self.lb_files
        lb.delete(0, "end")
        q = self.filter.get().lower()
        self.shown = [t for t in self.irs["files"].get(self.folder, []) if q in t[0].lower()]
        for n, _ in self.shown:
            lb.insert("end", n)
        names = [n for n, _ in self.shown]
        if select in names:
            i = names.index(select)
            lb.selection_set(i)
            lb.see(i)
        self.update_buttons()

    def on_folder(self):
        sel = self.lb_folders.curselection()
        if not sel:
            return
        self.folder = self.irs["folders"][sel[0]]
        self.var_folder.set(self.folder)
        self.fill_files()

    def on_file(self):
        sel = self.lb_files.curselection()
        if sel:
            self.var_folder.set(self.folder or "")
            self.var_name.set(self.shown[sel[0]][0])
            if self.audition:
                self.listen(self.folder or L.IR_ROOT, self.shown[sel[0]][0])
        self.update_buttons()

    def selected_file(self):
        """(Ordner, Name, Dateiname) der markierten Datei oder None."""
        sel = self.lb_files.curselection()
        if not sel or not self.folder:
            return None
        n, fn = self.shown[sel[0]]
        return self.folder, n, fn

    def update_buttons(self):
        if not self.manage:
            return
        has = self.selected_file() is not None
        own = self.folder not in (None, L.IR_ROOT, L.IR_USER)
        self.btn_download.configure(state="normal" if has else "disabled")
        self.btn_rename.configure(state="normal" if (has or own) else "disabled")
        self.btn_delete.configure(state="normal" if (has or own) else "disabled")

    def mark_changed(self):
        self.changed = True
        self.heard = None   # das Geraet kennt die geaenderten Dateien erst nach dem Neustart
        if not self.lbl_restart.winfo_ismapped():
            self.lbl_restart.pack(fill="x", pady=(0, px(8)), before=self.bf)
        self.lbl_restart.configure(text="The MX5 reads its IR files only at startup: the device app is restarted "
                                        "when this dialog closes (about 15 s).")

    # ---------------- Auswahl ----------------
    def listen(self, folder, name):
        """Probehoeren: IR sofort im Block setzen, der Dialog bleibt offen. Nach Dateiaenderungen
        kennt das Geraet neue Dateien noch nicht - dann erst beim Schliessen (nach dem Neustart)."""
        if (folder, name) == self.heard:
            return
        self.heard = (folder, name)
        if self.changed:
            self.pick_args = (folder, name)
            self.ed.status.set("“%s” is set once the device app has restarted (when this dialog closes)." % name)
        else:
            self.pick_args = None
            self.on_pick(folder, name)
        if self.original[0] is not None:
            self.btn_revert.configure(state="normal")

    def revert(self):
        """Die IR vom Oeffnen wieder setzen und schliessen."""
        d, n = self.original
        if d is None:
            return
        if self.heard and self.heard != (d, n):
            self.heard = None
            self.pick_args = (d, n) if self.changed else None
            if not self.changed:
                self.on_pick(d, n)
        self.close()

    def apply(self):
        folder, name = self.var_folder.get().strip(), self.var_name.get().strip()
        if not name:
            messagebox.showinfo(self.title(), "Please choose an IR file or enter a name.", parent=self)
            return
        if folder and folder not in self.irs["folders"] and self.irs["folders"] and not messagebox.askyesno(
                self.title(), "The editor does not know the folder “%s”. Use it anyway?" % folder, parent=self):
            return
        if self.audition:
            self.heard = None
            self.listen(folder or L.IR_ROOT, name)
            return
        self.pick_args = (folder or L.IR_ROOT, name)   # der Editor uebernimmt (nach dem Neustart, falls noetig)
        self.close()

    # ---------------- Verwalten ----------------
    def device_job(self, fn, done, text):
        """Geraeteaktion ueber den Editor; danach die Liste neu lesen."""
        def after(res, err):
            if err:
                messagebox.showwarning(self.title(), err, parent=self)
            else:
                done(res)
            self.refresh(err is None)
        self.ed.run_job(fn, after, text)

    def refresh(self, changed=False):
        if changed:
            self.mark_changed()
        folder, name = self.var_folder.get(), self.var_name.get()

        def got(res, err):
            if err:
                self.ed.status.set("Could not read the IR list: %s" % err)
                return
            if self.winfo_exists():
                self.set_irs(res, folder, name)
        self.ed.run_job(L.db_irs, got, "Reading IR files …")

    def upload(self):
        folder = self.folder
        if not folder or folder == L.IR_ROOT:
            messagebox.showinfo(self.title(), "Please choose a folder on the left first (or create one).", parent=self)
            return
        paths = filedialog.askopenfilenames(parent=self, title="Upload IR files to “%s”" % folder,
                                            filetypes=[("Impulse Responses", "*.wav *.mp3"), ("All files", "*.*")])
        if not paths:
            return
        taken = {n.lower() for n, _ in self.irs["files"].get(folder, [])}
        jobs = []
        for p in paths:
            name = os.path.splitext(os.path.basename(p))[0].strip()
            err = L.check_ir_name(name)
            if err:
                messagebox.showwarning(self.title(), "%s: %s" % (os.path.basename(p), err), parent=self)
                continue
            replace = False
            if name.lower() in taken:
                if not messagebox.askyesno(self.title(), "“%s” already exists in “%s”. Replace?" % (name, folder), parent=self):
                    continue
                replace = True
            jobs.append((p, name, replace))
        if not jobs:
            return
        say = lambda t: self.ed._inbox.put(lambda: self.ed.status.set(t))

        def job(br):
            n = 0
            for p, name, replace in jobs:
                say("Uploading %s (%d/%d) …" % (name, n + 1, len(jobs)))
                L.ir_upload(br, folder, p, name, replace=replace)
                n += 1
            return n
        self.var_name.set(jobs[-1][1])
        self.device_job(job, lambda n: self.ed.status.set("%d IR file(s) uploaded to “%s”." % (n, folder)),
                  "Uploading IR files …")

    def new_folder(self):
        name = U.TextDialog(self, "New IR folder", "Folder name:", "",
                            "No characters < > : \" / \\ | ? *").result
        if name is None:
            return
        name = name.strip()
        err = L.check_ir_name(name, "Folder name")
        if err:
            messagebox.showwarning(self.title(), err, parent=self)
            return
        if name in self.irs["folders"]:
            messagebox.showinfo(self.title(), "This folder already exists.", parent=self)
            return
        self.var_folder.set(name)
        self.device_job(lambda br: L.ir_create_folder(br, name), lambda _: self.ed.status.set("Folder “%s” created." % name),
                  "Creating folder …")

    def rename(self):
        sel = self.selected_file()
        if sel:
            folder, name, fn = sel
            new = U.TextDialog(self, "Rename IR", "New name for “%s”:" % name, name).result
            if new is None or new.strip() == name:
                return
            new = new.strip()
            if new.lower() in {n.lower() for n, _ in self.irs["files"].get(folder, [])}:
                messagebox.showinfo(self.title(), "This name already exists in “%s”." % folder, parent=self)
                return
            self.var_name.set(new)
            self.device_job(lambda br: L.ir_rename(br, folder, fn, new),
                      lambda _: self.ed.status.set("“%s” is now called “%s”. Rigs that use the IR show it as missing."
                                                   % (name, new)), "Renaming IR …")
            return
        folder = self.folder
        if folder in (None, L.IR_ROOT, L.IR_USER):
            return
        new = U.TextDialog(self, "Rename folder", "New name for the folder “%s”:" % folder, folder).result
        if new is None or new.strip() == folder:
            return
        new = new.strip()
        if new in self.irs["folders"]:
            messagebox.showinfo(self.title(), "This folder already exists.", parent=self)
            return
        self.var_folder.set(new)
        self.device_job(lambda br: L.ir_rename_folder(br, folder, new),
                  lambda _: self.ed.status.set("Folder “%s” is now called “%s”. Rigs using IRs from it show them as missing."
                                               % (folder, new)), "Renaming folder …")

    def delete_selected(self):
        sel = self.selected_file()
        if sel:
            folder, name, fn = sel

            def ask(users, err):
                if err:
                    messagebox.showwarning(self.title(), err, parent=self)
                    return
                text = "Delete “%s” in “%s” from the device?" % (name, folder)
                if users:
                    text += "\n\nThese rigs use the IR (they will show it as missing):\n" + "\n".join(users[:12])
                    if len(users) > 12:
                        text += "\n… and %d more" % (len(users) - 12)
                if not messagebox.askyesno(self.title(), text, parent=self):
                    return
                self.device_job(lambda br: L.ir_delete(br, folder, fn), lambda _: self.ed.status.set("“%s” deleted." % name),
                          "Deleting IR …")
            self.ed.run_job(lambda br: L.db_rigs_using_ir(br, folder, name), ask, "Checking which rigs use the IR …")
            return
        folder = self.folder
        if folder in (None, L.IR_ROOT, L.IR_USER):
            return
        n = len(self.irs["files"].get(folder, []))
        if not messagebox.askyesno(self.title(), "Delete folder “%s” with %d IR file(s) from the device?\n\n"
                                   "Rigs that use IRs from it will show them as missing." % (folder, n), parent=self):
            return
        self.device_job(lambda br: L.ir_delete_folder(br, folder), lambda _: self.ed.status.set("Folder “%s” deleted." % folder),
                  "Deleting folder …")

    def download(self):
        sel = self.selected_file()
        if not sel:
            return
        folder, name, fn = sel
        path = filedialog.asksaveasfilename(parent=self, title="Save IR", initialfile=fn,
                                            defaultextension=os.path.splitext(fn)[1],
                                            filetypes=[("Impulse Responses", "*.wav *.mp3"), ("All files", "*.*")])
        if not path:
            return

        def done(n, err):
            if err:
                messagebox.showwarning(self.title(), err, parent=self)
            else:
                self.ed.status.set("“%s” saved (%d KB): %s" % (name, n // 1024, path))
        self.ed.run_job(lambda br: L.ir_download(br, folder, fn, path), done, "Downloading “%s” …" % name)
