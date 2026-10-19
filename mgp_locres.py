"""Reader/writer for Unreal Engine .locres localization files (versions 1-3, the ones UE 4.27 writes).
Only the text of existing entries can be changed (keys, namespaces and hashes are kept as they are)."""
import struct

MAGIC = bytes([0x0E, 0x14, 0x74, 0x75, 0x67, 0x4A, 0x03, 0xFC, 0x4A, 0x15, 0x90, 0x9D, 0xC3, 0x37, 0x7F, 0x1B])


class LocresError(Exception):
    pass


class _R:
    def __init__(self, b, p=0):
        self.b, self.p = b, p

    def take(self, n):
        if n < 0 or self.p + n > len(self.b):
            raise LocresError("file is truncated or not a .locres")
        v = self.b[self.p:self.p + n]
        self.p += n
        return v

    def u8(self): return self.take(1)[0]
    def i32(self): return struct.unpack("<i", self.take(4))[0]
    def u32(self): return struct.unpack("<I", self.take(4))[0]
    def i64(self): return struct.unpack("<q", self.take(8))[0]

    def fstr(self):
        n = self.i32()
        if n == 0:
            return ("", False)
        if n > 0:
            raw = self.take(n)
            return (raw[:-1].decode("utf-8", "replace") if raw[-1:] == b"\0" else raw.decode("utf-8", "replace"), False)
        raw = self.take(-n * 2)
        return (raw[:-2].decode("utf-16le", "replace"), True)


def _fstr(item):
    text, wide = item
    if text == "" and not wide:
        return struct.pack("<i", 0)
    if not wide:
        try:
            raw = text.encode("latin-1") if all(ord(c) < 128 for c in text) else None
        except UnicodeEncodeError:
            raw = None
        if raw is not None:
            return struct.pack("<i", len(raw) + 1) + raw + b"\0"
    raw = text.encode("utf-16le") + b"\0\0"
    return struct.pack("<i", -(len(raw) // 2)) + raw


class Locres:
    def __init__(self, data):
        r = _R(data)
        if r.take(16) != MAGIC:
            raise LocresError("not a .locres file (old legacy format without a header is not supported)")
        self.version = r.u8()
        if self.version not in (1, 2, 3):
            raise LocresError("unsupported .locres version %d" % self.version)
        v = self.version
        arr_off = r.i64()
        self.arr = []                      # [[text item, refcount]]
        end_hdr = None
        if arr_off >= 0:
            save = r.p
            r.p = arr_off
            for _ in range(r.i32()):
                s = r.fstr()
                self.arr.append([s, r.i32() if v >= 2 else 0])
            end_hdr = r.p
            r.p = save
        self.total = r.u32() if v >= 2 else None
        self.namespaces = []               # [dict(hash, name, keys=[dict(hash, key, src, idx)])]
        for _ in range(r.u32()):
            nh = r.u32() if v >= 2 else None
            name = r.fstr()
            keys = []
            for _ in range(r.u32()):
                kh = r.u32() if v >= 2 else None
                key = r.fstr()
                src = r.u32()
                idx = r.i32()
                if not 0 <= idx < len(self.arr):
                    raise LocresError("a text index points outside the string table")
                keys.append(dict(hash=kh, key=key, src=src, idx=idx))
            self.namespaces.append(dict(hash=nh, name=name, keys=keys))
        self._tail = data[end_hdr:] if end_hdr is not None else b""
        self._head_len = r.p
        self.original = data

    # ---- reading
    def entries(self):
        for ni, ns in enumerate(self.namespaces):
            for ki, k in enumerate(ns["keys"]):
                yield ni, ki, ns["name"][0], k["key"][0], self.arr[k["idx"]][0][0]

    def count(self):
        return sum(len(n["keys"]) for n in self.namespaces)

    def find(self, namespace, key):
        for ns in self.namespaces:
            if ns["name"][0] == namespace:
                for k in ns["keys"]:
                    if k["key"][0] == key:
                        return k
        return None

    # ---- editing
    def set_text(self, namespace, key, text):
        k = self.find(namespace, key)
        if k is None:
            raise LocresError("no entry %r / %r" % (namespace, key))
        cur = self.arr[k["idx"]]
        if cur[0][0] == text:
            return False
        wide = cur[0][1] or any(ord(c) > 127 for c in text)
        for i, (s, _) in enumerate(self.arr):                # reuse an identical existing string
            if s[0] == text and (s[1] == wide or all(ord(c) < 128 for c in text)):
                k["idx"] = i
                return True
        self.arr.append([(text, wide), 0])
        k["idx"] = len(self.arr) - 1
        return True

    # ---- writing
    def to_bytes(self):
        v = self.version
        counts = [0] * len(self.arr)
        for ns in self.namespaces:
            for k in ns["keys"]:
                counts[k["idx"]] += 1
        body = bytearray()
        if v >= 2:
            body += struct.pack("<I", sum(len(n["keys"]) for n in self.namespaces))
        body += struct.pack("<I", len(self.namespaces))
        for ns in self.namespaces:
            if v >= 2:
                body += struct.pack("<I", ns["hash"])
            body += _fstr(ns["name"]) + struct.pack("<I", len(ns["keys"]))
            for k in ns["keys"]:
                if v >= 2:
                    body += struct.pack("<I", k["hash"])
                body += _fstr(k["key"]) + struct.pack("<I", k["src"]) + struct.pack("<i", k["idx"])
        head = MAGIC + bytes([v])
        arr_off = len(head) + 8 + len(body)
        arr = bytearray(struct.pack("<i", len(self.arr)))
        for (s, _), c in zip(self.arr, counts):
            arr += _fstr(s) + (struct.pack("<i", c) if v >= 2 else b"")
        return head + struct.pack("<q", arr_off) + bytes(body) + bytes(arr) + self._tail
