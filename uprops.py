"""Reader / in-place patcher for the tagged properties of cooked UE4.27 assets (customization data,
material instances ...). Only values whose size cannot change (numbers, bools, colours, vectors) are editable,
so a patch never moves any byte: nothing in the .uasset header or other offsets needs fixing."""
import struct

from mgp_core import UAsset, MgpError

SIMPLE = {"FloatProperty": ("<f", 4), "DoubleProperty": ("<d", 8), "IntProperty": ("<i", 4), "UInt32Property": ("<I", 4),
          "Int64Property": ("<q", 8), "UInt64Property": ("<Q", 8), "Int16Property": ("<h", 2), "UInt16Property": ("<H", 2),
          "Int8Property": ("<b", 1)}
STRUCT_FLOATS = {"LinearColor": 4, "Vector": 3, "Vector2D": 2, "Vector4": 4, "Quat": 4, "Rotator": 3, "Plane": 4}
STRUCT_LABELS = {"LinearColor": "rgba", "Vector": "xyz", "Vector2D": "xy", "Vector4": "xyzw", "Quat": "xyzw", "Rotator": "pyr", "Plane": "xyzw"}


class Asset:
    """A .uasset + .uexp pair opened for property reading/patching."""

    def __init__(self, uasset_bytes, uexp_bytes):
        self.ua = UAsset(uasset_bytes)
        self.uexp = bytearray(uexp_bytes)
        d = self.ua.data
        self.header = len(d)
        self.names = self.ua.texts()
        n_imp, o_imp = self.ua._get("importcount"), self.ua._get("importoff")
        self.imports = []
        for i in range(n_imp):
            b = o_imp + i * 28
            cp, cpn, cn, cnn, outer, on, onn = struct.unpack_from("<iiiiiii", d, b)
            self.imports.append(dict(cls=self.fname(cn, cnn), package=self.fname(cp, cpn), outer=outer, name=self.fname(on, onn)))
        n_exp, o_exp = self.ua._get("exportcount"), self.ua._get("exportoff")
        self.exports = []
        for i in range(n_exp):
            b = o_exp + i * UAsset.EXPORT_SIZE
            cls = struct.unpack_from("<i", d, b)[0]
            nm, nn = struct.unpack_from("<ii", d, b + 16)
            size, off = struct.unpack_from("<qq", d, b + 28)
            self.exports.append(dict(cls=self.class_name(cls), name=self.fname(nm, nn), size=size, off=off - self.header))

    def fname(self, idx, num=0):
        if not 0 <= idx < len(self.names):
            raise MgpError("bad name index %d" % idx)
        return self.names[idx] + ("_%d" % (num - 1) if num else "")

    def class_name(self, index):
        if index < 0 and -index - 1 < len(self.imports):
            return self.imports[-index - 1]["name"]
        if index > 0 and index - 1 < len(self.exports):
            return self.exports[index - 1]["name"]
        return ""

    def object_ref(self, index):
        """Readable target of an object reference: (package path or '', object name)."""
        if index == 0:
            return "", ""
        if index > 0:
            return "", self.exports[index - 1]["name"] if index - 1 < len(self.exports) else "?"
        imp = self.imports[-index - 1]
        o = imp["outer"]
        pkg = ""
        while o < 0:
            oi = self.imports[-o - 1]
            if oi["cls"] == "Package":
                pkg = oi["name"]; break
            o = oi["outer"]
        if imp["cls"] == "Package":
            pkg = imp["name"]
        return pkg, imp["name"]

    def referenced_packages(self):
        """[(package, [(object class, object name)])] for every package this asset imports from."""
        out = {}
        for imp in self.imports:
            if imp["cls"] == "Package":
                out.setdefault(imp["name"], [])
        for imp in self.imports:
            if imp["cls"] != "Package":
                pkg, _ = self.object_ref(-(self.imports.index(imp) + 1))
                if pkg:
                    out.setdefault(pkg, []).append((imp["cls"], imp["name"]))
        return list(out.items())

    # ---- tagged property parsing
    def parse_export(self, i=0):
        e = self.exports[i]
        end = e["off"] + e["size"]
        props, p = self._props(e["off"], end)
        return dict(name=e["name"], cls=e["cls"], props=props, end=p, size_end=end)

    def _fn(self, p):
        a, b = struct.unpack_from("<ii", self.uexp, p)
        return self.fname(a, b), p + 8

    def _props(self, p, end):
        out = []
        while True:
            if p + 8 > end:
                raise MgpError("property list runs past the export")
            name, p = self._fn(p)
            if name == "None":
                return out, p
            typ, p = self._fn(p)
            size, _arr = struct.unpack_from("<ii", self.uexp, p); p += 8
            tag = dict(name=name, type=typ)
            if typ == "StructProperty":
                tag["struct"], p = self._fn(p); p += 16
            elif typ == "BoolProperty":
                tag["bool_at"] = p; p += 1
            elif typ in ("ByteProperty", "EnumProperty"):
                tag["enum"], p = self._fn(p)
            elif typ in ("ArrayProperty", "SetProperty"):
                tag["inner"], p = self._fn(p)
            elif typ == "MapProperty":
                tag["inner"], p = self._fn(p); tag["vtype"], p = self._fn(p)
            has_guid = self.uexp[p]; p += 1
            if has_guid:
                p += 16
            tag["off"], tag["size"] = p, size
            self._value(tag, p, size)
            out.append(tag)
            p += size
            if p > end:
                raise MgpError("property %s overruns its export" % name)

    def _value(self, tag, p, size):
        t, u = tag["type"], self.uexp
        try:
            if t in SIMPLE:
                fmt, n = SIMPLE[t]
                tag["value"] = struct.unpack_from(fmt, u, p)[0]; tag["edit"] = "num"
            elif t == "BoolProperty":
                tag["value"] = bool(u[tag["bool_at"]]); tag["off"] = tag["bool_at"]; tag["edit"] = "bool"
            elif t == "ByteProperty" and tag["enum"] == "None":
                tag["value"] = u[p]; tag["edit"] = "num"
            elif t in ("ByteProperty", "EnumProperty"):
                tag["value"] = self._fn(p)[0]
            elif t == "NameProperty":
                tag["value"] = self._fn(p)[0]
            elif t == "StrProperty":
                n = struct.unpack_from("<i", u, p)[0]
                tag["value"] = "" if n == 0 else bytes(u[p + 4:p + 3 + n]).decode("latin1") if n > 0 else bytes(u[p + 4:p + 2 + (-n) * 2 - 2]).decode("utf-16le", "replace")
            elif t == "ObjectProperty":
                idx = struct.unpack_from("<i", u, p)[0]
                pkg, obj = self.object_ref(idx)
                tag["value"] = (pkg + "." + obj) if pkg else obj
                tag["ref"] = pkg
                if idx < 0:
                    tag["ref_cls"] = self.imports[-idx - 1]["cls"]
            elif t == "SoftObjectProperty":
                tag["value"] = self._fn(p)[0] + self._soft_tail(p + 8)
            elif t == "StructProperty":
                s = tag["struct"]
                if s in STRUCT_FLOATS:
                    n = STRUCT_FLOATS[s]
                    tag["value"] = list(struct.unpack_from("<%df" % n, u, p)); tag["edit"] = "floats"; tag["labels"] = STRUCT_LABELS[s]
                elif s == "Color":
                    b, g, r, a = u[p:p + 4]
                    tag["value"] = [r, g, b, a]; tag["edit"] = "color8"
                elif s == "Guid":
                    tag["value"] = bytes(u[p:p + 16]).hex()
                else:
                    kids, q = self._props(p, p + size)
                    if q != p + size:
                        tag["value"] = "(%d unparsed bytes)" % (p + size - q)
                    tag["children"] = kids
            elif t in ("ArrayProperty", "SetProperty"):
                self._array(tag, p, size)
            else:
                tag["value"] = "(%s, %d bytes)" % (t, size)
        except (struct.error, IndexError, MgpError) as ex:
            tag.pop("children", None); tag.pop("edit", None)
            tag["value"] = "(unreadable %s: %s)" % (t, ex)

    def _soft_tail(self, p):
        n = struct.unpack_from("<i", self.uexp, p)[0]
        return "" if n == 0 else ":" + bytes(self.uexp[p + 4:p + 3 + n]).decode("latin1")

    def _array(self, tag, p, size):
        u = self.uexp
        count = struct.unpack_from("<i", u, p)[0]
        inner, q = tag["inner"], p + 4
        items = []
        if inner == "StructProperty":
            _n, q = self._fn(q); _t, q = self._fn(q)
            esize, _ = struct.unpack_from("<ii", u, q); q += 8
            sname, q = self._fn(q); q += 16
            if u[q]:
                q += 16
            q += 1
            tag["elem_struct"] = sname
            if count and esize % count == 0 and sname in STRUCT_FLOATS | {"Color": 4, "Guid": 16}:
                each = esize // count
                for k in range(count):
                    items.append(dict(name="[%d]" % k, type="StructProperty", struct=sname,
                                      value=list(struct.unpack_from("<%df" % STRUCT_FLOATS[sname], u, q + k * each)) if sname in STRUCT_FLOATS else "", off=q + k * each,
                                      size=each, edit="floats" if sname in STRUCT_FLOATS else None, labels=STRUCT_LABELS.get(sname, "")))
            else:
                for k in range(count):
                    kids, q2 = self._props(q, p + size)
                    items.append(dict(name="[%d]" % k, type="StructProperty", struct=sname, children=kids))
                    q = q2
        else:
            fixed = {"FloatProperty": "<f", "IntProperty": "<i", "UInt32Property": "<I", "Int64Property": "<q", "DoubleProperty": "<d"}
            for k in range(count):
                if inner in fixed:
                    n = struct.calcsize(fixed[inner])
                    items.append(dict(name="[%d]" % k, type=inner, value=struct.unpack_from(fixed[inner], u, q)[0], off=q, size=n, edit="num")); q += n
                elif inner == "ObjectProperty":
                    pkg, obj = self.object_ref(struct.unpack_from("<i", u, q)[0])
                    items.append(dict(name="[%d]" % k, type=inner, value=(pkg + "." + obj) if pkg else obj, ref=pkg)); q += 4
                elif inner in ("NameProperty", "EnumProperty", "ByteProperty") and (size - 4) == count * 8:
                    items.append(dict(name="[%d]" % k, type=inner, value=self._fn(q)[0])); q += 8
                elif inner == "ByteProperty" and (size - 4) == count:
                    items.append(dict(name="[%d]" % k, type=inner, value=u[q], off=q, size=1, edit="num")); q += 1
                else:
                    tag["value"] = "(array of %s, %d items)" % (inner, count)
                    items = []
                    break
        tag["children"] = items
        tag["count"] = count

    # ---- patching
    def set_value(self, off, edit, value, size=None):
        """Patch the value at uexp offset `off` (found by a fresh parse). Never changes the length."""
        u = self.uexp
        ex = self.parse_export(0)
        node = self._find(ex["props"], off, [], ex["cls"])
        if not node:
            raise MgpError("that value cannot be edited (read-only, or not found)")
        k = node["edit"]
        if k == "num":
            if node["type"] in SIMPLE:
                fmt, n = SIMPLE[node["type"]]
            elif node["type"] == "ByteProperty":
                fmt, n = "<B", 1
            else:
                raise MgpError("unsupported number type")
            v = float(value) if fmt in ("<f", "<d") else int(float(value))
            try:
                struct.pack_into(fmt, u, off, v)
            except struct.error:
                raise MgpError("value out of range for %s" % node["type"])
        elif k == "bool":
            u[off] = 1 if (value is True or str(value).lower() in ("1", "true", "yes", "on")) else 0
        elif k == "floats":
            vals = [float(x) for x in value]
            if len(vals) != len(node["value"]):
                raise MgpError("expected %d numbers" % len(node["value"]))
            struct.pack_into("<%df" % len(vals), u, off, *vals)
        elif k == "color8":
            r, g, b, a = [max(0, min(255, int(float(x)))) for x in value]
            u[off:off + 4] = bytes([b, g, r, a])
        return True

    def _find(self, nodes, off, path, cls):
        for n in nodes:
            p = path + [n["name"]]
            if n.get("off") == off and n.get("edit") and allowed(p, cls):
                return n
            for c in n.get("children") or []:
                f = self._find([c], off, p, cls)
                if f:
                    return f
        return None


def allowed(path, cls):
    """Which values may be edited. Material instances: only the scalar/vector parameter VALUES - the static
    switches and base-property overrides are baked into precompiled shaders, so changing them would not
    behave. Everything else with a fixed size (data assets) is editable."""
    if cls == "MaterialInstanceConstant":
        return bool(path) and path[0] in ("ScalarParameterValues", "VectorParameterValues") and path[-1] == "ParameterValue"
    return True


def _label(n):
    """Nice name for an array item: a parameter's own name."""
    for c in n.get("children") or []:
        if c["name"] == "ParameterInfo":
            for cc in c.get("children") or []:
                if cc["name"] == "Name" and cc.get("value"):
                    return cc["value"]
    return n["name"]


def tree(asset):
    """JSON-friendly copy of the first export's properties."""
    ex = asset.parse_export(0)
    cls = ex["cls"]

    def conv(n, path):
        p = path + [n["name"]]
        d = dict(name=n["name"], type=n["type"])
        for k in ("struct", "value", "labels", "ref", "ref_cls", "enum", "count"):
            if k in n and n[k] is not None:
                d[k] = n[k]
        if n.get("edit") and allowed(p, cls):
            d["edit"] = n["edit"]; d["off"] = n["off"]
        if n.get("children") is not None:
            d["children"] = [conv(c, p) for c in n["children"]]
            if n["name"].startswith("[") and n["type"] == "StructProperty":
                d["label"] = _label(d)
        return d
    return dict(name=ex["name"], cls=cls, props=[conv(p, []) for p in ex["props"]], trailing=ex["size_end"] - ex["end"])
