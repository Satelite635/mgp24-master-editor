"""Read/write the number projectors (ProjectorCustomNNN_VVV / ProjectorsDataSource) of MotoGP 24 bikes.
No Blender imports here, so it can be tested outside Blender."""
import os, shutil

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
    a = uprops.Asset(open(path, "rb").read(), open(_uexp(path), "rb").read())
    t = uprops.tree(a)
    arr = next((p for p in t["props"] if p["name"] == "TaggedProjectors"), None)
    if arr is None:
        raise ValueError("%s has no TaggedProjectors - not a projector file" % os.path.basename(path))
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
        out.append(dict(tag=tag, loc=list(loc["value"]), quat=list(rot["value"]), scale=list(sc["value"]),
                        texture=tex, offs=dict(rot=rot["off"], loc=loc["off"], scale=sc["off"])))
    return a, out


def save(path, values, backup=True):
    """values: {tag: dict(loc, quat, scale)} - written in place (same file size). Returns the tags written.
    The first save of a file keeps a copy as <name>.uasset.bak / .uexp.bak."""
    a, projs = load(path)
    done = []
    for p in projs:
        v = values.get(p["tag"])
        if not v:
            continue
        a.set_value(p["offs"]["loc"], "floats", v["loc"])
        a.set_value(p["offs"]["rot"], "floats", v["quat"])
        a.set_value(p["offs"]["scale"], "floats", v["scale"])
        done.append(p["tag"])
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
