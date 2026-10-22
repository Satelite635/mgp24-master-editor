"""Read-only IoStore (.utoc/.ucas) reader for MotoGP 25+ (UE5.5, TOC version 8).

A container is a .utoc (table of contents) and a .ucas (data). Every package is one chunk (type ExportBundleData)
holding its zen header + export data. The directory index maps file names ('Content/.../X.uasset') to chunks.
Chunk data is cut into compression blocks (Oodle via mgp_oodle, or stored), optionally AES-encrypted."""
import os, struct

TOC_MAGIC = b"-==--==--==--==-"
F_COMPRESSED, F_ENCRYPTED, F_SIGNED, F_INDEXED = 1, 2, 4, 8
CHUNK_EXPORT_BUNDLE_DATA = 1


class IoStoreError(Exception):
    pass


def _u40be(b, p):
    return int.from_bytes(b[p:p + 5], "big")


class TocEntry:
    __slots__ = ("idx", "usize")

    def __init__(self, idx, usize):
        self.idx, self.usize = idx, usize


class Toc:
    def __init__(self, utoc_path, key=None):
        self.path, self.key = utoc_path, key
        self.ucas = utoc_path[:-5] + ".ucas"
        d = open(utoc_path, "rb").read()
        if d[:16] != TOC_MAGIC:
            raise IoStoreError("not a .utoc: " + os.path.basename(utoc_path))
        (self.version, _, _, hs, ec, bc, bsz, cmc, cml, self.block_size, dis, self.partitions, self.container_id
         ) = struct.unpack_from("<BBHIIIIIIIIIQ", d, 16)
        if self.version < 8:
            raise IoStoreError("unsupported .utoc version %d in %s" % (self.version, os.path.basename(utoc_path)))
        self.flags = d[80]
        seeds, self.partition_size, nph = struct.unpack_from("<4xIQI", d, 80)
        p = hs
        self.chunk_ids = [d[p + 12 * i:p + 12 * i + 12] for i in range(ec)]; p += 12 * ec
        self.offlen = [(_u40be(d, p + 10 * i), _u40be(d, p + 10 * i + 5)) for i in range(ec)]; p += 10 * ec
        p += 4 * seeds + 4 * nph
        self.blocks = []
        for i in range(bc):
            q = p + bsz * i
            self.blocks.append((int.from_bytes(d[q:q + 5], "little"), int.from_bytes(d[q + 5:q + 8], "little"),
                                int.from_bytes(d[q + 8:q + 11], "little"), d[q + 11]))
        p += bsz * bc
        self.methods = [d[p + cml * i:p + cml * (i + 1)].split(b"\0")[0].decode() for i in range(cmc)]; p += cmc * cml
        if self.flags & F_SIGNED:
            hsz = struct.unpack_from("<i", d, p)[0]
            p += 4 + 2 * hsz + 20 * bc
        self.files = {}                                      # 'motogp25/content/...' (lower) -> (original, toc index)
        if self.flags & F_INDEXED and dis:
            raw = d[p:p + dis]
            if self.flags & F_ENCRYPTED:
                from mgp_pak import _aes_decrypt
                if not key:
                    raise IoStoreError("%s is encrypted - AES key needed" % os.path.basename(utoc_path))
                raw = _aes_decrypt(key, raw)
            self._read_dir(raw)
        self.by_id = {cid: i for i, cid in enumerate(self.chunk_ids)}

    def _read_dir(self, b):
        p = [0]
        def u32():
            v = struct.unpack_from("<I", b, p[0])[0]; p[0] += 4; return v
        def fstr():
            n = struct.unpack_from("<i", b, p[0])[0]; p[0] += 4
            if n < 0:
                s = b[p[0]:p[0] - 2 * n].decode("utf-16le"); p[0] += -2 * n
            else:
                s = b[p[0]:p[0] + n].decode("utf-8", "replace"); p[0] += n
            return s.rstrip("\0")
        mount = fstr()
        dirs = [tuple(u32() for _ in range(4)) for _ in range(u32())]       # name, first child, next sibling, first file
        files = [tuple(u32() for _ in range(3)) for _ in range(u32())]      # name, next file, toc entry index
        strings = [fstr() for _ in range(u32())]
        NONE = 0xFFFFFFFF
        mount = mount.replace("\\", "/")
        while mount.startswith("../"):
            mount = mount[3:]
        stack = [(0, mount.rstrip("/"))]
        while stack:
            di, path = stack.pop()
            name, child, sib, f = dirs[di]
            here = path + "/" + strings[name] if name != NONE and di else path
            while f != NONE:
                fn, nxt, idx = files[f]
                full = (here + "/" + strings[fn]).lstrip("/")
                self.files[full.lower()] = (full, TocEntry(idx, self.offlen[idx][1]))
                f = nxt
            if sib != NONE:
                stack.append((sib, path))
            if child != NONE:
                stack.append((child, here))

    def size(self, idx):
        return self.offlen[idx][1]

    def read_index(self, idx):
        off, length = self.offlen[idx]
        if not length:
            return b""
        bs = self.block_size
        first, last = off // bs, (off + length - 1) // bs
        out = []
        with open(self.ucas, "rb") as f:
            for bi in range(first, last + 1):
                boff, csize, usize, meth = self.blocks[bi]
                f.seek(boff)
                raw = f.read((csize + 15) & ~15 if self.flags & F_ENCRYPTED else csize)
                if self.flags & F_ENCRYPTED:
                    from mgp_pak import _aes_decrypt
                    raw = _aes_decrypt(self.key, raw)
                raw = raw[:csize]
                if meth:
                    name = self.methods[meth - 1] if meth - 1 < len(self.methods) else "?"
                    if name.lower() != "oodle":
                        raise IoStoreError("unsupported compression '%s' in %s" % (name, os.path.basename(self.ucas)))
                    import mgp_oodle
                    try:
                        raw = mgp_oodle.decompress(raw, usize, [os.path.dirname(self.path)])
                    except (OSError, ValueError) as x:
                        raise IoStoreError("%s (%s)" % (x, os.path.basename(self.ucas)))
                out.append(raw[:usize])
        data = b"".join(out)
        s = off - first * bs
        return data[s:s + length]

    def read(self, lower_path):
        return self.read_index(self.files[lower_path][1].idx)

    def close(self):
        pass


def cityhash64(s):
    """CityHash64 (v1.0.3, as used by Unreal) of bytes `s`."""
    M = (1 << 64) - 1
    k0, k1, k2 = 0xc3a5c85c97cb3127, 0xb492b66fbe98f273, 0x9ae16a3b2f90404f
    f64 = lambda p: struct.unpack_from("<Q", s, p)[0]
    f32 = lambda p: struct.unpack_from("<I", s, p)[0]
    rot = lambda v, n: v if n == 0 else ((v >> n) | (v << (64 - n))) & M
    smix = lambda v: v ^ (v >> 47)
    def h16(u, v, mul=0x9ddfea08eb382d69):
        a = ((u ^ v) * mul) & M; a ^= a >> 47
        b = ((v ^ a) * mul) & M; b ^= b >> 47
        return (b * mul) & M
    n = len(s)
    def len0to16():
        if n >= 8:
            mul = (k2 + n * 2) & M
            a = (f64(0) + k2) & M
            b = f64(n - 8)
            c = (rot(b, 37) * mul + a) & M
            d = ((rot(a, 25) + b) * mul) & M
            return h16(c, d, mul)
        if n >= 4:
            mul = (k2 + n * 2) & M
            a = f32(0)
            return h16((n + (a << 3)) & M, f32(n - 4), mul)
        if n > 0:
            a, b, c = s[0], s[n >> 1], s[n - 1]
            y = (a + (b << 8)) & 0xFFFFFFFF
            z = (n + (c << 2)) & 0xFFFFFFFF
            return (smix(((y * k2) ^ (z * k0)) & M) * k2) & M
        return k2
    def len17to32():
        mul = (k2 + n * 2) & M
        a = (f64(0) * k1) & M; b = f64(8); c = (f64(n - 8) * mul) & M; d = (f64(n - 16) * k2) & M
        return h16((rot((a + b) & M, 43) + rot(c, 30) + d) & M, (a + rot((b + k2) & M, 18) + c) & M, mul)
    def wh(p, a, b):
        w, x, y, z = f64(p), f64(p + 8), f64(p + 16), f64(p + 24)
        a = (a + w) & M
        b = rot((b + a + z) & M, 21)
        c = a
        a = (a + x) & M; a = (a + y) & M
        b = (b + rot(a, 44)) & M
        return (a + z) & M, (b + c) & M
    bswap = lambda v: int.from_bytes(v.to_bytes(8, "little"), "big")
    def len33to64():
        mul = (k2 + n * 2) & M
        a = (f64(0) * k2) & M; b = f64(8); c = f64(n - 24); d = f64(n - 32)
        e = (f64(16) * k2) & M; f = (f64(24) * 9) & M; g = f64(n - 8); h = (f64(n - 16) * mul) & M
        u = (rot((a + g) & M, 43) + (rot(b, 30) + c) * 9) & M
        v = (((a + g) ^ d) + f + 1) & M
        w = (bswap(((u + v) * mul) & M) + h) & M
        x = (rot((e + f) & M, 42) + c) & M
        y = ((bswap(((v + w) * mul) & M) + g) * mul) & M
        z = (e + f + c) & M
        a = (bswap(((x + z) * mul + y) & M) + b) & M
        b = (smix(((z + a) * mul + d + h) & M) * mul) & M
        return (b + x) & M
    if n <= 32:
        return len0to16() if n <= 16 else len17to32()
    if n <= 64:
        return len33to64()
    x = f64(n - 40)
    y = (f64(n - 16) + f64(n - 56)) & M
    z = h16((f64(n - 48) + n) & M, f64(n - 24))
    v = wh(n - 64, n, z)
    w = wh(n - 32, (y + k1) & M, x)
    x = (x * k1 + f64(0)) & M
    end = ((n - 1) // 64) * 64
    p = 0
    while True:
        x = (rot((x + y + v[0] + f64(p + 8)) & M, 37) * k1) & M
        y = (rot((y + v[1] + f64(p + 48)) & M, 42) * k1) & M
        x ^= w[1]
        y = (y + v[0] + f64(p + 40)) & M
        z = (rot((z + w[0]) & M, 33) * k1) & M
        v = wh(p, (v[1] * k1) & M, (x + w[0]) & M)
        w = wh(p + 32, (z + w[1]) & M, (y + f64(p + 16)) & M)
        z, x = x, z
        p += 64
        if p == end:
            break
    return h16((h16(v[0], w[0]) + smix(y) * k1 + z) & M, (h16(v[1], w[1]) + x) & M)


# ---------------------------------------------------------------- BLAKE3 (chunk hashes in the .utoc)
_B3_IV = (0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19)
_B3_PERM = (2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8)


def _b3_compress(cv, m, counter, blen, flags):
    s = list(cv) + list(_B3_IV[:4]) + [counter & 0xFFFFFFFF, counter >> 32, blen, flags]
    M = 0xFFFFFFFF
    def g(a, b, c, d, x, y):
        s[a] = (s[a] + s[b] + x) & M; v = s[d] ^ s[a]; s[d] = ((v >> 16) | (v << 16)) & M
        s[c] = (s[c] + s[d]) & M; v = s[b] ^ s[c]; s[b] = ((v >> 12) | (v << 20)) & M
        s[a] = (s[a] + s[b] + y) & M; v = s[d] ^ s[a]; s[d] = ((v >> 8) | (v << 24)) & M
        s[c] = (s[c] + s[d]) & M; v = s[b] ^ s[c]; s[b] = ((v >> 7) | (v << 25)) & M
    m = list(m)
    for r in range(7):
        g(0, 4, 8, 12, m[0], m[1]); g(1, 5, 9, 13, m[2], m[3]); g(2, 6, 10, 14, m[4], m[5]); g(3, 7, 11, 15, m[6], m[7])
        g(0, 5, 10, 15, m[8], m[9]); g(1, 6, 11, 12, m[10], m[11]); g(2, 7, 8, 13, m[12], m[13]); g(3, 4, 9, 14, m[14], m[15])
        if r < 6:
            m = [m[i] for i in _B3_PERM]
    for i in range(8):
        s[i] ^= s[i + 8]; s[i + 8] ^= cv[i]
    return s


def blake3(data, size=32):
    """BLAKE3 hash (default mode) of bytes; pure Python, fine for small files."""
    START, END, PARENT, ROOT = 1, 2, 4, 8
    words = lambda b: struct.unpack("<16I", b.ljust(64, b"\0"))
    def chunk_out(i):                    # (cv, block words, counter, block len, flags) of chunk i's last block
        c = data[i * 1024:(i + 1) * 1024]
        cv, blocks = _B3_IV, [c[j:j + 64] for j in range(0, len(c), 64)] or [b""]
        for j, b in enumerate(blocks[:-1]):
            cv = _b3_compress(cv, words(b), i, 64, START if j == 0 else 0)[:8]
        return cv, words(blocks[-1]), i, len(blocks[-1]), END | (START if len(blocks) == 1 else 0)
    def node(lo, hi):
        if hi - lo == 1:
            return chunk_out(lo)
        n = 1 << ((hi - lo - 1).bit_length() - 1)
        left, right = node(lo, lo + n), node(lo + n, hi)
        cvl = _b3_compress(*left)[:8]; cvr = _b3_compress(*right)[:8]
        return _B3_IV, tuple(cvl) + tuple(cvr), 0, 64, PARENT
    cv, m, ctr, blen, flags = node(0, max(1, (len(data) + 1023) // 1024))
    return struct.pack("<16I", *_b3_compress(cv, m, ctr, blen, flags | ROOT))[:size]


# ---------------------------------------------------------------- writer (retoc's layout)
def package_id(game_path):
    """FPackageId of '/Game/.../Name'."""
    return cityhash64(game_path.lower().encode("utf-16le"))


def _dir_index(paths, mount="../../../"):
    """FIoDirectoryIndexResource for [(path 'motogp25/Content/.../X.uasset', toc index)]."""
    NONE = 0xFFFFFFFF
    strings, sidx = [], {}
    def s(t):
        if t not in sidx:
            sidx[t] = len(strings); strings.append(t)
        return sidx[t]
    dirs = [[NONE, NONE, NONE, NONE]]                  # name, first child, next sibling, first file
    files = []
    children, last_dir, last_file = {0: {}}, {}, {}
    for path, idx in paths:
        parts = path.split("/")
        d = 0
        for part in parts[:-1]:
            ch = children[d]
            if part not in ch:                                         # appended to the child list (as retoc)
                nd = len(dirs); dirs.append([s(part), NONE, NONE, NONE]); children[nd] = {}
                if d in last_dir:
                    dirs[last_dir[d]][2] = nd
                else:
                    dirs[d][1] = nd
                last_dir[d] = nd
                ch[part] = nd
            d = ch[part]
        f = len(files); files.append([s(parts[-1]), NONE, idx])
        if d in last_file:
            files[last_file[d]][1] = f
        else:
            dirs[d][3] = f
        last_file[d] = f
    def fstr(t):
        b = t.encode("utf-8") + b"\0"
        return struct.pack("<i", len(b)) + b
    out = bytearray(fstr(mount))
    out += struct.pack("<I", len(dirs)) + b"".join(struct.pack("<4I", *e) for e in dirs)
    out += struct.pack("<I", len(files)) + b"".join(struct.pack("<3I", *e) for e in files)
    out += struct.pack("<I", len(strings)) + b"".join(fstr(t) for t in strings)
    return bytes(out)


def write_container(utoc_path, packages, container_id=None, log=None):
    """Write an uncompressed, unencrypted .utoc/.ucas (as retoc does) holding zen packages.
    packages: [(path 'motogp25/Content/.../X.uasset', zen bytes, '/Game/.../X', [imported package ids])]."""
    import hashlib
    log = log or (lambda s: None)
    BS = 65536
    base = os.path.splitext(os.path.basename(utoc_path))[0]
    cid = container_id or (cityhash64(base.lower().encode("utf-16le")) ^ 0x5A5A5A5A5A5A5A5A)
    # container header: package ids sorted, store entries in the same order
    pk = sorted(((package_id(g), sorted(set(imp))) for _, _, g, imp in packages), key=lambda x: x[0])
    ids = [p for p, _ in pk]
    if len(set(ids)) != len(ids):
        raise IoStoreError("two packages with the same name")
    entries, tail = bytearray(), bytearray()
    for i, (_, imp) in enumerate(pk):
        at = 16 * len(pk) + len(tail)
        entries += struct.pack("<IIII", len(imp), (at - 16 * i) if imp else 0, 0, 0)
        tail += b"".join(struct.pack("<Q", x) for x in imp)
    blob = bytes(entries + tail)
    ch = struct.pack("<IIQ", 0x496F436E, 4, cid) + struct.pack("<I", len(ids)) + b"".join(struct.pack("<Q", x) for x in ids)
    ch += struct.pack("<I", len(blob)) + blob + bytes(24)
    chunks = [(struct.pack("<QHBB", package_id(g), 0, 0, CHUNK_EXPORT_BUNDLE_DATA), data, path) for path, data, g, _ in packages]
    chunks.append((struct.pack("<QHBB", cid, 0, 0, 6), ch, None))
    offlen, blocks, metas = [], [], []
    tmp = utoc_path[:-5] + ".ucas.tmp"
    with open(tmp, "wb") as f:
        logical = 0
        for cidb, data, path in chunks:
            if path:
                log("  %s (%.1f KB)" % (path, len(data) / 1024))
            offlen.append((logical, len(data)))
            for j in range(0, max(len(data), 1), BS):
                part = data[j:j + BS]
                blocks.append((f.tell(), len(part), len(part), 0))
                f.write(part)
            logical += max(1, (len(data) + BS - 1) // BS) * BS
            metas.append(blake3(data, 20) + bytes(4))
    d = _dir_index([(path, i) for i, (_, _, path) in enumerate(chunks) if path])
    hdr = bytearray(b"-==--==--==--==-")
    hdr += struct.pack("<BBHIIIIIIIIIQ", 8, 0, 0, 144, len(chunks), len(blocks), 12, 0, 32, BS, len(d), 1, cid)
    hdr += bytes(16) + struct.pack("<BBHIQII", F_INDEXED, 0, 0, 0, 0xFFFFFFFFFFFFFFFF, 0, 0) + bytes(40)
    assert len(hdr) == 144
    body = bytearray(hdr)
    body += b"".join(c for c, _, _ in chunks)
    body += b"".join(o.to_bytes(5, "big") + n.to_bytes(5, "big") for o, n in offlen)
    body += b"".join(o.to_bytes(5, "little") + c.to_bytes(3, "little") + u.to_bytes(3, "little") + bytes([m]) for o, c, u, m in blocks)
    body += d + b"".join(metas)
    with open(utoc_path + ".tmp", "wb") as f:
        f.write(body)
    os.replace(tmp, utoc_path[:-5] + ".ucas")
    os.replace(utoc_path + ".tmp", utoc_path)
    return len(packages)
