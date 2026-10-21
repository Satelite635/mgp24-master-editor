"""Font swap: put a real font file (.ttf/.otf, or a .ufont, which is the same bytes) in place of a game
FontFace's .ufont. The game's own FontFace asset reads <Fonts folder>/<FontFace name>.ufont, so a .ufont of the
same name in the mod pak replaces what it draws (this is how MotoGPText-Display was already replaced)."""
import struct

FONT_MAGIC = {b"\x00\x01\x00\x00": "TrueType", b"OTTO": "OpenType (CFF)", b"true": "TrueType (Apple)"}


def font_info(data):
    """{'kind', 'family', 'full'} of a single TrueType/OpenType font; ValueError if it is not one."""
    kind = FONT_MAGIC.get(bytes(data[:4]))
    if not kind:
        if data[:4] == b"ttcf":
            raise ValueError("this is a font collection (.ttc) - extract a single .ttf first")
        if data[:4] in (b"wOFF", b"wOF2"):
            raise ValueError("this is a web font (.woff) - convert it to .ttf/.otf first")
        raise ValueError("not a TrueType/OpenType font file")
    n = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for i in range(n):
        tag = bytes(data[12 + 16 * i:16 + 16 * i]).decode("latin1")
        off, ln = struct.unpack(">II", data[20 + 16 * i:28 + 16 * i])
        tables[tag] = (off, ln)
    names = {}
    if "name" in tables:
        o, ln = tables["name"]
        t = data[o:o + ln]
        count, strs = struct.unpack(">HH", t[2:6])
        for i in range(count):
            pid, eid, lid, nid, l, off = struct.unpack(">HHHHHH", t[6 + 12 * i:18 + 12 * i])
            raw = t[strs + off:strs + off + l]
            if pid in (0, 3):
                txt = raw.decode("utf-16-be", "replace")
            elif pid == 1:
                txt = raw.decode("latin1")
            else:
                continue
            if nid not in names or pid == 3:
                names[nid] = txt
    return dict(kind=kind, family=names.get(1, "?"), style=names.get(2, ""), full=names.get(4, names.get(1, "?")))
