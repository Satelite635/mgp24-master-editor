"""Copy values between assets (valcopy). Without arguments: synthetic GP24 (UE4.27 tagged) projector files.
With arguments: python test_valcopy.py <MotoGP_25.usmap> <gp25 zen projector .uasset> <gp25 legacy projector .uasset (+ .uexp next to it)>
(samples: project files gp25-samples/ and gp26-to-gp25-projectors/)."""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import projfile as PJ
import valcopy as V
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))


# ---- a minimal cooked UE4.27 projector asset (same layout the parsers read)
class Gp24:
    def __init__(self):
        self.names = ["None"]

    def n(self, text):
        if text not in self.names:
            self.names.append(text)
        return self.names.index(text)

    def fn(self, text):
        return struct.pack("<ii", self.n(text), 0)

    def tag(self, name, typ, body, extra=b""):
        return self.fn(name) + self.fn(typ) + struct.pack("<ii", len(body), 0) + extra + b"\0" + body

    def struct_(self, name, sname, body):
        return self.tag(name, "StructProperty", body, self.fn(sname) + bytes(16))

    def projector(self, tag, loc, quat, scale, prio):
        tr = (self.struct_("Rotation", "Quat", struct.pack("<4f", *quat)) + self.struct_("Translation", "Vector", struct.pack("<3f", *loc)) +
              self.struct_("Scale3D", "Vector", struct.pack("<3f", *scale)) + self.fn("None"))
        pr = self.tag("Priority", "IntProperty", struct.pack("<i", prio)) + self.struct_("Transform", "Transform", tr) + self.fn("None")
        return self.tag("Tag", "NameProperty", self.fn(tag)) + self.struct_("Projector", "VehicleCustomizationProjectorData", pr) + self.fn("None")

    def build(self, projs, extra_float=None, mesh=None):
        self.mesh = mesh
        items = b"".join(self.projector(*p) for p in projs)
        inner = self.fn("TaggedProjectors") + self.fn("StructProperty") + struct.pack("<ii", len(items), 0) + \
            self.fn("IgnitionTaggedProjectorData") + bytes(16) + b"\0"
        arr = struct.pack("<i", len(projs)) + inner + items
        body = self.tag("TaggedProjectors", "ArrayProperty", arr, self.fn("StructProperty"))
        if extra_float is not None:
            body += self.tag("TextureResidentTime", "FloatProperty", struct.pack("<f", extra_float))
        if mesh:
            body += self.tag("Mesh", "ObjectProperty", struct.pack("<i", -4))
        uexp = body + self.fn("None") + bytes(4) + struct.pack("<I", 0x9E2A83C1)
        for t in ("/Script/Engine", "Package", "BlueprintGeneratedClass", "ProjectorsDataSource_C", "/Game/x/ProjectorsDataSource", "projector103_001",
                  "/Script/CoreUObject", "SkeletalMesh") + ((mesh, "/Game/m/" + mesh) if mesh else ()):
            self.n(t)
        return self.header(len(uexp) - 4), uexp

    def header(self, size):
        def fstr(s):
            return struct.pack("<i", len(s) + 1) + s.encode() + b"\0"
        names = b"".join(fstr(t) + bytes(4) for t in self.names)
        imp = lambda cp, cn, outer, on: struct.pack("<iiiiiii", self.n(cp), 0, self.n(cn), 0, outer, self.n(on), 0)
        imports = imp("/Script/CoreUObject", "Package", 0, "/Game/x/ProjectorsDataSource") + \
            imp("/Script/Engine", "BlueprintGeneratedClass", -1, "ProjectorsDataSource_C")
        if self.mesh:
            imports += imp("/Script/CoreUObject", "Package", 0, "/Game/m/" + self.mesh) + imp("/Script/Engine", "SkeletalMesh", -3, self.mesh)
        fields = {}
        out = bytearray()
        out += struct.pack("<Iiiii", 0x9E2A83C1, -7, 864, 522, 0) + struct.pack("<i", 0)
        fields["total"] = len(out); out += bytes(4)
        out += fstr("None") + struct.pack("<I", 0x80000000)
        out += struct.pack("<i", len(self.names)); fields["nameoff"] = len(out); out += bytes(4)
        out += bytes(8)                                                     # gatherable text
        out += struct.pack("<i", 1); fields["exportoff"] = len(out); out += bytes(4)
        out += struct.pack("<i", 4 if self.mesh else 2); fields["importoff"] = len(out); out += bytes(4)
        fields["dependsoff"] = len(out); out += bytes(4)
        out += bytes(16) + bytes(16)                                        # soft refs, searchable, thumbnails, guid
        out += struct.pack("<i", 1) + struct.pack("<ii", 1, len(self.names))
        out += bytes(10) + fstr("") + bytes(10) + fstr("")
        out += bytes(4) + struct.pack("<i", 0) + bytes(4) + struct.pack("<i", 0)
        out += bytes(4) + bytes(8) + bytes(4) + struct.pack("<i", 0) + bytes(8)
        no = len(out); out += names
        io = len(out); out += imports
        eo = len(out); out += bytes(104)
        do = len(out); out += bytes(4)
        for k, v in (("nameoff", no), ("importoff", io), ("exportoff", eo), ("dependsoff", do), ("total", len(out))):
            struct.pack_into("<i", out, fields[k], v)
        struct.pack_into("<i", out, eo, -2)                                 # class: ProjectorsDataSource_C
        struct.pack_into("<ii", out, eo + 16, self.n("projector103_001"), 0)
        struct.pack_into("<qq", out, eo + 28, size, len(out))
        return bytes(out)


A = [("SidePlateRight", (82, 0, 96), (0.25, 0, -0.96, 0), (0.39, 0.26, 0.26), 0),
     ("FrontPlate", (-1.5, 33, 111), (-0.19, 0.18, -0.67, 0.68), (0.28, 0.24, 0.12), 2)]
B = [("FrontPlate", (-1.0, 30, 110), (-0.19, 0.18, -0.67, 0.68), (0.5, 0.5, 0.5), 5),
     ("SidePlateRight", (83, 0.3, 96.6), (0.25, -0.03, -0.96, 0.007), (0.21, 0.22, 0.21), 0),
     ("SidePlateLeft", (-8, -28, 112), (0.15, 0.16, 0.68, 0.69), (0.28, 0.21, 0.10), 0)]

ua, ux = Gp24().build(A, extra_float=3.0)
ub, uxb = Gp24().build(B, extra_float=7.5)
a, pa = PJ.parse(ua, ux)
ok([p["tag"] for p in pa] == ["SidePlateRight", "FrontPlate"], "synthetic GP24 projector file parses")
dst, src = V.Doc(ua, ux), V.Doc(ub, uxb)
ok(dst.kind == src.kind == "tagged" and dst.cls == "ProjectorsDataSource_C", "opened as tagged GP24 files")
r = V.copy(src, dst)
st = {x["path"]: x["status"] for x in r["rows"]}
ok(st.get("TaggedProjectors[FrontPlate].Projector.Transform.Translation") == "changed", "matched by tag, not by position")
ok(st.get("TaggedProjectors[FrontPlate].Projector.Priority") == "changed" and st.get("TextureResidentTime") == "changed", "numbers copied")
ok(st.get("TaggedProjectors[SidePlateLeft]") == "not in target", "extra source projector reported, not added")
ua2, ux2 = dst.files()
ok(ua2 == ua and len(ux2) == len(ux), "target .uasset untouched, .uexp same size")
_, p2 = PJ.parse(ua2, ux2)
f = {p["tag"]: p for p in p2}
ok(abs(f["FrontPlate"]["loc"][1] - 30) < 1e-6 and f["FrontPlate"]["priority"] == 5 and abs(f["SidePlateRight"]["scale"][0] - 0.21) < 1e-6,
   "patched values read back")
again = V.copy(V.Doc(ub, uxb), V.Doc(ua2, ux2), write=False)
ok(not again["changes"], "copying again changes nothing")
only = V.copy(V.Doc(ub, uxb), V.Doc(ua, ux), only=["TaggedProjectors[FrontPlate]"])
ok(only["changes"] and all(x["path"].startswith("TaggedProjectors[FrontPlate]") for x in only["rows"]), "copy limited to one projector")

# object references: repoint the target's import (same class), header grows, .uexp keeps its size
ma, mx = Gp24().build(A, mesh="meshA")
mb, mxb = Gp24().build(B, mesh="meshB_long_name")
t = V.Doc(ma, mx)
r = V.copy(V.Doc(mb, mxb), t)
st = {x["path"]: x for x in r["rows"]}
ok(st.get("Mesh", {}).get("status") == "changed", "mesh reference copied (%s)" % st.get("Mesh"))
ma2, mx2 = t.files()
ok(len(mx2) == len(mx) and len(ma2) > len(ma), ".uexp same size, .uasset grew (%d -> %d)" % (len(ma), len(ma2)))
from mgp_core import UAsset
h = UAsset(ma2)
eo = h._get("exportoff")
import zlib
from mgp_core import _name_hash
good = lambda u: all(struct.unpack_from("<HH", u.data, n["pos"] + n["nbytes"] + 1) == (_name_hash(n["text"]), zlib.crc32(n["text"].encode("utf-32-le")) & 0xFFFF)
                     for n in u.names)
ok(all(struct.unpack_from("<HH", h.data, n["pos"] + n["nbytes"] + 1) == (_name_hash(n["text"]), zlib.crc32(n["text"].encode("utf-32-le")) & 0xFFFF)
       for n in h.names[-2:]), "appended names get both hashes (UAssetGUI binary equality)")
u0 = UAsset(ma)
ok(u0.fix_name_hashes() == len(u0.names) and good(u0) and len(u0.to_bytes()) == len(ma), "fix_name_hashes repairs zero hashes in place")
ok(h._get("total") == len(ma2) and struct.unpack_from("<q", ma2, eo + 36)[0] == len(ma2), "header size and export SerialOffset follow the growth")
back = V.Doc(ma2, mx2)
mesh = next(x for x in back.props if x["name"] == "Mesh")
ok(mesh["value"] == "/Game/m/meshB_long_name.meshB_long_name", "target now points at the source's mesh: " + mesh["value"])
ok(PJ.parse(ma2, mx2)[1][0]["tag"] and not V.copy(V.Doc(mb, mxb), back, write=False)["changes"], "still parses; nothing left to copy")
ok(not h.duplicate_names(), "repoint adds no duplicate names")
# a name that is in the table twice, with the mesh import's object name pointing at the second copy
d = UAsset(ma2)
io = d._get("importoff")
mi = next(i for i in range(d._get("importcount")) if d.names[struct.unpack_from("<i", d.data, io + i * 28 + 20)[0]]["text"] == "meshB_long_name")
first = struct.unpack_from("<i", d.data, io + mi * 28 + 20)[0]
dup = d.append_name("meshB_long_name")
io = d._get("importoff")
struct.pack_into("<i", d.data, io + mi * 28 + 20, dup)
ok(d.duplicate_names() == {dup: first}, "duplicate found")
m, sk = UAsset(d.to_bytes()).merge_duplicate_names(struct.pack("<i", dup))
ok(not m and sk == ["meshB_long_name"], "left alone when its index may be used in the .uexp")
d2 = UAsset(d.to_bytes())
m, sk = d2.merge_duplicate_names(mx2)
ok(m == ["meshB_long_name"] and not sk and struct.unpack_from("<i", d2.data, d2._get("importoff") + mi * 28 + 20)[0] == first
   and len(d2.to_bytes()) == len(d.to_bytes()), "header use moved to the first copy, same size")
ok(next(x for x in V.Doc(d2.to_bytes(), mx2).props if x["name"] == "Mesh")["value"] == "/Game/m/meshB_long_name.meshB_long_name", "still reads the same mesh")
# Browse -> clone with a new name: the asset's own object name follows the package name
c = UAsset(ma)
on = c.export_object_names()[0]
ok(c.rename_object_name(on, on + "_copy2", mx) and c.export_object_names()[0] == on + "_copy2" and on not in c.texts()
   and not c.duplicate_names() and V.Doc(c.to_bytes(), mx).cls == "ProjectorsDataSource_C", "export name renamed in place (%s)" % on)
c = UAsset(ma)
ok(c.rename_object_name(on, on + "_copy2", struct.pack("<i", c.texts().index(on))) and c.export_object_names()[0] == on + "_copy2"
   and on in c.texts() and not c.duplicate_names() and V.Doc(c.to_bytes(), mx).cls == "ProjectorsDataSource_C", "kept when the .uexp may use it; export moved to a new name")
c = UAsset(ma)
ok(c.fix_own_name("newbase", mx) == on and c.export_object_names()[0] == "newbase" and c.fix_own_name("newbase", mx) is None, "Fix name tables renames an old clone's object name once")
r = V.copy(V.Doc(mb, mxb), V.Doc(ma, mx), refs=False, write=False)
ok(not any(x["path"] == "Mesh" and x["status"] == "changed" for x in r["rows"]), "refs=False keeps the path")

if len(sys.argv) > 3:
    import usmap
    u = usmap.load(sys.argv[1])
    zen = open(sys.argv[2], "rb").read()
    lua = open(sys.argv[3], "rb").read()
    lux = open(sys.argv[3][:-7] + ".uexp", "rb").read()
    z, l = V.Doc(zen, None, u), V.Doc(lua, lux, u)
    ok(z.kind == "zen" and l.kind == "legacy-unversioned" and z.cls == l.cls, "GP25 zen + legacy read with the .usmap (%s)" % z.cls)
    r = V.copy(z, l)
    ok(not any(x["status"] in ("different", "skipped") for x in r["rows"]), "zen -> legacy: nothing skipped (%s)" % r["counts"])
    ua2, ux2 = l.files()
    ok(ua2 == lua and len(ux2) == len(lux), "legacy target: .uasset untouched, .uexp same size")
    _, pz = PJ.parse(zen, None)
    _, pl = PJ.parse(ua2, ux2)
    ok([p["loc"] + p["quat"] + p["scale"] for p in pz] == [p["loc"] + p["quat"] + p["scale"] for p in pl], "legacy now has the zen file's transforms")
    back = V.copy(V.Doc(ua2, ux2, u), V.Doc(zen, None, u), write=False)
    ok(not back["changes"], "and the other way round there is nothing left to change")
    # GP25 -> GP24: doubles into floats
    g = V.Doc(ua, ux)
    r = V.copy(z, g)
    ok(r["changes"] > 0 and not any(x["why"].startswith("different type") for x in r["rows"] if x["status"] == "different"), "GP25 zen -> GP24 tagged: doubles written as floats (%s)" % r["counts"])
    _, pg = PJ.parse(*g.files())
    zt = {p["tag"]: p for p in pz}
    ok(all(abs(p["loc"][k] - zt[p["tag"]]["loc"][k]) < 1e-3 for p in pg for k in range(3)), "GP24 file has the GP25 positions")
    # zen target stays a valid zen file of the same size
    z2 = V.Doc(zen, None, u)
    r = V.copy(V.Doc(ub, uxb), z2)
    out, _ = z2.files()
    ok(len(out) == len(zen) and PJ.parse(out, None)[1][0]["tag"], "GP24 -> GP25 zen: same size, still parses (%s)" % r["counts"])
print("VALCOPY OK")
