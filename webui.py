"""Web UI for the MotoGP 24 Master Editor: a small local server (standard library only).

  python motogp_master_editor.py web            -> opens http://127.0.0.1:8765 in your browser
Only listens on 127.0.0.1; every request must carry a per-run token, so other websites cannot drive it.
"""
import json, os, re, secrets, shutil, sqlite3, struct, subprocess, sys, threading, time, traceback, webbrowser
from struct import error as struct_error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import mgp_core as C
import uprops as U
import audioport as AP

VERSION = "v102"
import mgp_pakwrite as PW
import mgp_locres as LR
import hudskin as HS
import projfile as PJ
import fontswap as FS

HERE = os.path.dirname(os.path.abspath(__file__))
PER_GAME = ("mod_folder", "paks_dir", "include_patch", "game")       # Setup fields each game keeps for itself


def gk(key, game):
    """Config key of a per-game setting: MotoGP 24 keeps the old names, others get a suffix ('paks_dir_gp25')."""
    return key if game == "gp24" else key + "_" + game


def migrate_cfg(cfg):
    """Before v100 all games shared one set of paths; a config last used for GP25 holds GP25's paths there."""
    g = cfg.get("game_id", "gp24")
    if g != "gp24" and gk("mod_folder", g) not in cfg:
        for k in PER_GAME:
            if k in cfg and k != "game":
                cfg[gk(k, g)] = cfg.pop(k)
    return cfg


GAME_KEYS = {"gp25": "0x5B209CEDF7FEF3C9B1E1EB4579099839DAA05A8D0A1E1948431E91FDB2004A77"}   # gp24's is default_key


class State:
    def __init__(self, load_cfg, save_cfg, default_key):
        self.load_cfg, self.save_cfg, self.default_key = load_cfg, save_cfg, default_key
        self.P = None
        self.db = None
        self.lock = threading.RLock()
        self.token = secrets.token_hex(16)

    def open(self, folder, paks, key, include_patch, game="gp24"):
        if not folder or not os.path.isdir(folder):
            raise C.MgpError("mod folder does not exist: %r (create an empty folder first)" % folder)
        if paks and not os.path.isdir(paks):
            raise C.MgpError("Paks folder does not exist: %r" % paks)
        cfg = self.load_cfg()
        kname = "aes_key" if game == "gp24" else "aes_key_" + game      # each game keeps its own saved key
        use = key or cfg.get(kname) or GAME_KEYS.get(game) or self.default_key
        P = C.Project(folder, paks or None, use, include_patch, staged=True, game=game)
        self.close_db()
        self.P = P
        cfg.update({gk("mod_folder", game): folder, gk("paks_dir", game): paks or "", gk("include_patch", game): include_patch,
                    "game_id": game})
        if key:
            cfg[kname] = key
        self.save_cfg(cfg)

    def close_db(self):
        if self.db:
            try:
                self.db.con.commit(); self.db.con.close()
            except Exception:
                pass
            self.db = None

    def need(self):
        if not self.P:
            raise C.MgpError("open a project first (Setup tab)")
        return self.P

    def get_db(self):
        P = self.need()
        if not self.db:
            self.db = C.Db(P)
        return self.db


def tname(rel):
    return rel.rsplit("/", 1)[1]


def similar(P, pkg):
    """Existing assets next to a missing one whose name differs only in the trailing number
    (bike_carbon_103_001 -> bike_carbon_103_004)."""
    import re
    folder, base = pkg.rsplit("/", 1)
    prefix = re.sub(r"\d+$", "", base)
    if not prefix or prefix == base and not base[-1:].isdigit():
        return []
    try:
        found = P.src.find(C.game_to_rel(folder), ".uasset")
    except Exception:
        return []
    out = []
    for f in found:
        p = "/Game/" + f[len("Content/"):-len(".uasset")]
        if p.rsplit("/", 1)[0] == folder and p != pkg and p.rsplit("/", 1)[1].startswith(prefix) \
                and re.fullmatch(r"\d+", p.rsplit("/", 1)[1][len(prefix):] or "x"):
            out.append(p)
    return sorted(out)[:6]


def is_game(target):
    """A row can point at nothing ('None'); only /Game/... targets are real assets."""
    return isinstance(target, str) and target.startswith("/Game/")


def need_key(t, key):
    if not key or key not in t.rows:
        raise C.MgpError("no entry selected (or it is not in this table) - click an entry on the left, then try again")


def bike_rel(P, group):
    name = C.BIKE_TABLE.get(group)
    return next((r for r in P.table_names() if tname(r) == name), None) if name else None


EDIT_KINDS = {"SkeletalMesh": "skeletal mesh", "Skeleton": "skeleton", "PhysicsAsset": "physics asset",
              "MaterialInstanceConstant": "material instance", "MaterialInstance": "material instance"}
KIND_ORDER = ["asset", "skeletal mesh", "skeleton", "physics asset", "material instance"]


def asset_members(P, pkg, kinds=None, depth=3):
    kinds = kinds or EDIT_KINDS
    found = {pkg: dict(pkg=pkg, main=True, kind="asset")}
    queue = [(pkg, 0)]
    while queue:
        cur, d = queue.pop(0)
        stem = C.game_to_rel(cur)
        if d >= depth or not P.src.exists(stem + ".uasset"):
            continue
        try:
            a = U.Asset(P.src.read(stem + ".uasset"), b"")
        except (C.MgpError, ValueError, struct_error):
            continue
        for i, imp in enumerate(a.imports):
            if imp["cls"] in kinds:
                mp, _ = a.object_ref(-(i + 1))
                if mp and mp.startswith("/Game/") and mp not in found:
                    found[mp] = dict(pkg=mp, main=False, kind=kinds[imp["cls"]])
                    queue.append((mp, d + 1))
    out = []
    for m in found.values():
        st = C.game_to_rel(m["pkg"])
        m["origin"] = P.src.origin(st + ".uasset")
        m["exists"] = m["origin"] != "missing"
        m["shared"] = "shared" in m["pkg"].lower()
        out.append(m)
    out.sort(key=lambda m: (m["shared"], KIND_ORDER.index(m["kind"]) if m["kind"] in KIND_ORDER else 9, m["pkg"]))
    return out


CAT_PREFIX = {"cat001": "MotoGP_", "cat002": "Moto2_", "cat003": "Moto3_"}


def in_cat(cat, key, target=""):
    if not cat:
        return True
    return key.startswith(CAT_PREFIX.get(cat, "\0")) or ("/%s/" % cat) in target


def _pick_result(S, kind, path):
    path = os.path.normpath(path) if path else ""
    if kind != "asset" or not path:
        return dict(path=path)
    root = os.path.normpath(S.need().real_root)
    rel = os.path.relpath(path, root).replace(os.sep, "/") if path.lower().startswith(root.lower()) else ""
    if not rel.lower().startswith("content/") or not rel.lower().endswith(".uasset"):
        raise C.MgpError("choose a .uasset inside your mod folder's Content folder")
    return dict(path=path, pkg="/Game/" + rel[len("Content/"):-len(".uasset")])


def _pick_powershell(kind, start):
    """Windows fallback when Python has no tkinter: the system folder/file dialogs through PowerShell."""
    q = lambda s: "'" + s.replace("'", "''") + "'"
    if kind in ("file", "asset", "game", "font"):
        flt = ("Unreal assets (*.uasset)|*.uasset" if kind == "asset" else
               "Game or shortcut (*.exe;*.lnk;*.url)|*.exe;*.lnk;*.url|All files (*.*)|*.*" if kind == "game" else
               "Fonts (*.ttf;*.otf;*.ufont)|*.ttf;*.otf;*.ufont|All files (*.*)|*.*" if kind == "font" else
               "Programs (*.exe)|*.exe|All files (*.*)|*.*")
        body = ("$d = New-Object System.Windows.Forms.OpenFileDialog; $d.DereferenceLinks = $false; $d.InitialDirectory = %s; "
                "$d.Filter = '" + flt + "'; "
                "if ($d.ShowDialog() -eq 'OK') { $d.FileName }" % q(start))
    else:
        body = ("$d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.SelectedPath = %s; "
                "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }" % q(start))
    script = "Add-Type -AssemblyName System.Windows.Forms; " + body
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise C.MgpError("could not open the chooser (%s) - paste the path instead" % e)
    return out.stdout.strip()


def gp24_only(P, what):
    if P.game != "gp24":
        raise C.MgpError("%s is not supported for MotoGP 25 yet" % what)


def make_api(S):
    def state(q, b):
        cfg = S.load_cfg()
        g = S.P.game if S.P else cfg.get("game_id", "gp24")
        games = {x: dict(mod_folder=cfg.get(gk("mod_folder", x), ""), paks_dir=cfg.get(gk("paks_dir", x), ""),
                         include_patch=cfg.get(gk("include_patch", x), True), game=cfg.get(gk("game", x), "")) for x in C.GAMES}
        return dict(version=VERSION, uassetgui=cfg.get("uassetgui", ""), open=bool(S.P), games=games, **games[g],
                    has_key=bool(cfg.get("aes_key")), game_id=g,
                    paks=bool(S.P and S.P.paks), root=S.P.root if S.P else "")

    def changes(q=None, b=None):
        if not S.P:
            return dict(files=[])
        return dict(files=S.P.staged_files())

    def save(q, b):
        j = getattr(S, "pakjob", None) or {}
        if j.get("running") and j.get("title") in ("Packing", "Importing"):
            raise C.MgpError("a background task (%s) is running - wait for it to finish" % j["title"].lower())
        P = S.need()
        S.close_db()
        files = P.save_staged()
        return dict(saved=len(files), files=files, files_now=[])

    def discard(q, b):
        j = getattr(S, "pakjob", None) or {}
        if j.get("running") and j.get("title") in ("Packing", "Importing"):
            raise C.MgpError("a background task (%s) is running - wait for it to finish" % j["title"].lower())
        P = S.need()
        S.close_db()
        P.clear_staging()
        return dict(files=[])

    def quit_(q, b):
        n = 0
        if S.P:
            S.close_db()
            if b.get("save"):
                n = len(S.P.save_staged())
            else:
                S.P.clear_staging()
        threading.Timer(0.3, S.on_quit).start()
        return dict(saved=n)

    def _job_start(title, work):
        """Run work(log) on a background thread; progress goes to the log shown by /api/pak/status."""
        job = getattr(S, "pakjob", None)
        if job and job["running"]:
            raise C.MgpError("another task (%s) is still running" % job["title"].lower())
        job = S.pakjob = dict(running=True, title=title, lines=[], result=None, error=None)

        def run():
            try:
                job["result"] = work(job["lines"].append)
            except C.MgpError as e:
                job["error"] = str(e)
                job["lines"].append("ERROR: " + job["error"])
            except Exception as e:
                job["error"] = "%s: %s" % (type(e).__name__, e)
                job["lines"].append("ERROR: " + job["error"])
            finally:
                job["running"] = False
        threading.Thread(target=run, daemon=True).start()

    def pak_mod(q, b):
        """Pack the mod folder's Content into a *_P.pak."""
        P = S.need()
        if P.staged_files():
            raise C.MgpError("you have unsaved changes - press Save first, so they are in the pak")
        name = (b.get("name") or "").strip() or "MyMod"
        name = os.path.basename(name)
        if name.lower().endswith(".pak"):
            name = name[:-4]
        if not name.lower().endswith("_p"):
            name += "_P"
        out = (b.get("folder") or "").strip().strip('"') or os.path.join(P.real_root, "_mgp_pak")
        os.makedirs(out, exist_ok=True)
        if not os.path.isdir(out):
            raise C.MgpError("output folder does not exist: %r" % out)
        files = PW.collect(P.real_root, P.project)
        zen = []
        if P.game != "gp24":                         # zen assets load only from a .utoc/.ucas next to the .pak
            zen = [f for f in files if f[0].lower().endswith((".uasset", ".ubulk", ".umap", ".uptnl"))]
            files = [f for f in files if f not in zen]
            other = [n for n, _ in zen if not n.lower().endswith((".uasset", ".ubulk")) or n.lower().endswith(".m.ubulk")]
            if other:
                raise C.MgpError("MotoGP 25: only .uasset and .ubulk files can be packed so far, not: " + ", ".join(o.rsplit("/", 1)[-1] for o in other[:5]))
            stems = {n.lower()[:-7] for n, _ in zen if n.lower().endswith(".uasset")}
            lone = [n for n, _ in zen if n.lower().endswith(".ubulk") and n.lower()[:-6] not in stems]
            if lone:
                raise C.MgpError("a .ubulk needs its .uasset next to it in the mod folder: " + ", ".join(o.rsplit("/", 1)[-1] for o in lone[:5]))
        if not files and not zen:
            raise C.MgpError("the mod folder has no Content folder with files in it")
        dest = os.path.join(out, name + ".pak")
        if os.path.exists(dest) and not b.get("overwrite"):
            return dict(exists=True, path=dest)
        def work(log):
            if zen:
                return _pack_zen(P, dest, files, zen, log)
            if not b.get("force") and P.paks and P.game == "gp24":
                log("Crash check before packing...")
                block, warn, n = _crash_scan(P, log)
                if block:
                    return dict(blocked=block, warn=warn, checked=n,
                                summary="Not packed: %d asset(s) would crash the game" % len(block))
            try:
                n, size = PW.write_pak(dest, files, log)
            except PermissionError:
                raise C.MgpError("cannot write %s - is the game running or the file in use? Close it and try again" % dest)
            except Exception:
                try:
                    os.remove(dest + ".tmp")
                except OSError:
                    pass
                raise
            return dict(path=dest, files=n, bytes=size, summary="%s (%d files, %.1f MB)" % (dest, n, size / 1048576))
        _job_start("Packing", work)
        return dict(started=True, path=dest, files=len(files) + len(zen))

    def _pack_zen(P, dest, files, zen, log):
        """MotoGP 25: zen .uassets into <name>.utoc/.ucas (uncompressed, like retoc), other files into <name>.pak
        (an empty one when there are none: the game mounts the .utoc through the .pak)."""
        import mgp_iostore as IO, mgp_zen as Z
        pk, bulk = [], []
        for name, path in zen:
            data = open(path, "rb").read()
            if name.lower().endswith(".ubulk"):
                bulk.append((name, data, "/Game/" + name.split("/", 2)[2][:-len(".ubulk")]))
                continue
            try:
                z = Z.ZenPackage(data)
            except Z.ZenError as e:
                raise C.MgpError("%s is not a MotoGP 25 (zen) asset: %s" % (name.rsplit("/", 1)[-1], e))
            game = "/Game/" + name.split("/", 2)[2][:-len(".uasset")]          # motogp25/Content/x -> /Game/x
            pk.append((name, data, game, z.imported_package_ids()))
        utoc = dest[:-4] + ".utoc"
        log("Writing %d asset(s) -> %s (+ .ucas)" % (len(pk), utoc))
        try:
            IO.write_container(utoc, pk, log=log, bulk=bulk)
            if files:
                n, size = PW.write_pak(dest, files, log)
            else:
                PW.write_empty_pak(dest); n = 0
        except PermissionError:
            raise C.MgpError("cannot write %s - is the game running or the file in use? Close it and try again" % dest)
        total = sum(os.path.getsize(dest[:-4] + e) for e in (".pak", ".utoc", ".ucas"))
        return dict(path=dest, files=n + len(pk) + len(bulk), bytes=total,
                    summary="%s + .utoc/.ucas (%d assets, %d .ubulk, %d other files, %.1f MB)" % (dest, len(pk), len(bulk), n, total / 1048576))

    def pak_status(q, b):
        job = getattr(S, "pakjob", None)
        if not job:
            return dict(none=True)
        frm = int((q.get("from") or ["0"])[0])
        return dict(running=job["running"], lines=job["lines"][frm:], next=len(job["lines"]), result=job["result"], error=job["error"], title=job["title"])

    def _loc_open(rel):
        P = S.need()
        if not rel.lower().endswith(".locres") or not P.src.exists(rel):
            raise C.MgpError("localization file not found: %r" % rel)
        data = P.src.read(rel)
        try:
            L = LR.Locres(data)
            if L.to_bytes() != data:
                raise LR.LocresError("this file's layout is not byte-exact when rewritten, so editing it is disabled to avoid corrupting it")
        except LR.LocresError as e:
            raise C.MgpError("%s: %s" % (rel, e))
        return P, L

    def loc_files(q, b):
        P = S.need()
        return dict(files=[dict(rel=r, origin=P.src.origin(r)) for r in P.src.find("Content", ".locres")])

    def loc_entries(q, b):
        P, L = _loc_open((q.get("rel") or [""])[0])
        text = (q.get("q") or [""])[0].strip().lower()
        offset = int((q.get("offset") or ["0"])[0])
        limit = min(int((q.get("limit") or ["200"])[0]), 500)
        rows = [dict(ns=n, key=k, text=t) for _, _, n, k, t in L.entries()
                if not text or text in n.lower() or text in k.lower() or text in t.lower()]
        return dict(total=len(rows), all=L.count(), rows=rows[offset:offset + limit], version=L.version)

    def loc_set(q, b):
        P, L = _loc_open(b.get("rel", ""))
        changed = 0
        for e in b.get("edits") or []:
            changed += bool(L.set_text(e["ns"], e["key"], e["text"]))
        if changed:
            dst = P.src.loose(b["rel"])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(L.to_bytes())
        return dict(changed=changed)

    _bcache = {}

    def _files(P, refresh=False):
        gen = P.paks.gen if P.paks else 0
        if refresh or _bcache.get("p") is not P or _bcache.get("gen") != gen:
            _bcache["p"], _bcache["gen"], _bcache["files"] = P, gen, P.src.find("Content", "")
        return _bcache["files"]

    def _scope_files(P, scope, refresh):
        if scope == "pak":
            return sorted(P.paks.find("Content", "")) if P.paks else []
        if scope == "mod":
            out = set()
            for root in (P.real_root, P.root):
                base = os.path.join(root, "Content")
                for d, _, fs in os.walk(base):
                    for f in fs:
                        out.add(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))
            return sorted(out)
        return _files(P, refresh)

    # ---- number projectors (ProjectorCustom/ProjectorOfficial... data assets)
    def _proj_open(P, pkg):
        rel = C.game_to_rel(C.normalize_target(pkg)) + ".uasset"
        ue = rel[:-7] + ".uexp"
        zen = P.game != "gp24"                                  # MotoGP 25: one zen .uasset, no .uexp
        if not P.src.exists(rel) or not (zen or P.src.exists(ue)):
            raise C.MgpError("projector file not found: %s" % pkg)
        try:
            a, projs = PJ.parse(P.src.read(rel), None if zen else P.src.read(ue))
        except ValueError as e:
            raise C.MgpError("%s: %s" % (rel.rsplit("/", 1)[-1], e))
        return rel, a, projs

    def _rotator(q):
        """UE quat (x,y,z,w) -> (pitch, yaw, roll) in degrees, as Unreal/FModel show it."""
        return [round(v, 3) + 0.0 for v in PJ.quat_to_rotator(q)]

    def _projector_tables(P, key, group):
        """Rows of the DT_NumbersProjectors* binding tables for `key`; riders have none, so their team's rows
        (Pilots.Teams_Key in the game database). Official/teams: the non-custom table first, custom: the custom one."""
        tabs = [r for r in P.table_names() if "numbersprojector" in tname(r).lower()]
        keys = [(key, "")]
        try:
            row = S.get_db().con.execute("select Teams_Key from Pilots where Key=?", (key,)).fetchone()
            if row and row[0] and row[0] != key:
                keys.append((row[0], " (team %s)" % row[0]))
        except Exception:
            pass
        out = []
        for k, note in keys:
            for r in tabs:
                try:
                    t = P.table(r)
                except Exception:
                    continue
                if k in t.rows and is_game(t.target(k)):
                    out.append(dict(pkg=t.target(k).partition(".")[0], how="%s row %s%s" % (tname(r), k, note)))
            if out:
                break
        want_custom = group == "custom"
        out.sort(key=lambda f: ("custom" in f["how"].split(" ", 1)[0].lower()) != want_custom)
        return out

    def _rider_projectors(P, key, group):
        """Projector files of a rider/team entry: [dict(pkg, how)]. First the DT_NumbersProjectors* tables (by key,
        else by the rider's team); then projector packages the entry's assets reference; then the chassis/variant naming guess."""
        rel = bike_rel(P, group or "official")
        t = P.table(rel) if rel else None
        obj = t.target(key) if t and key in t.rows and is_game(t.target(key)) else ""
        pkg = obj.partition(".")[0]
        pkgs = [pkg] if pkg else []
        if obj:
            try:
                pkgs += [m.pkg for m in C.resolve_set(P.src, obj)["members"]]
            except C.MgpError:
                pass
        for _r, _c, tgt in P.pilot_bindings(key, group):        # every customization_data the entry points at
            if is_game(tgt):
                pkgs.append(tgt.partition(".")[0])
        found, checked = _projector_tables(P, key, group), []
        for cur in ([] if found else dict.fromkeys(pkgs)):
            r = C.game_to_rel(cur) + ".uasset"
            if not P.src.exists(r):
                continue
            checked.append(cur.rsplit("/", 1)[-1])
            try:
                if P.game != "gp24":
                    import mgp_zen
                    z = mgp_zen.ZenPackage(P.src.read(r))
                    names = z.names + z.imported_package_names()
                else:
                    names = C.UAsset(P.src.read(r)).texts()
            except Exception:
                continue
            for n in names:
                n = n.partition(".")[0].partition(":")[0]             # soft paths are '/Game/x/Name.Name'
                if n.startswith("/Game/") and "projector" in n.rsplit("/", 1)[-1].lower() \
                        and n not in [f["pkg"] for f in found] and P.src.exists(C.game_to_rel(n) + ".uasset"):
                    found.append(dict(pkg=n, how="used by " + cur.rsplit("/", 1)[-1]))
        skipped = []

        def real(fs):                                           # keep only real projector data (TaggedProjectors)
            out = []
            for f in fs:
                try:
                    _proj_open(P, f["pkg"])
                    out.append(f)
                except Exception as e:
                    skipped.append("%s (%s)" % (f["pkg"].rsplit("/", 1)[-1], str(e)[:60]))
            return out
        found = real(found)
        m = re.search(r"^(.*/chassis\d+)/", pkg) if pkg else None
        v = re.search(r"_(\d+)$", pkg.rsplit("/", 1)[-1]) if pkg else None
        if not found and m and v:
            # naming the game uses: <chassis>/customization_data/projectorCCC_VVV (official), ProjectorCustomCCC_VVV (custom)
            folder, var = m.group(1) + "/customization_data", int(v.group(1))
            guess = []
            for r in P.src.find(C.game_to_rel(folder), ".uasset"):
                b = r.rsplit("/", 1)[-1][:-7]
                mv = re.search(r"_(\d+)$", b)
                if "projector" in b.lower() and mv and int(mv.group(1)) == var:
                    guess.append(dict(pkg=folder + "/" + b, how="guessed: same chassis and variant %s as %s" % (v.group(1), pkg.rsplit("/", 1)[-1])))
            want_custom = group == "custom"
            guess.sort(key=lambda f: ("custom" in f["pkg"].rsplit("/", 1)[-1].lower()) != want_custom)
            found = real(guess)
        if not pkgs and not found:
            return [], "this entry has no bindings"
        where = " (bike: %s)" % pkg if pkg else " (no bike row)"
        if not found and skipped:
            return [], "found only non-projector files: " + "; ".join(skipped) + where
        return found, "" if found else "no projector file found%s; checked %d asset(s): %s" % (where, len(checked), ", ".join(checked[:12]) + (" ..." if len(checked) > 12 else ""))

    def _number_textures(P, key):
        """[dict(table, asset, textures)]: the entry's rows in DT_Numbers_* (not the projector tables) and the
        Texture2D packages each number asset points at."""
        out = []
        for r in P.table_names():
            n = tname(r).lower()
            if not n.startswith("dt_numbers_") or "projector" in n:
                continue
            try:
                t = P.table(r)
            except Exception:
                continue
            if key not in t.rows or not is_game(t.target(key)):
                continue
            pkg = t.target(key).partition(".")[0]
            tex, rel = [], C.game_to_rel(pkg) + ".uasset"
            try:
                if P.game != "gp24":                              # zen: the packages it imports (guess: its textures)
                    import mgp_zen
                    tex = [n for n in mgp_zen.ZenPackage(P.src.read(rel)).imported_package_names() if "/DataSources/" not in n] or [pkg]
                    out.append(dict(table=tname(r), asset=pkg, textures=tex))
                    continue
                a = U.Asset(P.src.read(rel), b"")
                if any(e["cls"] == "Texture2D" for e in a.exports):
                    tex = [pkg]                                   # the row points straight at a texture
                else:
                    tex = sorted({a.object_ref(-(i + 1))[0] for i, im in enumerate(a.imports) if im["cls"] == "Texture2D"} - {""})
            except Exception as e:
                tex = ["(could not read %s: %s)" % (pkg.rsplit("/", 1)[-1], str(e)[:60])]
            out.append(dict(table=tname(r), asset=pkg, textures=tex))
        return out

    def proj_rider(q, b):
        P = S.need()
        key, group = q["key"][0], (q.get("group") or ["official"])[0]
        found, why = _rider_projectors(P, key, group)
        out = dict(found=found, why=why, numbers=_number_textures(P, key))
        want = (q.get("pkg") or [""])[0] or (found[0]["pkg"] if found else "")
        if want:
            rel, _, projs = _proj_open(P, want)
            out.update(pkg=want, origin=P.src.origin(rel), projectors=_proj_rows(projs))
        return out

    def proj_set(q, b):
        """Type values for one projector: loc [x,y,z] cm, rot [pitch,yaw,roll] deg, scale [x,y,z], priority."""
        P = S.need()
        rel, a, projs = _proj_open(P, b["pkg"])
        p = next((x for x in projs if x["tag"] == b["tag"]), None)
        if not p:
            raise C.MgpError("no projector %s in this file" % b["tag"])
        try:
            loc = [float(v) for v in b["loc"]]
            rot = [float(v) for v in b["rot"]]
            sc = [float(v) for v in b["scale"]]
            pri = int(b["priority"]) if b.get("priority") not in (None, "") else None
        except (TypeError, ValueError, KeyError):
            raise C.MgpError("every field needs a number")
        if len(loc) != 3 or len(rot) != 3 or len(sc) != 3:
            raise C.MgpError("position, rotation and scale need 3 numbers each")
        old = _rotator(p["quat"])
        quat = p["quat"] if all(abs(x - y) < 5e-4 for x, y in zip(rot, old)) else PJ.rotator_to_quat(*rot)  # untouched: keep exact
        PJ.patch(a, projs, {p["tag"]: dict(loc=loc, quat=quat, scale=sc, priority=pri)})
        _proj_write(P, rel, a)
        return dict(projectors=_proj_rows(_proj_reparse(a)[1]))

    def _proj_reparse(a):
        if getattr(a, "zen", False):
            return PJ.parse(a.to_bytes(), None)
        return PJ.parse(a.ua.to_bytes(), bytes(a.uexp))

    def _proj_write(P, rel, a):
        _proj_reparse(a)                                      # still parses after the patch
        files = [(rel, a.to_bytes())] if getattr(a, "zen", False) else [(rel, a.ua.to_bytes()), (rel[:-7] + ".uexp", bytes(a.uexp))]
        for path, data in files:
            full = P.src.loose(path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            P.backup(full)
            with open(full, "wb") as f:
                f.write(data)

    def _proj_rows(projs):
        return [dict(tag=p["tag"], loc=[round(v, 3) for v in p["loc"]], rot=_rotator(p["quat"]), scale=[round(v, 4) for v in p["scale"]],
                     priority=p["priority"], texture=(p["texture"] or "").rsplit("/", 1)[-1].split(".")[0]) for p in projs]

    def proj_list(q, b):
        """Projectors in one file, plus every projector file the mod folder/paks have (to copy from)."""
        P = S.need()
        pkg = (q.get("pkg") or [""])[0]
        out = dict(files=sorted("/Game/" + r[len("Content/"):-7] for r in P.src.find("Content/assets/graphics/vehicles", ".uasset")
                                if "projector" in r.rsplit("/", 1)[-1].lower()))
        if pkg:
            rel, _, projs = _proj_open(P, pkg)
            out.update(pkg=C.normalize_target(pkg), origin=P.src.origin(rel), projectors=_proj_rows(projs))
        return out

    def proj_copy(q, b):
        """Copy position/rotation/scale/priority of the chosen tags from `src` into `dst` (same file size; staged)."""
        P = S.need()
        rel, a, dprojs = _proj_open(P, b["dst"])
        src = b["src"]
        if not src.startswith("/Game/"):                  # a rider/team key: use its projector file
            found, why = _rider_projectors(P, src, b.get("group") or "official")
            if not found:
                raise C.MgpError("%s: %s" % (src, why))
            src = found[0]["pkg"]
        _, _, sprojs = _proj_open(P, src)
        want = set(b.get("tags") or [p["tag"] for p in sprojs])
        vals = {p["tag"]: p for p in sprojs if p["tag"] in want}
        done = PJ.patch(a, dprojs, vals)
        if done:
            _proj_write(P, rel, a)
        missing = sorted(want - set(done))
        return dict(done=done, missing=missing, src=src, projectors=_proj_rows(_proj_reparse(a)[1]))

    def refs(q, b):
        """Background job: which assets (mod folder + paks) mention a package name in their name table."""
        P = S.need()
        pkg = (b.get("pkg") or "").strip()
        name = pkg.rsplit("/", 1)[-1]
        if not name:
            raise C.MgpError("no asset given")
        folder = (b.get("folder") or "Content/assets").strip("/")
        needle = (pkg if pkg.startswith("/Game/") else name).lower().encode("latin1")

        def work(log):
            rels = P.src.find(folder, ".uasset")
            log("Looking for %s in %d asset(s) under %s ..." % (needle.decode(), len(rels), folder))
            hits, bad = [], 0
            for i, r in enumerate(rels):
                if i and i % 3000 == 0:
                    log("... %d/%d checked, %d found" % (i, len(rels), len(hits)))
                if r.rsplit("/", 1)[-1][:-7].lower() == name.lower():
                    continue                                      # the asset itself
                try:
                    data = P.src.read(r)
                except Exception:
                    bad += 1
                    continue
                if needle in data.lower():
                    hits.append(dict(file=r, origin=P.src.origin(r)))
                    log("USED BY: %s (%s)" % (r, hits[-1]["origin"]))
            log("Done: %d asset(s) use %s%s" % (len(hits), name, (" (%d unreadable)" % bad) if bad else ""))
            return dict(hits=hits, name=name, checked=len(rels), unreadable=bad,
                        summary="%d asset(s) use %s" % (len(hits), name))
        _job_start("Finding uses", work)
        return dict(started=True)

    def browse_list(q, b):
        P = S.need()
        files = _scope_files(P, (q.get("scope") or ["all"])[0], (q.get("refresh") or [""])[0] == "1")
        only_assets = (q.get("assets") or [""])[0] == "1"
        d = (q.get("dir") or [""])[0].strip("/")
        text = (q.get("q") or [""])[0].strip().lower()
        limit = min(int((q.get("limit") or ["400"])[0]), 1000)
        dirs, items = {}, {}
        pre = d.lower() + "/" if d else ""
        for rel in files:
            low = rel.lower()
            if pre and not low.startswith(pre):
                continue
            if only_assets and not low.endswith(".uasset"):
                continue
            if text:
                if text not in low:
                    continue
            elif "/" in rel[len(pre):]:
                seg = rel[len(pre):].split("/", 1)[0]
                dirs[seg] = dirs.get(seg, 0) + 1
                continue
            stem, ext = os.path.splitext(rel)
            ext = ext.lower()
            asset_part = ext in (".uasset", ".uexp", ".ubulk", ".uptnl")
            key = stem if asset_part else rel
            it = items.get(key)
            if it is None:
                it = items[key] = dict(base=key, name=key if text else key.rsplit("/", 1)[-1], exts=[], asset=False)
            it["exts"].append(ext if asset_part else "")
            if ext == ".uasset":
                it["asset"] = True
        out = []
        for k in sorted(items, key=str.lower):
            if len(out) >= limit:
                break
            it = items[k]
            first = k + ".uasset" if it["asset"] else k
            it["origin"] = P.src.origin(first) if P.src.exists(first) else ""
            if it["asset"]:
                it["pkg"] = "/Game/" + k[len("Content/"):]
            out.append(it)
        return dict(dir=d, dirs=[dict(name=k, count=v) for k, v in sorted(dirs.items(), key=lambda x: x[0].lower())],
                    items=out, truncated=len(items) > len(out), total_files=len(files))

    def browse_extract(q, b):
        """overwrite: None = ask (nothing is written if something already exists), 'replace' or 'skip'."""
        P = S.need()
        mode = b.get("overwrite")
        todo, exists = [], []
        for base in b.get("bases") or []:
            if ".." in base or not base.startswith("Content/"):
                raise C.MgpError("bad path: " + base)
            for e in C.SIDECARS + (".uptnl", ""):
                r = base + e
                if P.paks and P.paks.exists(r):                  # only files that come from the game's paks
                    (exists if os.path.exists(os.path.join(P.real_root, *r.split("/"))) else todo).append(r)
        if exists and mode is None:
            return dict(files=[], exists=exists, asked=True)
        made = []
        for r in todo + (exists if mode == "replace" else []):
            dst = os.path.join(P.real_root, *r.split("/"))
            data = P.paks.read(r)                                # the game's original, not an edited copy
            if os.path.exists(dst):
                bk = os.path.join(P.backup_dir, *r.split("/"))
                os.makedirs(os.path.dirname(bk), exist_ok=True)
                shutil.copyfile(dst, bk)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            made.append(r)
        return dict(files=made, exists=exists, skipped=0 if mode == "replace" else len(exists))

    def browse_clone(q, b):
        P = S.need()
        gp24_only(P, "copying assets")
        old = b["pkg"]
        name = (b.get("name") or "").strip()
        if not name or "/" in name or "." in name:
            raise C.MgpError("enter just the new file name (no folder, no extension)")
        new = old.rsplit("/", 1)[0] + "/" + name
        made = P._dup_asset(old, new)
        return dict(new=new, files=len(made))

    _pick_lock = threading.Lock()

    def pick(q, b):
        """Native folder/file chooser on the computer running the editor (the server runs locally)."""
        kind = b.get("kind", "folder")
        start = (b.get("initial") or "").strip().strip('"')
        if kind == "asset":                                      # a .uasset inside the mod folder's Content
            P = S.need()
            start = os.path.join(P.real_root, *(b.get("startrel") or "Content").split("/"))
            while start and not os.path.isdir(start) and start != P.real_root:
                start = os.path.dirname(start)
        if start and os.path.isfile(start):
            start = os.path.dirname(start)
        if not start or not os.path.isdir(start):
            start = os.path.expanduser("~")
        try:
            import tkinter
            from tkinter import filedialog
        except ImportError:
            if os.name != "nt":
                raise C.MgpError("the file chooser needs Python's tkinter, which is missing here - paste the path instead")
            return _pick_result(S, kind, _pick_powershell(kind, start))
        with _pick_lock:
            root = tkinter.Tk()
            try:
                root.withdraw()
                root.attributes("-topmost", True)
                if kind == "asset":
                    path = filedialog.askopenfilename(initialdir=start, title="Choose an asset from your mod folder",
                                                      filetypes=[("Unreal assets", "*.uasset")], parent=root)
                elif kind == "game":
                    path = filedialog.askopenfilename(initialdir=start, title="Choose the game .exe or a shortcut to it",
                                                      filetypes=[("Game or shortcut", "*.exe *.lnk *.url"), ("All files", "*.*")], parent=root)
                elif kind == "font":
                    path = filedialog.askopenfilename(initialdir=start, title="Choose the font file",
                                                      filetypes=[("Fonts", "*.ttf *.otf *.ufont"), ("All files", "*.*")], parent=root)
                elif kind == "file":
                    path = filedialog.askopenfilename(initialdir=start, title="Choose the file",
                                                      filetypes=[("Programs", "*.exe"), ("All files", "*.*")], parent=root)
                else:
                    path = filedialog.askdirectory(initialdir=start, title="Choose the folder", mustexist=True, parent=root)
            finally:
                root.destroy()
        return _pick_result(S, kind, path)

    def reveal(q, b):
        """Open a folder in the file manager; for a file, open its folder with the file selected."""
        path = (b.get("path") or "").strip().strip('"')
        if not path and b.get("rel"):                            # a file in the mod folder
            path = os.path.join(S.need().real_root, *b["rel"].split("/"))
        if not path and b.get("what") == "pak":                 # the Pack mod default output folder
            path = os.path.join(S.need().real_root, "_mgp_pak")
            os.makedirs(path, exist_ok=True)
        if not path:
            raise C.MgpError("the path is empty")
        if not os.path.exists(path):
            raise C.MgpError("this path does not exist: " + path)
        path = os.path.normpath(path)
        if os.name == "nt":
            if os.path.isfile(path):
                subprocess.Popen(["explorer", "/select,", path])      # shows the file, never runs it
            else:
                os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])
        else:
            subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
        return dict(ok=True)

    SHEET_FILE = "_mgp_replacement_sheet.json"

    def _db_rows(blob):
        """{table: {key: {col: value}}} for the tables the sheet uses."""
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        try:
            with open(path, "wb") as f:
                f.write(blob)
            con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
            out = {}
            for t in ("Pilots", "Teams", "VehicleModels", "Tracks"):
                try:
                    cur = con.execute('select * from "%s"' % t)
                except sqlite3.Error:
                    out[t] = {}
                    continue
                cols = [d[0] for d in cur.description]
                out[t] = {r[0]: dict(zip(cols, r)) for r in cur}
            con.close()
            return out
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _sheet_path(P):
        return os.path.join(P.real_root, SHEET_FILE)

    def _sheet_load(P):
        try:
            with open(_sheet_path(P), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _loc_ents(data):
        """[(normalised ns+key, ns, key, text)] of a .locres (short single-line texts only)."""
        import re
        norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
        L = LR.Locres(data)
        return [(norm(n + k), n, k, t) for _, _, n, k, t in L.entries() if t and len(t) <= 80 and "\n" not in t]

    def _loc_names(P, rels, entities):
        """Match DB keys to localization texts over several .locres files.
        {key: dict(text, ref, n, mod)}: text = the game's original, mod = your mod's text for the same entry."""
        import bisect, re
        norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
        base, mod = [], {}
        for rel in rels:
            try:
                bdata = P.paks.read(rel) if P.paks and P.paks.exists(rel) else P.src.read(rel)
                mdata = P.src.read(rel)
                for e in _loc_ents(bdata):
                    base.append((rel,) + e)
                if mdata != bdata:
                    for e in _loc_ents(mdata):
                        mod[(rel, e[1], e[2])] = e[3]
            except Exception:
                continue
        blob, starts = [], []
        pos = 0
        for e in base:
            starts.append(pos)
            blob.append(e[1])
            pos += len(e[1]) + 1
        blob = "\n".join(blob)

        def find(needle):
            hits, i = [], blob.find(needle)
            while i >= 0 and len(hits) < 200:
                hits.append(base[bisect.bisect_right(starts, i) - 1])
                i = blob.find(needle, i + 1)
            return hits
        out = {}
        for key in entities:
            full, short = norm(key), norm(key.split("_", 1)[-1])
            hits = (find(full) if full else []) or (find(short) if len(short) > 4 else [])
            if hits:
                hits.sort(key=lambda e: (len(e[1]), e[4] == e[4].upper() and len(hits) > 1))
                r, _, ns, k, t = hits[0]
                out[key] = dict(text=t, ref="%s: %s / %s" % (os.path.basename(r), ns, k), n=len(hits), mod=mod.get((r, ns, k), ""))
        return out

    def sheet(q, b):
        """Every rider, team, bike and track of the base game, what your mod changed on it, and your own
        'replaced with' notes (kept in the mod folder, not packed into the pak)."""
        P = S.need()
        mod = _db_rows(P.src.read(C.DB_REL))
        base = _db_rows(P.paks.read(C.DB_REL)) if P.paks and P.paks.exists(C.DB_REL) else mod
        saved = _sheet_load(P)

        def diff(t, k):
            a, m = base[t].get(k), mod[t].get(k)
            if a is None:
                return "added in mod"
            if m is None:
                return "removed in mod"
            ch = ["%s: %s -> %s" % (c, a[c], m[c]) for c in a if c in m and a[c] != m[c] and c != "UI_Index"]
            return "; ".join(ch[:5]) + (" ..." if len(ch) > 5 else "")

        def pretty(key):
            return key.split("_", 1)[-1].replace("-", " ")

        def num(r):
            return r["PilotNumberOverride"] or r["PilotNumber"]

        sections = dict(
            riders=[dict(key=k, name=pretty(k), group=k.split("_", 1)[0],
                         info="%s - #%s - %s" % (r["Teams_Key"], num(r), r["Nations_Key"])) for k, r in sorted(base["Pilots"].items())],
            teams=[dict(key=k, name=pretty(k), group=r["Categories_Key"],
                        info="%s - bike %s - %s" % (r["Categories_Key"], r["VehicleModels_Key"], r["Year"])) for k, r in sorted(base["Teams"].items())],
            bikes=[dict(key=k, name=k, group=r["Manufacturers_Key"], info=r["Manufacturers_Key"]) for k, r in sorted(base["VehicleModels"].items())],
            tracks=[dict(key=k, name=k, group=str(r["Nations_Key"]), info="%s - %s m" % (r["Nations_Key"], r["Length"])) for k, r in sorted(base["Tracks"].items())],
        )
        tmap = dict(riders="Pilots", teams="Teams", bikes="VehicleModels", tracks="Tracks")
        for kind, rows in sections.items():
            have = {r["key"] for r in rows}
            for r in rows:
                r["changed"] = diff(tmap[kind], r["key"])
                s = (saved.get(kind) or {}).get(r["key"]) or {}
                r["with"], r["notes"] = s.get("with", ""), s.get("notes", "")
            for k in sorted(mod[tmap[kind]]):
                if k not in have:
                    rows.append(dict(key=k, name=pretty(k), group="(new in mod)", info="", changed="added in mod",
                                     **{"with": ((saved.get(kind) or {}).get(k) or {}).get("with", ""), "notes": ((saved.get(kind) or {}).get(k) or {}).get("notes", "")}))
        locs = [r for r in P.src.find("Content", ".locres")]
        want = (q.get("loc") or ["__all__"])[0] or "__all__"
        lang = (q.get("lang") or ["it"])[0].lower()
        english = [r for r in locs if "/%s/" % lang in r.lower().replace("\\", "/")] or locs
        rels = english if want == "__all__" else ([want] if want in locs else [])
        names = {}
        if rels:
            allkeys = [r["key"] for rows in sections.values() for r in rows]
            names = _loc_names(P, rels, allkeys)
        sugg = 0
        for rows in sections.values():
            for r in rows:
                hit = names.get(r["key"])
                if hit:
                    r["loc"], r["loc_ref"], r["loc_n"] = hit["text"], hit["ref"], hit["n"]
                    r["suggest"] = hit["mod"] if hit["mod"] and hit["mod"] != hit["text"] else ""
                    sugg += bool(r["suggest"])
                else:
                    r["loc"], r["loc_ref"], r["loc_n"], r["suggest"] = "", "", 0, ""
        return dict(sections=sections, has_base=bool(P.paks), locs=locs, loc=want, matched=len(names), files=len(rels), suggestions=sugg)

    def sheet_set(q, b):
        P = S.need()
        kind, key = b.get("kind"), b.get("key")
        if kind not in ("riders", "teams", "bikes", "tracks") or not key:
            raise C.MgpError("bad sheet entry")
        data = _sheet_load(P)
        row = data.setdefault(kind, {}).setdefault(key, {})
        for f in ("with", "notes"):
            if f in b:
                row[f] = str(b[f])[:500]
        if not row.get("with") and not row.get("notes"):
            data[kind].pop(key, None)
        with open(_sheet_path(P), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        return dict(ok=True)

    def _hud_open(b):
        P = S.need()
        rel = b.get("target", "")
        if not rel.lower().endswith(".uasset") or not P.src.exists(rel):
            raise C.MgpError("target widget not found: %r" % rel)
        ue = rel[:-7] + ".uexp"
        if not P.src.exists(ue):
            raise C.MgpError("target has no .uexp")
        ta = U.Asset(P.src.read(rel), P.src.read(ue))
        sd = b.get("source_dir", "")
        base = os.path.splitext(os.path.basename(rel))[0].lower()
        sa = None
        if os.path.isdir(sd):
            for d, _, fs in os.walk(sd):
                low = {f.lower(): f for f in fs}
                if base + ".uasset" in low and base + ".uexp" in low:
                    sa = U.Asset(open(os.path.join(d, low[base + ".uasset"]), "rb").read(), open(os.path.join(d, low[base + ".uexp"]), "rb").read())
                    break
        if sa is None:
            raise C.MgpError("source folder %r has no %s.uasset + .uexp (extract the other game's widget there)" % (sd, base))
        return P, rel, ue, ta, sa

    PAIR_EXT = (".uasset", ".uexp", ".ubulk", ".uptnl")
    WARN_RE = __import__("re").compile(r"penal|warn|longlap|long_lap", __import__("re").I)
    FONT_RE = __import__("re").compile(r"(^|/)ui/fonts/", __import__("re").I)

    def _script_refs(a):
        """C++ classes/structs/enums an asset imports from game modules. motogp24 ones are plain names; other
        modules (e.g. /Script/sbk1 in SBK assets) are 'module:Name' and also add an '@module' marker."""
        out = set()
        for i, imp in enumerate(a.imports):
            if imp["cls"] in ("Class", "ScriptStruct", "Enum"):
                pkg, obj = a.object_ref(-(i + 1))
                if pkg.lower() == "/script/motogp24":
                    out.add(obj)
                elif pkg.lower().startswith("/script/"):
                    out.add("%s:%s" % (pkg[len("/Script/"):], obj))
                    out.add("@" + pkg[len("/Script/"):].lower())
        return out

    def _missing(refs, known):
        """What in `refs` the game does not have: unknown motogp24 classes, and anything from a module no game asset uses."""
        out = []
        for r in sorted(refs):
            if r.startswith("@"):
                continue
            if ":" in r:
                if ("@" + r.split(":", 1)[0].lower()) not in known:
                    out.append(r.replace(":", " (module not in this game): ", 1) if False else r)
            elif r not in known:
                out.append(r)
        return out

    def _game_classes(P, log):
        """Every C++ class/module the game's own UI assets use. Only the base paks count (not *_P.pak, which
        include your own mod, and not files your mod overrides), so SBK classes already packed into your mod
        are not mistaken for game classes."""
        key = tuple(id(r) for r in P.paks.base_readers()) if P.paks else None   # same until a base pak changes
        cache = getattr(S, "classcache", None)
        if cache and cache[0] == key:
            return cache[1]
        known = set()
        if P.paks:
            prefix = (P.paks.project + "/content/assets/ui/")
            readers = P.paks.base_readers() or P.paks.readers
            items = [(r, low) for r in readers for low in r.files if low.startswith(prefix) and low.endswith(".uasset")]
            for i, (r, low) in enumerate(items):
                if i % 400 == 0:
                    log("Reading the game's UI classes... %d/%d" % (i, len(items)))
                try:
                    for ref in _script_refs(U.Asset(r.read(low), b"")):
                        known.add(ref)
                except Exception:
                    continue
        S.classcache = (key, known)
        return known

    def _hud_scan(P, sd, log=lambda s: None):
        if not sd or not os.path.isdir(sd):
            raise C.MgpError("source folder not found: %r" % sd)
        known = _game_classes(P, log)
        log("Scanning %s ..." % sd)
        game = {}
        for r in P.src.find("Content", ".uasset"):
            game.setdefault(os.path.basename(r)[:-7].lower(), []).append(r)
        gamelow = {r.lower(): r for rs in game.values() for r in rs}
        groups = {}
        for d, _, fs in os.walk(sd):
            for f in sorted(fs):
                stem, ext = os.path.splitext(f)
                full = os.path.join(d, f)
                key = os.path.join(os.path.relpath(d, sd), stem if ext.lower() in PAIR_EXT else f)
                groups.setdefault(key, []).append((f, full))
        items = []
        for key, fl in sorted(groups.items()):
            parts = key.replace("\\", "/").split("/")
            low = [x.lower() for x in parts]
            dest, note = "", ""
            base = parts[-1]
            names = [f for f, _ in fl]
            has_asset = any(n.lower().endswith(".uasset") for n in names)
            if "content" in low[:-1]:
                dest = "/".join(parts[low.index("content"):])
            elif has_asset:
                c = game.get(base.lower(), [])
                if c:
                    dest = c[0][:-7]
                    if len(c) > 1:
                        note = "%d game assets share this name - using %s" % (len(c), c[0])
            if has_asset and dest:
                dest = gamelow.get(dest.lower() + ".uasset", dest + ".uasset")[:-7]      # keep the game's own letter case
            if has_asset and not any(n.lower().endswith(".uexp") for n in names):
                note = (note + "; " if note else "") + "no .uexp next to it"
            if not dest:
                note = (note + "; " if note else "") + "no place found - keep the folders from Content/ down, or the file name must exist in the game"
            font = bool(dest) and FONT_RE.search(dest)
            if font:
                note = (note + "; " if note else "") + "font - not imported (another game's font assets crash this one; copy the Fonts folder from your working pak instead)"
            first = dest + (".uasset" if has_asset else "") if dest else ""
            orig = P.src.origin(first) if first and has_asset else ("" if not dest else ("mod folder" if os.path.exists(P.src.loose(dest)) else "new"))
            items.append(dict(key=key.replace("\\", "/"), name=base, files=names, dest=dest, replaces=("game original" if orig.lower().endswith(".pak") else orig) if orig and orig != "missing" else "new",
                              warn=bool(WARN_RE.search(base)), font=bool(font), note=note, ok=bool(dest) and not font, size=sum(os.path.getsize(p) for _, p in fl),
                              _paths=fl))
        dests = {it["dest"].lower() + ".uasset" for it in items if it["ok"]}
        for it in items:
            it["crash"], it["missing_deps"] = [], []
            ua = next((p for f, p in it["_paths"] if f.lower().endswith(".uasset")), None)
            if not ua or not it["ok"]:
                continue
            try:
                with open(ua, "rb") as fh:
                    a = U.Asset(fh.read(), b"")
            except Exception:
                continue
            if known:
                it["crash"] = _missing(_script_refs(a), known)
            for imp in a.imports:
                n = imp["name"]
                if imp["cls"] == "Package" and n.startswith("/Game/") and ("Content/" + n[6:] + ".uasset").lower() not in gamelow and ("Content/" + n[6:] + ".uasset").lower() not in dests:
                    it["missing_deps"].append(n)
            it["missing_deps"] = it["missing_deps"][:6]
        return items

    def hud_scan(q, b):
        P = S.need()
        sd = b.get("source_dir", "")
        if not sd or not os.path.isdir(sd):
            raise C.MgpError("source folder not found: %r" % sd)

        def work(log):
            items = _hud_scan(P, sd, log)
            for it in items:
                it.pop("_paths")
            risky = sum(1 for it in items if it["crash"])
            log("Done: %d items, %d importable, %d need a game class this game lacks" % (len(items), sum(1 for i in items if i["ok"]), risky))
            return dict(items=items, summary="%d items, %d importable%s" % (len(items), sum(1 for i in items if i["ok"]), (", %d likely to crash" % risky) if risky else ""))
        _job_start("Scanning", work)
        return dict(started=True)

    def _font_tail(a):
        """Bytes after the tagged properties of a Font export (its native part), or None if not a Font."""
        for i, e in enumerate(a.exports):
            if e["cls"] == "Font":
                x = a.parse_export(i)
                return x["size_end"] - x["end"]
        return None

    def _game_font_tail(P):
        """Native-part size of the game's own Font assets (base paks only); None if none could be read."""
        key = tuple(id(r) for r in P.paks.base_readers()) if P.paks else None
        cache = getattr(S, "fontcache", None)
        if cache and cache[0] == key:
            return cache[1]
        tails = {}
        if P.paks:
            prefix = P.paks.project + "/content/assets/ui/fonts/"
            for r in (P.paks.base_readers() or P.paks.readers):
                for low in r.files:
                    if low.startswith(prefix) and low.endswith(".uasset") and len(tails) < 400:
                        try:
                            t = _font_tail(U.Asset(r.read(low), r.read(low[:-7] + ".uexp")))
                        except Exception:
                            continue
                        if t is not None:
                            tails[t] = tails.get(t, 0) + 1
        best = max(tails, key=tails.get) if tails else None
        S.fontcache = (key, best)
        return best

    FOREIGN_RE = __import__("re").compile(r"^(sbk|motogp(?!24$)|ride\d|mxgp)", __import__("re").I)

    def _crash_scan(P, log):
        """Loose mod assets that will (block) or may (warn) crash the game.
        block: imports from another game's C++ module (e.g. /Script/sbk1); a UI asset needing a motogp24 class no
               game UI asset uses; a Font whose native part differs from the game's Fonts (SBK Font: 'Serial size mismatch').
        warn:  a non-UI asset needing a motogp24 class no game *UI* asset uses (the class list comes from UI assets
               only, so this can be a false alarm)."""
        known = _game_classes(P, log)
        font_tail = _game_font_tail(P)
        rels = P.src.find("Content", ".uasset", loose_only=True)     # modded = loose files
        log("Checking %d modded asset(s)%s..." % (len(rels), "" if known else " (game classes unknown - class check skipped)"))
        block, warn = [], []
        for r in rels:
            try:
                ux = r[:-7] + ".uexp"
                a = U.Asset(P.src.read(r), P.src.read(ux) if P.src.exists(ux) else b"")
                refs = _script_refs(a)
            except Exception:
                continue
            hard, soft = [], []
            ui = "/content/assets/ui/" in r.lower()
            for m in sorted(x for x in refs if ":" in x):
                mod = m.split(":", 1)[0]
                if FOREIGN_RE.match(mod):
                    hard.append(m)
                elif known and ("@" + mod.lower()) not in known:
                    (hard if ui else soft).append(m)
            if known:
                (hard if ui else soft).extend(m for m in _missing(refs, known) if ":" not in m)
            if font_tail is not None and a.uexp:
                try:
                    t = _font_tail(a)
                except Exception:
                    t = None
                if t is not None and t != font_tail:
                    hard.append("Font made by another game (native part %d bytes, the game's Fonts have %d)" % (t, font_tail))
            if hard:
                block.append(dict(file=r, missing=hard, origin=P.src.origin(r)))
                log("CRASH RISK: %s needs %s" % (r, ", ".join(hard)))
            elif soft:
                warn.append(dict(file=r, missing=soft, origin=P.src.origin(r)))
                log("maybe: %s uses %s (not seen in the game's UI assets)" % (r, ", ".join(soft)))
        log("Done: %d of %d asset(s) will crash the game, %d to double-check" % (len(block), len(rels), len(warn)))
        return block, warn, len(rels)

    def hud_modscan(q, b):
        """Assets in the mod folder/staging that need a C++ class this game lacks (what causes 'Could not find SuperStruct')."""
        P = S.need()

        def work(log):
            if not P.paks:
                raise C.MgpError("game paks not available to learn the game's classes")
            block, warn, n = _crash_scan(P, log)
            return dict(bad=block, warn=warn, checked=n)
        _job_start("Checking mod", work)
        return dict(started=True)

    def hud_import(q, b):
        P = S.need()
        want = set(b.get("keys") or [])
        sd = b.get("source_dir", "")
        if not want:
            raise C.MgpError("nothing selected")

        def work(log):
            items = [it for it in _hud_scan(P, sd, log) if it["key"] in want and it["ok"] and ".." not in it["dest"] and it["dest"].startswith("Content/")]
            n = same = 0
            for i, it in enumerate(items, 1):
                log("[%d/%d] %s (%d file%s)" % (i, len(items), it["dest"], len(it["_paths"]), "" if len(it["_paths"]) == 1 else "s"))
                for f, full in it["_paths"]:
                    ext = os.path.splitext(f)[1]
                    rel = it["dest"] + ext if ext.lower() in PAIR_EXT else it["dest"]
                    dst = P.src.loose(rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copyfile(full, dst)
                    n += 1
                    if not P._differs(rel, dst, os.path.getsize(dst)):
                        same += 1
            changed = n - same
            if changed:
                msg = "%d items, %d files: %d changed - press Save to write them (%d already identical in your mod folder or the game)" % (len(items), n, changed, same)
            else:
                msg = "%d items, %d files - ALL are already identical to what your mod folder / the game has, so there is nothing to save" % (len(items), n)
            log("Done: " + msg)
            return dict(items=len(items), files=n, changed=changed, same=same, summary=msg)
        _job_start("Importing", work)
        return dict(started=True)

    def hud_targets(q, b):
        P = S.need()
        t = (q.get("q") or ["hud"])[0].lower()
        return dict(files=[r for r in P.src.find("Content", ".uasset") if t in r.lower()][:300])

    def hud_compare(q, b):
        P, rel, ue, ta, sa = _hud_open(b)
        r = HS.compare(ta, sa)
        return dict(rows=[x for x in r["rows"] if not x["status"].startswith("only-in")], hidden=sum(1 for x in r["rows"] if x["status"].startswith("only-in")),
                    only_target=r["only_target"], only_source=r["only_source"], common=r["common"])

    def hud_vis(q, b):
        P = S.need()
        rel = b.get("target", "")
        if not rel.lower().endswith(".uasset") or not P.src.exists(rel) or not P.src.exists(rel[:-7] + ".uexp"):
            raise C.MgpError("target widget not found: %r" % rel)
        a = U.Asset(P.src.read(rel), P.src.read(rel[:-7] + ".uexp"))
        return dict(widgets=HS.visibility_list(a))

    def hud_vis_set(q, b):
        P = S.need()
        rel = b.get("target", "")
        ue = rel[:-7] + ".uexp"
        if not rel.lower().endswith(".uasset") or not P.src.exists(rel) or not P.src.exists(ue):
            raise C.MgpError("target widget not found: %r" % rel)
        ch = {k: v for k, v in (b.get("changes") or {}).items() if v}
        if not ch:
            raise C.MgpError("nothing to change")
        ua, ux, done = HS.set_visibility(P.src.read(rel), P.src.read(ue), ch)
        for r, data in ((rel, ua), (ue, ux)):
            dst = P.src.loose(r)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
        return dict(done=done)

    def hud_graft(q, b):
        """Swap SBK's penalty widget for GP24's own (WB_RacePenaltiesWidgetContainer) and hide SBK's other penalty widgets."""
        P = S.need()
        rel = _race_target(P, b)
        ue = rel[:-7] + ".uexp"
        if not rel.lower().endswith(".uasset") or not P.src.exists(rel) or not P.src.exists(ue):
            raise C.MgpError("target widget not found: %r" % rel)
        donor = P.paks.read_base(rel)
        if donor is None:
            raise C.MgpError("the game has no original copy of this page to take the penalty widget from")
        ua, ux = P.src.read(rel), P.src.read(ue)
        users = []
        for frm, to in (("PenaltiesInfoWidgetManagerBP_C", "WB_RacePenaltiesWidgetContainer_C"),
                        ("WarningHUDSmallWidget_C", "PlayerAlertsHUDWidget_BP_C")):    # the second is the player's own alerts (warning / long lap / jump start)
            try:
                ua, ux, u = HS.retype_widget(ua, ux, donor, frm, to)
                users += u
            except C.MgpError as e:
                if "expected one import" in str(e) or "no widget of class" in str(e):
                    continue                                   # already swapped (or not in this page)
                raise
        swapped_now = list(users)
        vis = {w["name"]: w for w in HS.visibility_list(U.Asset(ua, ux))}
        keep = set(users) | {n for n, w in vis.items() if w["cls"] in ("WB_RacePenaltiesWidgetContainer_C", "PlayerAlertsHUDWidget_BP_C")}
        users = sorted(keep)
        hide = {n: "Collapsed" for n, w in vis.items()
                if w["warn"] and n not in keep and w["vis"] != "Collapsed" and "flag" not in (n + w["cls"]).lower()}
        hide.update({n: "SelfHitTestInvisible" for n in users if (vis.get(n) or {}).get("vis") == "Collapsed"})
        if not swapped_now and not hide:
            raise C.MgpError("%s already has GP24's penalty widgets and the old SBK ones hidden - nothing to change" % rel.rsplit("/", 1)[-1])
        hidden = []
        if hide:
            ua, ux, hidden = HS.set_visibility(ua, ux, hide)
        for r, data in ((rel, ua), (ue, ux)):
            dst = P.src.loose(r)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
        return dict(swapped=swapped_now, hidden=hidden, file=rel.rsplit("/", 1)[-1])

    def _race_target(P, b):
        """These two buttons are about the race HUD page, whatever is picked in the list."""
        sel = b.get("target", "")
        if sel.rsplit("/", 1)[-1].lower() == "racehud_bp.uasset":
            return sel
        for r in P.src.find("Content/assets/ui/Pages/HUD", ".uasset"):
            if r.rsplit("/", 1)[-1].lower() == "racehud_bp.uasset":
                return r
        return sel

    def hud_swappos(q, b):
        """Swap what the two penalty slots show: the stewards box <-> the player alerts (jump start / long lap)."""
        P = S.need()
        rel = _race_target(P, b)
        ue = rel[:-7] + ".uexp"
        if not rel.lower().endswith(".uasset") or not P.src.exists(rel) or not P.src.exists(ue):
            raise C.MgpError("target widget not found: %r" % rel)
        ux = P.src.read(ue)
        a = U.Asset(P.src.read(rel), ux)
        cls = {e["name"]: e["cls"] for e in a.exports}
        if {cls.get("PenaltiesInfoWidgetManagerBP"), cls.get("WarningHUDSmallWidget")} != {"WB_RacePenaltiesWidgetContainer_C", "PlayerAlertsHUDWidget_BP_C"}:
            raise C.MgpError("in %s the two widgets are %s / %s - run 'Use GP24's penalty widget' first" % (rel.rsplit("/", 1)[-1], cls.get("PenaltiesInfoWidgetManagerBP"), cls.get("WarningHUDSmallWidget")))
        ua = HS.swap_widget_types(P.src.read(rel), "PenaltiesInfoWidgetManagerBP", "WarningHUDSmallWidget")
        chk = U.Asset(ua, ux)
        for i in range(len(chk.exports)):
            chk.parse_export(i)
        with open(P.src.loose(rel), "wb") as f:
            f.write(ua)
        return dict(now={e["name"]: e["cls"] for e in chk.exports if e["name"] in ("PenaltiesInfoWidgetManagerBP", "WarningHUDSmallWidget")})

    FONT_DIR = "Content/assets/ui/Fonts"

    def _fs_faces(P):
        """The game's FontFace assets (base paks) + what the mod folder does to each."""
        if not P.paks:
            raise C.MgpError("the game's paks are needed to list its fonts (Setup tab)")
        rels = sorted(r for r in P.paks.find(FONT_DIR, ".uasset"))
        faces, users = [], {}
        for r in P.src.find(FONT_DIR, ".uasset"):                   # Font assets -> faces they use (as the game will load them)
            try:
                a = U.Asset(P.src.read(r), b"")
            except Exception:
                continue
            if any(e["cls"] == "Font" for e in a.exports):
                for im in a.imports:
                    if im["cls"] == "FontFace":
                        users.setdefault(im["name"], []).append(r.rsplit("/", 1)[-1][:-7])
        for r in rels:
            base = P.paks.read_base(r)
            if base is None:
                continue
            try:
                a = U.Asset(base, b"")
            except Exception:
                continue
            if not any(e["cls"] == "FontFace" for e in a.exports):
                continue
            name = r.rsplit("/", 1)[-1][:-7]
            uf = r[:-7] + ".ufont"
            f = dict(name=name, used_by=sorted(users.get(name, [])), game_ufont=P.paks.read_base(uf) is not None,
                     mod_ufont="", mod_face="")
            if os.path.exists(P.src.loose(uf)) or (P.src.base and os.path.exists(P.src._base(uf))):
                try:
                    f["mod_ufont"] = FS.font_info(P.src.read(uf))["full"]
                except ValueError as e:
                    f["mod_ufont"] = "(%s)" % e
            loose = [x for x in (P.src.loose(r), P.src._base(r) if P.src.base else None) if x and os.path.exists(x)]
            if loose:
                mine = open(loose[0], "rb").read()
                ux = loose[0][:-7] + ".uexp"
                mine_x = open(ux, "rb").read() if os.path.exists(ux) else b""
                if mine != base or mine_x != (P.paks.read_base(r[:-7] + ".uexp") or b""):
                    f["mod_face"] = "another game's FontFace (points to projects/sbk1)" if b"sbk1" in mine + mine_x else "modded FontFace"
            faces.append(f)
        return faces

    def fontswap_list(q, b):
        return dict(faces=_fs_faces(S.need()))

    def fontswap_check(q, b):
        path = (b.get("path") or "").strip().strip('"')
        if not path or not os.path.isfile(path):
            raise C.MgpError("font file not found: %r" % path)
        try:
            return FS.font_info(open(path, "rb").read())
        except ValueError as e:
            raise C.MgpError("%s: %s" % (os.path.basename(path), e))

    def fontswap_apply(q, b):
        """Write the font file as <face>.ufont for each chosen face; where the mod folder has a different
        FontFace asset of that name (e.g. SBK's), put the game's own back so it reads that .ufont. Staged."""
        P = S.need()
        path = (b.get("path") or "").strip().strip('"')
        data = open(path, "rb").read() if path and os.path.isfile(path) else None
        if data is None:
            raise C.MgpError("font file not found: %r" % path)
        info = FS.font_info(data)
        known = {f["name"]: f for f in _fs_faces(P)}
        done, restored = [], []
        for name in b.get("faces") or []:
            if name not in known:
                raise C.MgpError("not one of the game's fonts: %s" % name)
            stem = FONT_DIR + "/" + name
            out = [(stem + ".ufont", data)]
            if known[name]["mod_face"]:
                for ext in (".uasset", ".uexp"):
                    orig = P.paks.read_base(stem + ext)
                    if orig is None:
                        raise C.MgpError("the game has no original %s%s to put back" % (name, ext))
                    out.append((stem + ext, orig))
                restored.append(name)
            for rel, blob in out:
                full = P.src.loose(rel)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                P.backup(full)
                with open(full, "wb") as f:
                    f.write(blob)
            done.append(name)
        return dict(font=info["full"], done=done, restored=restored)

    def fonts_list(q, b):
        P = S.need()
        found = P.src.find(FONT_DIR, ".uasset")
        have = {r.rsplit("/", 1)[1][:-7] for r in found}
        new = sorted(n for n in have if n.startswith("FF_TTSupermolot"))
        rows, skipped = [], []
        for r in found:
            name = r.rsplit("/", 1)[1][:-7]
            try:
                faces = HS.font_faces(P.src.read(r))
            except Exception as e:
                skipped.append("%s: %s" % (name, e))
                continue
            if not faces:
                continue                                       # a FontFace / texture, not a Font
            mine = [f for _, f in faces if not HS.FONT_KEEP.search(f)]
            if not mine:
                skipped.append("%s: only fallback / Supermolot faces" % name)
                continue
            rows.append(dict(rel=r, name=name, faces=[f for f in mine], origin=P.src.origin(r),
                             pick=not re.search(r"digital|accelerator|vehicle_|american_purpose|characters_font|^f_ttsupermolot", name, re.I)))
        return dict(rows=rows, new=new, skipped=skipped, scanned=len(found))

    def fonts_apply(q, b):
        P = S.need()
        new = {n for n in (b.get("new") or [])}
        done = []
        for r in b.get("fonts") or []:
            ua = P.src.read(r)
            fm = {}
            for _, f in HS.font_faces(ua):
                if HS.FONT_KEEP.search(f):
                    continue
                w = HS.font_weight(r.rsplit("/", 1)[1], f)
                t = "FF_TTSupermolotNeue-%s_Mono" % w
                if t not in new:
                    t = "FF_TTSupermolotNeue-Regular_Mono"
                if t not in new:
                    raise C.MgpError("FF_TTSupermolotNeue-* font faces were not found in the Fonts folder")
                fm[f] = t
            out, d = HS.retarget_font(ua, fm)
            if d:
                chk = U.Asset(out, P.src.read(r[:-7] + ".uexp"))
                dst = P.src.loose(r)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(out)
                ue = P.src.loose(r[:-7] + ".uexp")                 # the .uexp must sit next to it, unchanged
                if not os.path.exists(ue):
                    with open(ue, "wb") as f:
                        f.write(P.src.read(r[:-7] + ".uexp"))
                done.append(r.rsplit("/", 1)[1][:-7])
        return dict(done=done)

    def hud_apply(q, b):
        P, rel, ue, ta, sa = _hud_open(b)
        picks = [(x["widget"], x["path"]) for x in b.get("picks") or []]
        n, skipped = HS.apply(ta, sa, picks)
        if n:
            for r, data in ((rel, bytes(ta.ua.data)), (ue, bytes(ta.uexp))):
                dst = P.src.loose(r)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(data)
        return dict(applied=n, skipped=[dict(widget=a, path=p, why=w) for a, p, w in skipped])

    def sheet_import(q, b):
        """Merge {kind: {key: {with, notes}}} into the saved sheet. Blank cells in the import keep what is there."""
        P = S.need()
        data, n = _sheet_load(P), 0
        for kind, rows in (b.get("data") or {}).items():
            if kind not in ("riders", "teams", "bikes", "tracks") or not isinstance(rows, dict):
                continue
            for key, v in rows.items():
                if not isinstance(v, dict):
                    continue
                row = data.setdefault(kind, {}).setdefault(key, {})
                for f in ("with", "notes"):
                    if str(v.get(f, "")).strip():
                        row[f] = str(v[f])[:500]
                if not row.get("with") and not row.get("notes"):
                    data[kind].pop(key, None)
                else:
                    n += 1
        with open(_sheet_path(P), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        return dict(ok=True, imported=n)

    def audio_scan(q, b):
        P = S.need()
        root = (q.get("root") or [""])[0].strip().strip('"')
        if not root:
            raise C.MgpError("enter the folder with the other game's extracted audio files")
        return AP.scan_source(P, root)

    def audio_port(q, b):
        P = S.need()
        root = (b.get("root") or "").strip().strip('"')
        if not b.get("bikes"):
            raise C.MgpError("tick at least one bike")
        return AP.port(P, root, b["bikes"], dry_run=bool(b.get("dry_run", True)), gain=float(b.get("gain") or 0))

    def scan(q, b):
        """Every binding row (all tables, or one) whose asset does not exist, with 'did you mean' suggestions;
        for a single table also which teams have riders pointing at different assets."""
        P = S.need()
        only = (q.get("table") or [""])[0]
        cat = (q.get("cat") or [""])[0]
        teams = {}
        try:
            db = S.get_db()
            teams = dict(db.con.execute("select Key, Teams_Key from Pilots"))
        except Exception:
            pass
        rows, tables, cache = [], 0, {}
        for rel in P.table_names():
            if only and tname(rel) != only:
                continue
            try:
                t = P.table(rel)
            except Exception:
                continue
            tables += 1
            seen = {}
            for key in t.rows:
                target = t.target(key)
                if not is_game(target) or not in_cat(cat, key, target):
                    continue
                pkg = target.partition(".")[0]
                seen.setdefault(teams.get(key, ""), set()).add(target)
                if pkg not in cache:
                    cache[pkg] = P.src.exists(C.game_to_rel(pkg) + ".uasset")
                if not cache[pkg]:
                    rows.append(dict(rel=rel, table=tname(rel), key=key, team=teams.get(key, ""), target=target,
                                     suggest=similar(P, pkg)))
            if only:
                for r in rows:
                    r["conflict"] = len(seen.get(r["team"], ())) > 1 and bool(r["team"])
        conflicts = []
        match = [r for r in P.table_names() if tname(r) == only]
        if only and match:
            t = P.table(match[0])
            by = {}
            for key in t.rows:
                tm = teams.get(key)
                if tm:
                    by.setdefault(tm, {}).setdefault(t.target(key), []).append(key)
            conflicts = [dict(team=tm, targets=[dict(target=tg.rsplit("/", 1)[1], riders=rs) for tg, rs in d.items()])
                         for tm, d in sorted(by.items()) if len(d) > 1]
        return dict(rows=rows, tables=tables, conflicts=conflicts, names=sorted({tname(r) for r in P.table_names()}))

    def pair_of(P, name):
        if not name.endswith("_BikeOfficial"):
            raise C.MgpError("pick a ..._BikeOfficial table")
        other = name[:-len("_BikeOfficial")] + "_BikeTeams"
        rel = next((r for r in P.table_names() if tname(r) == other), None)
        rel_o = next((r for r in P.table_names() if tname(r) == name), None)
        if not rel or not rel_o:
            raise C.MgpError("no matching team table %s" % other)
        return rel_o, rel

    def teamsync(q, b):
        """Riders whose row differs from their team's row in the matching ..._BikeTeams table."""
        P = S.need()
        name = (q.get("table") or [""])[0]
        cat = (q.get("cat") or [""])[0]
        if not name:   # list of usable tables
            return dict(names=sorted(tname(r) for r in P.table_names() if tname(r).endswith("_BikeOfficial")
                                     and any(tname(x) == tname(r)[:-13] + "_BikeTeams" for x in P.table_names())))
        ro, rt = pair_of(P, name)
        to, tt = P.table(ro), P.table(rt)
        teams = dict(S.get_db().con.execute("select Key, Teams_Key from Pilots"))
        rows = []
        for key in sorted(to.rows):
            tm = teams.get(key)
            if tm not in tt.rows or not in_cat(cat, key, to.target(key)):
                continue
            cur, want = to.target(key), tt.target(tm)
            if cur != want and is_game(want):
                wp = want.partition(".")[0]
                rows.append(dict(key=key, team=tm, current=cur.rsplit("/", 1)[-1], want=want, want_name=want.rsplit("/", 1)[-1],
                                 cur_exists=is_game(cur) and P.src.exists(C.game_to_rel(cur.partition(".")[0]) + ".uasset"),
                                 want_exists=P.src.exists(C.game_to_rel(wp) + ".uasset")))
        return dict(rows=rows, total=len(to.rows), rel=ro)

    def teamsync_apply(q, b):
        P = S.need()
        ro, rt = pair_of(P, b["table"])
        to, tt = P.table(ro), P.table(rt)
        teams = dict(S.get_db().con.execute("select Key, Teams_Key from Pilots"))
        keys = b.get("keys") or [k for k in to.rows if in_cat(b.get("cat", ""), k, to.target(k))]
        done, skipped = 0, []
        for key in keys:
            tm = teams.get(key)
            if tm not in tt.rows or to.target(key) == tt.target(tm) or not is_game(tt.target(tm)):
                continue
            want = tt.target(tm)
            if not P.src.exists(C.game_to_rel(want.partition(".")[0]) + ".uasset"):
                skipped.append(key); continue
            to.set_target(key, want); done += 1
        if done:
            P.save_table(ro)
        return dict(changed=done, skipped=skipped)

    def clone_row(q, b):
        """Give one entry its own copy of its current asset (asset only, or with its variant materials/textures)."""
        P = S.need()
        gp24_only(P, "copying assets")
        rel, key, mode = b["rel"], b["key"], b.get("mode", "asset")
        t = P.table(rel)
        need_key(t, key)
        old_obj = t.target(key)
        if not is_game(old_obj):
            raise C.MgpError("this entry points at nothing, so there is nothing to clone - use Replace instead")
        old_pkg = old_obj.partition(".")[0]
        name = (b.get("name") or "").strip()
        new_pkg = (old_pkg.rsplit("/", 1)[0] + "/" + name) if name else P.propose_name(old_pkg, t)
        if not new_pkg:
            raise C.MgpError("could not find a free name - type one")
        if "/" in name:
            raise C.MgpError("the name goes in the same folder; enter just the file name")
        plan = P.copy_plan(rel, key, new_pkg, mode)
        res = dict(old=old_obj, new_name=new_pkg.rsplit("/", 1)[1], mode=mode, **plan,
                   can_set="customization_data" in old_pkg.split("/"))
        if b.get("dry_run") or plan["problems"]:
            return res
        r = P.replace_with_copy(rel, key, new_pkg, mode)
        res.update(created=len(r["made"]), target=r["target"], warnings=r["warnings"], notes=plan["notes"] + r["warnings"], dry_run=False)
        return res

    def clone_audit(q, b):
        """Dry-run a full-set copy of every distinct asset in a table (or all tables) and group the failures."""
        P = S.need()
        only = (q.get("table") or [""])[0]
        seen, fails, ok, n = set(), {}, 0, 0
        for rel in P.table_names():
            if only and tname(rel) != only:
                continue
            try:
                t = P.table(rel)
            except Exception:
                continue
            for key in t.rows:
                obj = t.target(key)
                if obj in seen or not is_game(obj):
                    continue
                seen.add(obj); n += 1
                pkg = obj.partition(".")[0]
                new = P.propose_name(pkg, t)
                mode = "set" if "customization_data" in pkg.split("/") else "asset"
                pl = P.copy_plan(rel, key, new, mode) if new else dict(problems=["no free name"], files=0)
                if pl["problems"]:
                    why = pl["problems"][0]
                    why = why.replace(pkg.rsplit("/", 1)[1], "<asset>")
                    d = fails.setdefault(mode + ": " + why[:140], dict(count=0, examples=[]))
                    d["count"] += 1
                    if len(d["examples"]) < 4:
                        d["examples"].append(dict(table=tname(rel), key=key, asset=pkg.rsplit("/", 1)[1]))
                else:
                    ok += 1
        return dict(checked=n, ok=ok, fails=[dict(reason=k, **v) for k, v in sorted(fails.items(), key=lambda x: -x[1]["count"])])

    def members(q, b):
        """The row's asset first, then what it references that you may want to edit: skeletal mesh, skeleton,
        physics asset and material instances (followed up to 3 levels, e.g. asset -> mesh -> skeleton)."""
        P = S.need()
        rel, key = q["rel"][0], q["key"][0]
        pkg = P.table(rel).target(key).partition(".")[0]
        return asset_members(P, pkg)

    def edit_asset(q, b):
        """Put the asset's files into the staging folder (so edits are saved/discarded like everything else)
        and open the .uasset in UAssetGUI (or whatever opens .uasset files)."""
        P = S.need()
        stem = C.game_to_rel(b["pkg"])
        rels = [stem + e for e in C.SIDECARS if P.src.exists(stem + e)]
        if stem + ".uasset" not in rels:
            raise C.MgpError("asset not found in mod folder or paks: " + b["pkg"])
        for r in rels:
            dst = P.src.loose(r)
            if not os.path.exists(dst):
                data = P.src.read(r)                      # read BEFORE opening dst (open() would create it empty)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(data)
        path = P.src.loose(stem + ".uasset")
        exe = S.load_cfg().get("uassetgui", "")
        launched, err = False, ""
        try:
            if exe:
                if not os.path.isfile(exe):
                    raise OSError("UAssetGUI path is not a file: " + exe)
                subprocess.Popen([exe, path]); launched = True
            elif os.name == "nt":
                os.startfile(path); launched = True
        except OSError as e:
            err = str(e)
        return dict(path=path, launched=launched, error=err)

    def settings(q, b):
        cfg = S.load_cfg()
        g = b.get("game_id") or (S.P.game if S.P else cfg.get("game_id", "gp24"))
        if "uassetgui" in b:
            cfg["uassetgui"] = str(b["uassetgui"]).strip().strip('"')
        if "game" in b:
            cfg[gk("game", g)] = str(b["game"]).strip().strip('"')
        S.save_cfg(cfg)
        return dict(uassetgui=cfg.get("uassetgui", ""), game=cfg.get(gk("game", g), ""))

    def _lnk_target(path):
        """(target, arguments, working dir) of a Windows .lnk shortcut."""
        script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s'); "
                  "ConvertTo-Json @{t=$s.TargetPath; a=$s.Arguments; w=$s.WorkingDirectory} -Compress" % path.replace("'", "''"))
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=30)
        try:
            d = json.loads(out.stdout)
        except ValueError:
            raise C.MgpError("could not read the shortcut %s" % path)
        return d.get("t") or "", d.get("a") or "", d.get("w") or ""

    def launch(q, b):
        """Start the game from an .exe, or from a shortcut (.lnk / Steam .url)."""
        cfg = S.load_cfg()
        path = (b.get("path") or cfg.get(gk("game", S.P.game if S.P else cfg.get("game_id", "gp24"))) or "").strip().strip('"')
        if not path:
            raise C.MgpError("set the game's .exe or shortcut in Setup first")
        if not os.path.isfile(path):
            raise C.MgpError("game file not found: %s" % path)
        path = os.path.normpath(path)
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".exe":
                subprocess.Popen([path], cwd=os.path.dirname(path))
            elif ext == ".lnk":
                if os.name != "nt":
                    raise C.MgpError(".lnk shortcuts only work on Windows")
                target, args, wd = _lnk_target(path)
                if target.lower().endswith(".exe") and os.path.isfile(target):
                    subprocess.Popen('"%s" %s' % (target, args) if args else [target], cwd=wd if os.path.isdir(wd) else os.path.dirname(target))
                else:
                    os.startfile(path)          # a shortcut to something that is not a plain exe (Steam, a store launcher)
            elif ext == ".url":
                if os.name != "nt":
                    raise C.MgpError(".url shortcuts only work on Windows")
                os.startfile(path)
            else:
                raise C.MgpError("choose an .exe, .lnk or .url file")
        except OSError as e:
            raise C.MgpError("could not start the game: %s" % e)
        return dict(ok=True, started=path)

    def open_(q, b):
        if S.P and S.P.staged_files():
            raise C.MgpError("you have unsaved changes - save or discard them before opening another project")
        S.open(b.get("mod_folder", "").strip(), b.get("paks_dir", "").strip(), b.get("aes_key", "").strip(), bool(b.get("include_patch", True)),
               b.get("game_id") or "gp24")
        return state(q, b)

    def pilots(q, b):
        P = S.need()
        g = (q.get("group") or ["official"])[0]
        counts = {}
        for rel in P.table_names():
            if C.group_of(rel) not in (g, "official" if g == "teams" else g):
                continue
            try:
                for k in P.table(rel).rows:
                    if P.group_for(rel, k) == g:
                        counts[k] = counts.get(k, 0) + 1
            except Exception:
                pass
        return [dict(key=k, n=counts[k]) for k in sorted(counts)]

    def bindings(q, b):
        P = S.need()
        key = q["key"][0]
        out = []
        for rel, cat, target in P.pilot_bindings(key, (q.get("group") or [None])[0]):
            if not is_game(target):          # the row points at nothing; it can still be replaced
                out.append(dict(rel=rel, table=tname(rel), cat=cat, target=target, exists=True, suggest=[], origin="(empty)"))
                continue
            pkg = target.partition(".")[0]
            ex = P.src.exists(C.game_to_rel(pkg) + ".uasset")
            out.append(dict(rel=rel, table=tname(rel), cat=cat, target=target,
                            exists=ex, suggest=[] if ex else similar(P, pkg),
                            origin=P.src.origin(C.game_to_rel(pkg) + ".uasset") if hasattr(P.src, "origin") else ""))
        return out

    def choices(q, b):
        P = S.need()
        rel, key = q["rel"][0], q["key"][0]
        t = P.table(rel)
        need_key(t, key)
        try:
            cands = P.candidates(rel, key)
        except C.MgpError:               # an empty row has no folder to list
            cands = []
        riders = sorted(r for r in t.rows if r != key)
        return dict(packages=cands, riders=riders, current=t.target(key))

    def status(b):
        P = S.need()
        return P.target_status(b["rel"], b["key"], b["target"])

    def replace(q, b):
        P = S.need()
        rel, key, target, copy = b["rel"], b["key"], C.normalize_target(b["target"]), b.get("copy")
        need_key(P.table(rel), key)
        old = P.table(rel).target(key)
        st = P.target_status(rel, key, target)
        res = dict(old=old)
        if not st["exists"] and not copy:
            return dict(needs_choice=True, pkg=st["pkg"], old=old)
        if not st["exists"] and copy in ("asset", "set"):
            gp24_only(P, "copying assets")
            r = P.replace_with_copy(rel, key, st["pkg"], copy)
            res.update(created=len(r["made"]), notes=r["notes"] + r["warnings"])
        else:
            w = P.repoint_in(rel, key, target)
            res.update(warning=w)
        res["new"] = P.table(rel).target(key)
        return res

    def copy_look(q, b):
        P = S.need()
        cats = set(b["only"]) if b.get("only") else None
        ch = P.copy_look(b["key"], b["donor"], cats)
        out = [dict(table=tname(rel), old=o, new=n) for rel, o, n in ch]
        if cats and "style" in cats:                 # riding style lives in its own table (RidingStyle_DT)
            st = P.style()
            if b["donor"] in st.rows:
                if b["key"] not in st.rows:
                    st.add_row(b["key"], b["donor"]); changed = True
                else:
                    changed = bool(st.set_values(b["key"], st.values(b["donor"])))
                if changed:
                    P.save_style()
                    out.append(dict(table="RidingStyle_DT", old="", new=b["donor"]))
        return out

    # ---- riding style (RidingStyle_DT)
    def style_get(q, b):
        P = S.need()
        key = q["key"][0]
        try:
            st = P.style()
        except C.MgpError as e:
            return dict(error=str(e))
        styles = {st.values(p)["RidingStyle"]: p for p in st.presets() if "RidingStyle" in st.rows[p]}
        sources = st.presets() + sorted(r for r in st.rows if "_" in r and r != key)
        if key not in st.rows:
            return dict(exists=False, sources=sources, styles=styles)
        return dict(exists=True, values=st.values(key), types=st.types(key), sources=sources, styles=styles,
                    origin=P.src.origin(C.STYLE_REL + ".uasset") if hasattr(P.src, "origin") else "")

    def style_set(q, b):
        """{key, values:{field:number}} edits the row; {key, donor} copies a preset's/rider's row (adds the row if missing)."""
        P = S.need()
        st, key = P.style(), b["key"]
        if b.get("donor"):
            if b["donor"] not in st.rows:
                raise C.MgpError("no riding-style row named " + b["donor"])
            if key not in st.rows:
                st.add_row(key, b["donor"])
                P.save_style()
                return dict(added=True, changed={})
            vals = st.values(b["donor"])
        else:
            vals = b.get("values") or {}
        ch = st.set_values(key, vals)
        if ch:
            P.save_style()
        return dict(added=False, changed={k: list(v) for k, v in ch.items()})

    def clone(q, b):
        P = S.need()
        rel = bike_rel(P, b.get("group", "official"))
        plan, made, warns = P.clone_for_pilot(b["key"], b["tag"], dry_run=bool(b.get("dry_run")), rel=rel)
        t = P.table(rel)
        return dict(problems=plan["problems"], notes=plan["notes"], files=len(plan["jobs"]) if b.get("dry_run") else len(made),
                    warnings=warns, target=t.target(b["key"]), dry_run=bool(b.get("dry_run")),
                    suggest=P.suggest_tag(t.target(b["key"]), t))

    def describe_(q, b):
        P = S.need()
        key = q["key"][0]
        rel = bike_rel(P, (q.get("group") or ["official"])[0])
        t = P.table(rel) if rel else None
        if not t or key not in t.rows:
            return dict(target=None)
        obj = t.target(key)
        if not is_game(obj):
            return dict(target=obj)
        try:
            info = C.resolve_set(P.src, obj)
        except C.MgpError:
            info = None
        return dict(target=obj, tag=info["tag"] if info else None, assets=len(info["members"]) if info else 0,
                    missing=[m.rsplit("/", 1)[1] for m in info["missing"]] if info else [],
                    suggest=P.suggest_tag(obj, t) if info else "")

    # ---- database
    def db_tables(q, b):
        db = S.get_db()
        out = []
        for t in db.tables():
            n = db.con.execute('select count(*) from "%s"' % t).fetchone()[0]
            out.append(dict(name=t, rows=n))
        return out

    def db_rows(q, b):
        db = S.get_db()
        t = q["table"][0]
        if t not in db.tables():
            raise C.MgpError("unknown table " + t)
        text = (q.get("q") or [""])[0].strip().lower()
        off, lim = int(q.get("offset", ["0"])[0]), 200
        cols = [c for c, _ in db.columns(t)]
        rows = db.rows(t)
        if text:
            rows = [r for r in rows if any(text in str(v).lower() for v in r[1:] if v is not None)]
        keycol = "Key" if "Key" in cols else None
        return dict(cols=cols, types=[ty for _, ty in db.columns(t)], total=len(rows), offset=off,
                    rows=[list(r) for r in rows[off:off + lim]], keycol=keycol)

    def db_update(q, b):
        db = S.get_db()
        t, rowid, col = b["table"], int(b["rowid"]), b["col"]
        if col not in [c for c, _ in db.columns(t)]:
            raise C.MgpError("unknown column " + col)
        if t not in db.tables():
            raise C.MgpError("unknown table " + t)
        old = db.con.execute('select "%s" from "%s" where rowid=?' % (col, t), (rowid,)).fetchone()
        if old is None:
            raise C.MgpError("row vanished")
        try:
            val = db.coerce(t, col, b["value"], old[0])
        except ValueError:
            raise C.MgpError("%r is not a valid number for %s" % (b["value"], col))
        try:
            db.update(t, rowid, col, val)
            db.commit()
        except sqlite3.Error as e:
            db.rollback()
            raise C.MgpError("database refused the change: %s" % e)
        return dict(value=val)

    return {
        ("GET", "/api/state"): state, ("GET", "/api/audio/scan"): audio_scan, ("POST", "/api/pak"): pak_mod, ("POST", "/api/launch"): launch, ("GET", "/api/pak/status"): pak_status, ("GET", "/api/sheet"): sheet, ("POST", "/api/sheet/set"): sheet_set, ("POST", "/api/sheet/import"): sheet_import, ("GET", "/api/hud/targets"): hud_targets, ("POST", "/api/hud/scan"): hud_scan, ("POST", "/api/hud/import"): hud_import, ("POST", "/api/hud/modscan"): hud_modscan, ("POST", "/api/hud/compare"): hud_compare, ("POST", "/api/hud/apply"): hud_apply, ("POST", "/api/hud/vis"): hud_vis, ("POST", "/api/hud/vis/set"): hud_vis_set, ("POST", "/api/hud/graft"): hud_graft, ("POST", "/api/hud/swappos"): hud_swappos, ("POST", "/api/fonts/list"): fonts_list, ("POST", "/api/fonts/apply"): fonts_apply, ("GET", "/api/fontswap"): fontswap_list, ("POST", "/api/fontswap/check"): fontswap_check, ("POST", "/api/fontswap/apply"): fontswap_apply, ("POST", "/api/pick"): pick, ("POST", "/api/reveal"): reveal, ("GET", "/api/browse"): browse_list, ("POST", "/api/browse/extract"): browse_extract, ("POST", "/api/browse/clone"): browse_clone, ("POST", "/api/refs"): refs, ("GET", "/api/proj"): proj_list, ("GET", "/api/proj/rider"): proj_rider, ("POST", "/api/proj/set"): proj_set, ("POST", "/api/proj/copy"): proj_copy, ("GET", "/api/loc/files"): loc_files, ("GET", "/api/loc/entries"): loc_entries, ("POST", "/api/loc/set"): loc_set, ("POST", "/api/audio/port"): audio_port,  ("POST", "/api/clonerow"): clone_row, ("GET", "/api/cloneaudit"): clone_audit, ("GET", "/api/teamsync"): teamsync, ("POST", "/api/teamsync"): teamsync_apply, ("GET", "/api/scan"): scan, ("GET", "/api/members"): members, ("POST", "/api/edit"): edit_asset,
        ("POST", "/api/settings"): settings, ("GET", "/api/changes"): changes, ("POST", "/api/save"): save,
        ("POST", "/api/discard"): discard, ("POST", "/api/quit"): quit_, ("POST", "/api/open"): open_, ("GET", "/api/pilots"): pilots,
        ("GET", "/api/bindings"): bindings, ("GET", "/api/choices"): choices, ("POST", "/api/replace"): replace,
        ("POST", "/api/copylook"): copy_look, ("GET", "/api/style"): style_get, ("POST", "/api/style"): style_set, ("POST", "/api/clone"): clone, ("GET", "/api/describe"): describe_,
        ("GET", "/api/db/tables"): db_tables, ("GET", "/api/db/rows"): db_rows, ("POST", "/api/db/update"): db_update,
    }


LOCK_FREE = {"/api/pak/status"}


def _refresh_paks(S):
    """Before a request: re-read any pak replaced on disk (a repacked mod pak copied into Paks), so reads never
    use a stale index ('bad magic'). A stat of each .pak, at most once a second."""
    now = time.time()
    if not S.P or now - getattr(S, "_pak_checked", 0) < 1.0:
        return
    S._pak_checked = now
    try:
        if S.P.refresh_paks():
            S.close_db()
            print("paks changed on disk - re-read them")
    except Exception as e:
        print("could not re-read the paks:", e)


def serve(load_cfg, save_cfg, default_key, port=8765, open_browser=True):
    S = State(load_cfg, save_cfg, default_key)
    S.on_quit = lambda: None
    cfg = load_cfg()
    if cfg.get("game_id", "gp24") != "gp24" and gk("mod_folder", cfg["game_id"]) not in cfg:
        save_cfg(migrate_cfg(cfg))
    g = cfg.get("game_id", "gp24")
    if cfg.get(gk("mod_folder", g)) and os.path.isdir(cfg[gk("mod_folder", g)]):
        try:
            S.open(cfg[gk("mod_folder", g)], cfg.get(gk("paks_dir", g), ""), "", cfg.get(gk("include_patch", g), True), g)
        except Exception as e:
            print("could not reopen last project:", e)
    api = make_api(S)
    page = open(os.path.join(HERE, "webui.html"), encoding="utf-8").read().replace("__TOKEN__", S.token)

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"                    # keep-alive: no new connection per API call (every reply has Content-Length)

        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def handle_any(self, method):
            u = urlparse(self.path)
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                return self.send(403, "bad host", "text/plain")
            if method == "GET" and u.path in ("/", "/index.html"):
                return self.send(200, page, "text/html")
            if u.path == "/favicon.ico":
                return self.send(204, b"", "image/x-icon")
            fn = api.get((method, u.path))
            if not fn:
                return self.send(404, json.dumps(dict(error="not found")))
            if self.headers.get("X-MGP-Token") != S.token:
                return self.send(403, json.dumps(dict(error="bad token - reload the page")))
            try:
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                t0 = time.time()
                if u.path in LOCK_FREE:                  # progress polling must not wait behind a slow request
                    res = fn(parse_qs(u.query), body)
                else:
                    with S.lock:
                        _refresh_paks(S)
                        res = fn(parse_qs(u.query), body)
                if time.time() - t0 > 1.0 and u.path != "/api/pak/status":
                    print("[slow] %s %s took %.1fs" % (method, u.path, time.time() - t0))
                self.send(200, json.dumps(res, default=str))
            except C.MgpError as e:
                self.send(400, json.dumps(dict(error=str(e))))
            except KeyError as e:
                traceback.print_exc()
                what = e.args[0] if e.args else None
                msg = ("no entry selected - click an entry on the left, then try again" if what is None
                       else "missing or unknown value: %s" % (what,))
                self.send(400, json.dumps(dict(error=msg)))
            except Exception as e:
                traceback.print_exc()
                self.send(500, json.dumps(dict(error="%s: %s" % (type(e).__name__, e))))

        def do_GET(self):
            self.handle_any("GET")

        def do_POST(self):
            self.handle_any("POST")

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    S.on_quit = lambda: threading.Thread(target=srv.shutdown, daemon=True).start()
    url = "http://127.0.0.1:%d/" % port
    print("Master Editor running at", url, " (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
