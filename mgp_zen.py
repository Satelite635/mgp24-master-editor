"""Zen packages (UE5 IoStore .uasset, MotoGP 25+): header access and the binding DataTables.

A zen package is one file: summary, name batch, padding + bulk data map, import/export maps, then the export
data. Properties are *unversioned* (no names/types in the data; the .usmap knows the layout). The binding
tables (DT_Bike*, IgnitionDataAssetTableRow) are simple enough to read without the .usmap:
  export = [unversioned header 00 03][RowStruct import index i32][HasGuid i32][row count i32]
           rows * ([row FName 8][00 03][SoftObjectPath: package FName 8, asset FName 8, SubPath FString])
           then the package tag C1 83 2A 9E."""
import struct

from mgp_iostore import cityhash64

PKG_TAG = 0x9E2A83C1
SUMMARY = 52                       # bytes before the name batch (UE5.5 FZenPackageSummary, no versioning info)
OFFSETS = range(24, 52, 4)         # ImportedPublicExportHashes .. ImportedPackageNames offsets
EXPORT_ENTRY = 72


def script_import(path):
    """FPackageObjectIndex of a /Script object, e.g. '/Script/ignitioncore.IgnitionDataAssetTableRow'."""
    h = cityhash64(path.replace(".", "/").lower().encode("utf-16le"))
    return (h & ((1 << 62) - 1)) | (1 << 62)


ROW_STRUCT = script_import("/Script/ignitioncore.IgnitionDataAssetTableRow")


class ZenError(Exception):
    pass


def split_fname(text):
    """'T_Suit_12' -> ('T_Suit', 13) like FName does: a trailing _N (no leading zero) is stored as number N+1."""
    base, sep, num = text.rpartition("_")
    if sep and base and num.isdigit() and (num == "0" or num[0] != "0") and len(num) <= 10 and int(num) < 2 ** 31 - 1:
        return base, int(num) + 1
    return text, 0


def join_fname(text, number):
    return text + ("_%d" % (number - 1) if number else "")


class ZenPackage:
    def __init__(self, data):
        d = bytes(data)
        if len(d) < SUMMARY + 16:
            raise ZenError("file too small for a zen package")
        has_ver, self.header_size = struct.unpack_from("<II", d, 0)
        if has_ver:
            raise ZenError("zen package with versioning info - not supported (expected a cooked game file)")
        n, nbytes = struct.unpack_from("<II", d, SUMMARY)
        self.hash_version = struct.unpack_from("<Q", d, SUMMARY + 8)[0]
        p = SUMMARY + 16 + 8 * n
        lens = [struct.unpack_from(">H", d, p + 2 * i)[0] for i in range(n)]
        p += 2 * n
        self.names = []
        for ln in lens:
            if ln & 0x8000:
                k = (ln & 0x7FFF) * 2
                self.names.append(d[p:p + k].decode("utf-16le")); p += k
            else:
                self.names.append(d[p:p + ln].decode("latin-1")); p += ln
        if p != SUMMARY + 16 + 10 * n + nbytes:
            raise ZenError("name batch size mismatch - layout not understood")
        pad = struct.unpack_from("<Q", d, p)[0]
        q = p + 8 + pad
        if q % 8:
            raise ZenError("bulk data map not aligned - layout not understood")
        bulk = struct.unpack_from("<q", d, q)[0]
        self.after_names = q + 8 + bulk                      # first byte after the bulk data map
        if self.after_names != struct.unpack_from("<i", d, 24)[0]:
            raise ZenError("header layout not understood (imported export hashes not after the bulk data map)")
        self.bulk_map = d[q + 8:self.after_names]
        self.data = d
        self.exports = []
        eo, ebe = struct.unpack_from("<ii", d, 32)
        for i in range((ebe - eo) // EXPORT_ENTRY):
            off, size = struct.unpack_from("<QQ", d, eo + EXPORT_ENTRY * i)
            name = struct.unpack_from("<I", d, eo + EXPORT_ENTRY * i + 16)[0]
            self.exports.append(dict(entry=eo + EXPORT_ENTRY * i, serial_off=off, size=size, name=self.names[name]))
        io = struct.unpack_from("<i", d, 28)[0]
        self.imports = list(struct.unpack_from("<%dQ" % ((eo - io) // 8), d, io))

    def imported_package_names(self):
        """Names of the packages this one imports (its ImportedPackageNames name batch), in file order."""
        at, end = struct.unpack_from("<i", self.data, 48)[0], self.header_size
        if end - at < 4 or not struct.unpack_from("<I", self.data, at)[0]:
            return []
        n, nbytes = struct.unpack_from("<II", self.data, at)
        p = at + 16 + 8 * n
        lens = [struct.unpack_from(">H", self.data, p + 2 * i)[0] for i in range(n)]
        p += 2 * n
        out = []
        for ln in lens:
            if ln & 0x8000:
                k = (ln & 0x7FFF) * 2; t = self.data[p:p + k].decode("utf-16le")
            else:
                k = ln; t = self.data[p:p + k].decode("latin-1")
            p += k
            out.append(t)
        return out

    def imported_package_ids(self):
        """FPackageIds of the packages this one imports (its ImportedPackageNames name batch)."""
        from mgp_iostore import package_id
        return sorted(package_id(t) for t in self.imported_package_names())

    def import_package(self, package_index):
        """Package name a negative FPackageIndex imports from ('' if it is not a package import)."""
        v = self.import_at(package_index)
        if v is None or v >> 62 != 2:
            return ""
        names = self.imported_package_names()
        i = (v >> 32) & 0x3FFFFFFF
        return names[i] if i < len(names) else ""

    def import_at(self, package_index):
        """FPackageObjectIndex of a negative FPackageIndex (import), else None."""
        i = -package_index - 1
        return self.imports[i] if package_index < 0 and i < len(self.imports) else None

    def name_index(self, text):
        try:
            return self.names.index(text)
        except ValueError:
            return None

    def export_data(self):
        """Bytes of all exports (from the header end to the end of the file)."""
        return self.data[self.header_size:]

    def build(self, names, export_data, export_sizes=None):
        """New package bytes with `names` (old names + appended ones) and new export data."""
        d = self.data
        enc = []
        for t in names:
            try:
                b = t.encode("ascii"); enc.append((b, len(b), t.lower().encode("ascii")))
            except UnicodeEncodeError:
                b = t.encode("utf-16le"); enc.append((b, 0x8000 | len(t), t.lower().encode("utf-16le")))
        blob = b"".join(b for b, _, _ in enc)
        out = bytearray(d[:SUMMARY])
        out += struct.pack("<IIQ", len(names), len(blob), self.hash_version)
        for i, (b, _, low) in enumerate(enc):
            out += struct.pack("<Q", cityhash64(low) if i >= len(self.names) else
                               struct.unpack_from("<Q", d, SUMMARY + 16 + 8 * i)[0])
        for _, ln, _ in enc:
            out += struct.pack(">H", ln)
        out += blob
        pad = (-(len(out) + 8)) % 8
        out += struct.pack("<Q", pad) + bytes(pad)
        out += struct.pack("<q", len(self.bulk_map)) + self.bulk_map
        delta = len(out) - self.after_names
        out += d[self.after_names:self.header_size]
        for o in OFFSETS:
            v = struct.unpack_from("<i", out, o)[0]
            struct.pack_into("<i", out, o, v + delta)
        struct.pack_into("<I", out, 4, self.header_size + delta)
        if export_sizes:
            for e, size in zip(self.exports, export_sizes):
                struct.pack_into("<Q", out, e["entry"] + delta + 8, size)
        out += export_data
        return bytes(out)


class ZenBindingTable:
    """GP25 binding DataTable (IgnitionDataAssetTableRow {DataAsset: SoftObjectPath}); same interface as
    mgp_core.BindingTable: rows, target(row), set_target(row, '/Game/.../pkg.obj'), save()."""

    ROW = 30                               # FName 8 + header 2 + package 8 + asset 8 + empty SubPath 4

    def __init__(self, uasset_bytes, uexp_bytes=None):
        self.pkg = ZenPackage(uasset_bytes)
        if len(self.pkg.exports) != 1:
            raise ZenError("expected one export (DataTable), found %d" % len(self.pkg.exports))
        self.names = list(self.pkg.names)
        self.x = bytearray(self.pkg.export_data())
        self.ua = self                       # code written for BindingTable calls table.ua.texts()
        self.rows = {}
        self._parse()

    def _parse(self):
        x = self.x
        if x[:2] != b"\x00\x03":
            raise ZenError("DataTable header not understood (%s)" % x[:2].hex())
        if self.pkg.import_at(struct.unpack_from("<i", x, 2)[0]) != ROW_STRUCT:
            raise ZenError("not an IgnitionDataAssetTableRow table")
        count = struct.unpack_from("<i", x, 10)[0]
        p = 14
        for _ in range(count):
            ni, nn = struct.unpack_from("<II", x, p)
            if x[p + 8:p + 10] != b"\x00\x03" or struct.unpack_from("<i", x, p + 26)[0] != 0:
                raise ZenError("unexpected row layout at %d" % p)
            key = join_fname(self.names[ni], nn)
            self.rows[key] = dict(off=p + 10)
            p += self.ROW
        if p + 4 != len(x) or struct.unpack_from("<I", x, p)[0] != PKG_TAG:
            raise ZenError("DataTable end not understood - layout differs from the GP25 bike tables")

    def texts(self):
        return self.names + [self.target(r) for r in self.rows]

    def _pair(self, row):
        o = self.rows[row]["off"]
        pi, pn, ai, an = struct.unpack_from("<IIII", self.x, o)
        return pi, ai, pn, an

    def target_index(self, row):
        return self._pair(row)

    def target(self, row):
        pi, ai, pn, an = self._pair(row)
        return join_fname(self.names[pi], pn) + "." + join_fname(self.names[ai], an)

    def users_of(self, idx):
        return [r for r in self.rows if self.target_index(r) == idx]

    def _name(self, text):
        if text in self.names:
            return self.names.index(text)
        self.names.append(text)
        return len(self.names) - 1

    def set_target(self, row, new_obj_path):
        if not new_obj_path.startswith("/Game/") or "." not in new_obj_path:
            raise ZenError("target must look like /Game/.../pkg.obj")
        pkg, _, obj = new_obj_path.partition(".")
        (pb, pn), (ob, on) = split_fname(pkg), split_fname(obj)
        struct.pack_into("<IIII", self.x, self.rows[row]["off"], self._name(pb), pn, self._name(ob), on)

    def to_bytes(self):
        return self.pkg.build(self.names, bytes(self.x), [len(self.x) - 4])

    def save(self, uasset_path, uexp_path=None):
        data = self.to_bytes()
        ZenBindingTable(data)                # must re-parse before it is written
        with open(uasset_path, "wb") as f:
            f.write(data)


STYLE_FIELDS = [("StartLeg", "FloatProperty"), ("LegOut", "FloatProperty"), ("LegOutType", "FloatProperty"),
                ("BrakeFingers", "IntProperty"), ("RiderMaxLean", "FloatProperty"), ("OldSchoolAmount", "FloatProperty"),
                ("RidingStyle", "IntProperty"), ("SubRidingStyle", "IntProperty")]      # RidingStyle struct order (GP25 .usmap)


def _unversioned_header(x, p):
    """-> ([schema indices that have a value], set of those that are zero (no bytes)), new offset."""
    present, zeros, idx, frags = [], set(), 0, []
    while True:
        h = struct.unpack_from("<H", x, p)[0]; p += 2
        frags.append(h)
        idx += h & 0x7F
        n = h >> 9
        present += [(idx + i, bool(h & 0x80)) for i in range(n)]
        idx += n
        if h & 0x100:
            break
    masked = [i for i, z in present if z]
    if masked:
        nb = 1 if len(masked) <= 8 else 2 if len(masked) <= 16 else ((len(masked) + 31) // 32) * 4
        bits = int.from_bytes(x[p:p + nb], "little"); p += nb
        zeros = {i for k, i in enumerate(masked) if bits >> k & 1}
    return [i for i, _ in present], zeros, p


class ZenStyleTable:
    """GP25 RidingStyle_DT (zen, unversioned rows of 8 Int/Float fields); same interface as mgp_core.StyleTable.
    Row = [FName 8][unversioned header][zero mask][non-zero values 4 bytes each]. Rows are re-serialized on save
    (one fragment of all 8 fields, zeros in the mask), which is how the game's own file is written."""

    FMT = {"IntProperty": "<i", "FloatProperty": "<f"}

    def __init__(self, uasset_bytes, uexp_bytes=None):
        self.pkg = ZenPackage(uasset_bytes)
        if len(self.pkg.exports) != 1:
            raise ZenError("RidingStyle_DT: expected one export, found %d" % len(self.pkg.exports))
        self.names = list(self.pkg.names)
        x = self.pkg.export_data()
        if x[:2] != b"\x00\x03":
            raise ZenError("RidingStyle_DT header not understood (%s)" % x[:2].hex())
        self.head = x[:10]                                  # header, RowStruct import, HasGuid
        count = struct.unpack_from("<i", x, 10)[0]
        p, self.order, self._vals = 14, [], {}
        for _ in range(count):
            ni, nn = struct.unpack_from("<II", x, p); p += 8
            key = join_fname(self.names[ni], nn)
            present, zeros, p = _unversioned_header(x, p)
            vals = {}
            for i in present:
                if i >= len(STYLE_FIELDS):
                    raise ZenError("RidingStyle_DT row %s: field #%d not in the known layout" % (key, i))
                name, typ = STYLE_FIELDS[i]
                if i in zeros:
                    vals[name] = 0
                else:
                    vals[name] = struct.unpack_from(self.FMT[typ], x, p)[0]; p += 4
            for name, _ in STYLE_FIELDS:                      # skipped = default = 0
                vals.setdefault(name, 0)
            self.order.append(key)
            self._vals[key] = vals
        if p + 4 != len(x) or struct.unpack_from("<I", x, p)[0] != PKG_TAG:
            raise ZenError("RidingStyle_DT end not understood - layout differs")
        self.rows = {k: {n: (t, None) for n, t in STYLE_FIELDS} for k in self.order}

    def presets(self):
        return [r for r in self.rows if "_" not in r]

    def values(self, key):
        return {n: (int(self._vals[key][n]) if t == "IntProperty" else round(float(self._vals[key][n]), 4)) for n, t in STYLE_FIELDS}

    def types(self, key):
        return dict(STYLE_FIELDS)

    def set_values(self, key, vals):
        if key not in self.rows:
            raise ZenError("no riding-style row for " + key)
        old, types, changed = self.values(key), dict(STYLE_FIELDS), {}
        for name, v in vals.items():
            if name not in types:
                raise ZenError("unknown riding-style field: " + name)
            v = int(v) if types[name] == "IntProperty" else struct.unpack("<f", struct.pack("<f", float(v)))[0]
            self._vals[key][name] = v
            new = self.values(key)[name]
            if new != old[name]:
                changed[name] = (old[name], new)
        return changed

    def add_row(self, key, donor):
        if key in self.rows:
            raise ZenError("%s already has a riding-style row" % key)
        if donor not in self.rows:
            raise ZenError("no riding-style row for " + donor)
        self.order.append(key)
        self._vals[key] = dict(self._vals[donor])
        self.rows[key] = dict(self.rows[donor])

    def _row_bytes(self, key):
        base, num = split_fname(key)
        if base not in self.names:
            self.names.append(base)
        out = bytearray(struct.pack("<II", self.names.index(base), num))
        mask = 0
        vals = b""
        for i, (name, typ) in enumerate(STYLE_FIELDS):
            v = self._vals[key][name]
            if v == 0:
                mask |= 1 << i
            else:
                vals += struct.pack(self.FMT[typ], v)
        n = len(STYLE_FIELDS)
        out += struct.pack("<H", (n << 9) | 0x100 | (0x80 if mask else 0))
        if mask:
            out += bytes([mask])
        return bytes(out + vals)

    def to_bytes(self):
        body = bytearray(self.head) + struct.pack("<i", len(self.order))
        for k in self.order:
            body += self._row_bytes(k)
        body += struct.pack("<I", PKG_TAG)
        return self.pkg.build(self.names, bytes(body), [len(body) - 4])

    def save(self, uasset_path, uexp_path=None):
        data = self.to_bytes()
        ZenStyleTable(data)                    # must re-parse before it is written
        with open(uasset_path, "wb") as f:
            f.write(data)
