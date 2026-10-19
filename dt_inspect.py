"""Generic DataTable inspector: decode any DT_*.uasset/.uexp pair, report row layout and match row keys to DB columns."""
import os, struct, sqlite3, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mgp_core import UAsset, PKG_TAG


class DT:
    def __init__(self, stem):
        self.ua = UAsset(open(stem + ".uasset", "rb").read())
        self.d = open(stem + ".uexp", "rb").read()
        self.N = [n["text"] for n in self.ua.names]
        self.rows = []                       # (name, {prop: (type, value)})
        self.types = collections.OrderedDict()
        self._parse()

    def fn(self, p):
        i, n = struct.unpack_from("<ii", self.d, p)
        return (self.N[i] + ("" if n == 0 else "_%d" % (n - 1))), p + 8

    def props(self, p):
        out = collections.OrderedDict()
        while True:
            name, p = self.fn(p)
            if name == "None":
                return out, p
            typ, p = self.fn(p)
            size = struct.unpack_from("<i", self.d, p)[0]; p += 8
            extra = ""
            if typ == "StructProperty":
                extra, p = self.fn(p); p += 16
            elif typ == "BoolProperty":
                bv = self.d[p]; p += 1
            elif typ in ("ByteProperty", "EnumProperty"):
                extra, p = self.fn(p)
            elif typ in ("ArrayProperty", "SetProperty"):
                extra, p = self.fn(p)
            elif typ == "MapProperty":
                a, p = self.fn(p); b, p = self.fn(p); extra = a + "->" + b
            p += 1                                         # HasPropertyGuid
            raw = self.d[p:p + size]
            out[name] = (typ + (":" + extra if extra else ""), self.val(typ, raw, bv if typ == "BoolProperty" else None))
            p += size

    def val(self, typ, raw, bv):
        try:
            if typ == "SoftObjectProperty":
                i = struct.unpack_from("<i", raw, 0)[0]; return self.N[i]
            if typ in ("NameProperty",):
                i = struct.unpack_from("<i", raw, 0)[0]; return self.N[i]
            if typ == "ObjectProperty":
                return "import#%d" % struct.unpack_from("<i", raw, 0)[0]
            if typ == "IntProperty": return struct.unpack_from("<i", raw, 0)[0]
            if typ == "FloatProperty": return round(struct.unpack_from("<f", raw, 0)[0], 4)
            if typ == "BoolProperty": return bool(bv)
            if typ == "StrProperty":
                n = struct.unpack_from("<i", raw, 0)[0]; return raw[4:4 + n - 1].decode("latin1")
            if typ in ("ByteProperty", "EnumProperty"):
                i = struct.unpack_from("<i", raw, 0)[0]; return self.N[i] if len(raw) == 8 else raw[0]
            if typ == "TextProperty": return "<text>"
        except Exception:
            pass
        return "<%d bytes>" % len(raw)

    def _parse(self):
        _, p = self.props(0)
        p += 4
        cnt = struct.unpack_from("<i", self.d, p)[0]; p += 4
        for _ in range(cnt):
            name, p = self.fn(p)
            pr, p = self.props(p)
            self.rows.append((name, pr))
            for k, (t, _) in pr.items():
                self.types.setdefault(k, t)
        assert struct.unpack_from("<I", self.d, p)[0] == PKG_TAG, "footer"


def db_keys(dbpath):
    c = sqlite3.connect("file:%s?mode=ro" % dbpath, uri=True)
    out = {}
    for (t,) in c.execute("select name from sqlite_master where type='table'"):
        for _, col, typ, *_ in c.execute('pragma table_info("%s")' % t):
            if typ.upper().startswith("TEXT") or typ == "":
                vals = {r[0] for r in c.execute('select "%s" from "%s"' % (col, t)) if isinstance(r[0], str)}
                if vals:
                    out[(t, col)] = vals
    return out


if __name__ == "__main__":
    root, dbp = sys.argv[1], sys.argv[2]
    keys = db_keys(dbp)
    for d, _, fs in sorted(os.walk(root)):
        for f in sorted(fs):
            if not f.endswith(".uasset"): continue
            stem = os.path.join(d, f[:-7])
            rel = os.path.relpath(stem, root)
            try:
                t = DT(stem)
            except Exception as e:
                print("%-60s ERROR %s: %s" % (rel, type(e).__name__, e)); continue
            names = {r[0] for r in t.rows}
            best = max(keys.items(), key=lambda kv: len(kv[1] & names), default=None)
            m = len(best[1] & names) if best else 0
            match = "%s.%s (%d/%d)" % (best[0][0], best[0][1], m, len(names)) if m else "-"
            print("%-60s rows=%-4d key->%s" % (rel.replace("Characters/Rider/", "").replace("Vehicles/", "V/"), len(t.rows), match))
            print("      props:", ", ".join("%s[%s]" % (k, v.split(":")[0].replace("Property", "")) for k, v in t.types.items()))
