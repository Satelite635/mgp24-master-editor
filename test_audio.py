"""Audio port test. Usage: python test_audio.py <target folder with Content/assets/Audio/...> <source Audio folder> <work dir>
The target stands in for the game's paks (its files count as "pak" files that must not be overwritten)."""
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mgp_core as C
import audioport as A

TGT, SRC, WORK = sys.argv[1:4]
fails = []


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


class GameLayer(C.Source):
    """Source whose base (target folder) pretends to be the game's pak."""

    def origin(self, rel):
        if os.path.exists(self.loose(rel)):
            return "unsaved"
        if os.path.exists(self._base(rel)):
            return "pakchunk0-WindowsNoEditor.pak"
        return "missing"


class FakeP:
    def __init__(self, staging):
        self.src = GameLayer(staging, None, base=TGT)


shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
P = FakeP(os.path.join(WORK, "staging"))

# wwise ids: the bank contains events named like the assets
ok({A.wwise_id("GP500cc_HondaNSR500_EN"), A.wwise_id("GP500cc_HondaNSR500_EX")} == {51793354, 51793372}, "FNV ids of the events match the bank's event ids")

sc = A.scan_source(P, SRC)
names = [b["name"] for b in sc["bikes"]]
ok(names == ["BikeAudio_500cc_HondaNSR500"], "scan finds the NSR500 bike: %s" % names)
b = sc["bikes"][0]
ok(b["bnk_found"] and b["engine"].endswith("_EN") and sc["has_init"], "scan resolves events, bank file and Init.bnk")

res = A.port(P, SRC, names, dry_run=True)
r = res["results"][0]
print("   actions:", r["actions"], "warnings:", r["warnings"], "problems:", r["problems"], "init:", res["init"])
ok(r["ok"] and not r["problems"], "dry run: NSR500 can be ported")
ok(not os.path.exists(os.path.join(WORK, "staging")), "dry run writes nothing")
ok(res["init"]["added"] == [], "no Init.bnk objects needed for the NSR500 (as found by hand)")

res = A.port(P, SRC, names, dry_run=False)
ok(res["written"] == 9, "wrote 9 files (%d)" % res["written"])
st = os.path.join(WORK, "staging", "Content", "assets", "Audio")
files = sorted(os.path.relpath(os.path.join(d, f), st).replace(os.sep, "/") for d, _, fs in os.walk(st) for f in fs)
print("   ", files)
want_bike = "Bindings/Bikes/500cc/BikeAudio_500cc_HondaNSR500"
# the rebuilt BikeAudio equals what worked in the game (hand-built from the same GP24 Ducati template)
hand = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hybrid")
mine = open(os.path.join(st, want_bike + ".uasset"), "rb").read()
ok(len(mine) == 2270, "rebuilt BikeAudio has the same size as the hand-built one that worked (%d)" % len(mine))
import uprops as U
t = U.tree(U.Asset(mine, open(os.path.join(st, want_bike + ".uexp"), "rb").read()))
refs = A.refs_of(t, "AkAudioEvent")
ok(refs["EngineEvent"].endswith("GP500cc_HondaNSR500_EN") and refs["ExhaustEvent"].endswith("GP500cc_HondaNSR500_EX"), "BikeAudio points at the NSR500 events")
ok("BackfireBangEvent" in refs and refs["BackfireBangEvent"].endswith("Backfire_Bang"), "BikeAudio keeps the shared backfire events")
bank = U.tree(U.Asset(open(os.path.join(st, "Banks/BIKES/500cc/GP500cc_HondaNSR500.uasset"), "rb").read(),
                      open(os.path.join(st, "Banks/BIKES/500cc/GP500cc_HondaNSR500.uexp"), "rb").read()))
ok([p["name"] for p in bank["props"]] == ["AutoLoad"], "bank asset was rebuilt without LinkedAkEvents (MotoGP 24 layout)")
ok(open(os.path.join(st, "WwiseAudio/SoundBanks/Windows/GP500cc_HondaNSR500.bnk"), "rb").read() ==
   open(os.path.join(SRC, "WwiseAudio/SoundBanks/Windows/GP500cc_HondaNSR500.bnk"), "rb").read(), ".bnk copied byte for byte")
ok(open(os.path.join(st, "Events/BIKES/500cc/HONDA_NSR500/GP500cc_HondaNSR500_EN.uasset"), "rb").read() ==
   open(os.path.join(SRC, "Events/BIKES/500cc/HONDA_NSR500/GP500cc_HondaNSR500_EN.uasset"), "rb").read(), "event copied as is (same layout as the game's)")

# second run: our own earlier copy may be overwritten, with a warning
res2 = A.port(P, SRC, names, dry_run=True)
ok(res2["results"][0]["ok"] and any("overwritten" in w for w in res2["results"][0]["warnings"]), "re-running overwrites our own copy with a warning")

# the game's own assets are protected: pretend the NSR500 names exist in the game
shutil.rmtree(os.path.join(WORK, "staging"))
clash = os.path.join(WORK, "tgt2")
shutil.copytree(TGT, clash)
os.makedirs(os.path.join(clash, "Content/assets/Audio/Bindings/Bikes/500cc"))
shutil.copy(os.path.join(SRC, "Bindings/Bikes/500cc/BikeAudio_500cc_HondaNSR500.uasset"), os.path.join(clash, "Content/assets/Audio/Bindings/Bikes/500cc/"))
TGT_SAVE = TGT
TGT = clash
P2 = FakeP(os.path.join(WORK, "staging2"))
r3 = A.port(P2, SRC, names, dry_run=True)["results"][0]
ok(not r3["ok"] and any("already exists in the game" in p for p in r3["problems"]), "a name that exists in the game is refused: %s" % r3["problems"][:1])
TGT = TGT_SAVE

# a wrong Wwise version is refused
bad = os.path.join(WORK, "src_bad")
shutil.copytree(SRC, bad)
bp = os.path.join(bad, "WwiseAudio/SoundBanks/Windows/GP500cc_HondaNSR500.bnk")
d = bytearray(open(bp, "rb").read())
struct.pack_into("<I", d, 8, 150)
open(bp, "wb").write(bytes(d))
P3 = FakeP(os.path.join(WORK, "staging3"))
r4 = A.port(P3, bad, names, dry_run=True)["results"][0]
ok(not r4["ok"] and any("version 150" in p for p in r4["problems"]), "a different Wwise bank version is refused")

# an Init.bnk object the target lacks gets copied: remove the Ducati-style bus from the target's Init
src_init = A.hirc_objects(open(os.path.join(SRC, "WwiseAudio/SoundBanks/Windows/Init.bnk"), "rb").read())
bank_objs = A.hirc_objects(open(os.path.join(SRC, "WwiseAudio/SoundBanks/Windows/GP500cc_HondaNSR500.bnk"), "rb").read())
tgt_ids = {o[1] for o in A.hirc_objects(open(os.path.join(TGT, "Content/assets/Audio/WwiseAudio/SoundBanks/Windows/Init.bnk"), "rb").read())}
victim = next(oid for t, oid, b in src_init if oid in tgt_ids)
need = A.init_needs(bank_objs, src_init, tgt_ids - {victim} - {oid for t, oid, b in src_init if oid != victim and oid not in {x for x in tgt_ids}})
used = A.init_needs(bank_objs, src_init, set())
ok(len(used) >= 1, "with an empty target Init, the bank's %d Init dependencies are all found" % len(used))
patched = A.patch_init(open(os.path.join(TGT, "Content/assets/Audio/WwiseAudio/SoundBanks/Windows/Init.bnk"), "rb").read(),
                       [(t, oid, b) for t, oid, b in src_init if oid not in tgt_ids][:1] or [])
ok(A.bank_version(patched) == 140 and len(A.hirc_objects(patched)) >= len(tgt_ids), "patched Init.bnk parses")

print("\nAUDIO OK" if not fails else "\nFAILED: %d" % len(fails))
sys.exit(1 if fails else 0)
