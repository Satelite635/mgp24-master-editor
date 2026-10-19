import os, shutil, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mgp_core as C
SRC = sys.argv[1]                                   # extracted tree containing the bindings
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
REL = "Content/assets/graphics/bindings/Vehicles/Official/DT_BikeOfficial"
a0 = open(os.path.join(SRC, REL + ".uasset"), "rb").read(); u0 = open(os.path.join(SRC, REL + ".uexp"), "rb").read()

def sections(ua):
    g = lambda k: ua._get(k)
    pts = [("imports", g("importoff")), ("exports", g("exportoff")), ("depends", g("dependsoff")),
           ("assetreg", g("assetregoff")), ("preload", g("preloadoff")), ("end", g("total"))]
    pts.sort(key=lambda x: x[1])
    return {n: bytes(ua.data[o:pts[i + 1][1]]) for i, (n, o) in enumerate(pts[:-1])}, dict(pts)

t = C.BindingTable(a0, u0)
Q = "MotoGP_Fabio-Quartararo"; old = t.target(Q)
sec0, pos0 = sections(t.ua)
others = {r: t.target(r) for r in t.rows if r != Q}
new = "/Game/assets/graphics/vehicles/bikes/cat001/chassis/chassis103/customization_data/bike103_0010.bike103_0010"   # different length
t.set_target(Q, new)
ua = t.ua
ok(t.target(Q) == new, "row points to the new, longer path")
delta = len(ua.data) - len(a0)
print("header grew by", delta, "bytes (2 names appended)")
ok(ua._get("namecount") == 306 and len(ua.names) == 306, "name count +2")
ok(ua._get("total") == len(ua.data), "TotalHeaderSize == file length")
eo = ua._get("exportoff")
ss, so = struct.unpack_from("<qq", ua.data, eo + 28)
ok(so == len(ua.data) and ss == len(u0) - 4, "export SerialOffset/Size consistent")
ok(ua._get("bulk", "<q") == len(ua.data) + ss, "BulkDataStartOffset consistent")
sec1, pos1 = sections(ua)
ok(all(sec0[k] == sec1[k] or k == "exports" for k in sec0), "imports/depends/assetreg/preload bytes identical")
exp0, exp1 = bytearray(sec0["exports"]), bytearray(sec1["exports"])
struct.pack_into("<q", exp1, 36, struct.unpack_from("<q", exp1, 36)[0] - delta)
ok(bytes(exp0) == bytes(exp1), "export entry identical except SerialOffset (+%d)" % delta)
ok(all(pos1[k] == pos0[k] + delta for k in ("imports", "exports", "depends", "assetreg", "preload", "end")), "every section start shifted by exactly the added size")
ok(ua.names[304]["text"] == new.partition(".")[0] and ua.names[305]["text"] == new, "appended package + object names")
ok(C._name_hash(ua.names[0]["text"]) == struct.unpack_from("<H", a0, C.UAsset(a0).names[0]["pos"] + len(ua.names[0]["text"]) + 1)[0], "hash function reproduces a real stored hash")
ok(u0 != bytes(t.uexp) and sum(x != y for x, y in zip(u0, t.uexp)) <= 4, "uexp differs only in the 4-byte name index")

# round trip through disk and reparse with the independent inspector
tmp = os.path.join(os.path.dirname(SRC), "resize_out"); shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
t.save(tmp + "/x.uasset", tmp + "/x.uexp")
t2 = C.BindingTable(open(tmp + "/x.uasset", "rb").read(), open(tmp + "/x.uexp", "rb").read())
ok(t2.target(Q) == new and {r: t2.target(r) for r in t2.rows if r != Q} == others, "reload: new target set, other 95 rows unchanged")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dt_inspect import DT
d = DT(tmp + "/x"); ok(dict(d.rows)[Q]["DataAsset"][1] == new and len(d.rows) == 96, "independent inspector agrees")

# second repoint (grow again), then back to an existing target
t2.set_target(Q, new.replace("bike103_0010.bike103_0010", "bike103_00020.bike103_00020"))   # longer again -> grows
ok(t2.ua._get("namecount") == 308 and t2.ua._get("total") == len(t2.ua.data), "second growth consistent")
t2.set_target(Q, old)
ok(t2.target(Q) == old, "back to original target reuses existing name (no growth)")
ok(t2.ua._get("namecount") == 308, "no extra names added")
# shared target + different length: other row must be untouched
R = [r for r in t.rows if r != Q and t.target(r) != old][0]
t2.set_target(R, "/Game/assets/graphics/vehicles/bikes/cat001/chassis/chassis103/customization_data/z.z")
ok(t2.target(Q) == old and t2.target(R).endswith("/z.z"), "only the chosen row changes")
print("RESIZE OK")
