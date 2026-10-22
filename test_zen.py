"""Offline test of the MotoGP 25 zen/IoStore code: python test_zen.py <folder with GP25 DT_Bike*.uasset> [retoc mod .utoc]
Bike tables must parse, rebuild byte-identical, repoint and re-parse; with a retoc-made .utoc/.ucas, rewriting its
packages with mgp_iostore.write_container must give the identical .utoc and .ucas."""
import glob, os, sys, tempfile

import mgp_iostore as I
import mgp_zen as Z

d = sys.argv[1]
for f in sorted(glob.glob(os.path.join(d, "DT_Bike*.uasset"))):
    data = open(f, "rb").read()
    t = Z.ZenBindingTable(data)
    assert t.to_bytes() == data, f
    k = sorted(t.rows)[0]
    t.set_target(k, "/Game/test/new_pkg.new_pkg")
    assert Z.ZenBindingTable(t.to_bytes()).target(k) == "/Game/test/new_pkg.new_pkg"
    print("ok", os.path.basename(f), len(t.rows), "rows")
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
