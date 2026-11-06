"""Reader for .usmap files (property layouts of a game's classes/structs, as made by FModel/UE4SS/Dumper-7).
MotoGP 25/26 assets have unversioned properties (no names in the file); the .usmap gives their order and types."""
import struct

TYPES = ["ByteProperty", "BoolProperty", "IntProperty", "FloatProperty", "ObjectProperty", "NameProperty",
         "DelegateProperty", "DoubleProperty", "ArrayProperty", "StructProperty", "StrProperty", "TextProperty",
         "InterfaceProperty", "MulticastDelegateProperty", "WeakObjectProperty", "LazyObjectProperty",
         "AssetObjectProperty", "SoftObjectProperty", "UInt64Property", "UInt32Property", "UInt16Property",
         "Int64Property", "Int16Property", "Int8Property", "MapProperty", "SetProperty", "EnumProperty",
         "FieldPathProperty", "OptionalProperty", "Utf8StrProperty", "AnsiStrProperty"]


class UsmapError(Exception):
    pass


def _decompress(method, data, size):
    if method == 0:
        return data
    if method == 3:                                           # zstandard
        try:
            from compression import zstd                       # Python 3.14+
            return zstd.decompress(data)
        except ImportError:
            pass
        try:
            import zstandard
        except ImportError:
            raise UsmapError("this .usmap is zstd-compressed: run 'pip install zstandard' (the .exe has it built in), "
                             "or save an uncompressed .usmap")
        return zstandard.ZstdDecompressor().decompress(data, max_output_size=size)
    if method == 2:
        try:
            import brotli
        except ImportError:
            raise UsmapError("this .usmap is brotli-compressed: run 'pip install brotli' or save an uncompressed .usmap")
        return brotli.decompress(data)
    raise UsmapError("this .usmap uses compression %d (Oodle?) - save it uncompressed or with zstd" % method)


class Prop:
    __slots__ = ("name", "index", "array_dim", "type")

    def __init__(self, name, index, array_dim, typ):
        self.name, self.index, self.array_dim, self.type = name, index, array_dim, typ


class Usmap:
    """structs: {name: dict(super=name|None, count=props incl. array slots, props=[Prop])}; enums: {name: [names]}.
    A property type is a tuple: (type,) or ("StructProperty", struct) / ("EnumProperty", inner, enum) /
    ("ByteProperty",) / ("ArrayProperty", inner) / ("MapProperty", key, value) ..."""

    def __init__(self, data):
        d = bytes(data)
        magic, ver = struct.unpack_from("<HB", d, 0)
        if magic != 0x30C4:
            raise UsmapError("not a .usmap file")
        p = 3
        if ver >= 1:
            has, = struct.unpack_from("<i", d, p); p += 4
            if has:
                p += 8
                n, = struct.unpack_from("<i", d, p); p += 4 + n * 20
                p += 4
        method, csize, size = struct.unpack_from("<BII", d, p); p += 9
        b = _decompress(method, d[p:p + csize], size)
        if len(b) != size:
            raise UsmapError("the .usmap did not decompress to its stated size")
        self.version = ver
        self._b, self._p = b, 0
        names = [self._name_str(ver) for _ in range(self._u32())]
        self.enums = {}
        for _ in range(self._u32()):
            en = names[self._u32()]
            cnt = self._u16() if ver >= 3 else self._u8()
            vals = []
            for _ in range(cnt):
                if ver >= 4:
                    self._p += 8
                vals.append(names[self._u32()])
            self.enums[en] = vals
        self.structs = {}
        for _ in range(self._u32()):
            sn = names[self._u32()]
            si = self._u32()
            count, ser = self._u16(), self._u16()
            props = []
            for _ in range(ser):
                idx, dim, pn = self._u16(), self._u8(), names[self._u32()]
                props.append(Prop(pn, idx, dim, self._type(names)))
            self.structs[sn] = dict(super=None if si == 0xFFFFFFFF else names[si], count=count, props=props)
        del self._b

    def _u8(self):
        v = self._b[self._p]; self._p += 1; return v

    def _u16(self):
        v, = struct.unpack_from("<H", self._b, self._p); self._p += 2; return v

    def _u32(self):
        v, = struct.unpack_from("<I", self._b, self._p); self._p += 4; return v

    def _name_str(self, ver):
        n = self._u16() if ver >= 2 else self._u8()
        s = self._b[self._p:self._p + n].decode("utf-8", "replace"); self._p += n
        return s

    def _type(self, names):
        t = TYPES[self._u8()]
        if t == "EnumProperty":
            inner = self._type(names)
            return (t, inner, names[self._u32()])
        if t == "StructProperty":
            return (t, names[self._u32()])
        if t in ("ArrayProperty", "SetProperty", "OptionalProperty"):
            return (t, self._type(names))
        if t == "MapProperty":
            k = self._type(names)
            return (t, k, self._type(names))
        return (t,)

    def schema(self, name):
        """All properties of a struct/class incl. its supers, as {schema index: (Prop, array slot)}, and the total count.
        The struct's own properties come first, then its super's (same order as CUE4Parse/UE's field iterator)."""
        chain, n = [], name
        while n is not None:
            s = self.structs.get(n)
            if s is None:
                raise UsmapError("the .usmap has no layout for %s" % n)
            chain.append(s)
            n = s["super"]
        out, base = {}, 0
        for s in chain:
            for pr in s["props"]:
                for k in range(pr.array_dim):
                    out[base + pr.index + k] = (pr, k)
            base += s["count"]
        return out, base


_cache = {}


def load(path):
    import os
    key = (os.path.abspath(path), os.path.getmtime(path))
    if key not in _cache:
        _cache.clear()
        _cache[key] = Usmap(open(path, "rb").read())
    return _cache[key]


MODULES = ("CoreUObject", "Engine", "ignitioncore", "motogp25", "motogp26", "motogp24", "GameplayTags", "UMG", "SlateCore")


def script_names(u, modules=MODULES):
    """{FPackageObjectIndex: struct/class name} for the .usmap's types in the given /Script modules (zen imports
    of script objects are only hashes). Built once per .usmap (about a second)."""
    cached = getattr(u, "_script_names", None)
    if cached is None:
        import mgp_zen
        cached = {}
        for m in modules:
            for k in u.structs:
                cached.setdefault(mgp_zen.script_import("/Script/%s.%s" % (m, k)), k)
        u._script_names = cached
    return cached
