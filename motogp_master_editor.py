"""MotoGP 24 Master Editor.

  python motogp_master_editor.py                       -> web UI (opens in your browser; "web [port]")
  python motogp_master_editor.py gui                   -> old tkinter window
  python motogp_master_editor.py selftest --paks <Paks folder>      (check the pak reader on your game)
  python motogp_master_editor.py show   <mod folder> <PilotKey>
  python motogp_master_editor.py clone  <mod folder> <PilotKey> <NNN> [--dry-run]
  python motogp_master_editor.py repoint <mod folder> <PilotKey> </Game/...bikeCCC_VVV.bikeCCC_VVV>
  python motogp_master_editor.py bindings <mod folder> <PilotKey>              (every binding row of a rider)
  python motogp_master_editor.py choices <mod folder> <PilotKey> <TableName>    (assets that could replace a row)
  python motogp_master_editor.py replace <mod folder> <PilotKey> <TableName> <rider | /Game/pkg | /Game/pkg.obj>
      add  --copy asset|set  to create a missing target as a copy of the row's current asset (or its full set)
  python motogp_master_editor.py copy-look <mod folder> <PilotKey> <DonorKey> [--only helmet,gloves,...]

Files are read from <mod folder> first, then from the game's .pak files (--paks, or the folder saved by
the GUI). Everything the tool writes goes into <mod folder>; originals there are copied to
<mod folder>/_mgp_backup/<timestamp>/ before the first change.
Needs:  pip install pycryptodome   (AES for the encrypted paks)
        pip install blake3         (optional: fast chunk hashes when packing MotoGP 25 .utoc/.ucas)
"""
import argparse, json, os, sys, tempfile

import mgp_core as C

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mgp_config.json")
DEFAULT_KEY = "0xDAA05A8D0A1E1948431E91FDB2004A775B209CEDF7FEF3C9B1E1EB4579099839"


def load_cfg():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cfg(cfg):
    try:
        with open(CONFIG, "w") as f:
            json.dump(cfg, f, indent=1)
    except OSError:
        pass


def open_project(folder, paks=None, key=None, include_patch=True):
    cfg = load_cfg()
    paks = paks or cfg.get("paks_dir")
    return C.Project(folder, paks, key or cfg.get("aes_key") or DEFAULT_KEY, include_patch)


def selftest(paks, key, include_patch=True):
    import mgp_pak as K
    cfg = load_cfg()
    paks = paks or cfg.get("paks_dir")
    if not paks:
        print("give --paks <folder with the .pak files>"); return 1
    key = key or cfg.get("aes_key") or DEFAULT_KEY
    try:
        ps = K.PakSet(paks, key, include_patch=include_patch)
    except K.PakError as e:
        print("FAILED to open paks:", e); return 1
    print("pak                                            ver  files   index")
    for r in ps.readers:
        print("%-46s v%-3d %6d  %s" % (os.path.basename(r.path)[:46], r.version, len(r.files),
                                      "encrypted" if r.index_encrypted else "plain"))
    for e in ps.errors:
        print("SKIPPED:", e)
    print("total unique files:", len(ps.map))
    rc = 0
    with tempfile.TemporaryDirectory() as tmp:
        try:
            P = C.Project(tmp, paks, key, include_patch)
            print("DB       from", P.src.origin(C.DB_REL))
            import sqlite3
            n = len(sqlite3.connect(P.ensure_db()).execute("select name from sqlite_master where type='table'").fetchall())
            print("  sqlite opens, %d tables" % n)
            print("bindings from", P.src.origin(C.DT_REL + ".uasset"), "-", len(P.dt.rows), "rows")
            q = next((r for r in P.dt.rows if "uartararo" in r), next(iter(P.dt.rows)))
            print(describe(P, q))
            b = P.binding(q)
            if not (b and b["info"] and b["info"]["members"]):
                print("  FAILED: the bike set of %s was not found in the mod folder or paks" % q); rc = 1
            else:
                ok = True
                for m in b["info"]["members"]:
                    for rel in m.rels(P.src):
                        data = P.src.read(rel)
                        if rel.endswith(".uasset") and data[:4] != bytes.fromhex("c1832a9e"):
                            ok = False; print("  BAD uasset magic:", rel)
                print("  all assets of the set read and look valid" if ok else "  PROBLEMS above")
                rc = 0 if ok else 1
        except Exception as e:
            print("FAILED:", type(e).__name__, e); rc = 1
    print("SELFTEST", "OK" if rc == 0 else "FAILED")
    return rc


def describe(P, pilot):
    b = P.binding(pilot)
    if not b:
        return "No binding row for %s" % pilot
    out = ["%s -> %s" % (pilot, b["target"])]
    if b["info"]:
        ms = b["info"]["members"]
        out.append("variant %s: %d assets (%d customization/material, %d textures)" % (
            b["info"]["tag"], len(ms), sum("textures" not in m.pkg for m in ms), sum("textures" in m.pkg for m in ms)))
        for m in b["info"]["missing"]:
            out.append("  referenced, not in folder: " + m.rsplit("/", 1)[1])
    return "\n".join(out)


def cli(a):
    if a.cmd == "selftest":
        return selftest(a.paks, a.key, not a.no_patch)
    P = open_project(a.folder, a.paks, a.key, not a.no_patch)
    if a.cmd == "show":
        print(describe(P, a.pilot))
    elif a.cmd == "clone":
        plan, made, warns = P.clone_for_pilot(a.pilot, a.tag, dry_run=a.dry_run)
        for p in plan["problems"]:
            print("PROBLEM:", p)
        for n in plan["notes"]:
            print("note:", n)
        if plan["problems"]:
            return 1
        if a.dry_run:
            print("would create %d files; %s would point to variant %s" % (len(plan["jobs"]), a.pilot, a.tag))
        else:
            print("created %d files; %s now -> %s" % (len(made), a.pilot, P.dt.target(a.pilot)))
            for w in warns:
                print("WARNING:", w)
    elif a.cmd == "repoint":
        P.repoint(a.pilot, a.target)
        print(describe(P, a.pilot))
    elif a.cmd == "bindings":
        for rel, cat, target in P.pilot_bindings(a.pilot):
            print("%-9s %-44s %s" % (cat, rel.split("bindings/", 1)[-1], target))
    elif a.cmd == "replace":
        hits = [r for r in P.table_names() if r.rsplit("/", 1)[1].lower() == a.table.lower() or r.lower().endswith(a.table.lower())]
        if len(hits) != 1:
            print("table %r matches %d tables: %s" % (a.table, len(hits), ", ".join(h.rsplit("/", 1)[1] for h in hits[:6]))); return 1
        old = P.table(hits[0]).target(a.pilot)
        st = P.target_status(hits[0], a.pilot, a.target)
        warn = None
        if not st["exists"] and a.copy:
            r = P.replace_with_copy(hits[0], a.pilot, st["pkg"], a.copy)
            print("created %d files" % len(r["made"]))
            for n in r["notes"] + r["warnings"]:
                print("note:", n)
        else:
            warn = P.repoint_in(hits[0], a.pilot, a.target)
        print("%s: %s\n   was %s\n   now %s" % (hits[0].rsplit("/", 1)[1], a.pilot, old, P.table(hits[0]).target(a.pilot)))
        if warn:
            print(warn)
    elif a.cmd == "choices":
        hits = [r for r in P.table_names() if r.rsplit("/", 1)[1].lower() == a.table.lower()]
        if len(hits) != 1:
            print("unknown table", a.table); return 1
        for c in P.candidates(hits[0], a.pilot):
            print(c)
    elif a.cmd == "copy-look":
        cats = {c.strip() for c in a.only.split(",")} if a.only else None
        for rel, old, new in P.copy_look(a.pilot, a.donor, cats):
            print("%-48s -> %s" % (rel.split("bindings/", 1)[-1], new))
    return 0


# ------------------------------------------------------------------------ GUI
def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("MotoGP 24 Master Editor")
            self.geometry("1200x700")
            self.P = self.db = None
            self.table = None
            self.rowmap = {}
            self.dirty = False
            self._build()
            self.bind("<Control-s>", lambda e: self.save())
            self.protocol("WM_DELETE_WINDOW", self.on_close)

        def _build(self):
            bar = ttk.Frame(self); bar.pack(fill="x", padx=6, pady=4)
            self.cfg = load_cfg()
            ttk.Button(bar, text="Game paks…", command=self.pick_paks).pack(side="left")
            self.patch = tk.BooleanVar(value=self.cfg.get("include_patch", True))
            ttk.Checkbutton(bar, text="include *_P paks", variable=self.patch).pack(side="left", padx=4)
            ttk.Button(bar, text="Open mod folder…", command=self.open_folder).pack(side="left", padx=(8, 0))
            ttk.Button(bar, text="Save DB (Ctrl+S)", command=self.save).pack(side="left", padx=6)
            ttk.Label(bar, text="Filter:").pack(side="left", padx=(16, 2))
            self.filter = tk.StringVar(); self.filter.trace_add("write", lambda *a: self.fill())
            ttk.Entry(bar, textvariable=self.filter, width=30).pack(side="left")
            self.status = ttk.Label(bar, text="1) Game paks…  2) Open mod folder… (where your edits are written)")
            self.status.pack(side="right")
            panes = ttk.PanedWindow(self, orient="horizontal"); panes.pack(fill="both", expand=True)
            self.tlist = tk.Listbox(panes, exportselection=False, width=30)
            self.tlist.bind("<<ListboxSelect>>", lambda e: self.pick_table())
            panes.add(self.tlist, weight=0)
            right = ttk.Frame(panes); panes.add(right, weight=1)
            self.tree = ttk.Treeview(right, show="headings", selectmode="browse")
            sy = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
            sx = ttk.Scrollbar(right, orient="horizontal", command=self.tree.xview)
            self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
            sy.pack(side="right", fill="y"); sx.pack(side="bottom", fill="x")
            self.tree.pack(fill="both", expand=True)
            self.tree.bind("<Double-1>", self.edit_cell)
            self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_binding())
            self.bpanel = ttk.LabelFrame(self, text="Bindings of the selected pilot (every binding table with a row for this rider)")
            self.bpanel.pack(fill="x", padx=6, pady=4)
            side = ttk.Frame(self.bpanel); side.pack(side="right", fill="y", padx=4, pady=4)
            ttk.Button(side, text="Replace selected…", command=self.repoint).pack(fill="x", pady=2)
            ttk.Button(side, text="Copy look from rider…", command=self.copy_look).pack(fill="x", pady=2)
            ttk.Button(side, text="Clone bike set…", command=self.clone).pack(fill="x", pady=2)
            self.gtree = ttk.Treeview(self.bpanel, columns=("cat", "table", "target"), show="headings", height=7)
            for c, w in (("cat", 80), ("table", 260), ("target", 700)):
                self.gtree.heading(c, text=c); self.gtree.column(c, width=w, stretch=(c == "target"))
            self.gtree.pack(side="left", fill="x", expand=True, padx=4, pady=4)
            self.grel = {}

        # ---- project
        def pick_paks(self):
            path = filedialog.askdirectory(title="Game's Paks folder (…/MotoGP24/motogp24/Content/Paks)")
            if path:
                self.cfg.update(paks_dir=path, aes_key=self.cfg.get("aes_key") or DEFAULT_KEY)
                save_cfg(self.cfg)
                self.status.config(text="paks: " + path)

        def open_folder(self):
            path = filedialog.askdirectory(title="Mod folder (edits are written here; may be empty)")
            if not path:
                return
            self.cfg["include_patch"] = bool(self.patch.get()); save_cfg(self.cfg)
            try:
                self.status.config(text="reading paks…"); self.update_idletasks()
                self.P = open_project(path, include_patch=bool(self.patch.get()))
                self.db = C.Db(self.P)
            except Exception as e:
                messagebox.showerror("Cannot open", str(e)); return
            if self.P.paks and self.P.paks.errors:
                messagebox.showwarning("Some paks were skipped", "\n".join(self.P.paks.errors[:8]))
            self.tlist.delete(0, "end")
            for t in self.db.tables():
                self.tlist.insert("end", t)
            npk = len(self.P.paks.readers) if self.P.paks else 0
            self.status.config(text="%s   (%d paks)" % (self.P.root, npk))
            if "Pilots" in self.db.tables():
                i = self.db.tables().index("Pilots"); self.tlist.selection_set(i); self.pick_table()

        def pick_table(self):
            sel = self.tlist.curselection()
            if not sel:
                return
            self.table = self.tlist.get(sel[0])
            cols = [c for c, _ in self.db.columns(self.table)]
            self.tree["columns"] = cols
            for c in cols:
                self.tree.heading(c, text=c)
                self.tree.column(c, width=max(80, min(220, 9 * len(c) + 20)), stretch=False)
            self.fill()

        def fill(self):
            if not self.table:
                return
            self.tree.delete(*self.tree.get_children())
            self.rowmap = {}
            q = self.filter.get().lower()
            for r in self.db.rows(self.table):
                vals = ["" if v is None else v for v in r[1:]]
                if q and q not in " ".join(map(str, vals)).lower():
                    continue
                iid = self.tree.insert("", "end", values=vals)
                self.rowmap[iid] = r[0]

        # ---- cell editing
        def edit_cell(self, ev):
            if self.tree.identify_region(ev.x, ev.y) != "cell":
                return
            iid, col = self.tree.identify_row(ev.y), self.tree.identify_column(ev.x)
            if not iid:
                return
            cidx = int(col[1:]) - 1
            cname = self.tree["columns"][cidx]
            if self.table == "Pilots" and cname == "Key":
                messagebox.showinfo("Locked", "Pilots.Key is the link to the bindings table and to other DB tables.\n"
                                    "Renaming it is not supported yet."); return
            x, y, w, h = self.tree.bbox(iid, col)
            old = self.tree.item(iid, "values")[cidx]
            e = ttk.Entry(self.tree); e.insert(0, old); e.select_range(0, "end")
            e.place(x=x, y=y, width=w, height=h); e.focus()

            def done(commit):
                if commit:
                    try:
                        cur = [r for r in self.db.rows(self.table) if r[0] == self.rowmap[iid]][0][cidx + 1]
                        val = self.db.coerce(self.table, cname, e.get(), cur)
                        self.db.update(self.table, self.rowmap[iid], cname, val)
                        vals = list(self.tree.item(iid, "values")); vals[cidx] = e.get()
                        self.tree.item(iid, values=vals)
                        self.dirty = True
                        self.status.config(text="unsaved DB changes")
                    except Exception as ex:
                        messagebox.showerror("Edit failed", str(ex))
                e.destroy()
            e.bind("<Return>", lambda _: done(True))
            e.bind("<Escape>", lambda _: done(False))
            e.bind("<FocusOut>", lambda _: done(True))

        def save(self):
            if self.db:
                self.db.commit(); self.dirty = False
                self.status.config(text="DB saved (backup in _mgp_backup)")

        # ---- bindings
        def pilot(self):
            if self.table != "Pilots":
                return None
            sel = self.tree.selection()
            return self.tree.item(sel[0], "values")[0] if sel else None

        def show_binding(self):
            self.gtree.delete(*self.gtree.get_children()); self.grel = {}
            p = self.pilot()
            if not p or not self.P:
                return
            try:
                for rel, cat, target in self.P.pilot_bindings(p):
                    iid = self.gtree.insert("", "end", values=(cat, rel.split("bindings/", 1)[-1], target))
                    self.grel[iid] = rel
            except Exception as ex:
                messagebox.showerror("Cannot read bindings", str(ex))

        def clone(self):
            p = self.pilot()
            if not p:
                return
            b = self.P.binding(p)
            tag = simpledialog.askstring("Clone full set", "New variant number (3 digits, must not exist in the game).\n"
                                         "Suggested:", initialvalue=self.P.suggest_tag(b["target"]), parent=self)
            if not tag:
                return
            try:
                plan, _, _ = self.P.clone_for_pilot(p, tag, dry_run=True)
                if plan["problems"]:
                    messagebox.showerror("Cannot clone", "\n".join(plan["problems"])); return
                msg = "Create %d files for variant %s and point %s to it?" % (len(plan["jobs"]), tag, p)
                if plan["notes"]:
                    msg += "\n\nNote: " + "\n".join(plan["notes"])
                if not messagebox.askokcancel("Clone full set", msg):
                    return
                _, made, warns = self.P.clone_for_pilot(p, tag)
                messagebox.showinfo("Done", "Created %d files.%s" % (len(made), ("\n\n" + "\n".join(warns)) if warns else ""))
            except Exception as ex:
                messagebox.showerror("Clone failed", str(ex))
            self.show_binding()

        def pick(self, title, items, initial=""):
            """Dialog: type to filter a list of assets; or type a rider name / full /Game path and press OK."""
            win = tk.Toplevel(self); win.title(title); win.geometry("900x520"); win.transient(self); win.grab_set()
            ttk.Label(win, text="Filter the list, pick an asset (double-click) - or type another rider's name / a full /Game/... path:").pack(anchor="w", padx=8, pady=4)
            var = tk.StringVar(value=initial)
            ttk.Entry(win, textvariable=var).pack(fill="x", padx=8)
            lb = tk.Listbox(win, exportselection=False); lb.pack(fill="both", expand=True, padx=8, pady=6)
            shown, result = [], {"v": None}

            def refill(*_):
                q = var.get().lower(); lb.delete(0, "end"); shown.clear()
                for it in items:
                    if q in it.lower():
                        shown.append(it); lb.insert("end", it.replace("/Game/assets/graphics/", ".../"))
            var.trace_add("write", refill); refill()

            def ok(_=None):
                sel = lb.curselection()
                result["v"] = shown[sel[0]] if sel else var.get().strip()
                win.destroy()
            lb.bind("<Double-1>", ok)
            ttk.Button(win, text="OK", command=ok).pack(side="right", padx=8, pady=6)
            ttk.Button(win, text="Cancel", command=win.destroy).pack(side="right", pady=6)
            self.wait_window(win)
            return result["v"]

        def ask_choice(self, title, text, buttons):
            win = tk.Toplevel(self); win.title(title); win.transient(self); win.grab_set()
            ttk.Label(win, text=text, justify="left", wraplength=560).pack(padx=14, pady=12)
            out = {"v": None}
            bar = ttk.Frame(win); bar.pack(pady=(0, 12))
            for b_ in buttons:
                def pick_(v=b_):
                    out["v"] = v; win.destroy()
                ttk.Button(bar, text=b_, command=pick_).pack(side="left", padx=4)
            self.wait_window(win)
            return out["v"]

        def repoint(self):
            p, sel = self.pilot(), self.gtree.selection()
            if not p or not sel:
                messagebox.showinfo("Replace", "Select a binding row in the list first."); return
            rel = self.grel[sel[0]]
            try:
                items = self.P.candidates(rel, p)
            except Exception:
                items = []
            new = self.pick("Replace entry: " + rel.rsplit("/", 1)[1], items)
            if not new:
                return
            try:
                st = self.P.target_status(rel, p, new)
                if st["exists"]:
                    warn = self.P.repoint_in(rel, p, new)
                    if warn:
                        messagebox.showwarning("Replaced, but check this", warn)
                else:
                    cur = self.P.table(rel).target(p).partition(".")[0].rsplit("/", 1)[1]
                    choice = self.ask_choice(
                        "Asset does not exist",
                        "%s is not in your mod folder or the game paks.\n\nCreate it as a copy of the current entry (%s)?\n\n"
                        "- Copy this asset only: the copy keeps using the original's materials and textures.\n"
                        "- Copy full set: also copies the variant's materials and textures (needs a same-length variant number, e.g. helmet_109 -> helmet_900).\n"
                        "- Point anyway: just change the entry; the game will only load it if the asset exists." % (st["pkg"].rsplit("/", 1)[1], cur),
                        ["Copy this asset only", "Copy full set", "Point anyway", "Cancel"])
                    if choice in ("Copy this asset only", "Copy full set"):
                        r = self.P.replace_with_copy(rel, p, st["pkg"], "asset" if choice.startswith("Copy this") else "set")
                        extra = "\n\n".join(r["notes"] + r["warnings"])
                        messagebox.showinfo("Done", "Created %d files and pointed %s at the copy.%s" % (len(r["made"]), p, ("\n\n" + extra) if extra else ""))
                    elif choice == "Point anyway":
                        warn = self.P.repoint_in(rel, p, new)
                        if warn:
                            messagebox.showwarning("Replaced, but check this", warn)
            except Exception as ex:
                messagebox.showerror("Replace failed", str(ex))
            self.show_binding()

        def copy_look(self):
            p = self.pilot()
            if not p:
                return
            donor = simpledialog.askstring("Copy look", "Copy from which rider? (exact Pilots.Key, e.g. MotoGP_Alex-Rins)", parent=self)
            if not donor:
                return
            cats = simpledialog.askstring("Copy look", "Categories (helmet, suit, gloves, boots, buttpatch, face, bike):",
                                          initialvalue="helmet,suit,gloves,boots,buttpatch", parent=self)
            if not cats:
                return
            try:
                ch = self.P.copy_look(p, donor.strip(), {c.strip() for c in cats.split(",")})
                messagebox.showinfo("Done", "%d binding rows changed." % len(ch))
            except Exception as ex:
                messagebox.showerror("Copy failed", str(ex))
            self.show_binding()

        def on_close(self):
            if self.dirty and not messagebox.askyesno("Unsaved changes", "Discard unsaved DB changes?"):
                return
            self.destroy()

    App().mainloop()


def main():
    if len(sys.argv) == 1 or sys.argv[1] == "web":
        import webui
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
        return webui.serve(load_cfg, save_cfg, DEFAULT_KEY, port)
    if sys.argv[1] == "gui":
        return gui()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    def common(s):
        s.add_argument("--paks", help="folder with the game's .pak files")
        s.add_argument("--key", help="AES key (hex)")
        s.add_argument("--no-patch", action="store_true", help="ignore *_P.pak patch/mod paks")
    common(sub.add_parser("selftest"))
    for name in ("show", "clone", "repoint", "bindings", "copy-look", "replace", "choices"):
        s = sub.add_parser(name); common(s); s.add_argument("folder"); s.add_argument("pilot")
        if name in ("replace", "choices"):
            s.add_argument("table", help="e.g. DT_HELMET_Official")
        if name == "replace":
            s.add_argument("target", help="another rider's name, a /Game/...package, or a /Game/...pkg.obj path")
            s.add_argument("--copy", choices=("asset", "set"), help="if the target does not exist, create it as a copy of the row's current asset (this asset only, or the full set)")
        if name == "copy-look":
            s.add_argument("donor"); s.add_argument("--only", help="comma list: helmet,suit,gloves,boots,buttpatch,face,bike")
        if name == "clone":
            s.add_argument("tag"); s.add_argument("--dry-run", action="store_true")
        if name == "repoint":
            s.add_argument("target")
    try:
        return cli(ap.parse_args())
    except C.MgpError as e:
        print("ERROR:", e); return 1


if __name__ == "__main__":
    sys.exit(main())
