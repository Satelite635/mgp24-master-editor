"""Teams view: suits for custom riders (TeamSuits SU_ rows). Synthetic tables + DB, no game data needed."""
import sqlite3
import mgp_core as C
import webui as W

ok_n = 0
def ok(c, m):
    global ok_n
    if not c:
        raise SystemExit("FAIL: " + m)
    ok_n += 1; print("ok", m)

class T:
    def __init__(self, rows): self.rows = rows
    def target(self, k): return self.rows[k]

class Src:
    def exists(self, rel): return "missing" not in rel
    def origin(self, rel): return "pak"
    def find(self, *a): return []

class P:
    pilot_bindings, group_for = C.Project.pilot_bindings, C.Project.group_for
    def __init__(self, tabs): self.tabs, self.src, self.dt = tabs, Src(), T({})
    def table_names(self): return list(self.tabs)
    def table(self, rel):
        t = self.tabs[rel]
        if isinstance(t, Exception): raise t
        return t

SUN = "Content/assets/graphics/bindings/characters/Rider/OfficialTeams/DT_SUIT_MATERIAL_SUN_Teams"
MESH = "Content/assets/graphics/bindings/characters/Rider/OfficialTeams/DT_SUIT_MESH_MALE_Teams"
BAD = "Content/assets/graphics/bindings/characters/Rider/OfficialTeams/DT_SUIT_MATERIAL_RAIN_Teams"
BIKE = "Content/assets/graphics/bindings/vehicles/OfficialTeams/DT_BikeTeams"
k1, k2, k3 = ("SU_MotoGP_Alpinestars_GP-Tech-V2-Leather-Suit_KTM-Tech3", "SU_MotoGP_Unbranded_Custom_KTM-Tech3",
              "SU_Moto3_Unbranded_Custom_KTM-Tech3")
tabs = {SUN: T({k1: "/Game/a/sun1.sun1", k2: "/Game/a/missing.missing", k3: "/Game/a/m3.m3"}),
        MESH: T({k1: "/Game/a/mesh1.mesh1", "SU_MotoGP_Revit_Revit-GP_KTM-Tech3": "None"}),
        BAD: ValueError("unexpected row layout"),
        BIKE: T({"MotoGP_KTM-Tech3": "/Game/b/bike.bike"})}

db = sqlite3.connect(":memory:")
db.execute("create table TeamSuits (Key, Team_Key, SuitModels_Key, UI_Index)")
db.executemany("insert into TeamSuits values (?,?,?,0)", [(k1, "MotoGP_KTM-Tech3", "GP-Tech-V2-Leather-Suit"),
               (k2, "MotoGP_KTM-Tech3", "Custom"), ("SU_MotoGP_iXon_iXon-GP_KTM-Tech3", "MotoGP_KTM-Tech3", "iXon-GP"),
               (k3, "Moto3_KTM-Tech3", "Custom")])

class S:
    P = P(tabs)
    def need(self): return self.P
    def get_db(self):
        class D: con = db
        return D()

api = W.make_api(S())
r = api[("GET", "/api/teamsuits")]({"key": ["MotoGP_KTM-Tech3"]}, {})
keys = [s["key"] for s in r["suits"]]
ok(k1 in keys and k2 in keys, "DB suits with binding rows listed")
ok(k3 not in keys, "same team name in another class is not mixed in")
ok("SU_MotoGP_Revit_Revit-GP_KTM-Tech3" in keys, "name-pattern fallback finds a suit the DB does not list")
ok(keys.index(k1) < keys.index("SU_MotoGP_Revit_Revit-GP_KTM-Tech3"), "DB suits first")
s1 = r["suits"][keys.index(k1)]
ok(sorted(x["table"] for x in s1["rows"]) == ["DT_SUIT_MATERIAL_SUN_Teams", "DT_SUIT_MESH_MALE_Teams"], "all suit tables of one suit")
ok(all(x["key"] == k1 for x in s1["rows"]), "rows carry their own key")
s2 = r["suits"][keys.index(k2)]
ok(s2["model"] == "Custom" and not s2["rows"][0]["exists"], "missing asset flagged")
ok(r["missing"] == ["SU_MotoGP_iXon_iXon-GP_KTM-Tech3"], "DB suit with no rows reported")
ok(len(r["unreadable"]) == 1 and "DT_SUIT_MATERIAL_RAIN_Teams" in r["unreadable"][0], "unreadable suit table reported")
b = api[("GET", "/api/bindings")]({"key": ["MotoGP_KTM-Tech3"], "group": ["teams"]}, {})
ok(b and b[0]["key"] == "MotoGP_KTM-Tech3", "bindings rows carry key")

class S2(S):
    def get_db(self): raise C.MgpError("no db")
r = W.make_api(S2())[("GET", "/api/teamsuits")]({"key": ["MotoGP_KTM-Tech3"]}, {})
ok(r["db_note"] and len(r["suits"]) == 3, "works without the database (name pattern only)")
print("all %d ok" % ok_n)
