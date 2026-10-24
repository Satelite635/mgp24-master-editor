"""Offline test of the MotoGP 25 zen/IoStore code: python test_zen.py <folder with GP25 DT_Bike*.uasset / projector*.uasset> [retoc mod .utoc]
Bike tables must parse, rebuild byte-identical, repoint and re-parse; with a retoc-made .utoc/.ucas, rewriting its
packages with mgp_iostore.write_container must give the identical .utoc and .ucas."""
import glob, os, sys, tempfile

import mgp_iostore as I
import mgp_zen as Z
import projfile as PJ

d = sys.argv[1]
for f in sorted(glob.glob(os.path.join(d, "DT_Bike*.uasset"))):
    data = open(f, "rb").read()
    t = Z.ZenBindingTable(data)
    assert t.to_bytes() == data, f
    k = sorted(t.rows)[0]
    t.set_target(k, "/Game/test/new_pkg.new_pkg")
    assert Z.ZenBindingTable(t.to_bytes()).target(k) == "/Game/test/new_pkg.new_pkg"
    print("ok", os.path.basename(f), len(t.rows), "rows")
for f in sorted(glob.glob(os.path.join(d, "[Pp]rojector*.uasset"))):   # projector files: parse, no-op patch identical, edit re-parses
    data = open(f, "rb").read()
    a, ps = PJ.parse(data, None)
    PJ.patch(a, ps, {p["tag"]: p for p in ps})
    assert a.to_bytes() == data, f
    v = dict(ps[0], loc=[1.0, 2.0, 3.0])
    PJ.patch(a, ps, {ps[0]["tag"]: v})
    assert PJ.parse(a.to_bytes(), None)[1][0]["loc"] == [1.0, 2.0, 3.0] and len(a.to_bytes()) == len(data)
    print("ok", os.path.basename(f), [p["tag"] for p in ps])
for f in glob.glob(os.path.join(d, "RidingStyle_DT.uasset")):        # riding style: identical rebuild, edit + add row re-parse
    data = open(f, "rb").read()
    t = Z.ZenStyleTable(data)
    assert t.to_bytes() == data, f
    t.set_values("Balanced", {"LegOutType": 0.5, "StartLeg": 0})
    t.add_row("MotoGP_Test-Rider", "Balanced")
    t2 = Z.ZenStyleTable(t.to_bytes())
    assert t2.values("MotoGP_Test-Rider") == t2.values("Balanced") and t2.values("Balanced")["LegOutType"] == 0.5
    print("ok RidingStyle_DT", len(t.rows) - 1, "rows")
if len(sys.argv) > 2:
    src = I.Toc(sys.argv[2])
    pk = []
    for low, (full, e) in sorted(src.files.items(), key=lambda kv: kv[1][1].idx):
        data = src.read_index(e.idx)
        pk.append((full, data, "/Game/" + full.split("/Content/", 1)[1][:-7], Z.ZenPackage(data).imported_package_ids()))
    out = os.path.join(tempfile.mkdtemp(), "x.utoc")
    I.write_container(out, pk, container_id=src.container_id)
    assert open(out, "rb").read() == open(sys.argv[2], "rb").read(), "utoc differs"
    assert open(out[:-5] + ".ucas", "rb").read() == open(src.ucas, "rb").read(), "ucas differs"
    print("ok container rebuild identical:", os.path.basename(sys.argv[2]))
