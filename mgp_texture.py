"""Cooked Texture2D (UE 4.27, GP24) read / pixel replacement on a template.

Layout after the tagged properties of a cooked Texture2D export (checked on GP24 HUD textures):
  int32 0 (no object guid) | FStripDataFlags x2 (4 bytes) | int32 bCooked
  per platform format:  FName PixelFormat | int64 SkipOffset (absolute, points at the next FName)
     FTexturePlatformData: int32 SizeX, SizeY, PackedData | FString "PF_..." | int32 FirstMip, NumMips
        per mip: int32 bCooked | FByteBulkData header (u32 flags, int32/64 count, int32/64 size, int64 offset)
                 | [payload when inline] | int32 SizeX, SizeY, SizeZ
     int32 bIsVirtual
  FName None | (package tag)
Inline payload offsets are absolute (len(.uasset) + position in .uexp). Payloads stored in the .ubulk are
read by offset inside the .ubulk (base = 0 with BULKDATA_NoOffsetFixUp; else the summary's BulkDataStartOffset).
The .ubulk part is written from that reading but NOT yet checked against a real GP24 streaming texture."""
import io, os, shutil, struct, subprocess, tempfile

import mgp_core as C
import uprops

F_END_OF_FILE, F_SINGLE_USE, F_INLINE, F_SEPARATE = 0x1, 0x8, 0x40, 0x100
F_OPTIONAL, F_SIZE64, F_NO_FIXUP = 0x800, 0x2000, 0x10000

BLOCK = {"PF_DXT1": 8, "PF_DXT3": 16, "PF_DXT5": 16, "PF_BC4": 8, "PF_BC5": 16, "PF_BC7": 16}
PIXEL = {"PF_B8G8R8A8": 4, "PF_G8": 1, "PF_R8G8B8A8": 4}
DXGI = {70: "PF_DXT1", 71: "PF_DXT1", 72: "PF_DXT1", 73: "PF_DXT3", 74: "PF_DXT3", 76: "PF_DXT5", 77: "PF_DXT5", 78: "PF_DXT5", 79: "PF_BC4", 80: "PF_BC4",
        82: "PF_BC5", 83: "PF_BC5", 97: "PF_BC7", 98: "PF_BC7", 99: "PF_BC7", 87: "PF_B8G8R8A8", 61: "PF_G8", 28: "PF_R8G8B8A8"}
FOURCC = {b"DXT1": "PF_DXT1", b"DXT3": "PF_DXT3", b"DXT5": "PF_DXT5", b"ATI1": "PF_BC4", b"BC4U": "PF_BC4",
          b"ATI2": "PF_BC5", b"BC5U": "PF_BC5"}


class TexError(C.MgpError):
    pass


def mip_bytes(fmt, w, h):
    if fmt in BLOCK:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * BLOCK[fmt]
    if fmt in PIXEL:
        return w * h * PIXEL[fmt]
    raise TexError("pixel format %s is not supported yet" % fmt)


# ---------------------------------------------------------------- read
def parse(ua_bytes, ux_bytes, ubulk=None):
    """-> dict with the format, size, mips (each: w, h, flags, size, where 'inline'|'ubulk', data) and the
    positions needed to rebuild the .uexp."""
    a = uprops.Asset(ua_bytes, ux_bytes)
    if len(a.exports) != 1 or a.exports[0]["cls"] != "Texture2D":
        raise TexError("not a Texture2D asset (export class %s)" % ", ".join(e["cls"] for e in a.exports))
    ex = a.parse_export(0)
    u, p = ux_bytes, ex["end"]
    if struct.unpack_from("<i", u, p)[0] != 0:
        raise TexError("unexpected object guid after the properties")
    p += 4 + 4                                                   # guid flag, 2 x FStripDataFlags
    if struct.unpack_from("<i", u, p)[0] != 1:
        raise TexError("texture is not cooked")
    p += 4
    fmt_name_at = p
    skip_at = p + 8
    skip = struct.unpack_from("<q", u, skip_at)[0]
    q = skip_at + 8
    sx, sy, packed = struct.unpack_from("<iii", u, q)
    size_at = q
    q += 12
    n = struct.unpack_from("<i", u, q)[0]
    if not 0 < n < 64:
        raise TexError("unexpected texture layout (pixel format string length %d)" % n)
    fmt = u[q + 4:q + 4 + n - 1].decode("ascii")
    q += 4 + n
    first, nmips = struct.unpack_from("<ii", u, q)
    nmips_at = q
    q += 8
    ub = len(ua_bytes)
    bulk_start = C.UAsset(ua_bytes)._get("bulk", "<q")
    mips = []
    mips_at = q
    for i in range(nmips):
        cooked, flags = struct.unpack_from("<iI", u, q)
        q += 8
        if flags & F_SIZE64:
            cnt, sz = struct.unpack_from("<qq", u, q); q += 16
        else:
            cnt, sz = struct.unpack_from("<ii", u, q); q += 8
        off = struct.unpack_from("<q", u, q)[0]; q += 8
        if flags & F_OPTIONAL:
            raise TexError("mip %d uses an optional (.uptnl) payload - not supported yet" % i)
        if not flags & F_END_OF_FILE:
            where, data = "inline", u[q:q + sz]
            q += sz
        elif flags & F_SEPARATE:
            base = 0 if flags & F_NO_FIXUP else bulk_start
            where = "ubulk"
            data = None
            if ubulk is not None:
                if not 0 <= off - base <= len(ubulk) - sz:
                    raise TexError("mip %d points outside the .ubulk (offset %d, size %d, .ubulk %d bytes)"
                                   % (i, off - base, sz, len(ubulk)))
                data = ubulk[off - base:off - base + sz]
        else:
            raise TexError("mip %d stores its data at the end of the .uexp (flags 0x%x) - not supported yet" % (i, flags))
        w, h, d = struct.unpack_from("<iii", u, q); q += 12
        mips.append(dict(w=w, h=h, flags=flags, cooked=cooked, size=sz, off=off, where=where, data=data))
    mips_end = q
    virt = struct.unpack_from("<i", u, q)[0]
    if virt:
        raise TexError("virtual texture - not supported")
    if skip - ub != q + 4:
        raise TexError("unexpected texture layout (skip offset %d, expected %d)" % (skip - ub, q + 4))
    nxt = a.fname(*struct.unpack_from("<ii", u, q + 4))
    if nxt != "None":
        raise TexError("texture has more than one cooked format (%s) - not supported" % nxt)
    for m in mips:
        if m["data"] is not None and len(m["data"]) != m["size"]:
            raise TexError("mip data cut short")
    props = {t["name"]: t.get("value") for t in ex["props"]}
    return dict(fmt=fmt, w=sx, h=sy, packed=packed, first=first, mips=mips, props=props, ex=ex,
                fmt_name_at=fmt_name_at, skip_at=skip_at, size_at=size_at, nmips_at=nmips_at,
                mips_at=mips_at, mips_end=mips_end, has_ubulk=any(m["where"] == "ubulk" for m in mips))


def describe(info):
    m = info["mips"]
    ext = sum(1 for x in m if x["where"] == "ubulk")
    return dict(format=info["fmt"], width=info["w"], height=info["h"], mips=len(m), mips_in_ubulk=ext,
                srgb=info["props"].get("SRGB", True), compression=info["props"].get("CompressionSettings", "TC_Default"),
                lod_group=info["props"].get("LODGroup", ""), never_stream=bool(info["props"].get("NeverStream")))


def decode(fmt, w, h, data):
    """One mip -> PIL RGBA image."""
    from PIL import Image
    if fmt == "PF_B8G8R8A8":
        return Image.frombytes("RGBA", (w, h), data, "raw", "BGRA")
    if fmt == "PF_R8G8B8A8":
        return Image.frombytes("RGBA", (w, h), data)
    if fmt == "PF_G8":
        return Image.frombytes("L", (w, h), data).convert("RGBA")
    n = {"PF_DXT1": 1, "PF_DXT3": 2, "PF_DXT5": 3, "PF_BC4": 4, "PF_BC5": 5, "PF_BC7": 7}.get(fmt)
    if n is None:
        raise TexError("can't decode %s" % fmt)
    bw, bh = max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)
    mode = "L" if n == 4 else "RGB" if n == 5 else "RGBA"
    im = Image.frombytes(mode, (bw, bh), data, "bcn", (n,))
    return im.convert("RGBA").crop((0, 0, w, h))


def preview(info):
    """First mip that has data -> PIL image."""
    for m in info["mips"]:
        if m["data"] is not None:
            return decode(info["fmt"], m["w"], m["h"], m["data"])
    raise TexError("no mip data (the .ubulk is missing)")


# ---------------------------------------------------------------- DDS input
def read_dds(blob):
    """-> (fmt, w, h, [mip bytes]) for a DDS whose format we know, else None."""
    if blob[:4] != b"DDS ":
        return None
    h, w = struct.unpack_from("<II", blob, 12)
    mipcount = max(1, struct.unpack_from("<I", blob, 28)[0])
    pf_flags, fourcc = struct.unpack_from("<I4s", blob, 80)
    off = 128
    fmt = None
    if pf_flags & 4:
        if fourcc == b"DX10":
            fmt = DXGI.get(struct.unpack_from("<I", blob, 128)[0]); off = 148
        else:
            fmt = FOURCC.get(fourcc)
    else:
        bits, rm, gm, bm, am = struct.unpack_from("<IIIII", blob, 88)
        if bits == 32 and rm == 0xff0000 and bm == 0xff:
            fmt = "PF_B8G8R8A8"
        elif bits == 8:
            fmt = "PF_G8"
    if fmt is None:
        return None
    mips, mw, mh = [], w, h
    for i in range(mipcount):
        n = mip_bytes(fmt, mw, mh)
        if off + n > len(blob):
            break
        mips.append(blob[off:off + n]); off += n
        mw, mh = max(1, mw // 2), max(1, mh // 2)
    return fmt, w, h, mips


def load_image(path):
    """PNG/TGA/DDS/... -> (PIL RGBA image, dds tuple or None)."""
    from PIL import Image
    blob = open(path, "rb").read()
    dds = read_dds(blob)
    if dds and dds[3]:
        im = decode(dds[0], dds[1], dds[2], dds[3][0])
    else:
        im = Image.open(io.BytesIO(blob))
        im.load()
        im = im.convert("RGBA")
    return im, dds


# ---------------------------------------------------------------- encode
def _texconv():
    """Microsoft texconv.exe next to the tool (or on PATH): needed for BC7."""
    here = os.path.dirname(os.path.abspath(__file__))
    import sys
    for d in (getattr(sys, "_MEIPASS", None), os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None, here):
        if d and os.path.isfile(os.path.join(d, "texconv.exe")):
            return os.path.join(d, "texconv.exe")
    return shutil.which("texconv") or shutil.which("texconv.exe")


TEXCONV_FMT = {"PF_DXT1": "BC1_UNORM", "PF_DXT5": "BC3_UNORM", "PF_BC5": "BC5_UNORM", "PF_BC7": "BC7_UNORM"}


def _texconv_encode(im, fmt):
    exe = _texconv()
    if not exe:
        raise TexError("this texture is BC7: put Microsoft's texconv.exe (github.com/microsoft/DirectXTex/releases) "
                       "next to the tool, or import a BC7 .dds made with all its mips")
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "in.tga")                 # TGA: no colour-space tag, so texconv does no sRGB conversion
        im.convert("RGBA").save(src)
        r = subprocess.run([exe, "-nologo", "-y", "-m", "1", "-f", TEXCONV_FMT[fmt], "-o", d, src], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = next((os.path.join(d, f) for f in os.listdir(d) if f.lower() == "in.dds"), "")
        if r.returncode or not out:
            raise TexError("texconv failed: " + (r.stdout + r.stderr).strip()[-300:])
        dds = read_dds(open(out, "rb").read())
    return dds[3][0]


def encoder_name(fmt):
    """Which encoder encode() will use for fmt (shown in the UI)."""
    if fmt in TEXCONV_FMT and _texconv():
        return "texconv"
    if fmt in TEXCONV_FMT:
        return "built-in (lower quality: sharp colour edges can bleed, e.g. red next to white turns pink)"
    return "uncompressed"


def encode(fmt, im):
    """PIL RGBA image -> one mip in fmt."""
    w, h = im.size
    if fmt == "PF_B8G8R8A8":
        return im.tobytes("raw", "BGRA")
    if fmt == "PF_R8G8B8A8":
        return im.tobytes()
    if fmt == "PF_G8":
        return im.convert("L").tobytes()
    if fmt in TEXCONV_FMT and (fmt == "PF_BC7" or _texconv()) and w % 4 == 0 and h % 4 == 0:
        return _texconv_encode(im, fmt)         # better quality than Pillow's encoder (Pillow's DXT5 alpha is rough)
    pil = {"PF_DXT1": ("DXT1", "RGBA"), "PF_DXT5": ("DXT5", "RGBA"), "PF_BC5": ("BC5", "RGB")}.get(fmt)
    if pil is None:
        raise TexError("can't encode %s yet" % fmt)
    src = im.convert(pil[1])
    if w % 4 or h % 4:                                        # pad to whole blocks (tiny mips)
        from PIL import Image
        pad = Image.new(pil[1], (max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)))
        pad.paste(src, (0, 0))
        src = pad
    b = io.BytesIO()
    src.save(b, "DDS", pixel_format=pil[0])
    dds = read_dds(b.getvalue())
    data = dds[3][0]
    if len(data) != mip_bytes(fmt, w, h):
        raise TexError("encoder gave %d bytes for a %dx%d %s mip, expected %d" % (len(data), w, h, fmt, mip_bytes(fmt, w, h)))
    return data


def _s2l(c):
    import numpy as np
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _l2s(x):
    import numpy as np
    return 255.0 * np.where(x <= 0.0031308, x * 12.92, 1.055 * np.maximum(x, 0) ** (1 / 2.4) - 0.055)


def mip_chain(im, count, srgb=True):
    """2x2-average mips, each from the previous one. For sRGB textures the colour is averaged in linear light
    and alpha as is; otherwise everything as is. Checked against a GP24 cooked BGRA8 texture (livery001_ao_mask):
    ~87% of mip-1 values identical, the rest off by 1 (UE's own filter is not exactly this). No alpha
    premultiplying (Pillow's resize premultiplies RGBA, which UE does not)."""
    import numpy as np
    from PIL import Image
    out = [im.convert("RGBA")]
    a = np.asarray(out[0], dtype=np.float64)
    lin = a.copy()
    if srgb:
        lin[..., :3] = _s2l(a[..., :3])
    for _ in range(count - 1):
        h, w = lin.shape[:2]
        nh, nw = max(1, h // 2), max(1, w // 2)
        if h > 1 and w > 1:
            lin = lin[:nh * 2, :nw * 2].reshape(nh, 2, nw, 2, 4).mean((1, 3))
        elif h > 1:
            lin = lin[:nh * 2].reshape(nh, 2, w, 4).mean(1)
        elif w > 1:
            lin = lin[:, :nw * 2].reshape(h, nw, 2, 4).mean(2)
        px = lin.copy()
        if srgb:
            px[..., :3] = _l2s(lin[..., :3])
        out.append(Image.fromarray(np.clip(np.round(px), 0, 255).astype(np.uint8), "RGBA"))
    return out


# ---------------------------------------------------------------- write
def replace(ua_bytes, ux_bytes, ubulk, image_path=None, image=None, dds=None, allow_resize=True, log=None):
    """Template texture + new picture -> (uasset, uexp, ubulk or None). Keeps the template's pixel format,
    flags, settings and its split of mips between .uexp and .ubulk."""
    log = log or (lambda *a: None)
    info = parse(ua_bytes, ux_bytes, ubulk)
    if info["has_ubulk"] and ubulk is None:
        raise TexError("this texture keeps its big mips in a .ubulk - the template's .ubulk is needed")
    if image_path:
        image, dds = load_image(image_path)
    fmt, tm = info["fmt"], info["mips"]
    w, h = image.size
    if (w, h) != (info["w"], info["h"]):
        if not allow_resize:
            raise TexError("picture is %dx%d, the texture is %dx%d" % (w, h, info["w"], info["h"]))
        if len(tm) > 1 and (w & (w - 1) or h & (h - 1)):
            raise TexError("a texture with mips needs a power-of-two size (picture is %dx%d)" % (w, h))
    # how many mips: same as the template when the size is equal; full chain when the template has one
    full = lambda a, b: max(a, b).bit_length()
    if (w, h) == (info["w"], info["h"]):
        n = len(tm)
    elif len(tm) == 1:
        n = 1
    elif len(tm) == full(info["w"], info["h"]):
        n = full(w, h)
    else:
        n = max(1, full(w, h) - (full(info["w"], info["h"]) - len(tm)))
    n_inline = sum(1 for m in tm if m["where"] == "inline")
    tail_inline = all(m["where"] == "inline" for m in tm[len(tm) - n_inline:])
    if not tail_inline:
        raise TexError("unexpected mip split (inline mips are not the smallest ones)")
    ext_flags = next((m["flags"] for m in tm if m["where"] == "ubulk"), None)
    in_flags = next((m["flags"] for m in tm if m["where"] == "inline"), F_INLINE | F_SINGLE_USE)
    cooked = tm[0]["cooked"]

    raw = None
    if dds and dds[0] == fmt and (dds[1], dds[2]) == (w, h) and len(dds[3]) >= n:
        raw = dds[3][:n]
        log("using the .dds mips as they are (%s, %d mips)" % (fmt, n))
    elif dds and dds[0] != fmt:
        log("the .dds is %s, the texture is %s: re-encoding" % (dds[0], fmt))
    if raw is None:
        raw = [encode(fmt, m) for m in mip_chain(image, n, srgb=info["props"].get("SRGB", True) is not False)]
        log("encoded %d mips as %s" % (n, fmt))

    u = ux_bytes
    UA = len(ua_bytes)
    body = bytearray(u[:info["mips_at"]])
    struct.pack_into("<ii", body, info["size_at"], w, h)
    struct.pack_into("<i", body, info["nmips_at"] + 4, n)
    imp = [t for t in info["ex"]["props"] if t["name"] == "ImportedSize"]
    if imp:
        struct.pack_into("<ii", body, imp[0]["off"], w, h)
    new_bulk = bytearray()
    for i, data in enumerate(raw):
        mw, mh = max(1, w >> i), max(1, h >> i)
        if fmt in BLOCK:                              # GP24 cooks store block-format mips at least 4x4 (64,...,4,4,4)
            mw, mh = max(4, mw), max(4, mh)
        inline = i >= n - n_inline or ext_flags is None
        flags = in_flags if inline else ext_flags
        body += struct.pack("<iI", cooked, flags)
        body += struct.pack("<qq" if flags & F_SIZE64 else "<ii", len(data), len(data))
        if inline:
            body += struct.pack("<q", UA + len(body) + 8)
            body += data
        else:
            base = 0 if flags & F_NO_FIXUP else None
            if base is None:
                raise TexError(".ubulk mips without NoOffsetFixUp are not supported yet")
            body += struct.pack("<q", len(new_bulk))
            new_bulk += data
        body += struct.pack("<iii", mw, mh, 1)
    body += u[info["mips_end"]:]                          # bIsVirtual, None, tag
    struct.pack_into("<q", body, info["skip_at"], UA + len(body) - (len(u) - info["mips_end"]) + 4)
    ua = C.UAsset(ua_bytes)
    eo = ua._get("exportoff")
    struct.pack_into("<q", ua.data, eo + 28, len(body) - 4)
    ua._set("bulk", UA + len(body) - 4, "<q")
    out_ua = ua.to_bytes()
    assert len(out_ua) == UA
    nb = bytes(new_bulk) if (info["has_ubulk"] and new_bulk) else None
    # self-check: the result must re-parse to what we wrote
    chk = parse(out_ua, bytes(body), nb)
    assert (chk["w"], chk["h"], len(chk["mips"])) == (w, h, n)
    assert all(m["data"] == d for m, d in zip(chk["mips"], raw))
    return out_ua, bytes(body), nb
