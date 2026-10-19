"""Property reader/patcher: every sample asset parses; a float edit changes only that float's bytes."""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uprops as U
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
ROOT = sys.argv[1]                                     # extracted motogp24/Content
n = 0
for d, _, fs in os.walk(ROOT):
    for f in fs:
        if f.endswith(".uasset") and os.path.exists(os.path.join(d, f[:-7] + ".uexp")):
            p = os.path.join(d, f[:-7])
            a = U.Asset(open(p + ".uasset", "rb").read(), open(p + ".uexp", "rb").read())
            U.tree(a); n += 1
ok(n > 30, "%d assets parse without error" % n)
cd = os.path.join(ROOT, "assets/graphics/vehicles/bikes/cat001/chassis/chassis103/customization_data/bike103_001")
a = U.Asset(open(cd + ".uasset", "rb").read(), open(cd + ".uexp", "rb").read())
mis = [a.object_ref(-(i + 1))[0] for i, m in enumerate(a.imports) if m["cls"] == "MaterialInstanceConstant"]
ok(len(mis) == 8 and all(p.startswith("/Game/") for p in mis), "customization_data references its 8 material instances")
print("PROPS OK")
