"""Copy values from one asset into another while keeping the target's own file: its header, names, imports and
paths stay as they are, only fixed-size values are overwritten in place (the file size never changes).

Properties are matched by name (path like TaggedProjectors[SidePlateRight].Projector.Transform.Translation).
Works on GP24 assets (tagged properties) and MotoGP 25/26 assets (unversioned: zen .uasset or a retoc legacy
pair; needs the game's .usmap). Numbers, bools, vectors, colours and transforms are copied; float <-> double is
converted (GP24 floats vs GP25 doubles). Names are copied only if the target's name table already has them.
Strings, texts and soft paths are never copied. Object references (GP24 only) are copied when both point at an
import of the same class: the target's import is repointed to the source's package/object (names are appended,
so the .uasset header grows; the .uexp keeps its size). MotoGP 25/26 references are kept."""
import struct

import uprops
import uvprops
import usmap as US
from mgp_core import MgpError

KEEP = ("ref", "text", "locked")              # kinds that are reported but never written
WHY_KEPT = {"ref": "references point into the file's own import table: the target's are kept",
            "text": "texts are not copied (their size can differ): the target's is kept",
            "locked": "materials: only scalar/vector parameter values are copied (static switches and overrides are baked into shaders)"}


class Doc:
    """One opened asset: kind 'tagged' (GP24), 'zen' or 'legacy-unversioned' (MotoGP 25/26)."""

    def __init__(self, uasset, uexp=None, umap=None):
        self.uasset, self.uexp, self.umap = bytes(uasset), None if uexp is None else bytes(uexp), umap
        self.notes = []
        if uexp is None:
            self._open_zen()
        else:
            import projfile
            if projfile.is_unversioned_legacy(uasset):
                self._open_legacy_unv()
            else:
                self._open_tagged()

    # ---- opening
    def _need_umap(self):
        if self.umap is None:
            raise MgpError("this is a MotoGP 25/26 file (no property names inside): give the .usmap of the game it comes from")

    def _open_tagged(self):
        self.kind = "tagged"
        self.buf = bytearray(self.uexp)
        try:
            a = uprops.Asset(self.uasset, self.buf)
            a.uexp = self.buf                                   # same buffer: offsets point into it
            ex = a.parse_export(0)
        except (MgpError, struct.error, IndexError) as e:
            raise MgpError("could not read the properties: %s" % e)
        self.cls, self.names, self.asset = ex["cls"], a.names, a
        self.props = [_from_tagged(n, ex["cls"], []) for n in ex["props"]]
        self.rows = None
        if ex["cls"] == "DataTable":
            self.rows = self._tagged_rows(a, ex)
        if len(a.exports) > 1:
            self.notes.append("only the first of %d exports (%s) is compared" % (len(a.exports), a.exports[0]["name"]))

    def _tagged_rows(self, a, ex):
        p = ex["end"] + 4                                       # object guid flag
        n = struct.unpack_from("<i", self.buf, p)[0]; p += 4
        rows = []
        for _ in range(n):
            key, p = a._fn(p)
            kids, p = a._props(p, ex["size_end"])
            for k in kids:
                a._value(k, k["off"], k["size"])
            rows.append((key, [_from_tagged(k, "DataTable", []) for k in kids]))
        return rows

    def _open_zen(self):
        import mgp_zen
        self.kind = "zen"
        try:
            z = mgp_zen.ZenPackage(self.uasset)
        except Exception as e:
            raise MgpError("not a .uasset this tool can read (%s)" % e)
        self._need_umap()
        self.buf = bytearray(self.uasset)
        self.names = z.names
        short = self.uasset and z.exports and z.exports[0]["name"]
        i = next((k for k, e in enumerate(z.exports) if e["name"] == short), 0)
        if len(z.exports) > 1:
            self.notes.append("only export %s of %d is compared" % (z.exports[i]["name"], len(z.exports)))
        e = z.exports[i]
        start = z.header_size + e["serial_off"]
        cls_hash = struct.unpack_from("<Q", self.uasset, e["entry"] + 32)[0]
        sn = US.script_names(self.umap)
        hints = [sn[cls_hash]] if cls_hash in sn else []
        self._read_unv(start, start + e["size"], list(z.names), row_hint=lambda idx: sn.get(z.import_at(idx)),
                       exact=hints[0] if hints else None)

    def _open_legacy_unv(self):
        import projfile
        self.kind = "legacy-unversioned"
        self._need_umap()
        s = projfile.legacy_summary(self.uasset)
        self.names = s["names"]
        self.buf = bytearray(self.uexp)
        self._read_unv(0, len(self.buf) - 4, list(self.names), row_hint=lambda idx: None)

    def _read_unv(self, start, end, hints, row_hint, exact=None):
        u, d = self.umap, self.buf
        self.rows = None
        g = None if exact == "DataTable" else uvprops.guess_class(u, d, self.names, start, end, hints, exact)
        if g:
            self.cls, props, p, others = g
            if self.cls != exact:
                self.notes.append("class not named in the file: read as %s%s" % (self.cls, " (also fits: %s)" % ", ".join(others[:4]) if others else ""))
            if end - p > 8:
                self.notes.append("%d bytes of native data after the properties are not compared" % (end - p))
        else:
            rh = []
            try:
                r = uvprops.Reader(u, d, self.names, start, end)
                first = r.struct("DataTable")
                rs = next((n for n in first if n["name"] == "RowStruct" and isinstance(n.get("value"), int)), None)
                if rs and row_hint(rs["value"]):
                    rh.append(row_hint(rs["value"]))
            except (uvprops.ReadError, struct.error):
                pass
            t = uvprops.read_datatable(u, d, self.names, start, end, rh + hints)
            if not t:
                raise MgpError("the .usmap has no class that reads this file exactly (wrong game's .usmap, or a "
                               "layout this tool does not know)")
            props, row_struct, rows = t
            self.cls = "DataTable"
            self.notes.append("DataTable, rows read as %s%s" % (row_struct, "" if rh and rh[0] == row_struct else " (guessed)"))
            self.rows = [(k, [_from_unv(n, "DataTable") for n in kids]) for k, kids in rows]
        self.props = [_from_unv(n, self.cls) for n in props]

    # ---- output
    def files(self):
        """(uasset bytes, uexp bytes or None) as they are now."""
        if self.kind == "zen":
            return bytes(self.buf), None
        if self.kind == "tagged":
            return self.asset.ua.to_bytes(), bytes(self.buf)
        return self.uasset, bytes(self.buf)

    def flat(self):
        """{path: leaf} and the set of every node path."""
        out, nodes = {}, set()
        _flatten(self.props, "", out, nodes)
        if self.rows is not None:
            _flatten([dict(name="[%s]" % k, children=kids) for k, kids in self.rows], "Rows", out, nodes, labels=False)
        return out, nodes


# ---- common node form: dict(name, children?) or leaf dict(name, kind, fmt, off, value, zero?)
def _from_tagged(n, cls, path):
    p = path + [n["name"]]
    d = dict(name=n["name"])
    if n.get("edit") and uprops.allowed(p, cls):
        k = n["edit"]
        if k == "num":
            fmt = uprops.SIMPLE[n["type"]][0] if n["type"] in uprops.SIMPLE else "<B"
        elif k == "bool":
            fmt = "<B"
        elif k == "floats":
            fmt = "<%df" % len(n["value"])
        else:                                                  # color8: stored B, G, R, A
            fmt = "<4B"
        d.update(kind=k, fmt=fmt, off=n["off"], value=n["value"], type=n["type"])
        return d
    if n.get("edit"):
        d.update(kind="locked", value=n["value"], type=n["type"])
        return d
    if n.get("children") is not None and not (n["type"] == "StructProperty" and n.get("struct") in ("IntPoint", "IntVector")):
        d["children"] = [_from_tagged(c, cls, p) for c in n["children"]]
        d["type"] = n["type"]
        d["array"] = n["type"] in ("ArrayProperty", "SetProperty", "MapProperty")
        return d
    t = n["type"]
    if t == "StructProperty" and n.get("struct") in ("IntPoint", "IntVector") and "off" in n and uprops.allowed(p, cls):
        d.update(kind="ints", fmt="<%di" % (n["size"] // 4), off=n["off"], value=n["value"], type=n["struct"])
    elif "off" in n and n.get("size") == 8 and (t == "NameProperty" or t in ("ByteProperty", "EnumProperty") and n.get("enum") not in (None, "None")) \
            and uprops.allowed(p, cls):
        d.update(kind="name", off=n["off"], value=n.get("value"), type=t)
    elif t in ("StrProperty", "TextProperty"):
        d.update(kind="text", value=n.get("value"), type=t)
    elif t == "ObjectProperty" and "idx" in n and "off" in n:
        d.update(kind="ref", obj=True, off=n["off"], idx=n["idx"], value=n.get("value"), type=t)
    else:
        d.update(kind="ref", value=n.get("value"), type=t)
    return d


def _from_unv(n, cls, path=()):
    p = list(path) + [n["name"]]
    d = dict(name=n["name"], type=n.get("struct") or n["type"])
    if n.get("zero"):
        d.update(kind="zero", ptype=n["ptype"])
        return d
    if n.get("edit") and not uprops.allowed(p, cls):
        d.update(kind="locked", value=n.get("value"))
        return d
    if n.get("edit"):
        k = n["edit"]
        d.update(kind="name" if k == "name" else k, fmt=n.get("fmt"), off=n["off"], value=n.get("value"))
        return d
    if n.get("children") is not None:
        d["children"] = [_from_unv(c, cls, p) for c in n["children"]]
        d["array"] = n["type"] in ("ArrayProperty", "SetProperty", "MapProperty")
        return d
    d.update(kind="text" if n["type"] in ("StrProperty", "TextProperty") else "ref", value=n.get("value"))
    return d


def _label(item):
    """Name of an array item for matching: its Tag, or a material parameter's name."""
    for c in item.get("children") or []:
        if c["name"] == "Tag" and c.get("kind") in ("name", "locked") and isinstance(c.get("value"), str):
            return c["value"]
        if c["name"] == "ParameterInfo":
            for cc in c.get("children") or []:
                if cc["name"] == "Name" and cc.get("kind") in ("name", "locked") and isinstance(cc.get("value"), str):
                    return cc["value"]
    return None


def _flatten(nodes, prefix, out, all_nodes, labels=True):
    """path -> leaf for every leaf; all_nodes gets every path (structs and arrays too)."""
    labs = [_label(n) for n in nodes] if labels and nodes and nodes[0]["name"].startswith("[") else []
    use = labs and all(labs) and len(set(labs)) == len(labs)
    for i, n in enumerate(nodes):
        key = "[%s]" % labs[i] if use else n["name"]
        path = prefix + key if key.startswith("[") else (prefix + "." + key if prefix else key)
        all_nodes.add(path)
        if "children" in n:
            if n.get("array"):
                out[path + "#count"] = dict(kind="count", value=len(n["children"]))
            _flatten(n["children"], path, out, all_nodes)
        else:
            out[path] = n


# ---- copying
INTS = set("bBhHiIqQ")


def _scalars(fmt):
    return struct.unpack("<" + fmt.lstrip("<"), bytes(struct.calcsize(fmt)))


def _compatible(s, d):
    """Can source leaf s be written into target leaf d? -> '' or the reason it can't."""
    if s["kind"] != d["kind"]:
        return "different type (%s -> %s)" % (s.get("type", s["kind"]), d.get("type", d["kind"]))
    if s["kind"] == "name":
        return ""
    sf, df = s["fmt"].lstrip("<"), d["fmt"].lstrip("<")
    sc, dc = _codes(sf), _codes(df)
    if len(sc) != len(dc):
        return "different size (%d -> %d values)" % (len(sc), len(dc))
    for a, b in zip(sc, dc):
        if (a in INTS) != (b in INTS):
            return "different type (%s -> %s)" % (s.get("type", sf), d.get("type", df))
    return ""


def _codes(fmt):
    out, num = [], ""
    for ch in fmt:
        if ch.isdigit():
            num += ch
        else:
            out += [ch] * int(num or 1); num = ""
    return out


def _read(doc, leaf):
    return list(struct.unpack_from(leaf["fmt"], doc.buf, leaf["off"]))


def _show(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (list, tuple)):
        return [_show(x) for x in v]
    if isinstance(v, bytes):
        return v.hex()
    return v


def _zero_src(spath, S):
    """Is the source value at `spath` (missing from S) zero because it or a parent was stored as all-zero?"""
    p = spath
    while p:
        leaf = S.get(p)
        if leaf is not None:
            return leaf.get("kind") == "zero"
        cut = max(p.rfind("."), p.rfind("["))
        p = p[:cut] if cut > 0 else ""
    return False


def plan(src, dst, only=None, refs=True):
    """Compare src with dst. -> (rows, writes, repoints); rows: dict(path, status, src, dst); writes: [(off, bytes)];
    repoints: header changes for object references (see _plan_refs).
    status: changed / same / skipped / different / not in target / not in source / kept.
    only: optional path prefixes to limit the copy to. refs: also copy object references (GP24 files)."""
    S, Snodes = src.flat()
    D, Dnodes = dst.flat()
    rows, writes = [], []
    refs_kept = 0
    obj_ops = []

    def want(p):
        return not only or any(p == o or p.startswith(o + ".") or p.startswith(o + "[") for o in only)

    for path, d in D.items():
        if not want(path):
            continue
        s = S.get(path)
        if d["kind"] == "count":
            if s is not None and s["value"] != d["value"]:
                rows.append(dict(path=path[:-6], status="different", src="%d items" % s["value"], dst="%d items" % d["value"],
                                 why="different number of items: matching items are copied, the rest is left as it is"))
            continue
        if s is None:
            if src.kind == "tagged" or d["kind"] in KEEP + ("zero", "name") or not _zero_src(path, S):
                continue                                       # reported below as "not in source"
            s = dict(kind=d["kind"], fmt=d["fmt"], zero=True, type=d.get("type"))
        if refs and d.get("obj") and s.get("obj") and src.kind == dst.kind == "tagged":
            if s["value"] != d["value"]:
                obj_ops.append((path, s, d))
            continue
        if d["kind"] in KEEP:
            if d["kind"] == "ref" and not (isinstance(s.get("value"), str) and isinstance(d.get("value"), str)):
                refs_kept += s.get("value") != d.get("value")  # unversioned: only an import number, not worth a row
            elif s.get("kind") != "zero" and str(s.get("value")) != str(d.get("value")):
                rows.append(dict(path=path, status="kept", src=_show(s.get("value")), dst=_show(d.get("value")), why=WHY_KEPT[d["kind"]]))
            continue
        if s.get("kind") == "zero" and d["kind"] == "zero":
            continue
        if d["kind"] == "zero":
            sv = s.get("value")
            nonzero = s.get("kind") not in ("zero",) and not s.get("zero") and (
                s["kind"] == "name" and sv not in (None, "None") or s["kind"] not in ("name",) + KEEP and any(_read(src, s)))
            if nonzero:
                rows.append(dict(path=path, status="skipped", src=_show(sv), dst="0 (not stored)",
                                 why="the target stores this value as zero with no bytes; writing it would change the file size"))
            continue
        if s.get("kind") == "zero":
            s = dict(kind=d["kind"], fmt=d.get("fmt"), zero=True, type=d.get("type"))
        why = _compatible(s, d) if not (s.get("zero") and d["kind"] != "name") else ""
        if why:
            rows.append(dict(path=path, status="different", src=_show(s.get("value")), dst=_show(d.get("value")), why=why))
            continue
        if d["kind"] == "name":
            sv = "None" if s.get("zero") else s["value"]
            if sv == d["value"]:
                rows.append(dict(path=path, status="same", src=sv, dst=sv)); continue
            base, num = _split(sv)
            if base not in dst.names:
                rows.append(dict(path=path, status="skipped", src=sv, dst=d["value"],
                                 why="name %s is not in the target's name table (adding it would change the header)" % base))
                continue
            new = struct.pack("<II", dst.names.index(base), num)
            writes.append((d["off"], new))
            rows.append(dict(path=path, status="changed", src=sv, dst=d["value"]))
            continue
        vals = _scalars(d["fmt"]) if s.get("zero") else _read(src, s)
        dc = _codes(d["fmt"].lstrip("<"))
        try:
            vals = [int(v) if c in INTS else float(v) for v, c in zip(vals, dc)]
            new = struct.pack(d["fmt"], *vals)
        except (struct.error, OverflowError, ValueError):
            rows.append(dict(path=path, status="skipped", src=_show(vals), dst=_show(d.get("value")), why="value does not fit the target's type"))
            continue
        old = bytes(dst.buf[d["off"]:d["off"] + len(new)])
        shown = vals if len(vals) > 1 else bool(vals[0]) if d["kind"] == "bool" else vals[0]
        if d["kind"] == "color8":
            shown = [vals[2], vals[1], vals[0], vals[3]]
        if old == new:
            rows.append(dict(path=path, status="same", src=_show(shown), dst=_show(d.get("value"))))
        else:
            writes.append((d["off"], new))
            rows.append(dict(path=path, status="changed", src=_show(shown), dst=_show(d.get("value"))))
    for path in Snodes - Dnodes:                               # only the top-most missing node is reported
        s = S.get(path)
        if want(path) and _top_missing(path, Dnodes) and not (s and s["kind"] == "zero"):
            rows.append(dict(path=path, status="not in target", src=_show(s.get("value")) if s else "",
                             why="the target does not store this (uses the default): adding it would change the file size"))
    for path in Dnodes - Snodes:
        d = D.get(path)
        if want(path) and _top_missing(path, Snodes) and not (d and d["kind"] == "zero") \
                and not (src.kind != "tagged" and _zero_src(path, S)):
            rows.append(dict(path=path, status="not in source", dst=_show(d.get("value")) if d else "",
                             why="the source does not store this%s: the target's value is kept" % (" (uses the default)" if src.kind == "tagged" else "")))
    repoints = _plan_refs(src, dst, obj_ops, D, rows, writes) if obj_ops else []
    rows.sort(key=lambda r: r["path"])
    if refs_kept:
        rows.append(dict(path="(references)", status="kept", src="", dst="%d" % refs_kept, why=WHY_KEPT["ref"]))
    return rows, writes, repoints


# ---- object references (GP24 tagged files): repoint the target's import
def _imp(doc, idx):
    """Raw import entry of FPackageIndex idx (< 0): dict(cp, cpn, cn, cnn, outer, on, onn) + texts."""
    ua = doc.asset.ua
    v = struct.unpack_from("<7i", ua.data, ua._get("importoff") + (-idx - 1) * 28)
    e = dict(zip(("cp", "cpn", "cn", "cnn", "outer", "on", "onn"), v))
    e["cls"] = ua.names[e["cn"]]["text"]
    e["cpkg"] = ua.names[e["cp"]]["text"]
    e["name"] = (ua.names[e["on"]]["text"], e["onn"])
    return e


def _key(doc, idx):
    """(class package, class, package name, object name) of an import whose outer is its package, else None."""
    e = _imp(doc, idx)
    if e["outer"] >= 0:
        return None
    o = _imp(doc, e["outer"])
    if o["cls"] != "Package" or o["outer"] != 0:
        return None
    return (e["cpkg"], e["cls"], o["name"], e["name"])


def _plan_refs(src, dst, ops, D, rows, writes):
    n_imp = len(dst.asset.imports)
    existing = {}
    for j in range(n_imp):
        k = _key(dst, -(j + 1))
        if k:
            existing.setdefault(k, -(j + 1))
    groups = {}
    for path, s, d in ops:
        si, di = s["idx"], d["idx"]
        if si >= 0 or di >= 0:
            rows.append(dict(path=path, status="kept", src=_show(s["value"]), dst=_show(d["value"]),
                             why="one of them points at an object inside its own file (or at nothing): not changed"))
            continue
        sc, dc = _imp(src, si)["cls"], _imp(dst, di)["cls"]
        if sc != dc:
            rows.append(dict(path=path, status="different", src=_show(s["value"]), dst=_show(d["value"]),
                             why="different object type (%s -> %s): the path is not changed" % (sc, dc)))
            continue
        k = _key(src, si)
        if not k:
            rows.append(dict(path=path, status="kept", src=_show(s["value"]), dst=_show(d["value"]),
                             why="the source points at an object nested inside another one: not changed"))
            continue
        if k in existing:                                  # the target already imports that object: same size
            writes.append((d["off"], struct.pack("<i", existing[k])))
            rows.append(dict(path=path, status="changed", src=_show(s["value"]), dst=_show(d["value"]),
                             why="path changed (the target already imports it)"))
            continue
        groups.setdefault(di, []).append((path, s, d, k))
    out = []
    users = {}
    for p, l in D.items():
        if l.get("obj"):
            users.setdefault(l["idx"], []).append(p)
    ua = dst.asset.ua
    eo = ua._get("exportoff")
    in_exports = set()
    for i in range(ua._get("exportcount")):
        in_exports.update(struct.unpack_from("<4i", ua.data, eo + i * ua.EXPORT_SIZE))   # class, super, template, outer
    for di, g in groups.items():
        why = ""
        keys = {k for _, _, _, k in g}
        e = _imp(dst, di)
        sib = [-(j + 1) for j in range(n_imp) if -(j + 1) != di and _imp(dst, -(j + 1))["outer"] == e["outer"]]
        if len(keys) > 1:
            why = "this import is used by several properties that get different paths"
        elif set(users.get(di, [])) - {p for p, _, _, _ in g}:
            why = "the same import is also used by %s, which would change too" % ", ".join(sorted(set(users[di]) - {p for p, _, _, _ in g})[:3])
        elif len(dst.asset.exports) > 1:
            why = "the target has several exports (only the first is compared)"
        elif di in in_exports:
            why = "the export table uses this import"
        elif e["outer"] >= 0 or _imp(dst, e["outer"])["cls"] != "Package":
            why = "the target points at an object nested inside another one"
        elif any(_imp(dst, j)["name"] != ("Default__" + e["name"][0], e["name"][1]) for j in sib):
            why = "its package has other imported objects too"
        for path, s, d, k in g:
            rows.append(dict(path=path, status="skipped" if why else "changed", src=_show(s["value"]), dst=_show(d["value"]),
                             why=(why + ": the path is not changed") if why else "path changed (the .uasset header grows by the new names)"))
        if not why:
            k = g[0][3]
            out.append(dict(imp=di, pkg_imp=e["outer"], siblings=sib, pkg=k[2], obj=k[3]))
    return out


def _name_index(ua, text):
    texts = ua.texts()
    return texts.index(text) if text in texts else ua.append_name(text)


def _top_missing(path, nodes):
    """True if `path` is missing from `nodes` but its parent is there (so only the top-most missing node is reported)."""
    cut = max(path.rfind("."), path.rfind("["))
    return cut <= 0 or path[:cut] in nodes


def _split(text):
    base, _, n = text.rpartition("_")
    if base and n.isdigit() and not (len(n) > 1 and n[0] == "0"):
        return base, int(n) + 1
    return text, 0


def apply(dst, writes, repoints=()):
    for off, data in writes:
        dst.buf[off:off + len(data)] = data
    if not repoints:
        return
    ua = dst.asset.ua
    plan_ = []
    for r in repoints:                                     # append every name first: appending moves the import table
        plan_.append((r, _name_index(ua, r["pkg"][0]), _name_index(ua, r["obj"][0]),
                      _name_index(ua, "Default__" + r["obj"][0]) if r["siblings"] else None))
    io = ua._get("importoff")
    for r, pi, oi, di in plan_:
        struct.pack_into("<ii", ua.data, io + (-r["pkg_imp"] - 1) * 28 + 20, pi, r["pkg"][1])
        struct.pack_into("<ii", ua.data, io + (-r["imp"] - 1) * 28 + 20, oi, r["obj"][1])
        for j in r["siblings"]:
            struct.pack_into("<ii", ua.data, io + (-j - 1) * 28 + 20, di, r["obj"][1])


def summary(rows):
    out = {}
    for r in rows:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def copy(src, dst, only=None, write=True, refs=True):
    """Plan and (if write) apply. Returns dict(rows, counts, notes, written); dst is re-read to prove it still parses."""
    rows, writes, repoints = plan(src, dst, only, refs)
    n = len(writes) + sum(1 for r in rows if r["status"] == "changed" and r.get("why", "").startswith("path changed (the .uasset"))
    if write and (writes or repoints):
        apply(dst, writes, repoints)
        ua, ux = dst.files()
        again = Doc(ua, ux, dst.umap)                          # still reads, same class
        if again.cls != dst.cls:
            raise MgpError("internal check failed: the patched file reads as %s instead of %s" % (again.cls, dst.cls))
    return dict(rows=rows, counts=summary(rows), written=n if write else 0, changes=n,
                notes=["source: " + n for n in src.notes] + ["target: " + n for n in dst.notes],
                src_cls=src.cls, dst_cls=dst.cls, src_kind=src.kind, dst_kind=dst.kind)
