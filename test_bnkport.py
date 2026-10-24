"""GP26 -> GP24 bank import test. Usage: python test_bnkport.py <GP24 bank> <GP26 bank of the same bike> [expected result bank]
Samples: project files gp26-audio-test/ (D_full_port/MotoGP_Ducati.bnk is the result tested in game)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audioport as A
import bnkport as B

TGT, SRC = sys.argv[1:3]
fails = []


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


tgt, src = open(TGT, "rb").read(), open(SRC, "rb").read()
out, r = B.port_bank(tgt, src)
print(r)
ok(out is not None and not r["problems"], "bank ported")
ok(A.bank_version(out) == A.bank_version(tgt), "keeps this game's Wwise version")
om, _ = B.media(A.sections(out))
ok(all(B.adm_version(v) == 6 for v in om.values() if v[:4] == b"ADM3"), "engine models are ADM3 v6")
ok(not any(B.has_hash(v) for v in om.values() if v[:4] == b"RIFF"), "no .wem keeps a hash chunk")
ok(len(A.hirc_objects(out)) == len(A.hirc_objects(tgt)), "same HIRC objects")
if len(sys.argv) > 3:
    ok(out == open(sys.argv[3], "rb").read(), "byte-identical to the expected bank")
print("FAILED: %d" % len(fails) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
