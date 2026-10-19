"""Localization test. Usage: python test_locres.py <work dir>   (synthetic files: no real .locres needed)"""
import os, shutil, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mgp_locres as L
import mgp_core as C


def fs(t):
    try:
        r = t.encode("ascii"); return struct.pack("<i", len(r) + 1) + r + b"\0"
    except UnicodeEncodeError:
        r = t.encode("utf-16le") + b"\0\0"; return struct.pack("<i", -(len(r) // 2)) + r


def build(v):
    strs = ["Hello", "Rider", "Shared", "日本語"]
    ents = [("Menu", "A", 0), ("Menu", "B", 2), ("Menu", "C", 2), ("Race", "D", 3), ("Race", "E", 1)]
    ns = {}
    for n, k, i in ents:
        ns.setdefault(n, []).append((k, i))
    body = struct.pack("<I", len(ents)) if v >= 2 else b""
    body += struct.pack("<I", len(ns))
    for n, ks in ns.items():
        body += (struct.pack("<I", 123) if v >= 2 else b"") + fs(n) + struct.pack("<I", len(ks))
        for k, i in ks:
            body += (struct.pack("<I", 456) if v >= 2 else b"") + fs(k) + struct.pack("<I", 789) + struct.pack("<i", i)
    cnt = [0] * 4
    for _, _, i in ents:
        cnt[i] += 1
    arr = struct.pack("<i", 4) + b"".join(fs(s) + (struct.pack("<i", cnt[j]) if v >= 2 else b"") for j, s in enumerate(strs))
    head = L.MAGIC + bytes([v])
    return head + struct.pack("<q", len(head) + 8 + len(body)) + body + arr


for v in (1, 2, 3):
    d = build(v); l = L.Locres(d)
    assert l.to_bytes() == d, ("roundtrip", v)
    assert l.count() == 5
    assert l.set_text("Menu", "B", "Changed")
    assert l.arr[l.find("Menu", "C")["idx"]][0][0] == "Shared"
    l.set_text("Race", "E", "Ünïcode ✓")
    t = {(n, k): x for _, _, n, k, x in L.Locres(l.to_bytes()).entries()}
    assert t[("Menu", "B")] == "Changed" and t[("Menu", "C")] == "Shared" and t[("Race", "E")] == "Ünïcode ✓" and t[("Race", "D")] == "日本語"
for bad in (b"", b"x" * 40, build(2)[:-9]):
    try:
        L.Locres(bad); raise SystemExit("accepted garbage")
    except L.LocresError:
        pass
# through the editor's file layers
W = sys.argv[1]
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W + "/Content/Localization/Game/en")
open(W + "/Content/Localization/Game/en/Game.locres", "wb").write(build(3))
src = C.Source(W + "/_staging", None, base=W)
rel = "Content/Localization/Game/en/Game.locres"
assert rel in src.find("Content", ".locres")
print("LOCRES OK")
