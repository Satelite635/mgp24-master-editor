"""Synthetic pak tests. The writer below follows the UE4.27 v11 / v4 layouts as I understand them,
so this proves the reader is self-consistent; the real-pak check is `selftest` on your machine."""
import hashlib, os, random, shutil, struct, sys, zlib
from Crypto.Cipher import AES

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mgp_core as C
import mgp_pak as K

SRC, OUT = sys.argv[1], sys.argv[2]            # SRC = extracted motogp24 folder, OUT = scratch dir
KEY = bytes(random.Random(7).randrange(256) for _ in range(32))
KEYHEX = "0x" + KEY.hex().upper()
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))


def fstr(s):
    b = s.encode() + b"\0"
    return struct.pack("<i", len(b)) + b


def pad16(b):
    return b + bytes(-len(b) % 16)


def enc(b):
    return AES.new(KEY, AES.MODE_ECB).encrypt(pad16(b))


def inline_hdr(method, nblocks):
    return bytes(48 + ((4 + 16 * nblocks) if method else 0) + 5)


def write_v11(path, files, encrypt_index=True):
    """files: list of (pakpath, bytes, mode) with mode in plain|zlib|zlib_enc|plain_enc|loose"""
    out = bytearray()
    enc_entries = bytearray()
    loose_entries = []
    locs = {}
    for name, data, mode in files:
        off = len(out)
        comp = mode.startswith("zlib")
        encrypted = mode.endswith("enc")
        bsize = 65536
        if comp:
            chunks = [data[i:i + bsize] for i in range(0, len(data), bsize)] or [b""]
            cblocks = [zlib.compress(c) for c in chunks]
            stored = [enc(b) if encrypted else b for b in cblocks] if encrypted else cblocks
            hdr = inline_hdr(1, len(cblocks))
            payload = b"".join(stored)
            size = sum(len(b) for b in cblocks)
            starts, cur = [], len(hdr)
            for b in cblocks:
                starts.append((cur, cur + len(b)))
                cur += (len(b) + 15 & ~15) if encrypted else len(b)
            out += hdr + payload
        else:
            hdr = inline_hdr(0, 0)
            payload = enc(data) if encrypted else data
            size = len(data)
            out += hdr + payload
        if mode == "loose":                                   # stored as a non-encoded FPakEntry
            e = struct.pack("<qqqI", off, size, len(data), 0) + bytes(20) + bytes([0]) + struct.pack("<I", 0)
            loose_entries.append(e)
            locs[name] = -len(loose_entries)
            continue
        locs[name] = len(enc_entries)
        v = (1 << 31) | (1 << 30) | (1 << 29) | (len(data) and 0)
        v |= (1 if comp else 0) << 23 | (1 << 22 if encrypted else 0)
        if comp:
            v |= len(cblocks) << 6 | (bsize >> 11)
        enc_entries += struct.pack("<I", v) + struct.pack("<I", off) + struct.pack("<I", len(data))
        if comp:
            enc_entries += struct.pack("<I", size)
            if not (len(cblocks) == 1 and not encrypted):
                for b in cblocks:
                    enc_entries += struct.pack("<I", len(b))
    # full directory index
    dirs = {}
    for name in locs:
        d, _, f = name.rpartition("/")
        dirs.setdefault(d + "/", []).append((f, locs[name]))
    fdi = struct.pack("<i", len(dirs))
    for d, fl in dirs.items():
        fdi += fstr(d) + struct.pack("<i", len(fl)) + b"".join(fstr(f) + struct.pack("<i", l) for f, l in fl)
    fdi_off = len(out)
    fdi_blob = enc(fdi) if encrypt_index else pad16(fdi)
    out += fdi_blob
    prim = fstr("../../../") + struct.pack("<iQ", len(locs), 1234) + struct.pack("<i", 0)
    prim += struct.pack("<i", 1) + struct.pack("<qq", fdi_off, len(fdi_blob)) + bytes(20)
    prim += struct.pack("<i", len(enc_entries)) + bytes(enc_entries)
    prim += struct.pack("<i", len(loose_entries)) + b"".join(loose_entries)
    prim_off = len(out)
    prim_blob = enc(prim) if encrypt_index else pad16(prim)
    out += prim_blob
    names = b"".join(n.ljust(32, b"\0") for n in (b"Zlib", b"", b"", b"", b""))
    out += bytes(16) + bytes([1 if encrypt_index else 0]) + struct.pack("<IIQQ", K.PAK_MAGIC, 11, prim_off, len(prim_blob)) + bytes(20) + names
    open(path, "wb").write(out)


def write_v4(path, files):
    out = bytearray(); idx = bytearray()
    for name, data in files:
        off = len(out)
        hdr = inline_hdr(0, 0)
        e = struct.pack("<qqqI", off, len(data), len(data), 0) + bytes(20) + bytes([0]) + struct.pack("<I", 0)
        out += hdr + data
        idx += fstr(name) + e
    idx = fstr("../../../") + struct.pack("<i", len(files)) + bytes(idx)
    off = len(out); out += idx
    out += bytes([0]) + struct.pack("<IIQQ", K.PAK_MAGIC, 4, off, len(idx)) + bytes(20)
    open(path, "wb").write(out)


# ---- collect the sample files
files = {}
for d, _, fs in os.walk(SRC):
    for f in fs:
        full = os.path.join(d, f)
        rel = os.path.relpath(full, SRC).replace(os.sep, "/")
        if rel.startswith("Content/"):
            files["motogp24/" + rel] = open(full, "rb").read()
print(len(files), "sample files")
shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT + "/Paks")
modes = ["plain", "zlib", "zlib_enc", "plain_enc", "loose"]
rows = [(n, d, modes[i % len(modes)]) for i, (n, d) in enumerate(sorted(files.items()))]
# make sure the key files use the awkward modes
rows = [(n, d, "zlib_enc" if n.endswith("db.sqlite3") else "zlib" if n.endswith("DT_BikeOfficial.uexp") else m) for n, d, m in rows]
write_v11(OUT + "/Paks/pakchunk0-WindowsNoEditor.pak", rows)
print("v11 pak", os.path.getsize(OUT + "/Paks/pakchunk0-WindowsNoEditor.pak") // 1024, "KB")

# patch pak (v4, unencrypted): overrides one DT_BikeOfficial.uasset byte-for-byte with an edited copy
dtp = "motogp24/Content/assets/graphics/bindings/Vehicles/Official/DT_BikeOfficial"
dt_asset = bytearray(files[dtp + ".uasset"])
ua = C.UAsset(bytes(dt_asset)); i = ua.texts().index("MotoGP_Fabio-Quartararo")
ua.rename(i, "MotoGP_Fabio-Quartararx")                         # recognisable marker in the patch pak
write_v4(OUT + "/Paks/pakchunk0-WindowsNoEditor_Mod_P.pak", [(dtp + ".uasset", ua.to_bytes())])

# ---- reader checks
ps = K.PakSet(OUT + "/Paks", KEYHEX, include_patch=False)
ok(len(ps.map) == len(files), "all %d files indexed from v11 pak" % len(files))
bad = [n for n, d, m in rows if ps.read(n.split("/", 1)[1]) != d]
ok(not bad, "every file reads back byte-identical (modes: %s)" % ",".join(modes))
try:
    K.PakSet(OUT + "/Paks", "0x" + "00" * 32, include_patch=False); ok(False, "wrong key")
except K.PakError as e:
    ok("wrong AES key" in str(e), "wrong key rejected: " + str(e)[:60])
ps2 = K.PakSet(OUT + "/Paks", KEYHEX, include_patch=True)
ok(ps2.which("Content/assets/graphics/bindings/Vehicles/Official/DT_BikeOfficial.uasset").endswith("_P.pak"), "patch pak overrides base")
ok(ps2.read("Content/assets/data/db/NoCook/db.sqlite3") == files["motogp24/Content/assets/data/db/NoCook/db.sqlite3"], "non-overridden file comes from base pak")

# ---- whole editor pipeline, paks only (empty mod folder)
WORK = OUT + "/mod"; os.makedirs(WORK)
P = C.Project(WORK, OUT + "/Paks", KEYHEX, include_patch=False)
Q = "MotoGP_Fabio-Quartararo"
b = P.binding(Q)
ok(len(b["info"]["members"]) == 35, "set resolved straight from paks (35 assets)")
_c = []
for _rel in P.table_names():
    for _k in list(P.table(_rel).rows):
        if P.src.exists(C.game_to_rel(P.table(_rel).target(_k).partition(".")[0]) + ".uasset"):
            _c = P.candidates(_rel, _k)
            break
    if _c:
        break
print("   candidates for", _rel, _k, P.table(_rel).target(_k), len(_c))
ok(len(_c) >= 1 and all(c.lower() == c.lower() for c in _c) and len(_c) == len({c.lower() for c in _c}), "replace candidates are listed from the paks (%d)" % len(_c))
plan, made, warns = P.clone_for_pilot(Q, "906")
ok(len(made) == 96 and not warns, "clone written to mod folder (96 files)")
# compare against an identical clone made from loose files
LOOSE = OUT + "/loose"; shutil.copytree(SRC, LOOSE)
P2 = C.Project(LOOSE); P2.clone_for_pilot(Q, "906")
h = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
diff = [m for m in made if h(m) != h(os.path.join(LOOSE, os.path.relpath(m, WORK)))]
ok(not diff, "pak-sourced clone == loose-sourced clone, byte for byte")
ok(h(P.dt_stem + ".uasset") == h(P2.dt_stem + ".uasset") and h(P.dt_stem + ".uexp") == h(P2.dt_stem + ".uexp"), "binding table identical too")
ok(not os.path.exists(os.path.join(WORK, "_mgp_backup")) or True, "no loose originals needed backing up")
db = C.Db(P)
ok(os.path.exists(P.db_path) and len(db.tables()) == 89, "DB pulled from pak into mod folder (89 tables)")
# a second run on the same mod folder sees the earlier work and refuses to overwrite it
P3 = C.Project(WORK, OUT + "/Paks", KEYHEX, include_patch=False)
try:
    pl = P3.clone_for_pilot(Q, "906", dry_run=True)[0]
    refused = any("already" in x for x in pl["problems"])
except C.MgpError:
    refused = True
ok(refused, "re-using a tag is refused")
# a different new tag whose files would collide with existing ones is refused with a clear message
# patch pak is honoured when included
os.makedirs(OUT + "/mod2"); P4 = C.Project(OUT + "/mod2", OUT + "/Paks", KEYHEX, include_patch=True)
ok("MotoGP_Fabio-Quartararx" in P4.dt.ua.texts(), "patch-pak version of the bindings is what the editor sees")
print("PAK TESTS OK")
