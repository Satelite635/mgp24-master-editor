import os, shutil, struct, sys, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mgp_core as C
BIND, BASE, WORK = sys.argv[1:4]
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
def fresh():
    shutil.rmtree(WORK, ignore_errors=True); shutil.copytree(BASE, WORK)
    shutil.copytree(os.path.join(BIND, "Content"), os.path.join(WORK, "Content"), dirs_exist_ok=True)
    return C.Project(WORK)
h = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
Q = "MotoGP_Fabio-Quartararo"; T = "Content/assets/graphics/bindings/Vehicles/Official/DT_BikeOfficial"
D = "/Game/assets/graphics/vehicles/bikes/cat001/chassis/chassis103/customization_data/"
P = fresh()
st = P.target_status(T, Q, D + "bike103_0900.bike103_001")
ok(st["exists"] is False, "missing target detected")
ok(P.target_status(T, Q, D + "bike103_001")["exists"] and P.target_status(T, Q, "MotoGP_Alex-Rins")["donor"], "existing package / donor row detected")
orig_asset = P.src.loose("Content/assets/graphics/vehicles/bikes/cat001/chassis/chassis103/customization_data/bike103_001")
ua0 = C.UAsset(open(orig_asset + ".uasset", "rb").read()); h0 = h(orig_asset + ".uasset")
for new, label in ((D + "bike103_0900", "longer"), (D + "b1", "shorter")):
    P = fresh(); ua0 = C.UAsset(open(orig_asset + ".uasset", "rb").read())
    r = P.replace_with_copy(T, Q, new, "asset")
    new_stem = P.src.loose("Content/" + new[len("/Game/"):])
    ua1 = C.UAsset(open(new_stem + ".uasset", "rb").read())
    ok(r["target"] == new + ".bike103_001", "%s name: row points at new package + the asset's own object name" % label)
    t0, t1 = ua0.texts(), ua1.texts()
    old_pkg = D + "bike103_001"
    ok([x for x in t0 if x != old_pkg] == [x for x in t1 if x != new] and t1[t0.index(old_pkg)] == new, "%s name: only the package name changed" % label)
    delta = len(ua1.data) - len(ua0.data); ok(delta == len(new) - len(old_pkg), "%s name: size changed by %+d" % (label, delta))
    ok(ua1._get("total") == len(ua1.data), "total header size consistent")
    eo = ua1._get("exportoff"); ss, so = struct.unpack_from("<qq", ua1.data, eo + 28)
    ok(so == len(ua1.data), "export SerialOffset == header size")
    for k in ("importoff", "exportoff", "dependsoff", "assetregoff", "preloadoff"):
        ok(ua1._get(k) == ua0._get(k) + delta, "  %s shifted" % k) if False else None
    ok(all(ua1._get(k) == ua0._get(k) + delta for k in ("importoff", "exportoff", "dependsoff", "assetregoff", "preloadoff")), "all section offsets shifted by the same amount")
    tail0, tail1 = bytes(ua0.data[ua0._get("importoff"):]), bytes(ua1.data[ua1._get("importoff"):])
    e0 = bytearray(tail0); e1 = bytearray(tail1)
    q = ua0._get("exportoff") - ua0._get("importoff") + 36; struct.pack_into("<q", e1, q, struct.unpack_from("<q", e1, q)[0] - delta)
    ok(bytes(e0) == bytes(e1), "everything after the name table identical (except SerialOffset)")
    ok(open(new_stem + ".uexp", "rb").read() == open(orig_asset + ".uexp", "rb").read(), ".uexp identical")
    ok(h(orig_asset + ".uasset") == h0, "original asset untouched")
    ok(C.Project(WORK).dt.target(Q) == r["target"], "binding saved")
    ok(P.object_path(new) == new + ".bike103_001", "new asset resolves like a normal one")
    try:
        P.replace_with_copy(T, Q, new, "asset"); ok(False, "duplicate refused")
    except C.MgpError as e:
        ok("already exists" in str(e), "copying onto an existing asset refused")

# full set: must equal the dedicated bike clone, byte for byte
P = fresh(); r = P.replace_with_copy(T, Q, D + "bike103_905", "set")
P2 = fresh(); P2.clone_for_pilot(Q, "905")
rels = lambda root: {os.path.relpath(os.path.join(d, f), root): h(os.path.join(d, f)) for d, _, fs in os.walk(root) for f in fs if "905" in f}
a, b = rels(P.root), rels(P2.root)
ok(len(a) == 96 and a == b, "full-set copy == bike clone (%d files, identical bytes)" % len(a))
ok(P.dt.target(Q) == D + "bike103_905.bike103_905", "row points at the copied set")
for bad in (D + "bike103_90", D[:-len("customization_data/")] + "other/bike103_905"):
    try:
        fresh().replace_with_copy(T, Q, bad, "set"); ok(False, "bad set copy accepted")
    except C.MgpError as e:
        ok(True, "set copy refused: " + str(e)[:60])
ok(C.Project._infer_tag("helmet_109", "helmet_119") == ("109", "119") and C.Project._infer_tag("bike103_001", "bike103_905") == ("001", "905"), "variant number inferred as a whole digit run")
print("DUP OK")
