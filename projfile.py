"""Read/write the number projectors (ProjectorCustomNNN_VVV / ProjectorsDataSource) of MotoGP 24 bikes.
No Blender imports here, so it can be tested outside Blender."""
import os, re, shutil, struct

import uprops


def _kid(node, name):
    for c in node.get("children") or []:
        if c["name"] == name:
            return c
    return None


def _uexp(path):
    return os.path.splitext(path)[0] + ".uexp"


def load(path):
    """-> (Asset, [dict(tag, loc, quat, scale, texture, offs)]) ; quat is UE order (x, y, z, w)."""
    return parse(open(path, "rb").read(), open(_uexp(path), "rb").read())


def parse(uasset_bytes, uexp_bytes):
    """Same as load() from bytes (used by the editor, which reads through mod folder + paks).
    uexp_bytes None: a MotoGP 25 zen package (one .uasset), see parse_zen."""
    if uexp_bytes is None:
        return parse_zen(uasset_bytes)
    a = uprops.Asset(uasset_bytes, uexp_bytes)
    t = uprops.tree(a)
    arr = next((p for p in t["props"] if p["name"] == "TaggedProjectors"), None)
    if arr is None:
        raise ValueError("no TaggedProjectors - not a projector file")
    out = []
    for item in arr.get("children") or []:
        pr = _kid(item, "Projector")
        tr = _kid(pr, "Transform") if pr else None
        if not tr:
            continue
        rot, loc, sc = _kid(tr, "Rotation"), _kid(tr, "Translation"), _kid(tr, "Scale3D")
        if not (rot and loc and sc and "off" in rot and "off" in loc and "off" in sc):
            raise ValueError("projector %s: transform not readable" % item["name"])
        tex = ""
        layers = _kid(pr, "Layers")
        if layers and layers.get("children"):
            bc = _kid(layers["children"][0], "BaseColorMap")
            tex = (bc or {}).get("value", "") or ""
        tag = (_kid(item, "Tag") or {}).get("value", item["name"])
        pri = _kid(pr, "Priority") or {}
        out.append(dict(tag=tag, loc=list(loc["value"]), quat=list(rot["value"]), scale=list(sc["value"]),
                        priority=pri.get("value"), texture=tex,
                        offs=dict(rot=rot["off"], loc=loc["off"], scale=sc["off"], priority=pri.get("off"))))
    return a, out


class ZenProjectors:
    """A MotoGP 25 projector file (zen package, unversioned properties) patched in place: the transform is
    10 doubles (UE5 LWC), so edits never change the size."""
    zen = True

    def __init__(self, data):
        self.data = bytearray(data)

    def set_value(self, off, kind, vals):
        if kind == "floats":
            struct.pack_into("<%dd" % len(vals), self.data, off, *vals)
        elif kind == "num":
            struct.pack_into("<i", self.data, off, int(vals))
        else:
            raise ValueError("unsupported value kind " + kind)

    def to_bytes(self):
        return bytes(self.data)


# One TaggedProjectors item (IgnitionTaggedProjectorData), unversioned (read on GP25 projector108_00X):
# [00 05][Tag FName 8][Projector: header 80 07 + zero mask 01 (Priority=0) | header 00 07 + Priority i32]
# [Transform: 00 07][Rotation 4 doubles][Translation 3][Scale3D 3][Layers count i32][layer header u16 ...]
_ZEN_ITEM = re.compile(rb"\x00\x05(.{8})(?:\x80\x07\x01|\x00\x07(.{4}))\x00\x07", re.S)


def parse_zen(data):
    import mgp_zen
    z = mgp_zen.ZenPackage(data)
    if len(z.exports) != 1 or not any(n.endswith("/ProjectorsDataSource") for n in z.imported_package_names()):
        raise ValueError("no TaggedProjectors - not a projector file")
    base, x = z.header_size, z.export_data()
    out = []
    for m in _ZEN_ITEM.finditer(x):
        ni, nn = struct.unpack_from("<II", m.group(1))
        if ni >= len(z.names) or nn > 1000:
            continue
        p = m.end()
        if p + 84 > len(x):
            raise ValueError("projector %s: transform not readable" % z.names[ni])
        v = struct.unpack_from("<10d", x, p)
        tex, q = "", p + 80
        if struct.unpack_from("<i", x, q)[0] > 0:                     # first layer: BaseColorMap is its first property
            hdr = struct.unpack_from("<H", x, q + 4)[0]
            q += 6
            zero_first = False
            if hdr & 0x80:                                             # zero mask follows the header
                nvals = hdr >> 9
                zero_first = bool(x[q] & 1)
                q += 1 if nvals <= 8 else 2 if nvals <= 16 else ((nvals + 31) // 32) * 4
            if not zero_first and not hdr & 0x7F:
                tex = z.import_package(struct.unpack_from("<i", x, q)[0])
        pri = struct.unpack_from("<i", m.group(2))[0] if m.group(2) else 0
        out.append(dict(tag=mgp_zen.join_fname(z.names[ni], nn), loc=list(v[4:7]), quat=list(v[0:4]), scale=list(v[7:10]),
                        priority=pri, texture=tex,
                        offs=dict(rot=base + p, loc=base + p + 32, scale=base + p + 56,
                                  priority=base + m.start(2) if m.group(2) else None)))
    count = struct.unpack_from("<i", x, _ZEN_ITEM.search(x).start() - 4)[0] if out else -1
    if count != len(out):
        raise ValueError("TaggedProjectors layout not understood (found %d of %d)" % (len(out), count))
    return ZenProjectors(data), out


def patch(a, projs, values):
    """Write {tag: dict(loc, quat, scale[, priority])} into the parsed asset `a` in place; returns the tags written."""
    done = []
    for p in projs:
        v = values.get(p["tag"])
        if not v:
            continue
        a.set_value(p["offs"]["loc"], "floats", v["loc"])
        a.set_value(p["offs"]["rot"], "floats", v["quat"])
        a.set_value(p["offs"]["scale"], "floats", v["scale"])
        if v.get("priority") is not None and p["offs"].get("priority") is not None:
            a.set_value(p["offs"]["priority"], "num", v["priority"])
        done.append(p["tag"])
    return done


def save(path, values, backup=True):
    """values: {tag: dict(loc, quat, scale)} - written in place (same file size). Returns the tags written.
    The first save of a file keeps a copy as <name>.uasset.bak / .uexp.bak."""
    a, projs = load(path)
    done = patch(a, projs, values)
    if backup:
        for f in (path, _uexp(path)):
            if not os.path.exists(f + ".bak"):
                shutil.copyfile(f, f + ".bak")
    with open(_uexp(path), "wb") as f:
        f.write(bytes(a.uexp))
    return done


# ---- UE (cm, left-handed, X fwd / Y right / Z up) <-> Blender (right-handed). flip_y mirrors Y, which is how
# UE importers (UModel, FModel, the psk/gltf add-ons) usually bring models into Blender.
def ue_to_blender(loc, quat, scale, unit=0.01, flip_y=True):
    x, y, z = loc
    qx, qy, qz, qw = quat
    if flip_y:
        return (x * unit, -y * unit, z * unit), (qw, -qx, qy, -qz), tuple(scale)
    return (x * unit, y * unit, z * unit), (qw, qx, qy, qz), tuple(scale)


def blender_to_ue(loc, quat_wxyz, scale, unit=0.01, flip_y=True):
    x, y, z = loc
    w, bx, by, bz = quat_wxyz
    if flip_y:
        return [x / unit, -y / unit, z / unit], [-bx, by, -bz, w], list(scale)
    return [x / unit, y / unit, z / unit], [bx, by, bz, w], list(scale)


# ---- FRotator (degrees: pitch, yaw, roll) <-> FQuat (x, y, z, w), same formulas as UE 4.27 (Rotator.Quaternion / Quat.Rotator)
def rotator_to_quat(pitch, yaw, roll):
    import math
    p, y, r = (math.radians(v) / 2 for v in (pitch, yaw, roll))
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(r), math.cos(r)
    return [cr * sp * sy - sr * cp * cy, -cr * sp * cy - sr * cp * sy, cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy]


def quat_to_rotator(q):
    import math
    x, y, z, w = q
    sing = z * x - w * y
    yaw = math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))
    if sing < -0.4999995:
        return [-90.0, yaw, _norm(-yaw - 2 * math.degrees(math.atan2(x, w)))]
    if sing > 0.4999995:
        return [90.0, yaw, _norm(yaw - 2 * math.degrees(math.atan2(x, w)))]
    return [math.degrees(math.asin(2 * sing)), yaw, math.degrees(math.atan2(-2 * (w * x + y * z), 1 - 2 * (x * x + y * y)))]


def _norm(a):
    a = (a + 180) % 360 - 180
    return a
