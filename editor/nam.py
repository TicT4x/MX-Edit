"""nam.py - Dialog "NAM models": die Modelle der NAM-Mod (github.com/lolgab/headrush-nam-mod) auf
dem Geraet verwalten - hochladen, ersetzen, umbenennen, sortieren, loeschen, herunterladen - ueber
die Dateifunktionen der Bruecke (0.7 mit NAM gebaut).

Die Liste zeigt die Modelle in der Reihenfolge des Geraets: Platz = Drive-Wert des Anxiety OD,
der das Modell waehlt. Jede Aenderung benennt den Ordner lueckenlos 'NNN - Name.nam' und zieht
die Drive-Werte der Rigs und NAM-Presets nach (live.nam_apply), damit jedes Rig sein Modell
behaelt; Rigs mit einem geloeschten Modell werden stumm. Die Mod liest den Ordner nur beim
App-Start - der Editor startet die Geraete-App beim Schliessen neu (nam_dialog_done). Der Dialog
ist eine Ebene ueber dem Fenster (ui.Overlay wie der IR-Dialog), nicht modal.

NAMBrowser ist die Modellauswahl eines NAM-Blocks (Parameterzeile "Model"); mit der Einstellung
"audition" setzt ein Klick das Modell sofort und die Auswahl bleibt zum Durchprobieren offen.
"""
import os, tkinter as tk
from tkinter import ttk, filedialog

import live as L
import ui as U
from ui import PANEL, CARD, ACCENT, ACCENT_TXT, TEXT, MUTED, DIM, px
from ui import FONT_SMALL
from ui import messagebox


FONT_MONO = ("Consolas", 10)   # Liste mit Spalten (Platz, Name, Groesse)


def size_text(n):
    return "%.1f MB" % (n / 1048576.0) if n >= 1048576 else "%d KB" % max(1, n // 1024)


class NAMDialog(U.Overlay):
    """data: {'nam': nam_status, 'models': db_nam_models()['models'], 'usage': nam_usage}."""

    def __init__(self, editor, data):
        super().__init__(editor, "NAM models", width=820, height=580)
        self.ed = editor
        self.closed = False
        self.changed = False          # Dateien geaendert -> Neustart der Geraete-App noetig
        self.set_data(data, build=True)
        self.bind_keys()

    def title(self):
        return "NAM models"   # fuer Rueckfragen (wie Toplevel.title())

    def cancel(self):
        self.close()

    def close(self, result=None):
        if self.closed:
            return
        self.closed = True
        self.ed.nam_dialog_done(self)
        super().close(result)

    # ---------------- Aufbau ----------------
    def build(self):
        b = self.body
        self.lbl_info = tk.Label(b, text="", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w")
        self.lbl_info.pack(fill="x", pady=(0, px(6)))
        head = tk.Frame(b, bg=PANEL)
        head.pack(fill="x", pady=(0, px(4)))
        tk.Label(head, text="DRIVE   MODEL", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").pack(side="left")
        tk.Label(head, text="SIZE · USED BY", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="e").pack(side="right")
        f = tk.Frame(b, bg=PANEL)
        f.pack(fill="both", expand=True)
        self.lb = tk.Listbox(f, activestyle="none", exportselection=False, bg=CARD, fg=TEXT, selectbackground=ACCENT,
                             selectforeground=ACCENT_TXT, bd=0, highlightthickness=0, font=FONT_MONO, width=10,
                             selectmode="extended")
        sb = ttk.Scrollbar(f, command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb.bind("<<ListboxSelect>>", lambda e: self.on_select())
        self.lb.bind("<Double-Button-1>", lambda e: self.rename())
        self.lb.bind("<Delete>", lambda e: self.delete_selected())
        self.lb.bind("<Alt-Up>", lambda e: self.move(-1))
        self.lb.bind("<Alt-Down>", lambda e: self.move(1))
        self.lb.bind("<Configure>", lambda e: self.fill())
        self.lbl_sel = tk.Label(b, text="", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w", justify="left",
                                wraplength=px(780))
        self.lbl_sel.pack(fill="x", pady=(px(6), 0))
        tk.Label(b, text="The Drive knob of the Anxiety OD chooses the model: Drive = number in this list, positions "
                         "without a model are silent. Moving or deleting models updates the rigs and NAM presets that "
                         "use them, so every rig keeps its model.",
                 bg=PANEL, fg=DIM, font=FONT_SMALL, anchor="w", justify="left", wraplength=px(780)
                 ).pack(fill="x", pady=(px(6), 0))
        bf = self.bf = tk.Frame(b, bg=PANEL)
        bf.pack(fill="x", side="bottom", pady=(px(12), 0))
        U.Btn(bf, "Close", command=self.close, kind="primary").pack(side="right")
        small = dict(padx=10, pady=4, font=FONT_SMALL)
        U.Btn(bf, "Upload …", command=self.upload, **small).pack(side="left")
        self.btn_up = U.Btn(bf, "▲", command=lambda: self.move(-1), **small)
        self.btn_up.pack(side="left", padx=(px(10), 0))
        self.btn_down = U.Btn(bf, "▼", command=lambda: self.move(1), **small)
        self.btn_down.pack(side="left", padx=(px(2), 0))
        self.btn_sort = U.Btn(bf, "Sort A–Z", command=self.sort_by_name, **small)
        self.btn_sort.pack(side="left", padx=(px(6), 0))
        self.btn_rename = U.Btn(bf, "Rename …", command=self.rename, **small)
        self.btn_rename.pack(side="left", padx=(px(10), 0))
        self.btn_replace = U.Btn(bf, "Replace file …", command=self.replace_file, **small)
        self.btn_replace.pack(side="left", padx=(px(6), 0))
        self.btn_download = U.Btn(bf, "Download …", command=self.download, **small)
        self.btn_download.pack(side="left", padx=(px(6), 0))
        self.btn_delete = U.Btn(bf, "Delete …", command=self.delete_selected, kind="danger", **small)
        self.btn_delete.pack(side="left", padx=(px(10), 0))
        self.lbl_restart = tk.Label(b, text="", bg=PANEL, fg=ACCENT, font=FONT_SMALL, anchor="w", wraplength=px(780),
                                    justify="left")   # erst bei einer Aenderung gezeigt (mark_changed)

    # ---------------- Liste ----------------
    def set_data(self, data, select=None, build=False):
        self.nam = dict(data["nam"], active=True)   # Umschreiben der Rigs auch, wenn NAM gerade aus ist
        self.models = data["models"]
        self.usage = data.get("usage") or {}
        if build:
            self.build()
        nam = data["nam"]
        state = "on" if nam.get("active") else ("switched off automatically" if nam.get("auto_off") else "off")
        ref = nam.get("ref") or ""
        ref = "" if ref == "unbekannt" else " " + ref   # Patcher ohne Herkunftsangabe schreibt 'unbekannt'
        self.lbl_info.configure(text="NAM mod%s  ·  %s  ·  %d instance(s)  ·  %d of %d possible models"
                                % (ref, state, nam.get("instances", 2), len(self.models), L.NAM_STEPS))
        self.fill(select)

    def fill(self, select=None):
        lb = self.lb
        keep = select if select is not None else [self.models[i]["file"] for i in lb.curselection()
                                                  if i < len(self.models)]
        lb.delete(0, "end")
        # Spaltenbreite in Zeichen der Festbreitenschrift aus der Listenbreite
        cw = max(40, lb.winfo_width() // max(1, U.text_size("0", FONT_MONO)[0]) - 1)
        for m in self.models:
            users = self.usage.get(m["index"], [])
            right = "%s · %s" % (size_text(m["size"]), "%d rig(s)/preset(s)" % len(users) if users else "unused")
            left = "%03d  %s" % (m["index"], m["name"])
            room = cw - len(right) - 2
            if len(left) > room:
                left = left[:max(8, room - 1)] + "…"
            lb.insert("end", left + " " * max(2, cw - len(left) - len(right)) + right)
        if not self.models:
            lb.insert("end", "  No NAM models on the device yet – “Upload …” adds .nam files.")
            lb.itemconfigure(0, fg=MUTED)
        files = [m["file"] for m in self.models]
        for fn in keep or []:
            if fn in files:
                lb.selection_set(files.index(fn))
                lb.see(files.index(fn))
        self.on_select()

    def selected(self):
        return [self.models[i] for i in self.lb.curselection() if i < len(self.models)]

    def on_select(self):
        sel = self.selected()
        if len(sel) == 1:
            m = sel[0]
            users = self.usage.get(m["index"], [])
            text = "%s  ·  file “%s”" % (m["name"], m["file"])
            if users:
                text += "\nUsed by: " + ", ".join(users[:8]) + (" … and %d more" % (len(users) - 8) if len(users) > 8 else "")
            self.lbl_sel.configure(text=text)
        else:
            self.lbl_sel.configure(text="%d models selected" % len(sel) if sel else "")
        one, some = len(sel) == 1, bool(sel)
        idx = [m["index"] for m in sel]
        self.btn_up.configure(state="normal" if some and min(idx) > 0 else "disabled")
        self.btn_down.configure(state="normal" if some and max(idx) < len(self.models) - 1 else "disabled")
        self.btn_sort.configure(state="normal" if len(self.models) > 1 else "disabled")
        for b in (self.btn_rename, self.btn_replace, self.btn_download):
            b.configure(state="normal" if one else "disabled")
        self.btn_delete.configure(state="normal" if some else "disabled")

    def mark_changed(self):
        self.changed = True
        if not self.lbl_restart.winfo_ismapped():
            self.lbl_restart.pack(fill="x", pady=(px(8), 0), before=self.bf)
        self.lbl_restart.configure(text="The NAM mod reads its models only when the device app starts: the app is "
                                        "restarted when this dialog closes (about 15 s).")

    # ---------------- Aenderungen ----------------
    def apply(self, final, text, delete=(), replace=None, select=None, done_text=None):
        """final: [(Quelle, Name)] in neuer Reihenfolge -> live.nam_apply, danach alles neu lesen."""
        old = [m["file"] for m in self.models]
        nam = self.nam
        say = lambda t: self.ed._inbox.put(lambda: self.ed.status.set(t))

        def job(br):
            res = L.nam_apply(br, nam, old, final, delete=delete, replace=replace, progress=say)
            models = L.db_nam_models(br)["models"]
            return {"res": res, "nam": L.nam_status(br), "models": models, "usage": L.nam_usage(br, nam)}

        def after(data, err):
            if err:
                messagebox.showwarning(self.title(), err, parent=self)
                self.reload()
                return
            self.mark_changed()
            self.ed.lrig.nam_models = data["models"]
            if not self.winfo_exists():
                return
            sel = [m["file"] for m in data["models"] if m["name"] in (select or [])]
            self.set_data(data, select=sel)
            r = data["res"]["remapped"]
            self.ed.status.set((done_text or "NAM models updated.") +
                               ("  %d rig(s)/preset(s) updated so they keep their model." % r if r else ""))
        self.ed.run_job(job, after, text)

    def reload(self):
        nam = self.nam

        def job(br):
            return {"nam": L.nam_status(br), "models": L.db_nam_models(br)["models"], "usage": L.nam_usage(br, nam)}

        def got(data, err):
            if not err and self.winfo_exists():
                self.set_data(data)
        self.ed.run_job(job, got, "Reading NAM models …")

    def current(self):
        return [(m["file"], m["name"]) for m in self.models]

    def upload(self):
        paths = filedialog.askopenfilenames(parent=self, title="Upload NAM models",
                                            filetypes=[("NAM models", "*.nam"), ("All files", "*.*")])
        if not paths:
            return
        final = self.current()
        names = {n.lower(): fn for fn, n in final}
        replace, added = {}, []
        for p in paths:
            name = L.nam_base(os.path.basename(p)).strip()
            err = L.check_nam_name(name)
            if err:
                messagebox.showwarning(self.title(), "%s: %s" % (os.path.basename(p), err), parent=self)
                continue
            try:
                with open(p, "rb") as f:
                    L.check_nam_data(f.read(), os.path.basename(p))
            except (OSError, L.LiveError) as e:
                messagebox.showwarning(self.title(), str(e), parent=self)
                continue
            if name.lower() in names:
                if not messagebox.askyesno(self.title(), "“%s” is already on the device. Replace its file?\n"
                                           "(Its position and the rigs that use it stay.)" % name, parent=self):
                    continue
                replace[names[name.lower()]] = p
            elif name.lower() in {n.lower() for n in added}:
                continue
            else:
                final.append((p, name))
                added.append(name)
        if not added and not replace:
            return
        if len(final) > L.NAM_STEPS:
            messagebox.showwarning(self.title(), "At most %d models are reachable with the Drive knob (0–100 %%)."
                                   % L.NAM_STEPS, parent=self)
            return
        self.apply(final, "Uploading NAM models …", replace=replace, select=added or None,
                   done_text="%d model(s) uploaded%s." % (len(added) + len(replace),
                                                           ", %d replaced" % len(replace) if replace else ""))

    def move(self, d):
        sel = self.selected()
        if not sel:
            return
        idx = sorted(m["index"] for m in sel)
        items = self.current()
        if (d < 0 and idx[0] == 0) or (d > 0 and idx[-1] == len(items) - 1):
            return
        order = list(range(len(items)))
        for i in (idx if d < 0 else reversed(idx)):   # Block der Auswahl um eins verschieben
            order[i], order[i + d] = order[i + d], order[i]
        final = [items[i] for i in order]
        self.apply(final, "Moving NAM models …", select=[m["name"] for m in sel], done_text="Moved.")

    def sort_by_name(self):
        items = self.current()
        final = sorted(items, key=lambda t: t[1].lower())
        if final == items:
            self.ed.status.set("The models are already sorted by name.")
            return
        if not messagebox.askyesno(self.title(), "Sort all models by name? Their Drive positions change; rigs and "
                                   "NAM presets are updated so they keep their model.", parent=self):
            return
        self.apply(final, "Sorting NAM models …", done_text="Sorted by name.")

    def rename(self):
        sel = self.selected()
        if len(sel) != 1:
            return
        m = sel[0]
        new = U.TextDialog(self, "Rename NAM model", "New name for “%s”:" % m["name"], m["name"],
                           "The number in front (Drive position) is added automatically.").result
        if new is None or new.strip() == m["name"]:
            return
        new = L.nam_base(new.strip() + L.NAM_EXT)
        if new.lower() in {x["name"].lower() for x in self.models if x is not m}:
            messagebox.showinfo(self.title(), "This name already exists.", parent=self)
            return
        final = [(fn, new if fn == m["file"] else n) for fn, n in self.current()]
        self.apply(final, "Renaming NAM model …", select=[new], done_text="“%s” is now called “%s”." % (m["name"], new))

    def replace_file(self):
        sel = self.selected()
        if len(sel) != 1:
            return
        m = sel[0]
        p = filedialog.askopenfilename(parent=self, title="New file for “%s”" % m["name"],
                                       filetypes=[("NAM models", "*.nam"), ("All files", "*.*")])
        if not p:
            return
        self.apply(self.current(), "Replacing “%s” …" % m["name"], replace={m["file"]: p}, select=[m["name"]],
                   done_text="File of “%s” replaced." % m["name"])

    def delete_selected(self):
        sel = self.selected()
        if not sel:
            return
        users = [u for m in sel for u in self.usage.get(m["index"], [])]
        names = ", ".join("“%s”" % m["name"] for m in sel[:5]) + (" …" if len(sel) > 5 else "")
        text = "Delete %s from the device?" % names
        if users:
            text += ("\n\nThese rigs/presets use it and will be silent (Drive %d %%):\n" % L.NAM_SILENT
                     + "\n".join(users[:10]) + ("\n… and %d more" % (len(users) - 10) if len(users) > 10 else ""))
        text += "\n\nThe models after it move up; rigs using them are updated."
        if not messagebox.askyesno(self.title(), text, parent=self):
            return
        gone = {m["file"] for m in sel}
        final = [(fn, n) for fn, n in self.current() if fn not in gone]
        self.apply(final, "Deleting NAM models …", delete=sorted(gone), done_text="%d model(s) deleted." % len(sel))

    def download(self):
        sel = self.selected()
        if len(sel) != 1:
            return
        m = sel[0]
        path = filedialog.asksaveasfilename(parent=self, title="Save NAM model", initialfile=m["name"] + L.NAM_EXT,
                                            defaultextension=L.NAM_EXT,
                                            filetypes=[("NAM models", "*.nam"), ("All files", "*.*")])
        if not path:
            return

        def done(n, err):
            if err:
                messagebox.showwarning(self.title(), err, parent=self)
            else:
                self.ed.status.set("“%s” saved (%s): %s" % (m["name"], size_text(n), path))
        self.ed.run_job(lambda br: L.nam_download(br, m["file"], path), done, "Downloading “%s” …" % m["name"])


class NAMBrowser(U.Overlay):
    """Auswahl des NAM-Modells eines Blocks (ersetzt die einfache Liste). labels: Anzeige je
    Drive-Platz 0..n-1, dahinter 'kein Modell (stumm)' = L.NAM_SILENT. on_pick(idx) setzt den Drive.
    audition (Einstellung): ein Klick setzt das Modell sofort, der Dialog bleibt offen;
    "Done"/x behaelt es, "Revert" setzt das Modell vom Oeffnen zurueck. Ohne audition wie bisher:
    Doppelklick/Apply setzt und schliesst. on_manage: Knopf "Manage models …" (oeffnet den NAMDialog)."""

    SILENT = "No model (silent)"

    def __init__(self, editor, title, labels, current, on_pick, audition=False, on_manage=None):
        super().__init__(editor, title, width=520, height=600)
        self.ed = editor
        self.closed = False
        self.labels = list(labels)
        self.on_pick = on_pick
        self.audition = audition
        self.original = current
        self.heard = None
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.fill())
        b = self.body
        tk.Label(b, text=("A click loads the model – “Done” keeps it, “Revert” goes back." if audition else
                          "Double-click applies the model."),
                 bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x", pady=(0, px(6)))
        e = U.Entry(b, textvariable=self.filter, placeholder="Search …", font=FONT_SMALL)
        e.pack(fill="x", pady=(0, px(8)))
        e.bind_entry("<Down>", lambda ev: (self.lb.focus_set(), self.step(1)))
        f = tk.Frame(b, bg=PANEL)
        f.pack(fill="both", expand=True)
        self.lb = tk.Listbox(f, activestyle="none", exportselection=False, bg=CARD, fg=TEXT, selectbackground=ACCENT,
                             selectforeground=ACCENT_TXT, bd=0, highlightthickness=0, font=FONT_MONO, width=10)
        sb = ttk.Scrollbar(f, command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        bf = tk.Frame(b, bg=PANEL)
        bf.pack(fill="x", side="bottom", pady=(px(12), 0))
        if audition:
            self.lb.bind("<<ListboxSelect>>", lambda ev: self.listen())
            self.lb.bind("<Return>", lambda ev: self.close())
            U.Btn(bf, "Done", command=self.close, kind="primary").pack(side="right")
            self.btn_revert = U.Btn(bf, "Revert", command=self.revert, kind="ghost", state="disabled")
            self.btn_revert.pack(side="right", padx=px(8))
        else:
            self.lb.bind("<Double-Button-1>", lambda ev: self.apply())
            self.lb.bind("<Return>", lambda ev: self.apply())
            U.Btn(bf, "Apply", command=self.apply, kind="primary").pack(side="right")
            U.Btn(bf, "Cancel", command=self.close, kind="ghost").pack(side="right", padx=px(8))
        if on_manage:
            U.Btn(bf, "Manage models …", command=lambda: (self.close(), on_manage()), padx=10, pady=4,
                  font=FONT_SMALL).pack(side="left")
        self.fill(select=current)
        self.bind_keys()
        self.lb.focus_set()

    def fill(self, select=None):
        if select is None:
            select = self.selected()
        q = self.filter.get().lower()
        items = list(enumerate(self.labels)) + [(L.NAM_SILENT, self.SILENT)]
        self.shown = [(i, t) for i, t in items if q in t.lower()]
        self.lb.delete(0, "end")
        for i, t in self.shown:
            self.lb.insert("end", t)
            if i == L.NAM_SILENT:
                self.lb.itemconfigure("end", fg=MUTED)
        idx = [i for i, _ in self.shown]
        if select in idx:
            self.lb.selection_set(idx.index(select))
            self.lb.see(idx.index(select))

    def selected(self):
        sel = self.lb.curselection()
        return self.shown[sel[0]][0] if sel else None

    def step(self, d):
        sel = self.lb.curselection()
        n = len(self.shown)
        if not n:
            return
        i = 0 if not sel else max(0, min(n - 1, sel[0] + d))
        self.lb.selection_clear(0, "end")
        self.lb.selection_set(i)
        self.lb.see(i)
        self.lb.event_generate("<<ListboxSelect>>")

    def listen(self):
        i = self.selected()
        if i is None or i == self.heard:
            return
        self.heard = i
        self.on_pick(i)
        self.btn_revert.configure(state="normal")

    def revert(self):
        if self.heard is not None and self.heard != self.original:
            self.on_pick(self.original)
        self.close()

    def apply(self):
        i = self.selected()
        if i is not None:
            self.on_pick(i)
            self.close()

    def cancel(self):
        self.close()

    def close(self, result=None):
        if self.closed:
            return
        self.closed = True
        self.ed.nam_browser_done(self)
        super().close(result)
