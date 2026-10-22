"""Read-only Unreal Engine .pak reader (versions 3-11) for the MotoGP 24 Master Editor.

Supports: AES-256 (ECB) encrypted index and entries, zlib and Oodle (via mgp_oodle) block compression, the v10/v11
full-directory index with encoded entries, and the old flat index (v3-v9, e.g. the v4 mod pak).
Needs the AES key (hex) and, for encrypted paks, `pip install pycryptodome` (or `cryptography`).
"""
import bisect, glob, os, struct, zlib

PAK_MAGIC = 0x5A6F12E1


class PakError(Exception):
    pass


def _aes_decrypt(key, data):
    if len(data) % 16:
        raise PakError("encrypted block is not 16-byte aligned")
    try:
        from Crypto.Cipher import AES                       # pycryptodome
        return AES.new(key, AES.MODE_ECB).decrypt(data)
    except ImportError:
        pass
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        d = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        return d.update(data) + d.finalize()
    except ImportError:
        raise PakError("AES support missing: run  pip install pycryptodome")


def parse_key(hexstr):
    h = hexstr.strip()
    if h.lower().startswith("0x"):
        h = h[2:]
    k = bytes.fromhex(h)
    if len(k) != 32:
        raise PakError("AES key must be 32 bytes (64 hex digits)")
    return k


def _align16(n):
    return (n + 15) & ~15


def _hdr_size(method, nblocks):
    """Size of the FPakEntry header stored in front of every entry's data (v3+)."""
    return 48 + ((4 + 16 * nblocks) if method else 0) + 5


class _R:
    """Tiny cursor over a bytes object."""
    def __init__(self, b, p=0):
        self.b, self.p = b, p

    def u8(self):  v = self.b[self.p]; self.p += 1; return v
    def i32(self): v = struct.unpack_from("<i", self.b, self.p)[0]; self.p += 4; return v
    def u32(self): v = struct.unpack_from("<I", self.b, self.p)[0]; self.p += 4; return v
    def i64(self): v = struct.unpack_from("<q", self.b, self.p)[0]; self.p += 8; return v
    def u64(self): v = struct.unpack_from("<Q", self.b, self.p)[0]; self.p += 8; return v
    def skip(self, n): self.p += n

    def fstr(self):
        n = self.i32()
        if n == 0:
            return ""
        if n > 0:
            s = self.b[self.p:self.p + n - 1].decode("utf-8", "replace"); self.p += n
        else:
            s = self.b[self.p:self.p + (-n - 1) * 2].decode("utf-16le"); self.p += -n * 2
        return s


class Entry:
    __slots__ = ("offset", "size", "usize", "method", "blocks", "encrypted", "bsize")


def _parse_full_entry(r, version):
    e = Entry()
    e.offset, e.size, e.usize = r.i64(), r.i64(), r.i64()
    e.method = r.u32()
    if version <= 1:
        r.skip(8)
    r.skip(20)                                              # sha1
    e.blocks, e.encrypted, e.bsize = [], False, 0
    if version >= 3:
        if e.method:
            for _ in range(r.i32()):
                e.blocks.append((r.i64(), r.i64()))
        e.encrypted = bool(r.u8() & 1)
        e.bsize = r.u32()
    return e


def _decode_encoded(b, p):
    r = _R(b, p)
    v = r.u32()
    e = Entry()
    e.method = (v >> 23) & 0x3F
    e.encrypted = bool(v & (1 << 22))
    n = (v >> 6) & 0xFFFF
    bs = v & 0x3F
    e.bsize = r.u32() if bs == 0x3F else bs << 11
    e.offset = r.u32() if v & (1 << 31) else r.u64()
    e.usize = r.u32() if v & (1 << 30) else r.u64()
    if e.method:
        e.size = r.u32() if v & (1 << 29) else r.u64()
    else:
        e.size = e.usize
    e.blocks = []
    if n:
        base = _hdr_size(e.method, n)
        if n == 1 and not e.encrypted:
            e.blocks = [(base, base + e.size)]
        else:
            cur = base
            for _ in range(n):
                s = r.u32()
                e.blocks.append((cur, cur + s))
                cur += _align16(s) if e.encrypted else s
    return e


class PakReader:
    def __init__(self, path, key):
        self.path, self.key = path, key
        self.f = open(path, "rb")           # only open while reading: a held handle locks the file on Windows
        self.f.seek(0, 2)
        size = self.fsize = self.f.tell()
        self.f.seek(max(0, size - 512))
        tail = self.f.read()
        at = tail.rfind(struct.pack("<I", PAK_MAGIC))
        if at < 0:
            self.f.close()
            raise PakError("no pak footer in " + os.path.basename(path))
        self.version = struct.unpack_from("<I", tail, at + 4)[0]
        self.index_off, self.index_size = struct.unpack_from("<QQ", tail, at + 8)
        self.index_encrypted = bool(tail[at - 1]) if self.version >= 4 else False
        self.comp = ["Zlib", "Gzip", "Oodle"]
        if self.version >= 8:
            rest = tail[at + 8 + 16 + 20:]
            self.comp = [rest[i:i + 32].split(b"\0")[0].decode("ascii", "replace") for i in range(0, 160, 32)]
        self.mount = ""
        self.files = {}                                      # lower-case full path -> (display path, Entry)
        try:
            self._load_index()
        finally:
            self.f.close()

    # ---- index
    def _read_region(self, off, size, encrypted):
        self.f.seek(off)
        data = self.f.read(size)
        if len(data) != size:
            raise PakError("truncated index in " + os.path.basename(self.path))
        if encrypted:
            data = _aes_decrypt(self.key, data)
        return data

    def _norm(self, p):
        p = p.replace("\\", "/")
        while p.startswith("../") or p.startswith("./") or p.startswith("/"):
            p = p[3:] if p.startswith("../") else p[2:] if p.startswith("./") else p[1:]
        return p

    def _load_index(self):
        data = self._read_region(self.index_off, self.index_size, self.index_encrypted)
        r = _R(data)
        try:
            n0 = struct.unpack_from("<i", data, 0)[0]
            if not 0 <= n0 < 512:
                raise PakError("cannot parse index of %s - wrong AES key?" % os.path.basename(self.path))
            self.mount = r.fstr()
            count = r.i32()
            if not self.mount.isprintable() or count < 0:
                raise PakError("cannot parse index of %s - wrong AES key?" % os.path.basename(self.path))
            if self.version < 10:
                for _ in range(count):
                    name = r.fstr()
                    e = _parse_full_entry(r, self.version)
                    full = self._norm(self.mount + name)
                    self.files[full.lower()] = (full, e)
                return
            r.u64()                                          # path hash seed
            if r.i32():                                      # path hash index (unused)
                r.skip(8 + 8 + 20)
            fdi = None
            if r.i32():
                fdi = (r.i64(), r.i64())
                r.skip(20)
            enc_blob = data[r.p + 4:r.p + 4 + struct.unpack_from("<i", data, r.p)[0]]
            r.skip(4 + len(enc_blob))
            loose = [_parse_full_entry(r, self.version) for _ in range(r.i32())]
        except (struct.error, IndexError):
            raise PakError("cannot parse index of %s - wrong AES key?" % os.path.basename(self.path))
        if not fdi:
            raise PakError("%s has no full directory index (unsupported)" % os.path.basename(self.path))
        d = _R(self._read_region(fdi[0], fdi[1], self.index_encrypted))
        try:
            for _ in range(d.i32()):
                dirname = d.fstr()
                for _ in range(d.i32()):
                    fname = d.fstr()
                    loc = d.i32()
                    e = _decode_encoded(enc_blob, loc) if loc >= 0 else loose[-loc - 1]
                    full = self._norm(self.mount + dirname + fname)
                    self.files[full.lower()] = (full, e)
        except (struct.error, IndexError):
            raise PakError("cannot parse directory index of %s" % os.path.basename(self.path))

    # ---- data
    def read(self, lower_path):
        with open(self.path, "rb") as f:
            if os.fstat(f.fileno()).st_size != self.fsize:     # rewritten since its index was read: offsets are wrong
                raise PakError("%s changed on disk since it was opened - try again (the tool re-reads it)" % os.path.basename(self.path))
            return self._read(f, lower_path)

    def _read(self, f, lower_path):
        _, e = self.files[lower_path]
        if e.method == 0:
            f.seek(e.offset + _hdr_size(0, 0))
            raw = f.read(_align16(e.size) if e.encrypted else e.size)
            if e.encrypted:
                raw = _aes_decrypt(self.key, raw)
            return raw[:e.usize]
        name = self.comp[e.method - 1] if e.method - 1 < len(self.comp) else "?"
        if name.lower() not in ("zlib", "oodle"):
            raise PakError("unsupported compression '%s' in %s" % (name, os.path.basename(self.path)))
        out = []
        for i, (s, t) in enumerate(e.blocks):
            f.seek(e.offset + s if self.version >= 5 else s)
            raw = f.read(_align16(t - s) if e.encrypted else t - s)
            if e.encrypted:
                raw = _aes_decrypt(self.key, raw)
            if name.lower() == "zlib":
                out.append(zlib.decompress(raw[:t - s]))
                continue
            import mgp_oodle                                 # MotoGP 25+: needs the oo2core DLL (Windows)
            bs = e.bsize or e.usize
            try:
                out.append(mgp_oodle.decompress(raw[:t - s], min(bs, e.usize - i * bs), [os.path.dirname(self.path)]))
            except (OSError, ValueError) as x:
                raise PakError("%s (%s)" % (x, os.path.basename(self.path)))
        return b"".join(out)[:e.usize]

    def close(self):
        self.f.close()


def _stat_sig(path):
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


class PakSet:
    """All paks of a game folder, layered: base paks first, *_P patch paks override them.
    refresh() notices paks that were added, removed or rewritten (e.g. a repacked mod pak copied into
    the Paks folder) and re-reads only those, so an old index never points into a new file."""

    def __init__(self, paks_dir, key_hex, project="motogp24", include_patch=True):
        self.project = project.lower()
        self.paks_dir, self.include_patch = paks_dir, include_patch
        self.key = parse_key(key_hex)
        self.gen = 0                                         # bumped whenever the set of paks changes
        self.readers, self.map, self.errors, self._sigs = [], {}, [], {}
        self._load()
        if not self.readers:
            raise PakError("; ".join(self.errors) or "no .pak files in " + paks_dir)

    def _names(self):
        names = glob.glob(os.path.join(self.paks_dir, "*.pak"))
        is_patch = lambda n: os.path.basename(n).lower().endswith("_p.pak")
        names.sort(key=lambda n: (is_patch(n), _natural(os.path.basename(n))))
        if not self.include_patch:
            names = [n for n in names if not is_patch(n)]
        return names

    def _load(self):
        """(Re)build readers and the lookup map; readers of unchanged files are kept."""
        old = {r.path: r for r in self.readers}
        readers, errors, sigs = [], [], {}
        for n in self._names():
            try:
                sig = _stat_sig(n)
            except OSError:
                continue
            r = old.get(n) if self._sigs.get(n) == sig else None
            if r is None:
                try:
                    r = PakReader(n, self.key)
                except PakError as e:
                    errors.append(str(e)); continue
            readers.append(r)
            sigs[n] = sig
        m = {}
        for r in readers:
            for low in r.files:
                m[low] = r
        # swap in whole new objects: a background job iterating the old ones is not disturbed
        self.readers, self.map, self.errors, self._sigs = readers, m, errors, sigs
        self._sorted = None
        self.gen += 1

    def refresh(self):
        """Re-read paks that changed on disk since they were opened. True if anything changed."""
        try:
            now = {}
            for n in self._names():
                now[n] = _stat_sig(n)
        except OSError:
            return False
        if now == self._sigs:
            return False
        self._load()
        return True

    def _key(self, rel):                                     # 'Content/assets/x' -> 'motogp24/content/assets/x'
        return (self.project + "/" + rel).lower()

    def exists(self, rel):
        return self._key(rel) in self.map

    def read(self, rel):
        k = self._key(rel)
        return self.map[k].read(k)

    def find(self, rel_dir, ext):
        """All files below rel_dir (project-relative, original case) ending in ext."""
        prefix = (self.project + "/" + rel_dir).lower().rstrip("/") + "/"
        keys, m = self._sorted, self.map
        if keys is None:
            keys = self._sorted = sorted(m)
        ext = ext.lower()
        out = []
        for i in range(bisect.bisect_left(keys, prefix), len(keys)):   # only the keys under rel_dir
            low = keys[i]
            if not low.startswith(prefix):
                break
            if low.endswith(ext):
                out.append(m[low].files[low][0][len(self.project) + 1:])
        return out

    def which(self, rel):
        return os.path.basename(self.map[self._key(rel)].path)

    def size(self, rel):
        """Uncompressed size of rel in the pak (None if absent) - no data is read."""
        k = self._key(rel)
        r = self.map.get(k)
        return r.files[k][1].usize if r else None

    def read_base(self, rel):
        """The game's own copy of rel (from the base paks, ignoring *_P.pak patch/mod paks), or None."""
        k = self._key(rel)
        for r in reversed(self.base_readers()):
            if k in r.files:
                return r.read(k)
        return None

    def base_readers(self):
        """Readers of the game's own base paks (not *_P.pak patch/mod paks)."""
        return [r for r in self.readers if not os.path.basename(r.path).lower().endswith("_p.pak")]

    def close(self):
        for r in self.readers:
            r.close()


def _natural(s):
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
