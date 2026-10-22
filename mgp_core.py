"""MotoGP 24 Master Editor - core logic (no GUI, no third-party deps).

Model of the game data (verified on the chassis103 sample):
  db.sqlite3  Pilots.Key  ==  row name in DT_BikeOfficial
  DT_BikeOfficial row     ->  soft path to a customization_data asset (bikeCCC_VVV)
  customization_data      ->  material_instances (mat_*VVV)  ->  textures (*VVV_*)

Clone = copy that set under a new 3-digit variant tag.  Because the tag has the
same length as the old one, a clone is a same-length rewrite of the name table
inside each .uasset; every other byte (and every .uexp/.ubulk) is copied as is.
"""
import os, re, shutil, sqlite3, struct, time

PKG_TAG = 0x9E2A83C1
STAGING = "_mgp_unsaved"
DT_REL = "Content/assets/graphics/bindings/Vehicles/Official/DT_BikeOfficial"
DB_REL = "Content/assets/data/db/NoCook/db.sqlite3"
BIND_DIR = "Content/assets/graphics/bindings"
STYLE_REL = "Content/assets/data/datatables/Anim/RidingStyle_DT"
SIDECARS = (".uasset", ".uexp", ".ubulk")
# Supported games: id -> Unreal project folder name. MotoGP 25 (UE5.5, IoStore) is limited to the non-asset
# files that stay in its .pak (Localization .locres, Database db.sqlite3); its .uassets live in .utoc/.ucas.
GAMES = {"gp24": "motogp24", "gp25": "motogp25"}


class MgpError(Exception):
    pass


# ----------------------------------------------------------------- .uasset
def _name_hash(text):
    """Non-case-preserving name hash as stored in the name table (verified against 304 real names)."""
    global _HT
    if "_HT" not in globals():
        _HT = []
        for i in range(256):
            c = i << 24
            for _ in range(8):
                c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
            _HT.append(c)
    x = 0
    for ch in text.upper():
        x = ((x >> 8) & 0xFFFFFF) ^ _HT[(x ^ ord(ch)) & 0xFF]
    return x & 0xFFFF


class UAsset:
    """Cooked UE4.27 .uasset: name table access, same-length renames and appending names.

    Appending only adds bytes at the END of the name table, so every existing name index stays valid;
    the offsets of everything after it (and the export's SerialOffset) are shifted by the added size."""

    EXPORT_SIZE = 104

    def __init__(self, data):
        self.data = bytearray(data)
        d = self.data
        if len(d) < 64 or struct.unpack_from("<I", d, 0)[0] != PKG_TAG:
            raise MgpError("not a .uasset (bad magic)")
        self.p = 4
        self.f = {}                                    # summary field name -> position

        def i32(name=None):
            if name:
                self.f[name] = self.p
            v = struct.unpack_from("<i", d, self.p)[0]
            self.p += 4
            return v

        def fstr():
            n = i32()
            self.p += n if n > 0 else -n * 2

        legacy = i32(); i32(); i32()                   # legacy ver, ue3 ver, ue4 ver
        if legacy <= -8:
            i32()
        i32()                                          # licensee ver
        ncv = i32(); self.p += ncv * 20                # custom versions
        i32("total"); fstr()
        flags = struct.unpack_from("<I", d, self.p)[0]; self.p += 4
        if not flags & 0x80000000:
            raise MgpError("asset is not cooked (FilterEditorOnly missing); unsupported")
        count = i32("namecount"); offset = i32("nameoff")
        i32("gathercount"); i32("gatheroff")
        i32("exportcount"); i32("exportoff"); i32("importcount"); i32("importoff")
        i32("dependsoff"); i32("softcount"); i32("softoff"); i32("searchoff"); i32("thumboff")
        self.p += 16                                   # guid
        ngen = i32(); self.p += ngen * 8
        self.p += 10; fstr(); self.p += 10; fstr()     # saved-by / compatible engine versions
        self.p += 4; nch = i32(); self.p += nch * 0 + 4
        nadd = i32()
        for _ in range(nadd):
            fstr()
        i32("assetregoff"); self.f["bulk"] = self.p; self.p += 8
        i32("worldoff"); nci = i32(); self.p += nci * 4
        i32("preloadcount"); i32("preloadoff")
        self.names, p = [], offset
        for _ in range(count):
            ln = struct.unpack_from("<i", d, p)[0]; p += 4
            if ln > 0:
                self.names.append(dict(text=bytes(d[p:p + ln - 1]).decode("latin1"), pos=p, nbytes=ln - 1, wide=False)); p += ln
            elif ln < 0:
                self.names.append(dict(text=bytes(d[p:p + (-ln - 1) * 2]).decode("utf-16le"), pos=p, nbytes=(-ln - 1) * 2, wide=True)); p += -ln * 2
            else:
                self.names.append(dict(text="", pos=p, nbytes=0, wide=False))
            p += 4                                     # two uint16 hashes
        self.names_end = p

    def _get(self, name, fmt="<i"):
        return struct.unpack_from(fmt, self.data, self.f[name])[0]

    def _set(self, name, v, fmt="<i"):
        struct.pack_into(fmt, self.data, self.f[name], v)

    def texts(self):
        return [n["text"] for n in self.names]

    def export_object_names(self):
        off, cnt = self._get("exportoff"), self._get("exportcount")
        out = []
        for i in range(cnt):
            idx = struct.unpack_from("<i", self.data, off + i * self.EXPORT_SIZE + 16)[0]
            out.append(self.names[idx]["text"])
        return out

    def rename(self, idx, new):
        n = self.names[idx]
        if n["wide"] or not new.isascii():
            raise MgpError("cannot rename non-ASCII name %r" % n["text"])
        if len(new) != n["nbytes"]:
            raise MgpError("same-length rename required: %r -> %r" % (n["text"], new))
        self.data[n["pos"]:n["pos"] + n["nbytes"]] = new.encode("ascii")
        n["text"] = new

    def _check_layout(self):
        n = self._get("exportcount")
        if self._get("importoff") != self.names_end or self._get("dependsoff") - self._get("exportoff") != n * self.EXPORT_SIZE:
            raise MgpError("unexpected asset layout; refusing to resize its name table")

    def _shift_after(self, at, delta):
        """The name table changed size by `delta` at old position `at` (its old end): move everything after it."""
        for k in ("gatheroff", "exportoff", "importoff", "dependsoff", "softoff", "searchoff", "thumboff",
                  "assetregoff", "worldoff", "preloadoff"):
            v = self._get(k)
            if v and v >= at:
                self._set(k, v + delta)
        bulk = self._get("bulk", "<q")
        if bulk >= at:
            self._set("bulk", bulk + delta, "<q")
        self._set("total", self._get("total") + delta)
        eo = self._get("exportoff")
        for i in range(self._get("exportcount")):
            q = eo + i * self.EXPORT_SIZE + 36          # SerialOffset
            struct.pack_into("<q", self.data, q, struct.unpack_from("<q", self.data, q)[0] + delta)

    @staticmethod
    def _entry(text):
        return struct.pack("<i", len(text) + 1) + text.encode("ascii") + b"\0" + struct.pack("<HH", _name_hash(text), 0)

    def append_name(self, text):
        """Add a name at the end of the name table; returns its index. Existing indices do not change."""
        if not text.isascii():
            raise MgpError("cannot add non-ASCII name")
        self._check_layout()
        blob = self._entry(text)
        at = self.names_end
        self.data[at:at] = blob
        self._shift_after(at, len(blob))
        self._set("namecount", self._get("namecount") + 1)
        self.names.append(dict(text=text, pos=at + 4, nbytes=len(text), wide=False))
        self.names_end += len(blob)
        return len(self.names) - 1

    def replace_name(self, idx, text):
        """Give name `idx` a new text of any length (indices stay valid)."""
        n = self.names[idx]
        if n["wide"] or not text.isascii():
            raise MgpError("cannot rename non-ASCII name %r" % n["text"])
        if len(text) == n["nbytes"]:
            return self.rename(idx, text)
        self._check_layout()
        start, end = n["pos"] - 4, n["pos"] + n["nbytes"] + 1 + 4
        blob = self._entry(text)
        delta, at = len(blob) - (end - start), self.names_end
        self.data[start:end] = blob
        for m in self.names[idx + 1:]:
            m["pos"] += delta
        n["pos"], n["nbytes"], n["text"] = start + 4, len(text), text
        self.names_end += delta
        self._shift_after(at, delta)

    def to_bytes(self):
        return bytes(self.data)


# ------------------------------------------------------------ binding table
class BindingTable:
    """DT_BikeOfficial: DataTable of IgnitionDataAssetTableRow {DataAsset: SoftObjectPath}."""

    def __init__(self, uasset_bytes, uexp_bytes):
        self.ua = UAsset(uasset_bytes)
        self.uexp = bytearray(uexp_bytes)
        self.rows = {}        # row name -> dict(value_off)
        self._parse()

    def _fname(self, p):
        i, n = struct.unpack_from("<ii", self.uexp, p)
        return self.ua.names[i]["text"], i, n

    def _props(self, p):
        """Walk tagged properties until 'None'. Returns (props, end_offset); props: name -> (type, value_off, size)."""
        props = {}
        while True:
            name, _, _ = self._fname(p); p += 8
            if name == "None":
                return props, p
            typ, _, _ = self._fname(p); p += 8
            size = struct.unpack_from("<i", self.uexp, p)[0]; p += 8
            p += 1                             # HasPropertyGuid (0 for these types)
            props[name] = (typ, p, size)
            p += size

    def _parse(self):
        d = self.uexp
        _, p = self._props(0)
        p += 4                                 # ObjectGuid flag
        count = struct.unpack_from("<i", d, p)[0]; p += 4
        for _ in range(count):
            row, _, _ = self._fname(p); p += 8
            props, p = self._props(p)
            typ, off, size = props.get("DataAsset", (None, 0, 0))
            if typ != "SoftObjectProperty" or size != 12:
                raise MgpError("unexpected row layout in %s" % row)
            self.rows[row] = dict(off=off)
        if struct.unpack_from("<I", d, p)[0] != PKG_TAG:
            raise MgpError("DataTable footer mismatch - layout not understood")

    # target = "/Game/.../bikeCCC_VVV.bikeCCC_VVV"
    def target_index(self, row):
        return struct.unpack_from("<i", self.uexp, self.rows[row]["off"])[0]

    def target(self, row):
        return self.ua.names[self.target_index(row)]["text"]

    def users_of(self, idx):
        return [r for r in self.rows if self.target_index(r) == idx]

    def set_target(self, row, new_obj_path):
        """Point `row` at new_obj_path ('/Game/...pkg.obj'): reuse an existing name, rewrite the row's own
        name in place (same length, not shared), or append new names to the table."""
        idx = self.target_index(row)
        old = self.ua.names[idx]["text"]
        if new_obj_path == old:
            return
        if not new_obj_path.startswith("/Game/") or "." not in new_obj_path:
            raise MgpError("target must look like /Game/.../pkg.obj")
        texts = self.ua.texts()
        off = self.rows[row]["off"]
        if new_obj_path in texts:                          # an entry another row already uses
            struct.pack_into("<i", self.uexp, off, texts.index(new_obj_path))
            return
        new_pkg = new_obj_path.partition(".")[0]
        old_pkg = old.partition(".")[0]
        if len(new_obj_path) == len(old) and len(self.users_of(idx)) == 1 and new_pkg not in texts:
            for i, t in enumerate(texts):                  # object path and package path entries
                if t == old:
                    self.ua.rename(i, new_obj_path)
                elif t == old_pkg:
                    self.ua.rename(i, new_pkg)
            return
        if new_pkg not in texts:
            self.ua.append_name(new_pkg)
        new_idx = self.ua.append_name(new_obj_path)
        struct.pack_into("<i", self.uexp, off, new_idx)

    def save(self, uasset_path, uexp_path):
        with open(uasset_path, "wb") as f:
            f.write(self.ua.to_bytes())
        with open(uexp_path, "wb") as f:
            f.write(bytes(self.uexp))


# ------------------------------------------------------------ riding style table
class StyleTable:
    """RidingStyle_DT: one row per rider key (same keys as the binding tables), each a fixed set of
    Int/Float properties (RidingStyle, SubRidingStyle, StartLeg, LegOut, ...). Rows without '_'
    (Balanced, Centered, ElbowOut, ShouldersOut, BodyOut, OldSchool) are the game's presets."""
    FMT = {"IntProperty": "<i", "FloatProperty": "<f"}

    def __init__(self, uasset_bytes, uexp_bytes):
        self.ua = UAsset(uasset_bytes)
        self.uexp = bytearray(uexp_bytes)
        self._parse()

    def _fname(self, p):
        i, n = struct.unpack_from("<ii", self.uexp, p)
        t = self.ua.names[i]["text"]
        return (t + "_%d" % (n - 1) if n else t), p + 8

    def _parse(self):
        d = self.uexp
        self.rows, self.order = {}, []                 # key -> {prop: (type, value_off)}; row start/end
        p = 0
        while True:                                    # object properties (RowStruct)
            name, p = self._fname(p)
            if name == "None":
                break
            typ, p = self._fname(p)
            if typ != "ObjectProperty":
                raise MgpError("RidingStyle_DT: unexpected %s %s in header" % (typ, name))
            p += 8 + 1 + struct.unpack_from("<i", d, p)[0]
        p += 4                                         # ObjectGuid flag
        self.count_off = p
        count = struct.unpack_from("<i", d, p)[0]; p += 4
        for _ in range(count):
            start = p
            row, p = self._fname(p)
            props = {}
            while True:
                name, p = self._fname(p)
                if name == "None":
                    break
                typ, p = self._fname(p)
                size = struct.unpack_from("<i", d, p)[0]; p += 8 + 1
                if typ not in self.FMT or size != 4:
                    raise MgpError("RidingStyle_DT: %s.%s is %s (%d bytes) - layout not understood" % (row, name, typ, size))
                props[name] = (typ, p)
                p += size
            self.rows[row] = props
            self.order.append((row, start, p))
        self.rows_end = p
        if struct.unpack_from("<I", d, p)[0] != PKG_TAG:
            raise MgpError("RidingStyle_DT footer mismatch - layout not understood")

    def presets(self):
        return [r for r in self.rows if "_" not in r]

    def values(self, key):
        out = {}
        for name, (typ, off) in self.rows[key].items():
            v = struct.unpack_from(self.FMT[typ], self.uexp, off)[0]
            out[name] = v if typ == "IntProperty" else round(v, 4)
        return out

    def types(self, key):
        return {n: t for n, (t, _) in self.rows[key].items()}

    def set_values(self, key, vals):
        """Write the given {prop: number}; returns {prop: (old, new)} for what changed."""
        if key not in self.rows:
            raise MgpError("no riding-style row for " + key)
        old, changed = self.values(key), {}
        for name, v in vals.items():
            if name not in self.rows[key]:
                raise MgpError("unknown riding-style field: " + name)
            typ, off = self.rows[key][name]
            v = int(v) if typ == "IntProperty" else float(v)
            struct.pack_into(self.FMT[typ], self.uexp, off, v)
            new = self.values(key)[name]
            if new != old[name]:
                changed[name] = (old[name], new)
        return changed

    def add_row(self, key, donor):
        """Append a row for `key` that copies `donor`'s values (export size and bulk offset follow)."""
        if key in self.rows:
            raise MgpError("%s already has a riding-style row" % key)
        if donor not in self.rows:
            raise MgpError("no riding-style row for " + donor)
        texts = self.ua.texts()
        idx = texts.index(key) if key in texts else self.ua.append_name(key)
        _, start, end = next(o for o in self.order if o[0] == donor)
        blob = struct.pack("<ii", idx, 0) + bytes(self.uexp[start + 8:end])
        at = self.rows_end
        self.uexp[at:at] = blob
        struct.pack_into("<i", self.uexp, self.count_off, struct.unpack_from("<i", self.uexp, self.count_off)[0] + 1)
        eo = self.ua._get("exportoff")
        if self.ua._get("exportcount") != 1:
            raise MgpError("RidingStyle_DT: expected one export")
        sz = struct.unpack_from("<q", self.ua.data, eo + 28)[0]
        struct.pack_into("<q", self.ua.data, eo + 28, sz + len(blob))
        bulk = self.ua._get("bulk", "<q")
        if bulk:
            self.ua._set("bulk", bulk + len(blob), "<q")
        self._parse()

    def save(self, uasset_path, uexp_path):
        with open(uasset_path, "wb") as f:
            f.write(self.ua.to_bytes())
        with open(uexp_path, "wb") as f:
            f.write(bytes(self.uexp))


# ---------------------------------------------------------------- file source
def game_to_rel(game_path):
    if not game_path.startswith("/Game/"):
        raise MgpError("not a /Game path: " + game_path)
    return "Content/" + game_path[len("/Game/"):]


class Source:
    """Layered read access: [staging folder] > mod folder (loose files) > the game's paks.
    `work` is where writes go (the mod folder, or the staging folder when `base` is given).
    Paths are relative to the project folder, e.g. 'Content/assets/data/db/NoCook/db.sqlite3'."""

    def __init__(self, work_root, paks=None, base=None):
        self.work, self.paks, self.base = work_root, paks, base

    def loose(self, rel):
        return os.path.join(self.work, *rel.split("/"))

    def _base(self, rel):
        return os.path.join(self.base, *rel.split("/")) if self.base else None

    def _layers(self, rel):
        return [p for p in (self.loose(rel), self._base(rel)) if p]

    def exists(self, rel):
        return any(os.path.exists(p) for p in self._layers(rel)) or bool(self.paks and self.paks.exists(rel))

    def read(self, rel):
        for p in self._layers(rel):
            if os.path.exists(p):
                with open(p, "rb") as f:
                    return f.read()
        if self.paks and self.paks.exists(rel):
            return self.paks.read(rel)
        raise MgpError("file not found in mod folder or paks: " + rel)

    def read_underlying(self, rel):
        """What `rel` would be if nothing were staged (None if it would not exist)."""
        p = self._base(rel)
        if p and os.path.exists(p):
            with open(p, "rb") as f:
                return f.read()
        if self.paks and self.paks.exists(rel):
            return self.paks.read(rel)
        return None

    def find(self, rel_dir, ext, loose_only=False):
        """Files below rel_dir ending in ext; loose_only: only the mod folder / staging (no paks)."""
        out = set()
        for root in (self.work, self.base):
            if not root:
                continue
            for d, _, fs in os.walk(os.path.join(root, *rel_dir.split("/"))):
                for f in fs:
                    if f.endswith(ext):
                        out.add(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))
        if self.paks and not loose_only:
            out |= self._pak_find(rel_dir, ext)
        return sorted(out)

    def _pak_find(self, rel_dir, ext):
        """paks.find, remembered until the paks change (the pak index is fixed while a pak is open)."""
        c = self.__dict__.setdefault("_pf", {})
        k = (self.paks.gen, rel_dir.lower(), ext)
        if k not in c:
            if len(c) > 64:
                c.clear()
            c[k] = frozenset(self.paks.find(rel_dir, ext))
        return c[k]

    def origin(self, rel):
        if os.path.exists(self.loose(rel)):
            return "unsaved" if self.base else "mod folder"
        if self.base and os.path.exists(self._base(rel)):
            return "mod folder"
        return self.paks.which(rel) if self.paks and self.paks.exists(rel) else "missing"


def find_root(path, project="motogp24"):
    """Mod/working folder: the folder that holds Content/, or its parent (e.g. 'motogp24')."""
    for cand in (path, os.path.join(path, project)):
        if os.path.isdir(os.path.join(cand, "Content")):
            return cand
    if os.path.isdir(path):
        return path
    raise MgpError("not a folder: " + path)


class Member:
    def __init__(self, pkg):
        self.pkg = pkg                                   # /Game/.../name
        self.base = pkg.rsplit("/", 1)[1]

    def rels(self, src):
        stem = game_to_rel(self.pkg)
        return [stem + e for e in SIDECARS if src.exists(stem + e)]


def _asset_names(src, pkg):
    rel = game_to_rel(pkg) + ".uasset"
    return UAsset(src.read(rel)).texts() if src.exists(rel) else None


def resolve_set(src, obj_path, tag=None):
    """All assets of one variant: the customization_data plus everything it references
    inside the same chassis folder whose name carries the variant tag."""
    pkg = obj_path.partition(".")[0]
    parts = pkg.split("/")
    if "customization_data" not in parts:
        raise MgpError("target is not a customization_data asset: " + pkg)
    base = parts[-1]
    if tag is None:
        if "_" not in base:
            raise MgpError("cannot find variant tag in " + base)
        tag = base.rsplit("_", 1)[1]
    chassis_dir = "/".join(parts[:parts.index("customization_data")])
    members, missing, queue, seen = [], [], [pkg], {pkg}
    while queue:
        cur = queue.pop(0)
        names = _asset_names(src, cur)
        if names is None:
            missing.append(cur)
            continue
        members.append(Member(cur))
        for t in names:
            if t.startswith(chassis_dir + "/") and "." not in t and tag in t.rsplit("/", 1)[1] and t not in seen:
                seen.add(t)
                queue.append(t)
    return dict(tag=tag, chassis_dir=chassis_dir, members=members, missing=missing)


def _mapping(info, new_tag):
    if not re.fullmatch(r"[0-9A-Za-z]+", new_tag) or len(new_tag) != len(info["tag"]) or new_tag == info["tag"]:
        raise MgpError("new tag must be %d letters/digits and differ from %s" % (len(info["tag"]), info["tag"]))
    pkgmap, basemap = {}, {}
    for m in info["members"]:
        nb = m.base.replace(info["tag"], new_tag)
        basemap[m.base] = nb
        pkgmap[m.pkg] = m.pkg.rsplit("/", 1)[0] + "/" + nb
    return pkgmap, basemap


def _rename_asset(ua, pkgmap, basemap):
    for i, n in enumerate(ua.names):
        s = n["text"]
        if s.startswith("/Game/"):
            pkg, dot, obj = s.partition(".")
            if pkg in pkgmap:
                new = pkgmap[pkg] + (dot + basemap.get(obj, obj) if dot else "")
                ua.rename(i, new)
        elif s in basemap:
            ua.rename(i, basemap[s])


def plan_clone(src, obj_path, new_tag, dt=None, tag=None):
    info = resolve_set(src, obj_path, tag)
    pkgmap, basemap = _mapping(info, new_tag)
    problems, notes = [], []
    if info["missing"]:
        notes.append("not available (mod folder or paks), so the clone keeps pointing at the original: " +
                     ", ".join(m.rsplit("/", 1)[1] for m in info["missing"]))
    jobs = []
    for m in info["members"]:
        newstem = game_to_rel(pkgmap[m.pkg])
        for s in m.rels(src):
            ext = os.path.splitext(s)[1]
            dst = newstem + ext
            if src.exists(dst):
                problems.append("already exists (%s): %s" % (src.origin(dst), dst))
            jobs.append((s, dst, ext == ".uasset"))
    if dt is not None:
        new_obj = pkgmap[obj_path.partition(".")[0]] + "." + basemap[obj_path.rpartition(".")[2]]
        if new_obj in dt.ua.texts():
            problems.append("tag %s is already used by a rider in the game's bindings" % new_tag)
    return dict(info=info, pkgmap=pkgmap, basemap=basemap, jobs=jobs, problems=problems, notes=notes)


def do_clone(src, plan):
    if plan["problems"]:
        raise MgpError("; ".join(plan["problems"]))
    made, warnings = [], []
    olds = list(plan["basemap"])
    try:
        for s, dst_rel, is_asset in plan["jobs"]:
            dst = src.loose(dst_rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            blob = src.read(s)
            if is_asset:
                ua = UAsset(blob)
                _rename_asset(ua, plan["pkgmap"], plan["basemap"])
                left = [n["text"] for n in ua.names if any(o in n["text"] for o in olds)]
                if left:
                    warnings.append("%s still mentions old names: %s" % (os.path.basename(dst), left))
                blob = ua.to_bytes()
            elif s.endswith(".uexp") and any(o.encode() in blob for o in olds):
                warnings.append(os.path.basename(s) + " embeds an old asset name in its data")
            with open(dst, "wb") as fh:
                fh.write(blob)
            made.append(dst)
    except Exception:
        for f in made:
            os.remove(f)
        raise
    return made, warnings


def group_of(rel):
    """'official' (keyed by rider), 'custom' (custom-team/custom-rider entries), 'teams' or 'other'."""
    n = rel.rsplit("/", 1)[1]
    if "/Custom/" in rel or n.endswith(("_Custom", "BikeCustom")):
        return "custom"
    if "/OfficialTeams/" in rel or n.endswith(("_Teams", "BikeTeams")):
        return "teams"
    if "/Official/" in rel or n.endswith(("_Official", "BikeOfficial")):
        return "official"
    return "other"


BIKE_TABLE = {"official": "DT_BikeOfficial", "custom": "DT_BikeCustom", "teams": "DT_BikeTeams"}


def category(rel):
    n = rel.rsplit("/", 1)[1].upper()
    for c in ("HELMET", "SUIT", "GLOVES", "BOOTS", "BUTTPATCH"):
        if c in n:
            return c.lower()
    for c in ("FACE", "HAIR", "HEAD", "HANDS"):
        if c in n:
            return "face"
    return "bike" if ("/Vehicles/" in rel or "_BIKE" in n or "BOX_" in n) else "other"


# ------------------------------------------------------------------- project
def normalize_target(text):
    """Accept what people paste: a rider row name, /Game/... path, or a file path such as
    'motogp24/Content/assets/.../Name.uasset' (-> '/Game/assets/.../Name')."""
    import re
    t = (text or "").strip().strip("\"'").replace("\\", "/")
    if "/" not in t or t.startswith("/Game/"):
        pass
    else:
        m = re.search(r"(?i)(?:^|/)content/(.+)$", t)
        if m:
            t = "/Game/" + m.group(1)
    if t.startswith("/Game/"):
        t = re.sub(r"(?i)\.(uasset|uexp|ubulk|umap)$", "", t)
    return t


class Project:
    def __init__(self, work, paks_dir=None, key=None, include_patch=True, staged=False, game="gp24"):
        if game not in GAMES:
            raise MgpError("unknown game %r" % game)
        self.game, self.project = game, GAMES[game]
        self.real_root = find_root(work, self.project)
        self.staged = staged
        self.root = os.path.join(self.real_root, STAGING) if staged else self.real_root
        self.paks = None
        if paks_dir:
            from mgp_pak import PakSet, PakError
            try:
                self.paks = PakSet(paks_dir, key or "", project=self.project, include_patch=include_patch)
            except PakError as e:
                raise MgpError(str(e))
        self.src = Source(self.root, self.paks, self.real_root if staged else None)
        self.dt_rel = DT_REL
        self.dt_stem = self.src.loose(DT_REL)
        self.db_path = self.src.loose(DB_REL)
        self.backup_dir = os.path.join(self.real_root, "_mgp_backup", time.strftime("%Y%m%d-%H%M%S"))
        self._backed = set()
        self.reload_bindings()

    def reload_bindings(self):
        self._tables, self._names, self._style = {}, None, None
        if self.game != "gp24":                      # GP25's binding tables are zen assets in .utoc/.ucas: not read yet
            self._names, self.dt = [], None
            return
        self.dt = self.table(DT_REL)                 # the bike table (DT_BikeOfficial)

    def refresh_paks(self):
        """Pick up paks that were added/replaced since opening (e.g. a repacked mod pak). True if any changed."""
        if not self.paks or not self.paks.refresh():
            return False
        self.__dict__.pop("_cmp", None)              # staged-vs-pak comparisons were made against the old paks
        self.reload_bindings()                       # tables not in the mod folder came from the old paks
        return True

    # ---- every binding DataTable (riders' gear, suits, bike extras, ...)
    def table(self, rel):
        if rel not in self._tables:
            self._tables[rel] = BindingTable(self.src.read(rel + ".uasset"), self.src.read(rel + ".uexp"))
        return self._tables[rel]

    def table_names(self):
        if self._names is None:
            self._names = [p[:-len(".uasset")] for p in self.src.find(BIND_DIR, ".uasset")]
        return self._names

    def group_for(self, rel, key):
        """Which view a row belongs to: official-named tables that hold team keys (not riders) count as 'teams'."""
        g = group_of(rel)
        return "teams" if g == "official" and key not in self.dt.rows else g

    def pilot_bindings(self, key, group=None):
        """[(table rel path, category, target)] for every binding table that has a row named `key`."""
        out = []
        for rel in self.table_names():
            if group and self.group_for(rel, key) != group:
                continue
            try:
                t = self.table(rel)
            except Exception:
                continue
            if key in t.rows:
                out.append((rel, category(rel), t.target(key)))
        return out

    # ---- riding style (RidingStyle_DT, keyed like the binding tables)
    def style(self):
        if self._style is None:
            self._style = StyleTable(self.src.read(STYLE_REL + ".uasset"), self.src.read(STYLE_REL + ".uexp"))
        return self._style

    def save_style(self):
        stem = self.src.loose(STYLE_REL)
        os.makedirs(os.path.dirname(stem), exist_ok=True)
        for e in (".uasset", ".uexp"):
            self.backup(stem + e)
        self.style().save(stem + ".uasset", stem + ".uexp")

    def save_table(self, rel):
        stem = self.src.loose(rel)
        os.makedirs(os.path.dirname(stem), exist_ok=True)
        for e in (".uasset", ".uexp"):
            self.backup(stem + e)
        self.table(rel).save(stem + ".uasset", stem + ".uexp")

    def object_path(self, pkg):
        """'/Game/.../pkg' -> '/Game/.../pkg.ObjectName' using the asset's own export name."""
        rel = game_to_rel(pkg) + ".uasset"
        if not self.src.exists(rel):
            raise MgpError("asset not found in mod folder or paks: " + pkg)
        names = UAsset(self.src.read(rel)).export_object_names()
        if not names:
            raise MgpError("asset has no exports: " + pkg)
        return pkg + "." + names[0]

    def candidates(self, rel, key):
        """Packages that could replace this row's current target (same kind of asset), sorted."""
        cur = self.table(rel).target(key).partition(".")[0]
        parts = cur.split("/")
        if "customization_data" in parts:
            i = parts.index("customization_data")
            root = parts[:i]
            if root and re.search(r"\d+$", root[-1]):
                root = root[:-1]
            folder, must = "/".join(root), "/customization_data/"
        else:
            folder, must = "/".join(parts[:-1]), None
        out = []
        for f in self.src.find(game_to_rel(folder), ".uasset"):
            pkg = "/Game/" + f[len("Content/"):-len(".uasset")]
            if must and must not in pkg:
                continue
            if not must and pkg.rsplit("/", 1)[0].lower() != "/".join(parts[:-1]).lower():
                continue
            out.append(pkg)
        seen = {}                       # paks and the mod folder may spell folders differently (MotoGp/MotoGP)
        for pkg in sorted(set(out)):
            k = pkg.lower()
            if k not in seen or pkg.rsplit("/", 1)[0] == "/".join(parts[:-1]):
                seen[k] = pkg
        return sorted(seen.values())

    def repoint_in(self, rel, key, target):
        """`target`: another row's name in the same table, a package path (/Game/.../pkg) or a full object
        path (/Game/.../pkg.obj)."""
        t = self.table(rel)
        target = normalize_target(target)
        if not target.startswith("/Game/"):
            if target not in t.rows:
                raise MgpError("%s has no row %r - type a rider name from this table or a /Game/... path" % (rel.rsplit("/", 1)[1], target))
            target = t.target(target)
        elif "." not in target.rsplit("/", 1)[1]:
            target = self.object_path(target)
        t.set_target(key, target)
        self.save_table(rel)
        pkg = target.partition(".")[0]
        if not self.src.exists(game_to_rel(pkg) + ".uasset"):
            return "warning: %s was not found in the mod folder or paks - the game will only load it if it exists there" % pkg.rsplit("/", 1)[1]
        return None

    # ---- replacing with an asset that does not exist yet
    def target_status(self, rel, key, target):
        """Where would this replacement point, and does that asset exist? ->
        dict(exists, pkg, obj or None, donor_row)."""
        t = self.table(rel)
        target = normalize_target(target)
        if not target.startswith("/Game/"):
            if target not in t.rows:
                raise MgpError("%s has no row %r - type a rider name from this table or a /Game/... path" % (rel.rsplit("/", 1)[1], target))
            obj = t.target(target)
            return dict(exists=True, pkg=obj.partition(".")[0], obj=obj, donor=target)
        pkg, dot, objname = target.partition(".")
        return dict(exists=self.src.exists(game_to_rel(pkg) + ".uasset"), pkg=pkg, obj=target if dot else None, donor=None)

    def _dup_asset(self, old_pkg, new_pkg):
        """Copy ONE data asset to a new package name (any length). It keeps pointing at the original's
        materials/textures."""
        stem_old, stem_new = game_to_rel(old_pkg), game_to_rel(new_pkg)
        if self.src.exists(stem_new + ".uasset"):
            raise MgpError("already exists: " + new_pkg)
        if not self.src.exists(stem_old + ".uasset"):
            raise MgpError("the asset being copied is not available: " + old_pkg)
        if self.src.exists(stem_old + ".ubulk"):
            raise MgpError("this asset has bulk data (a texture); only data assets can be copied on their own")
        ua = UAsset(self.src.read(stem_old + ".uasset"))
        idxs = [i for i, n in enumerate(ua.names) if n["text"] == old_pkg]
        if not idxs:
            raise MgpError("package name not found inside " + old_pkg.rsplit("/", 1)[1])
        for i in idxs:
            ua.replace_name(i, new_pkg)
        made = []
        dst = self.src.loose(stem_new)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst + ".uasset", "wb") as f:
            f.write(ua.to_bytes())
        made.append(dst + ".uasset")
        if self.src.exists(stem_old + ".uexp"):
            with open(dst + ".uexp", "wb") as f:
                f.write(self.src.read(stem_old + ".uexp"))
            made.append(dst + ".uexp")
        return made

    @staticmethod
    def _infer_tag(old, new):
        """The differing middle part of two names, widened to whole digit runs: helmet_109 / helmet_900 -> 109, 900."""
        n = min(len(old), len(new))
        i = 0
        while i < n and old[i] == new[i]:
            i += 1
        j = 0
        while j < n - i and old[-1 - j] == new[-1 - j]:
            j += 1
        a = i
        while a > 0 and old[a - 1].isdigit():
            a -= 1
        oe, ne = len(old) - j, len(new) - j
        while oe < len(old) and old[oe].isdigit():
            oe += 1; ne += 1
        return old[a:oe], new[a:ne]

    def _dup_set(self, old_obj, new_pkg, dry=False):
        """Copy the asset plus its variant-specific materials/textures, renaming the variant token."""
        old_pkg = old_obj.partition(".")[0]
        if old_pkg.rsplit("/", 1)[0] != new_pkg.rsplit("/", 1)[0]:
            raise MgpError("a full-set copy needs the new asset in the same folder as the old one")
        old_tok, new_tok = self._infer_tag(old_pkg.rsplit("/", 1)[1], new_pkg.rsplit("/", 1)[1])
        if not old_tok or len(old_tok) != len(new_tok):
            raise MgpError("full-set copy needs a same-length variant number that differs (e.g. helmet_109 -> helmet_900)")
        plan = plan_clone(self.src, old_obj, new_tok, None, tag=old_tok)
        if plan["pkgmap"].get(old_pkg) != new_pkg:
            raise MgpError("cannot derive %s from %s by replacing %s with %s" % (new_pkg.rsplit("/", 1)[1], old_pkg.rsplit("/", 1)[1], old_tok, new_tok))
        if dry:
            return plan
        made, warnings = do_clone(self.src, plan)
        return made, warnings, plan["notes"]

    def propose_name(self, pkg, table=None):
        """A free name for a copy of `pkg`: the last number in the name replaced by an unused one of the same
        width (bike103_001 -> bike103_901), or '_2', '_3'... appended when the name has no number."""
        folder, base = pkg.rsplit("/", 1)
        used = " ".join(table.ua.texts()) if table is not None else ""
        free = lambda b: not self.src.exists(game_to_rel(folder + "/" + b) + ".uasset") and (folder + "/" + b) not in used
        runs = list(re.finditer(r"\d+", base))
        if runs:
            m = runs[-1]
            w = len(m.group())
            start = 9 * 10 ** (w - 1) + 1 if w > 1 else 9
            for n in range(start, 10 ** w):
                b = base[:m.start()] + str(n).zfill(w) + base[m.end():]
                if free(b):
                    return folder + "/" + b
        for n in range(2, 100):
            if free("%s_%d" % (base, n)):
                return "%s/%s_%d" % (folder, base, n)
        return ""

    def copy_plan(self, rel, key, new_pkg, mode):
        """Dry run of replace_with_copy: {problems, notes, files}."""
        t = self.table(rel)
        old_obj = t.target(key)
        old_pkg = old_obj.partition(".")[0]
        problems, notes, files = [], [], 0
        if self.src.exists(game_to_rel(new_pkg) + ".uasset"):
            problems.append("%s already exists" % new_pkg.rsplit("/", 1)[1])
        stem = game_to_rel(old_pkg)
        if not self.src.exists(stem + ".uasset"):
            problems.append("the current asset %s is not available (nothing to copy)" % old_pkg.rsplit("/", 1)[1])
        elif mode == "asset":
            if self.src.exists(stem + ".ubulk"):
                problems.append("this asset has bulk data (a texture); only data assets can be copied on their own")
            files = sum(self.src.exists(stem + e) for e in (".uasset", ".uexp"))
        elif mode == "set":
            try:
                plan = self._dup_set(old_obj, new_pkg, dry=True)
                problems += plan["problems"]; notes += plan["notes"]; files = len(plan["jobs"])
            except MgpError as e:
                problems.append(str(e))
        else:
            problems.append("mode must be 'asset' or 'set'")
        return dict(problems=problems, notes=notes, files=files)

    def replace_with_copy(self, rel, key, new_target, mode):
        """new_target does not exist: create it as a copy of the row's CURRENT asset, then point the row at it.
        mode: 'asset' (this asset only) or 'set' (asset + its variant materials/textures)."""
        t = self.table(rel)
        old_obj = t.target(key)
        new_pkg = new_target.partition(".")[0]
        notes, warnings = [], []
        if mode == "asset":
            made = self._dup_asset(old_obj.partition(".")[0], new_pkg)
        elif mode == "set":
            made, warnings, notes = self._dup_set(old_obj, new_pkg)
        else:
            raise MgpError("mode must be 'asset' or 'set'")
        obj = self.object_path(new_pkg)                    # object name comes from the copy itself
        t.set_target(key, obj)
        self.save_table(rel)
        return dict(made=made, target=obj, warnings=warnings, notes=notes)

    def copy_look(self, key, donor, categories=None):
        """Point every table row of `key` at the donor's, optionally only for some categories."""
        changes = []
        for rel in self.table_names():
            cat = category(rel)
            if categories is not None and cat not in categories:
                continue
            try:
                t = self.table(rel)
            except Exception:
                continue
            if key in t.rows and donor in t.rows and t.target(key) != t.target(donor):
                old = t.target(key)
                t.set_target(key, t.target(donor))
                self.save_table(rel)
                changes.append((rel, old, t.target(key)))
        return changes

    def ensure_db(self):
        """The DB is edited as a working copy in the mod folder; pull it out of the paks on first use."""
        if not os.path.exists(self.db_path):
            data = self.src.read(DB_REL)                 # read first: opening the target would create it empty
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            with open(self.db_path, "wb") as f:
                f.write(data)
        return self.db_path

    # ---- staging (web UI): nothing reaches the mod folder until save_staged()
    def staged_files(self):
        """Relative paths of staged files that really differ from what is saved/in the paks.
        Sizes are compared first, so a pak file is only read and decompressed when the size is equal."""
        out = []
        if not self.staged:
            return out
        cache = self.__dict__.setdefault("_cmp", {})
        for d, ds, fs in os.walk(self.root):
            for f in fs:
                if f.endswith(("-journal", "-wal", "-shm")):
                    continue
                full = os.path.join(d, f)
                rel = os.path.relpath(full, self.root).replace(os.sep, "/")
                st = os.stat(full)
                bp = self.src._base(rel)
                try:
                    b = os.stat(bp) if bp else None
                    bst = (b.st_size, b.st_mtime_ns) if b else None
                except OSError:
                    bst = None
                key = (rel, st.st_size, st.st_mtime_ns, bst)
                if key not in cache:
                    cache[key] = self._differs(rel, full, st.st_size)
                if cache[key]:
                    out.append(rel)
        return sorted(out)

    def _differs(self, rel, full, size):
        try:
            p = self.src._base(rel)
            if p and os.path.exists(p):
                if os.path.getsize(p) != size:
                    return True
            elif self.paks and self.paks.exists(rel):
                if self.paks.size(rel) != size:
                    return True
            else:
                return True                                  # new file
            with open(full, "rb") as fh:
                mine = fh.read()
            return self.src.read_underlying(rel) != mine
        except Exception:
            return True                                      # cannot compare: treat as changed so it can be saved

    def save_staged(self):
        """Copy staged changes into the mod folder (old versions go to _mgp_backup), then clear staging."""
        files = self.staged_files()
        for rel in list(files):                       # an asset's .uasset/.uexp/.ubulk always travel together
            stem = rel.rsplit(".", 1)[0]
            for e in SIDECARS:
                r2 = stem + e
                if r2 not in files and os.path.exists(os.path.join(self.root, *r2.split("/"))) and rel.endswith(SIDECARS):
                    files.append(r2)
        for rel in files:
            dst = os.path.join(self.real_root, *rel.split("/"))
            if os.path.exists(dst):
                b = os.path.join(self.backup_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(b), exist_ok=True)
                shutil.copyfile(dst, b)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(self.root, *rel.split("/")), dst)
        self.clear_staging()
        return files

    def clear_staging(self):
        if self.staged:
            shutil.rmtree(self.root, ignore_errors=True)
            self.backup_dir = os.path.join(self.real_root, "_mgp_backup", time.strftime("%Y%m%d-%H%M%S"))
            self.reload_bindings()

    def backup(self, path):
        if self.staged or path in self._backed or not os.path.exists(path):
            return
        dst = os.path.join(self.backup_dir, os.path.relpath(path, self.root))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(path, dst)
        self._backed.add(path)

    def save_bindings(self):
        os.makedirs(os.path.dirname(self.dt_stem), exist_ok=True)
        for e in (".uasset", ".uexp"):
            self.backup(self.dt_stem + e)
        self.dt.save(self.dt_stem + ".uasset", self.dt_stem + ".uexp")

    # ---- binding views
    def binding(self, pilot_key):
        if pilot_key not in self.dt.rows:
            return None
        obj = self.dt.target(pilot_key)
        try:
            info = resolve_set(self.src, obj)
        except MgpError:
            info = None
        return dict(target=obj, info=info)

    def suggest_tag(self, obj_path, dt=None):
        stem = obj_path.partition(".")[0].rsplit("_", 1)[0]
        parts = obj_path.partition(".")[0].rsplit("_", 1)
        if len(parts) < 2:
            return ""
        tag = parts[1]
        used = " ".join((dt or self.dt).ua.texts())
        for n in range(901, 1000):
            t = "%03d" % n
            if len(t) == len(tag) and ("_" + t) not in used and not self.src.exists(game_to_rel(stem + "_" + t) + ".uasset"):
                return t
        return ""

    def clone_for_pilot(self, pilot_key, new_tag, dry_run=False, rel=None):
        """Clone the pilot's set under new_tag and repoint the pilot's binding row to it.
        `rel`: the bike table to use (default DT_BikeOfficial)."""
        dt = self.table(rel) if rel else self.dt
        obj = dt.target(pilot_key)
        plan = plan_clone(self.src, obj, new_tag, dt)
        if dry_run or plan["problems"]:
            return plan, [], []
        made, warnings = do_clone(self.src, plan)
        new_obj = plan["pkgmap"][obj.partition(".")[0]] + "." + plan["basemap"][obj.rpartition(".")[2]]
        dt.set_target(pilot_key, new_obj)
        if rel:
            self.save_table(rel)
        else:
            self.save_bindings()
        return plan, made, warnings

    def repoint(self, pilot_key, new_obj):
        self.dt.set_target(pilot_key, new_obj)
        self.save_bindings()


# ------------------------------------------------------------------------- DB
class Db:
    def __init__(self, project):
        self.p = project
        self.con = sqlite3.connect(project.ensure_db(), check_same_thread=False)
        self.con.row_factory = None

    def tables(self):
        return [r[0] for r in self.con.execute(
            "select name from sqlite_master where type='table' and name!='sqlite_sequence' order by name")]

    def columns(self, table):
        return [(r[1], r[2]) for r in self.con.execute('pragma table_info("%s")' % table)]

    def rows(self, table):
        cols = ",".join('"%s"' % c for c, _ in self.columns(table))
        return self.con.execute('select rowid,%s from "%s"' % (cols, table)).fetchall()

    def coerce(self, table, col, text, old):
        if text == "" and old is None:
            return None
        if isinstance(old, int) and not isinstance(old, bool):
            try:
                return int(text)
            except ValueError:
                return float(text)
        if isinstance(old, float):
            return float(text)
        return text

    def update(self, table, rowid, col, value):
        self.p.backup(self.p.db_path)
        self.con.execute('update "%s" set "%s"=? where rowid=?' % (table, col), (value, rowid))

    def commit(self):
        self.con.commit()

    def rollback(self):
        self.con.rollback()
