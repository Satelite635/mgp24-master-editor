"""Writes an Unreal Engine .pak (version 8: uncompressed, unencrypted) from a mod folder.
UE 4.27 mounts older pak versions fine, and unencrypted paks load next to the game's encrypted ones.
Name the file *_P.pak so it overrides the game's own paks."""
import hashlib
import os
import struct

PAK_MAGIC = 0x5A6F12E1
VERSION = 8
MOUNT = "../../../"
SKIP_SUFFIX = ("-journal", "-wal", "-shm", ".bak", ".tmp")


def _fstr(s):
    b = s.encode("utf-8") + b"\0"
    try:
        s.encode("ascii")
        return struct.pack("<i", len(b)) + b
    except UnicodeEncodeError:
        w = s.encode("utf-16le") + b"\0\0"
        return struct.pack("<i", -(len(w) // 2)) + w


def _entry(offset, size, sha):
    # offset, size, uncompressed size, compression method, sha1, flags (not encrypted), block size
    return struct.pack("<QQQI", offset, size, size, 0) + sha + struct.pack("<BI", 0, 0)


def collect(root, project="motogp24"):
    """[(name inside the pak, file path)] for everything under <root>/Content."""
    out = []
    base = os.path.join(root, "Content")
    for d, _, fs in os.walk(base):
        for f in sorted(fs):
            if f.lower().endswith(SKIP_SUFFIX):
                continue
            p = os.path.join(d, f)
            out.append((project + "/" + os.path.relpath(p, root).replace(os.sep, "/"), p))
    return sorted(out)


def write_pak(dest, files, log=None):
    """files: [(name, path)]. Returns (count, bytes). `log(line)` is called with progress lines."""
    log = log or (lambda s: None)
    total = len(files)
    log("Packing %d files -> %s" % (total, dest))
    index = bytearray()
    index += _fstr(MOUNT) + struct.pack("<i", len(files))
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        for i, (name, path) in enumerate(files, 1):
            data = open(path, "rb").read()
            log("[%d/%d] %s (%.1f KB)" % (i, total, name, len(data) / 1024))
            sha = hashlib.sha1(data).digest()
            off = f.tell()
            rec = _entry(off, len(data), sha)
            f.write(struct.pack("<QQQI", 0, len(data), len(data), 0) + sha + struct.pack("<BI", 0, 0))
            f.write(data)
            index += _fstr(name) + rec
        log("Writing index (%d entries)..." % total)
        idx_off = f.tell()
        f.write(index)
        footer = bytes(16) + bytes([0]) + struct.pack("<II", PAK_MAGIC, VERSION) + struct.pack("<QQ", idx_off, len(index)) \
            + hashlib.sha1(bytes(index)).digest() + b"".join(n.ljust(32, b"\0") for n in (b"Zlib", b"", b"", b"", b""))
        f.write(footer)
        size = f.tell()
    os.replace(tmp, dest)
    log("Done: %d files, %.1f MB" % (total, size / 1048576))
    return len(files), size


# An empty v11 pak exactly as retoc writes it next to a .utoc/.ucas (UE mounts a container through its .pak).
EMPTY_PAK_V11 = bytes.fromhex(
    "0a0000002e2e2f2e2e2f2e2e2f00000000000000000000000000010000007200000000000000080000000000000005fe"
    "405753166f125559e7c9ac558654f107c7e9010000007a0000000000000004000000000000009069ca78e7450a285173"
    "431b3e52c5c25299e47300000000000000000000000000000000000000000000000000000000000000000000000000e1"
    "126f5a0b00000000000000000000007200000000000000ace857fc068a791ca324a99e384f0629d18c6c4d0000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000")


def write_empty_pak(dest):
    with open(dest + ".tmp", "wb") as f:
        f.write(EMPTY_PAK_V11)
    os.replace(dest + ".tmp", dest)
