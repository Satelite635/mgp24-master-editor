"""Reader for *unversioned* properties (MotoGP 25/26: zen .uasset, or a UE5 legacy pair made by retoc to-legacy).
The file stores no property names or types: a small header says which of the class's properties (by schema
index, from the .usmap) have a value, and which of those are all-zero (no bytes). See usmap.py.

Gives the same kind of tree as uprops.tree(): nodes dict(name, type, value, off, size, edit/fmt, children)."""
import struct

from usmap import UsmapError

# structs the engine writes as raw bytes (their own Serialize), not as unversioned properties. UE5: doubles (LWC).
NATIVE = {"Vector": ("floats", "<3d", "xyz"), "Vector2D": ("floats", "<2d", "xy"), "Vector4": ("floats", "<4d", "xyzw"),
          "Quat": ("floats", "<4d", "xyzw"), "Rotator": ("floats", "<3d", "pyr"), "Plane": ("floats", "<4d", "xyzw"),
          "LinearColor": ("floats", "<4f", "rgba"), "Vector3f": ("floats", "<3f", "xyz"), "Vector2f": ("floats", "<2f", "xy"),
          "Vector4f": ("floats", "<4f", "xyzw"), "Rotator3f": ("floats", "<3f", "pyr"),
          "Color": ("color8", "<4B", "bgra"), "IntPoint": ("ints", "<2i", "xy"), "IntVector": ("ints", "<3i", "xyz"),
          "IntVector4": ("ints", "<4i", "xyzw"), "DateTime": ("num", "<q", ""), "Timespan": ("num", "<q", ""),
          "FrameNumber": ("num", "<i", ""), "Box": ("raw", "<6dB", ""), "Box2D": ("raw", "<4dB", ""),
          "Guid": ("raw", "<16s", ""), "SimpleCurveKey": ("floats", "<2f", "tv"), "RichCurveKey": ("raw", "<3B6f", ""),
          "FloatRange": ("raw", "<bfbf", ""), "Int32Range": ("raw", "<bibi", "")}
NUM = {"IntProperty": "<i", "FloatProperty": "<f", "DoubleProperty": "<d", "UInt32Property": "<I", "Int64Property": "<q",
       "UInt64Property": "<Q", "Int16Property": "<h", "UInt16Property": "<H", "Int8Property": "<b", "ByteProperty": "<B"}


class ReadError(Exception):
    pass


class Reader:
    """Reads one export's unversioned properties. names: the package's name map (for FName values)."""

    def __init__(self, umap, data, names, start=0, end=None):
        self.u, self.d, self.names = umap, data, names
        self.end = len(data) if end is None else end
        self.p = start

    # ---- primitives
    def take(self, n):
        if self.p + n > self.end:
            raise ReadError("ran past the end of the export at %d" % self.p)
        p = self.p
        self.p += n
        return p

    def un(self, fmt):
        return struct.unpack_from(fmt, self.d, self.take(struct.calcsize(fmt)))

    def i32(self):
        return self.un("<i")[0]

    def fname(self):
        i, n = self.un("<II")
        if i >= len(self.names) or n > 1 << 20:
            raise ReadError("bad name index %d at %d" % (i, self.p - 8))
        return self.names[i] + ("_%d" % (n - 1) if n else "")

    def fstring(self):
        n = self.i32()
        if n == 0:
            return ""
        if n > 0:
            if n > 1 << 16:
                raise ReadError("bad string length %d" % n)
            return bytes(self.d[self.take(n):self.p - 1]).decode("latin1")
        if -n > 1 << 16:
            raise ReadError("bad string length %d" % n)
        return bytes(self.d[self.take(-n * 2):self.p - 2]).decode("utf-16le", "replace")

    def count(self):
        n = self.i32()
        if not 0 <= n <= (self.end - self.p):
            raise ReadError("bad item count %d at %d" % (n, self.p - 4))
        return n

    # ---- unversioned header
    def header(self):
        present, idx = [], 0
        while True:
            h = self.un("<H")[0]
            idx += h & 0x7F
            n = h >> 9
            present += [(idx + i, bool(h & 0x80)) for i in range(n)]
            idx += n
            if h & 0x100:
                break
            if len(present) > 4096:
                raise ReadError("unversioned header not understood")
        masked = [i for i, z in present if z]
        zeros = set()
        if masked:
            nb = 1 if len(masked) <= 8 else 2 if len(masked) <= 16 else ((len(masked) + 31) // 32) * 4
            bits = int.from_bytes(self.d[self.take(nb):self.p], "little")
            zeros = {i for k, i in enumerate(masked) if bits >> k & 1}
        return [i for i, _ in present], zeros

    # ---- structures
    def struct(self, name):
        """Properties of an unversioned struct/class body -> [node]."""
        try:
            schema, total = self.u.schema(name)
        except UsmapError as e:
            raise ReadError(str(e))
        present, zeros = self.header()
        out = []
        for i in present:
            if i not in schema:
                raise ReadError("%s has no property #%d (the .usmap does not match this file?)" % (name, i))
            prop, slot = schema[i]
            nm = prop.name + ("[%d]" % slot if prop.array_dim > 1 else "")
            if i in zeros:
                out.append(dict(name=nm, type=prop.type[0], zero=True, value="(zero)", ptype=prop.type))
                continue
            out.append(self.value(nm, prop.type))
        return out

    def value(self, nm, t):
        k = t[0]
        node = dict(name=nm, type=k, ptype=t)
        if k in NUM:
            fmt = NUM[k]
            node.update(off=self.p, value=self.un(fmt)[0], edit="num", fmt=fmt)
        elif k == "EnumProperty":
            inner = t[1][0]
            fmt = NUM.get(inner, "<B")
            node.update(off=self.p, value=self.un(fmt)[0], edit="num", fmt=fmt, enum=t[2])
            vals = self.u.enums.get(t[2])
            if vals and isinstance(node["value"], int) and 0 <= node["value"] < len(vals):
                node["label"] = vals[node["value"]]
        elif k == "BoolProperty":
            node.update(off=self.p, value=bool(self.un("<B")[0]), edit="bool", fmt="<B")
        elif k == "NameProperty":
            node.update(off=self.p, value=self.fname(), edit="name")
        elif k in ("StrProperty", "Utf8StrProperty", "AnsiStrProperty"):
            node["value"] = self.fstring()
        elif k == "TextProperty":
            node["value"] = self.text()
        elif k in ("ObjectProperty", "WeakObjectProperty", "InterfaceProperty"):
            node.update(value=self.i32(), ref=True)
        elif k == "LazyObjectProperty":
            node.update(value=bytes(self.d[self.take(16):self.p]).hex(), ref=True)
        elif k in ("SoftObjectProperty", "AssetObjectProperty"):
            node.update(value=self.soft(), ref=True)
        elif k == "DelegateProperty":
            self.i32(); node["value"] = self.fname()
        elif k == "MulticastDelegateProperty":
            for _ in range(self.count()):
                self.i32(); self.fname()
            node["value"] = "(delegates)"
        elif k == "FieldPathProperty":
            node["value"] = ".".join(self.fname() for _ in range(self.count())); self.i32()
        elif k == "StructProperty":
            self.struct_value(node, t[1])
        elif k in ("ArrayProperty", "SetProperty"):
            if k == "SetProperty":
                for _ in range(self.count()):
                    self.value("-", t[1])
            n = self.count()
            node["children"] = [self.value("[%d]" % j, t[1]) for j in range(n)]
            node["count"] = n
        elif k == "MapProperty":
            for _ in range(self.count()):
                self.value("-", t[1])
            n = self.count()
            kids = []
            for j in range(n):
                key = self.value("key", t[1])
                val = self.value("[%s]" % _short(key), t[2])
                kids.append(val)
            node["children"] = kids
            node["count"] = n
            node["map"] = True
        elif k == "OptionalProperty":
            if self.un("<B")[0]:
                node["children"] = [self.value("value", t[1])]
        else:
            raise ReadError("%s: %s values are not supported" % (nm, k))
        return node

    def struct_value(self, node, s):
        node["struct"] = s
        if s in NATIVE:
            kind, fmt, labels = NATIVE[s]
            n = struct.calcsize(fmt)
            node.update(off=self.p, size=n, fmt=fmt)
            v = self.un(fmt)
            if kind in ("floats", "ints", "color8"):
                node.update(value=list(v), edit=kind, labels=labels)
                if kind == "color8":
                    node["value"] = [v[2], v[1], v[0], v[3]]
            elif kind == "num":
                node.update(value=v[0], edit="num")
            else:
                node["value"] = bytes(self.d[node["off"]:self.p]).hex()
        elif s in ("SoftObjectPath", "SoftClassPath"):
            node.update(value=self.soft(), ref=True)
        elif s == "GameplayTag":
            node.update(off=self.p, value=self.fname(), edit="name")
        elif s == "GameplayTagContainer":
            node["value"] = ", ".join(self.fname() for _ in range(self.count()))
        elif s in ("PerPlatformFloat", "PerPlatformInt"):
            self.i32()
            fmt = "<f" if s == "PerPlatformFloat" else "<i"
            node["children"] = [dict(name="Default", type="FloatProperty" if fmt == "<f" else "IntProperty", off=self.p,
                                     value=self.un(fmt)[0], edit="num", fmt=fmt)]
        else:
            node["children"] = self.struct(s)

    def soft(self):
        pkg, asset = self.fname(), self.fname()
        sub = self.fstring()
        return pkg + ("." + asset if asset and asset != "None" else "") + (":" + sub if sub else "")

    def text(self):
        self.i32()                                         # flags
        h = struct.unpack_from("<b", self.d, self.take(1))[0]
        if h == -1:
            return self.fstring() if self.i32() else ""
        if h == 0:
            self.fstring(); self.fstring()
            return self.fstring()
        if h == 11:
            t = self.fname()
            return "%s:%s" % (t, self.fstring())
        raise ReadError("text history type %d is not supported" % h)


def _short(node):
    v = node.get("value")
    return str(v)[:40] if v is not None else node.get("name", "?")


def read_export(umap, data, names, cls, start, end):
    """-> (props, end of properties). Raises ReadError if the layout does not fit."""
    r = Reader(umap, data, names, start, end)
    props = r.struct(cls)
    return props, r.p


def fits(umap, data, names, cls, start, end):
    """Does `cls` read this export's properties exactly? Accepts up to 8 bytes after them (UObject trailer)."""
    try:
        props, p = read_export(umap, data, names, cls, start, end)
    except (ReadError, struct.error, IndexError, KeyError, RecursionError):
        return None
    if not props or not 0 <= end - p <= 8 or any(data[p:end]) and end - p != 4:
        return None
    return props, p


def guess_class(umap, data, names, start, end, hints=(), exact=None):
    """Which .usmap class reads this export: `exact` (the export's class, known from its import), then the hinted
    names (e.g. names in the file), then every class. -> (class, props, end, [other classes that also fit]) or None.
    Only the exact class may leave bytes after its properties (native data, e.g. a material's cached data)."""
    tried, found = set(), []
    if exact and exact in umap.structs:
        tried.add(exact)
        try:
            props, p = read_export(umap, data, names, exact, start, end)
            return exact, props, p, []
        except (ReadError, struct.error, IndexError, KeyError, RecursionError):
            pass
    for c in list(hints):
        for cand in (c, c[:-2] if c.endswith("_C") else None):
            if cand and cand in umap.structs and cand not in tried:
                tried.add(cand)
                r = fits(umap, data, names, cand, start, end)
                if r:
                    return cand, r[0], r[1], []
    for c, s in umap.structs.items():
        if c in tried or s["super"] is None:                 # classes only (structs have no super ... mostly)
            continue
        r = fits(umap, data, names, c, start, end)
        if r:
            found.append((c, r))
            if len(found) > 40:
                break
    if not found:
        return None
    # prefer the class whose read uses the most properties, then the smallest layout (fewest unknown extras)
    found.sort(key=lambda f: (-_count(f[1][0]), umap.schema(f[0])[1]))
    c, (props, p) = found[0]
    return c, props, p, [f[0] for f in found[1:]]


def _count(nodes):
    return sum(1 + _count(n.get("children") or []) for n in nodes)


def read_datatable(umap, data, names, start, end, hints=()):
    """A DataTable export: its properties, then [guid flag i32][row count i32] rows * ([row FName][row struct]).
    The row struct is guessed (hinted names first, then every struct that reads all rows exactly).
    -> (props, row struct, [(row name, props)]) or None."""
    try:
        r = Reader(umap, data, names, start, end)
        props = r.struct("DataTable")
        if r.i32():
            r.take(16)
        n = r.count()
        first = r.p
    except (ReadError, struct.error):
        return None

    def rows_with(s):
        rr = Reader(umap, data, names, first, end)
        out = []
        for _ in range(n):
            key = rr.fname()
            out.append((key, rr.struct(s)))
        return out, rr.p

    cands = [h for h in hints if h in umap.structs] + [c for c, s in umap.structs.items() if s["super"] is None]
    seen = set()
    for s in cands:
        if s in seen:
            continue
        seen.add(s)
        try:
            rows, p = rows_with(s)
        except (ReadError, struct.error, IndexError, KeyError, RecursionError):
            continue
        if 0 <= end - p <= 8 and (n == 0 or any(props for _, props in rows)):
            return props, s, rows
    return None
