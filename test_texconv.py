"""texconv check (Windows, texconv.exe next to this file or on PATH): DXT1/DXT5/BC5/BC7 through texconv give the
right sizes, no sRGB shift, and a sharp red/white edge stays red (Pillow's encoder turns it pink). Run by CI."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
import mgp_texture as T

if not T._texconv():
    print("SKIP texconv.exe not found"); sys.exit(0)
a = np.zeros((64, 64, 4), np.uint8); a[..., 3] = 255
a[:, :] = (222, 227, 239, 255); a[:, :17] = (231, 4, 8, 255); a[:, 17] = (228, 78, 85, 255)   # edge inside a block
a[40:, 40:] = (128, 128, 128, 255)                                                          # mid grey: sRGB shift check
im = Image.fromarray(a, "RGBA")
fails = 0
for fmt in ("PF_DXT1", "PF_DXT5", "PF_BC5", "PF_BC7"):
    assert T.encoder_name(fmt) == "texconv"
    data = T.encode(fmt, im)
    got = np.asarray(T.decode(fmt, 64, 64, data), int)
    ch = 2 if fmt == "PF_BC5" else 3
    d = np.abs(got[..., :ch] - a[..., :ch].astype(int))
    good = len(data) == T.mip_bytes(fmt, 64, 64) and d.max() <= 40 and abs(got[50, 50, 0] - 128) <= 4
    print(("PASS " if good else "FAIL ") + "%s: %d bytes, max diff %d, grey %d" % (fmt, len(data), d.max(), got[50, 50, 0]))
    fails += not good
sys.exit(1 if fails else 0)
