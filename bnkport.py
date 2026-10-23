"""Import bike banks from a newer Wwise game (MotoGP 26, Wwise bank v154) into this game's bank of the same name.

A newer bank cannot load here (Wwise refuses other bank versions), but GP26 keeps GP24's sound, source and media ids.
So the game's own bank stays the template (events, structure, mix, RPM curves) and only data is swapped in:
  - Vorbis .wem media of the same id: the 'hash' chunk newer Wwise adds is dropped;
  - CrankcaseAudio REV engine models (ADM3 v7, in a PLUG wrapper) are converted to the ADM3 v6 the game's plugin reads;
  - the REV plugin's settings (FxCustom param block, same id and size); the game's RTPC curves stay.
Media only one side has are left alone. Nothing is written unless dry_run is False; writes go to the staging layer.
Reproduces a GP26->GP24 Ducati bank that was tested in game byte for byte (except the Sound inMemSize fields, which
are kept equal to the media size like the game's own banks)."""
import os
import re
import struct

import mgp_core as C
import audioport as A

BANK_DIR = A.BANK_DIR
REV = 0x01a01052                         # CrankcaseAudioREVModelPlayer
FX_CUSTOM = 17


# ------------------------------------------------------------------ bank pieces
def media(secs):
    """({media id: bytes}, [ids in DIDX order]) of a bank's embedded media."""
    s = dict(secs)
    out, order = {}, []
    didx, data = s.get("DIDX", b""), s.get("DATA", b"")
    for i in range(0, len(didx) - 11, 12):
        k, o, n = struct.unpack_from("<III", didx, i)
        out[k] = data[o:o + n]
        order.append(k)
    return out, order


def riff_chunks(w):
    o, out = 12, []
    while o + 8 <= len(w):
        n = struct.unpack_from("<I", w, o + 4)[0]
        out.append((w[o:o + 4], o, n))
        o += 8 + n
    return out


def strip_hash(w):
    """Drop the 'hash' chunk of a Wwise 2022+ .wem; the RIFF is kept even-sized."""
    for t, o, n in riff_chunks(w):
        if t == b"hash":
            r = bytearray(w[:o] + w[o + 8 + n:])
            if len(r) & 1:
                r.append(0)
            struct.pack_into("<I", r, 4, len(r) - 8)
            return bytes(r)
    return w


def has_hash(w):
    return any(t == b"hash" for t, _, _ in riff_chunks(w))


# ------------------------------------------------------------------ REV model (ADM3)
def unwrap_plug(v):
    """REV model inside the PLUG wrapper newer Wwise puts around plugin media (PLUG, hash, junk, data)."""
    if v[:4] != b"PLUG":
        return v
    j = v.find(b"data", 8)
    if j < 0:
        raise C.MgpError("PLUG media without a data chunk")
    n = struct.unpack_from("<I", v, j + 4)[0]
    return v[j + 8:j + 8 + n]


def adm_version(v):
    v = unwrap_plug(v)
    return struct.unpack_from("<H", v, 10)[0] if v[:4] == b"ADM3" and len(v) >= 12 else None


def _smp2(x):
    return [m.start() for m in re.finditer(rb"SMP2\x00\x00\x00\x00", x)]


def adm3_v7_to_v6(v):
    """ADM3 v7 -> v6. Samples are ADPCM blocks of 64 samples: v7 = 3-byte header (s16 big-endian predictor, step
    index) + 32 bytes, v6 = 2-byte header (9-bit predictor/128, 7-bit step) + the same 32 bytes. Each SMP2 entry
    (version 5 -> 4) holds the sample's size (+0x24) and absolute offset (+0x2c, 16-byte aligned)."""
    x = unwrap_plug(v)
    if x[:4] != b"ADM3" or adm_version(x) != 7:
        raise C.MgpError("not an ADM3 v7 engine model")
    ents = _smp2(x)
    if not ents:
        raise C.MgpError("engine model has no samples")
    first = min(struct.unpack_from("<I", x, e + 0x2c)[0] for e in ents)
    head = bytearray(x[:first])
    struct.pack_into("<H", head, 10, 6)
    body = bytearray()
    for e in sorted(ents, key=lambda e: struct.unpack_from("<I", x, e + 0x2c)[0]):
        if struct.unpack_from("<H", x, e + 10)[0] != 5:
            raise C.MgpError("engine model sample entry with unknown version at 0x%x" % e)
        size, _, off = struct.unpack_from("<III", x, e + 0x24)
        if size % 35 or off + size > len(x):
            raise C.MgpError("engine model sample at 0x%x is not in 35-byte blocks" % off)
        while (first + len(body)) % 16:
            body.append(0)
        struct.pack_into("<H", head, e + 10, 4)
        struct.pack_into("<I", head, e + 0x24, size // 35 * 34)
        struct.pack_into("<I", head, e + 0x2c, first + len(body))
        for i in range(off, off + size, 35):
            q = (struct.unpack_from(">h", x, i)[0] + 64) >> 7
            q = max(-256, min(255, q)) & 0x1FF
            body += bytes((q >> 1, ((q & 1) << 7) | (x[i + 2] & 0x7F)))
            body += x[i + 3:i + 35]
    return bytes(head + body)


# ------------------------------------------------------------------ one bank
def port_bank(tgt, src):
    """(new bank bytes, report) for the game's bank `tgt` with the newer game's bank `src` swapped in."""
    r = dict(wem=0, rev=0, fx=0, kept=0, unused=0, problems=[], warnings=[])
    if A.bank_version(src) <= A.bank_version(tgt):
        r["warnings"].append("source bank is Wwise v%d, not newer than this game's v%d" % (A.bank_version(src), A.bank_version(tgt)))
    ts, ss = A.sections(tgt), A.sections(src)
    tm, order = media(ts)
    sm, _ = media(ss)
    if not tm:
        r["problems"].append("this game's bank has no embedded media")
        return None, r
    new = dict(tm)
    for k in order:
        if k not in sm:
            r["kept"] += 1
            continue
        t, s = tm[k], sm[k]
        try:
            if t[:4] == b"RIFF" and s[:4] == b"RIFF":
                new[k] = s if has_hash(t) else strip_hash(s)
                r["wem"] += 1
            elif t[:4] == b"ADM3" and s[:4] in (b"PLUG", b"ADM3"):
                tv, sv = adm_version(t), adm_version(s)
                if tv == sv:
                    new[k] = unwrap_plug(s)
                elif (tv, sv) == (6, 7):
                    new[k] = adm3_v7_to_v6(s)
                else:
                    raise C.MgpError("engine model v%s cannot be converted to v%s" % (sv, tv))
                r["rev"] += 1
            else:
                r["warnings"].append("media %d: different kinds (%r / %r), kept" % (k, t[:4], s[:4]))
                r["kept"] += 1
        except C.MgpError as e:
            r["problems"].append("media %d: %s" % (k, e))
    r["unused"] = len(set(sm) - set(tm))
    if r["problems"]:
        return None, r
    if not r["wem"] and not r["rev"]:
        r["problems"].append("no media ids in common - not the same bike's bank?")
        return None, r
    sfx = {oid: b for t, oid, b in A.hirc_objects(src) if t == FX_CUSTOM and len(b) >= 12}
    didx, data = bytearray(), bytearray()
    for k in order:
        data += b"\0" * (-len(data) % 16)
        didx += struct.pack("<III", k, len(data), len(new[k]))
        data += new[k]
    out = []
    for t, body in ts:
        if t == "DIDX":
            body = bytes(didx)
        elif t == "DATA":
            body = bytes(data)
        elif t == "HIRC":
            nb, q = bytearray(body), 4
            for _ in range(struct.unpack_from("<I", body, 0)[0]):
                ty, ln, o = nb[q], struct.unpack_from("<I", nb, q + 1)[0], q + 5
                if ty == 2 and ln >= 17:                       # Sound: keep inMemSize = size of its embedded media
                    sid, ims = struct.unpack_from("<II", nb, o + 9)
                    if sid in new and ims == len(tm[sid]):
                        struct.pack_into("<I", nb, o + 13, len(new[sid]))
                elif ty == FX_CUSTOM and ln >= 12:             # REV settings: same plugin, same param size
                    oid, pid, sz = struct.unpack_from("<III", nb, o)
                    g = sfx.get(oid)
                    if pid == REV and g and g[4:12] == bytes(nb[o + 4:o + 12]) and 12 + sz <= ln:
                        nb[o + 12:o + 12 + sz] = g[12:12 + sz]
                        r["fx"] += 1
                q += 5 + ln
            body = bytes(nb)
        out.append([t, body])
    res = A.join_sections(out)
    A.hirc_objects(res)
    if media(A.sections(res))[0] != new:
        raise C.MgpError("rebuilt bank does not read back")
    return res, r


# ------------------------------------------------------------------ project level
def source_banks(path):
    path = (path or "").strip().strip('"')
    if not path or not os.path.isdir(path):
        raise C.MgpError("folder does not exist: %r" % path)
    out = {}
    for d, _, fs in os.walk(path):
        for f in fs:
            if f.lower().endswith(".bnk") and f.lower() != "init.bnk":
                out.setdefault(f.lower(), os.path.join(d, f))
    return out


def target_banks(P):
    return {rel.rsplit("/", 1)[1].lower(): rel for rel in P.src.find(BANK_DIR, ".bnk")}


def game_copy(P, rel):
    """The game's own bank (so porting twice does not port onto an earlier port)."""
    data = P.paks.read_base(rel) if getattr(P, "paks", None) else None
    return data if data is not None else P.src.read(rel)


def scan(P, path):
    src, tgt = source_banks(path), target_banks(P)
    banks = []
    for key, real in sorted(src.items()):
        b = dict(name=os.path.basename(real), path=real, target=tgt.get(key, ""))
        try:
            with open(real, "rb") as f:
                data = f.read()
            b["version"] = A.bank_version(data)
            sm, _ = media(A.sections(data))
            b["media"] = len(sm)
            b["engine"] = sum(1 for v in sm.values() if v[:4] in (b"PLUG", b"ADM3"))
            if b["target"]:
                tm, _ = media(A.sections(game_copy(P, b["target"])))
                b["shared"] = len(set(sm) & set(tm))
        except Exception as e:
            b["error"] = "%s: %s" % (type(e).__name__, e)
        banks.append(b)
    return dict(root=path, banks=banks)


def port(P, path, names, dry_run=True):
    src, tgt = source_banks(path), target_banks(P)
    results, written = [], 0
    for name in names:
        r = dict(bank=name, problems=[], warnings=[], actions=[])
        results.append(r)
        key = name.lower()
        try:
            if key not in src:
                raise C.MgpError("not in the source folder")
            if key not in tgt:
                raise C.MgpError("this game has no bank of that name in " + BANK_DIR)
            with open(src[key], "rb") as f:
                data, rep = port_bank(game_copy(P, tgt[key]), f.read())
            r["problems"] += rep["problems"]
            r["warnings"] += rep["warnings"]
            if data is not None:
                r["actions"].append("%d sounds, %d engine models, %d engine settings swapped; %d kept from this game; %d only in the source (not used)"
                                    % (rep["wem"], rep["rev"], rep["fx"], rep["kept"], rep["unused"]))
                r["file"] = tgt[key]
                if not dry_run:
                    dst = P.src.loose(tgt[key])
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, "wb") as f:
                        f.write(data)
                    written += 1
        except C.MgpError as e:
            r["problems"].append(str(e))
        r["ok"] = not r["problems"]
    return dict(results=results, dry_run=dry_run, written=written)
