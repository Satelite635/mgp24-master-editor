"""Pak writer test. Usage: python test_pakwrite.py <work dir>"""
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mgp_pak as K, mgp_pakwrite as W
d = sys.argv[1]
shutil.rmtree(d, ignore_errors=True); os.makedirs(d + "/Content/a/b"); os.makedirs(d + "/_mgp_backup")
big = os.urandom(300000)
open(d + "/Content/a/b/x.uasset", "wb").write(big); open(d + "/Content/y.bnk", "wb").write(b"z" * 7)
open(d + "/Content/db.sqlite-wal", "wb").write(b"x"); open(d + "/_mgp_backup/n.uasset", "wb").write(b"x")
n, size = W.write_pak(d + "/t_P.pak", W.collect(d))
r = K.PakReader(d + "/t_P.pak", None)
ok = n == 2 and sorted(r.files) == ["motogp24/content/a/b/x.uasset", "motogp24/content/y.bnk"] and r.version == 8
ok = ok and r.read("motogp24/content/a/b/x.uasset") == big and r.read("motogp24/content/y.bnk") == b"z" * 7
os.makedirs(d + "/Paks"); shutil.copy(d + "/t_P.pak", d + "/Paks/Mod_P.pak")
s = K.PakSet(d + "/Paks", "00" * 32)
ok = ok and s.exists("Content/y.bnk") and s.read("Content/y.bnk") == b"z" * 7
held = [l for l in (os.readlink("/proc/self/fd/" + x) for x in os.listdir("/proc/self/fd") if os.path.exists("/proc/self/fd/" + x)) if l.endswith(".pak")] if os.path.isdir("/proc/self/fd") else []
ok = ok and not held
print("open pak handles:", held)
print("PAKWRITE OK" if ok else "PAKWRITE FAILED"); sys.exit(0 if ok else 1)
