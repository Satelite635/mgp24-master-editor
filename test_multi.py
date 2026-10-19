import os, shutil, sys, hashlib, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mgp_core as C
BIND, BASE, WORK = sys.argv[1], sys.argv[2], sys.argv[3]
shutil.rmtree(WORK, ignore_errors=True); shutil.copytree(BASE, WORK)
for d, _, fs in os.walk(BIND):
    for f in fs:
        dst = os.path.join(WORK, os.path.relpath(os.path.join(d, f), BIND)); os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(d, f), dst)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
P = C.Project(WORK)
names = P.table_names(); print(len(names), "binding tables found")
ok(len(names) >= 80, "all binding tables discovered")
Q, R = "MotoGP_Fabio-Quartararo", "MotoGP_Alex-Rins"
pb = P.pilot_bindings(Q); cats = collections.Counter(c for _, c, _ in pb)
print(len(pb), "tables with a Quartararo row;", dict(cats))
ok(cats["helmet"] == 3 and cats["suit"] >= 8 and cats["gloves"] == 1 and cats["boots"] == 1 and cats["buttpatch"] == 1, "gear categories detected")
before = {rel: {k: t.target(k) for k in t.rows} for rel in names for t in [P.table(rel)]}
changes = P.copy_look(Q, R, {"helmet", "gloves"})
print([ (r.rsplit('/',1)[1], o[-30:], n[-30:]) for r,o,n in changes][:3])
ok(len(changes) >= 4, "%d tables changed for helmet+gloves" % len(changes))
P2 = C.Project(WORK)                                         # fresh reload from disk
for rel in names:
    t = P2.table(rel)
    for k in t.rows:
        exp = before[rel][k]
        if k == Q and C.category(rel) in ("helmet", "gloves") and R in t.rows:
            exp = before[rel][R]
        ok(t.target(k) == exp, "") if False else None
        if t.target(k) != exp: ok(False, "unexpected change %s %s" % (rel, k))
ok(True, "only Quartararo's helmet/gloves rows changed; every other row in all tables identical")
ok(all(P2.table(rel).target(Q) == P2.table(rel).target(R) for rel, c, _ in P2.pilot_bindings(Q) if c in ("helmet", "gloves") and R in P2.table(rel).rows), "Quartararo now shares Rins' helmet+gloves")
# the uexp of a shared-route repoint differs in 4 bytes only
rel = [r for r, c, _ in pb if c == "gloves"][0]
a = open(os.path.join(P.backup_dir, rel.replace("/", os.sep) + ".uexp"), "rb").read(); b = open(P.src.loose(rel) + ".uexp", "rb").read()
ok(len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 4, "uexp changes by <=4 bytes")
P2.repoint_in(pb[0][0], Q, "/Game/x/y.y")
ok(C.Project(WORK).table(pb[0][0]).target(Q) == "/Game/x/y.y", "arbitrary-length path accepted")
try:
    P2.repoint_in(pb[0][0], Q, "No_Such_Rider"); ok(False, "unknown donor")
except C.MgpError as e:
    ok(True, "unknown donor refused: " + str(e)[:50])
print("MULTI OK")
