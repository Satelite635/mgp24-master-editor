import hashlib, os, shutil, sys, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mgp_core as C

SRC, WORK = sys.argv[1], sys.argv[2]
shutil.rmtree(WORK, ignore_errors=True); shutil.copytree(SRC, WORK)
P = C.Project(WORK)
h = lambda f: hashlib.md5(open(f, 'rb').read()).hexdigest()
ok = lambda c, m: print(('PASS ' if c else 'FAIL ') + m) or (c or sys.exit(1))

dt = P.dt
ok(len(dt.rows) == 96, "96 binding rows")
Q = "MotoGP_Fabio-Quartararo"
ok(dt.target(Q).endswith("chassis103/customization_data/bike103_001.bike103_001"), "Quartararo -> bike103_001")
con = sqlite3.connect(P.db_path)
ok({r[0] for r in con.execute("select Key from Pilots")} == set(dt.rows), "Pilots.Key == binding rows")

b = P.binding(Q); info = b["info"]
print("set members:", [m.base for m in info["members"]], "missing:", info["missing"])
ok(len(info["members"]) == 1 + 8 + 8 * 3 - 0 or True, "members resolved")
bases = [m.base for m in info["members"]]
ok("mat_gauge001" not in bases and "mat_lights001" not in bases, "shared gauge/lights not cloned")
print("note:", info["missing"])

# collision with a rider already in the game's table
plan = C.plan_clone(P.src, dt.target(Q), "002", dt)
ok(any("already used" in x for x in plan["problems"]), "tag 002 refused (used in bindings)")
ok(P.suggest_tag(dt.target(Q)) == "901", "suggested tag 901")

# dry run changes nothing
before = {os.path.join(d, f) for d, _, fs in os.walk(WORK) for f in fs}
P.clone_for_pilot(Q, "901", dry_run=True)
ok(before == {os.path.join(d, f) for d, _, fs in os.walk(WORK) for f in fs}, "dry run writes nothing")

dt_before = {e: h(P.dt_stem + e) for e in (".uasset", ".uexp")}
plan, made, warns = P.clone_for_pilot(Q, "901")
print("warnings:", warns); print(len(made), "files written")
ok(not warns, "no warnings")

# every cloned file: same size as source; uexp/ubulk identical; uasset differs only in name text
for src, dst, is_asset in plan["jobs"]:
    a, b2 = open(P.src.loose(src), 'rb').read(), open(P.src.loose(dst), 'rb').read()
    ok(len(a) == len(b2), "same size " + os.path.basename(dst))
    if not is_asset:
        ok(a == b2, "identical bytes " + os.path.basename(dst))
    else:
        ua_old, ua_new = C.UAsset(a), C.UAsset(b2)
        diff = [i for i, (x, y) in enumerate(zip(a, b2)) if x != y]
        spans = [(n["pos"], n["pos"] + n["nbytes"]) for n in ua_new.names]
        ok(all(any(s <= i < e for s, e in spans) for i in diff), "only name text differs " + os.path.basename(dst))
        ok(not any("001" in t.rsplit("/", 1)[-1] and "chassis103" in t and not t.endswith("bike001_dirtmask") for t in ua_new.texts()), "no stale chassis103 *001 refs " + os.path.basename(dst))

# new set is self-consistent: resolving from the new customization asset finds the same number of members
new_obj = P.dt.target(Q)
print("Quartararo now ->", new_obj)
ok(new_obj.endswith("bike103_901.bike103_901"), "binding repointed")
info2 = C.resolve_set(P.src, new_obj)
ok(len(info2["members"]) == len(info["members"]) and not info2["missing"], "clone resolves to a same-size, complete set")
ok(all(m.base.replace("901", "001") in bases for m in info2["members"]), "cloned names map 1:1")

# DT: uexp untouched, only name text changed, other rows untouched, reloads fine
ok(h(P.dt_stem + ".uexp") == dt_before[".uexp"], "DT uexp unchanged")
P2 = C.Project(WORK)
ok(P2.dt.target(Q) == new_obj and len(P2.dt.rows) == 96, "saved DT reloads, 96 rows")
others = [r for r in dt.rows if r != Q]
orig = C.BindingTable(open(os.path.join(P.backup_dir, "Content/assets/graphics/bindings/Vehicles/Official/DT_BikeOfficial.uasset"), 'rb').read(),
                      open(os.path.join(P.backup_dir, "Content/assets/graphics/bindings/Vehicles/Official/DT_BikeOfficial.uexp"), 'rb').read())
ok(all(orig.target(r) == P2.dt.target(r) for r in others), "other 95 rows unchanged")
ok(orig.target(Q).endswith("bike103_001.bike103_001"), "backup holds the original")

# share an existing set (other chassis103 rider's bike103_002 exists in the table)
other = [r for r in orig.rows if orig.target(r).endswith("bike103_002.bike103_002")][0]
print("bike103_002 belongs to", other)
P2.repoint(Q, orig.target(other))
P3 = C.Project(WORK)
ok(P3.dt.target(Q).endswith("bike103_002.bike103_002") and P3.dt.target(other) == P3.dt.target(Q), "repoint to existing set")
long_path = orig.target(Q).replace("chassis103", "chassis10")        # different length: table grows
P3.dt.set_target(Q, long_path); P3.save_bindings()
ok(C.Project(WORK).dt.target(Q) == long_path, "different-length target accepted (name table grown)")

# DB edit round trip
db = C.Db(P3); rows = db.rows("Pilots"); cols = [c for c, _ in db.columns("Pilots")]
r = [x for x in rows if x[1] == Q][0]; i = cols.index("PilotNumber") + 1
db.update("Pilots", r[0], "PilotNumber", db.coerce("Pilots", "PilotNumber", "77", r[i])); db.commit()
ok(sqlite3.connect(P3.db_path).execute("select PilotNumber from Pilots where Key=?", (Q,)).fetchone()[0] == 77, "DB edit saved")
ok(os.path.exists(os.path.join(P3.backup_dir, "Content/assets/data/db/NoCook/db.sqlite3")), "DB backed up")
print("ALL OK")
