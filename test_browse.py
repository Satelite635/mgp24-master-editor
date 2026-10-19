"""Browser / localization API test. Usage: python test_browse.py <loose project folder (has Content/...)> <work dir>"""
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mgp_core as C
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
S = W.State(lambda: cfg, lambda c: cfg.update(c), "")
S.open(WORK, None, "", True)
R = W.make_api(S)
get = lambda p, **q: R[("GET", p)]({k: [str(v)] for k, v in q.items()}, {})
post = lambda p, b: R[("POST", p)]({}, b)

top = get("/api/browse", dir="Content")
ok(top["dirs"] and top["total_files"] > 0, "root lists folders (%d files)" % top["total_files"])
# walk down to the first folder holding an asset
d, found = "Content", None
for _ in range(12):
    r = get("/api/browse", dir=d)
    assets = [i for i in r["items"] if i["asset"]]
    if assets:
        found = (d, assets[0]); break
    if not r["dirs"]:
        break
    d += "/" + r["dirs"][0]["name"]
ok(found is not None, "found an asset folder: %s" % (found and found[0]))
d, it = found
ok(it["pkg"].startswith("/Game/") and ".uasset" in "".join(it["exts"] + [".uasset"]) and it["origin"], "asset row has pkg and origin: %s" % it["pkg"])
s = get("/api/browse", dir="Content", q=it["name"][:8])
ok(any(x["base"] == it["base"] for x in s["items"]), "search finds it")
if "ubulk" not in " ".join(it["exts"]):
    c = post("/api/browse/clone", dict(pkg=it["pkg"], name=it["name"] + "_zz"))
    ok(os.path.exists(os.path.join(S.P.root, *(C.game_to_rel(c["new"]) + ".uasset").split("/"))), "clone creates the asset: %s" % c["new"])
    try:
        post("/api/browse/clone", dict(pkg=it["pkg"], name=it["name"] + "_zz")); ok(False, "second clone must fail")
    except C.MgpError:
        ok(True, "cloning onto an existing name is refused")
e = post("/api/browse/extract", dict(bases=["Content/Localization/none"]))
ok(e["files"] == [], "extracting nothing real does nothing")
try:
    post("/api/browse/extract", dict(bases=["../x"])); ok(False, "bad path must fail")
except C.MgpError:
    ok(True, "bad extract path refused")
print("\nBROWSE OK" if not fails else "\nFAILED %d" % len(fails)); sys.exit(1 if fails else 0)
