"""Texture import test. Usage: python test_texture.py <loose project folder with cooked GP24 Texture2D assets> <work dir>
Every Texture2D found: parse, preview, same-picture rewrite (byte-identical for uncompressed formats), a
resized replacement through the API (staged), and a .dds round trip."""
import glob, io, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
import mgp_texture as T
import webui as W

SRC, WORK = sys.argv[1:3]
shutil.rmtree(WORK, ignore_errors=True)
shutil.copytree(SRC, WORK)
fails = []
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c:
        fails.append(m)

cfg = {}
if not glob.glob(os.path.join(WORK, "Content", "assets", "graphics", "bindings", "Vehicles", "Official", "DT_BikeOfficial.uasset")):
    W.C.Project.reload_bindings = lambda self: None          # texture-only sample folder
S = W.State(lambda: cfg, lambda c: cfg.update(c), "")
S.open(WORK, None, "", True)
R = W.make_api(S)
post = lambda p, b: R[("POST", p)]({}, b)
tmp = os.path.join(WORK, "_pics"); os.makedirs(tmp)

n = 0
for ux_path in sorted(glob.glob(os.path.join(WORK, "Content", "**", "*.uexp"), recursive=True)):
    stem = ux_path[:-5]
    ua, ux = open(stem + ".uasset", "rb").read(), open(ux_path, "rb").read()
    ub = open(stem + ".ubulk", "rb").read() if os.path.exists(stem + ".ubulk") else None
    try:
        info = T.parse(ua, ux, ub)
    except T.TexError:
        continue
    n += 1
    name = os.path.basename(stem)
    pkg = "/Game/" + os.path.relpath(stem, os.path.join(WORK, "Content")).replace(os.sep, "/")
    im = T.preview(info)
    raw = (info["fmt"], info["w"], info["h"], [m["data"] for m in info["mips"]])
    a1, u1, b1 = T.replace(ua, ux, ub, image=im, dds=raw)
    ok(a1 == ua and u1 == ux and b1 == ub, name + ": its own mips written back -> byte-identical (.uasset/.uexp/.ubulk)")
    a2, u2, b2 = T.replace(ua, ux, ub, image=im)
    if info["fmt"] in ("PF_B8G8R8A8", "PF_G8", "PF_R8G8B8A8") and len(info["mips"]) == 1:
        ok(a2 == ua and u2 == ux and b2 == ub, name + ": same picture rewrites byte-identical")
    else:
        d = np.abs(np.asarray(T.preview(T.parse(a2, u2, b2)), int) - np.asarray(im, int))
        ok(len(u2) == len(ux) and d.mean() <= 4, "%s: %s re-encode same size, pixel diff mean %.2f max %d (lossy)" % (name, info["fmt"], d.mean(), d.max()))
    d = post("/api/tex/info", {"pkg": pkg})
    ok(d["width"] == info["w"] and d.get("preview", "").startswith("data:image/png"), name + ": info + preview")
    # new picture, double size, through the API (staged)
    k = 2 if info["w"] <= 1024 else 0.5
    w, h = int(info["w"] * k), int(info["h"] * k)
    if len(info["mips"]) > 1:
        w, h = 1 << (w.bit_length() - 1), 1 << (h.bit_length() - 1)
    pic = Image.fromarray((np.random.RandomState(1).rand(h, w, 4) * 255).astype("uint8"), "RGBA")
    pp = os.path.join(tmp, name + ".png"); pic.save(pp)
    if ub is not None and w < info["w"] and sum(m["where"] == "inline" for m in info["mips"]) >= max(w, h).bit_length():
        continue
    r = post("/api/tex/replace", {"pkg": pkg, "path": pp})
    ok(r["info"]["width"] == w and r["info"]["height"] == h and r["info"]["format"] == info["fmt"],
       "%s: replaced with %dx%d via API" % (name, w, h))
    staged = S.need().src
    rel = "Content" + pkg[len("/Game"):]
    j = T.parse(staged.read(rel + ".uasset"), staged.read(rel + ".uexp"),
                staged.read(rel + ".ubulk") if staged.exists(rel + ".ubulk") else None)
    got = np.asarray(T.preview(j), int)
    tol = 0 if info["fmt"] == "PF_B8G8R8A8" else 255
    ok(np.abs(got - np.asarray(pic, int)).max() <= tol, name + ": staged file holds the new picture")
    ex = post("/api/tex/export", {"pkg": pkg})
    ok(Image.open(ex["path"]).size == (w, h), name + ": export PNG")

# .dds input used as is (DXT5, full mips, from Pillow)
pic = Image.fromarray((np.random.RandomState(2).rand(64, 64, 4) * 255).astype("uint8"), "RGBA")
b = io.BytesIO(); pic.save(b, "DDS", pixel_format="DXT5")
dds = T.read_dds(b.getvalue())
ok(dds and dds[0] == "PF_DXT5" and (dds[1], dds[2]) == (64, 64), ".dds header read")
for fmt in ("PF_DXT1", "PF_DXT5", "PF_BC5", "PF_B8G8R8A8", "PF_G8"):
    ok(len(T.encode(fmt, pic)) == T.mip_bytes(fmt, 64, 64), fmt + " encodes to the right size")

# synthetic streaming texture (mips in .ubulk + inline tail), built from a 1-mip DXT5 template. This only
# checks that the reader and writer agree with each other - the real GP24 layout still needs a game sample.
def synth(ua, ux, size=256, n_ext=3, ext_flags=0x10501):
    import struct
    info = T.parse(ua, ux)
    fmt, n = info["fmt"], size.bit_length()
    body = bytearray(ux[:info["mips_at"]]); struct.pack_into("<ii", body, info["size_at"], size, size)
    struct.pack_into("<i", body, info["nmips_at"] + 4, n)
    bulk = bytearray()
    for i in range(n):
        m = max(1, size >> i); data = bytes([i]) * T.mip_bytes(fmt, m, m)
        if i < n_ext:
            body += struct.pack("<iIiiq", 1, ext_flags, len(data), len(data), len(bulk)); bulk += data
        else:
            body += struct.pack("<iIiiq", 1, 0x48, len(data), len(data), len(ua) + len(body) + 24) + data
        body += struct.pack("<iii", m, m, 1)
    body += ux[info["mips_end"]:]
    struct.pack_into("<q", body, info["skip_at"], len(ua) + len(body) - (len(ux) - info["mips_end"]) + 4)
    return bytes(body), bytes(bulk)

for ux_path in glob.glob(os.path.join(SRC, "Content", "**", "*.uexp"), recursive=True):
    ua, ux = open(ux_path[:-5] + ".uasset", "rb").read(), open(ux_path, "rb").read()
    try:
        if T.parse(ua, ux)["fmt"] != "PF_DXT5":
            continue
    except T.TexError:
        continue
    sux, sub = synth(ua, ux)
    si = T.parse(ua, sux, sub)
    ok(len(si["mips"]) == 9 and sum(m["where"] == "ubulk" for m in si["mips"]) == 3, "synthetic: 9 mips, 3 in .ubulk")
    pic = Image.fromarray((np.random.RandomState(3).rand(256, 256, 4) * 255).astype("uint8"), "RGBA")
    a2, u2, b2 = T.replace(ua, sux, sub, image=pic)
    ok(b2 is not None and len(b2) == len(sub), "synthetic: same size -> .ubulk same length")
    big = pic.resize((512, 512))
    a3, u3, b3 = T.replace(ua, sux, sub, image=big)
    j = T.parse(a3, u3, b3)
    ok(len(j["mips"]) == 10 and sum(m["where"] == "ubulk" for m in j["mips"]) == 4 and j["mips"][0]["w"] == 512,
       "synthetic: 512 -> 10 mips, 4 in .ubulk, inline tail kept")
    ok(len(b3) == sum(m["size"] for m in j["mips"] if m["where"] == "ubulk"), "synthetic: .ubulk holds exactly the big mips")
    break
ok(n > 0, "%d textures tested" % n)
print("ALL PASS" if not fails else "%d FAIL" % len(fails))
sys.exit(1 if fails else 0)
