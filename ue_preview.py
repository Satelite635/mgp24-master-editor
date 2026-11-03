"""Unreal Editor preview of number projectors (v114).

The editor writes two scripts into <mod folder>/_mgp_ue_preview/ for one projector file:
  mgp_ue_load.py  run in Unreal (File > Execute Python Script) with the bike's Skeletal Mesh selected in the
                  Content Browser: places the bike in the level and one decal per projector, attached to bone
                  BONE_CHASSIS (else VEHICLE_BASE), at the projector's position/rotation/scale.
  mgp_ue_send.py  run after moving/rotating/scaling the decals: sends their values back to the editor
                  (same as typing them on the rider page and pressing Apply), the tool must be running.
Facts: projector position/rotation are in the bike mesh's space (a socket with the same values sits where the
number shows in game, Faizal 2026-11-03). Guesses: the decal size that matches projector scale 1 (DECAL_SIZE,
calibrate once against the game) and that the game projects along the decal's X like a UE decal.
"""
import json
import os
import re

TEMPLATE = r'''# MGP24 Master Editor - number projector preview in Unreal (generated, mode: @MODE@).
# Load: select the bike's Skeletal Mesh in the Content Browser, then File > Execute Python Script > mgp_ue_load.py.
# Send: move/rotate/scale the MGP_<tag> decals (keep them attached to the bike), then run mgp_ue_send.py.
# The editor must be running (same run that made this file; after restarting it, press "Preview in UE" again).
import json, os, urllib.error, urllib.request
import unreal

MODE = "@MODE@"
URL = "@URL@"
TOKEN = "@TOKEN@"
PKG = "@PKG@"
PROJECTORS = json.loads(r"""@PROJECTORS@""")
# --- you may change these two; the editor keeps them when it writes the scripts again
DECAL_SIZE = @DECAL_SIZE@   # UE decal box size at projector scale 1 (a guess: calibrate once against the game)
NUMBER_PNG = r"@NUMBER_PNG@"   # number image for the preview; empty = number.png next to this script, else a checker
# ---
BONES = ["BONE_CHASSIS", "VEHICLE_BASE"]   # first one the mesh has (his socket sat on BONE_CHASSIS and matched the game)
FOLDER = "/Game/MGP_Preview"
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ""


def log(msg):
    unreal.log_warning("[MGP] " + msg)


def level_actors():
    try:
        return unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    except Exception:
        return unreal.EditorLevelLibrary.get_all_level_actors()


def spawn(cls):
    try:
        return unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(cls, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    except Exception:
        return unreal.EditorLevelLibrary.spawn_actor_from_class(cls, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))


def tagged(t):
    return [a for a in level_actors() if t in [str(x) for x in a.tags]]


def number_texture():
    png = NUMBER_PNG or (os.path.join(HERE, "number.png") if HERE else "")
    if png and os.path.isfile(png):
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", png)
        task.set_editor_property("destination_path", FOLDER)
        task.set_editor_property("destination_name", "T_MGP_Number")
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", False)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        tex = unreal.load_asset(FOLDER + "/T_MGP_Number")
        if tex:
            return tex
        log("could not import " + png + ", using a checker texture")
    elif png:
        log("number image not found: " + png + ", using a checker texture")
    return unreal.load_asset("/Engine/EngineResources/DefaultTexture")


def decal_material():
    at, mel = unreal.AssetToolsHelpers.get_asset_tools(), unreal.MaterialEditingLibrary
    mat = unreal.load_asset(FOLDER + "/M_MGP_Number")
    if not mat:
        mat = at.create_asset("M_MGP_Number", FOLDER, unreal.Material, unreal.MaterialFactoryNew())
        mat.set_editor_property("material_domain", unreal.MaterialDomain.MD_DEFERRED_DECAL)
        mat.set_editor_property("decal_blend_mode", unreal.DecalBlendMode.DBM_TRANSLUCENT)
        tp = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -400, 0)
        tp.set_editor_property("parameter_name", "Number")
        tp.set_editor_property("texture", unreal.load_asset("/Engine/EngineResources/DefaultTexture"))
        mel.connect_material_property(tp, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)
        mel.connect_material_property(tp, "A", unreal.MaterialProperty.MP_OPACITY)
        mel.recompile_material(mat)
    mi = unreal.load_asset(FOLDER + "/MI_MGP_Number")
    if not mi:
        mi = at.create_asset("MI_MGP_Number", FOLDER, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        mel.set_material_instance_parent(mi, mat)
    mel.set_material_instance_texture_parameter_value(mi, "Number", number_texture())
    return mi


def set_mesh(comp, mesh):
    try:
        comp.set_skeletal_mesh(mesh)
    except Exception:
        comp.set_skinned_asset_and_update(mesh)          # UE 5.1+


def load():
    sel = [a for a in unreal.EditorUtilityLibrary.get_selected_assets() if isinstance(a, unreal.SkeletalMesh)]
    bikes = tagged("MGP_BIKE")
    bike = bikes[0] if bikes else None
    if sel:
        if not bike:
            bike = spawn(unreal.SkeletalMeshActor)
            bike.set_actor_label("MGP_Bike")
            bike.tags = ["MGP_BIKE"]
            try:
                bike.set_folder_path("MGP_Preview")
            except Exception:
                pass
        set_mesh(bike.skeletal_mesh_component, sel[0])
    if not bike:
        raise RuntimeError("[MGP] select the bike's Skeletal Mesh in the Content Browser first")
    comp = bike.skeletal_mesh_component
    bone = next((b for b in BONES if comp.does_socket_exist(b)), "")
    if not bone:
        log("bones %s not found on the mesh: decals attached to the mesh origin instead" % "/".join(BONES))
    for a in tagged("MGP_PROJ"):
        a.destroy_actor()
    mi = decal_material()
    keep = unreal.AttachmentRule.KEEP_RELATIVE
    for p in PROJECTORS:
        d = spawn(unreal.DecalActor)
        d.set_actor_label("MGP_" + p["tag"])
        d.tags = ["MGP_PROJ", p["tag"]]
        dc = d.decal
        dc.set_decal_material(mi)
        dc.set_editor_property("decal_size", unreal.Vector(*DECAL_SIZE))
        d.attach_to_actor(bike, bone, keep, keep, keep, False)
        rc = d.root_component
        rc.set_editor_property("relative_location", unreal.Vector(*p["loc"]))
        rc.set_editor_property("relative_rotation", unreal.Rotator(pitch=p["rot"][0], yaw=p["rot"][1], roll=p["rot"][2]))
        rc.set_editor_property("relative_scale3d", unreal.Vector(*p["scale"]))
    log("placed %d projector decal(s) of %s on %s%s" % (len(PROJECTORS), PKG.split("/")[-1], bike.get_actor_label(), (" / bone " + bone) if bone else ""))


def send():
    prio = {p["tag"]: p.get("priority") for p in PROJECTORS}
    sent = []
    for a in tagged("MGP_PROJ"):
        tag = [str(x) for x in a.tags if str(x) != "MGP_PROJ"][0]
        if tag not in prio:
            continue
        rc = a.root_component
        l, r, s = rc.get_editor_property("relative_location"), rc.get_editor_property("relative_rotation"), rc.get_editor_property("relative_scale3d")
        body = dict(pkg=PKG, tag=tag, loc=[l.x, l.y, l.z], rot=[r.pitch, r.yaw, r.roll], scale=[s.x, s.y, s.z], priority=prio[tag])
        req = urllib.request.Request(URL + "/api/proj/set", json.dumps(body).encode(), {"Content-Type": "application/json", "X-MGP-Token": TOKEN})
        try:
            urllib.request.urlopen(req, timeout=20).read()
        except urllib.error.HTTPError as e:
            raise RuntimeError("[MGP] %s: editor said %s %s" % (tag, e.code, e.read()[:200]))
        except Exception as e:
            raise RuntimeError("[MGP] cannot reach the editor at %s (is it running? after a restart press Preview in UE again): %s" % (URL, e))
        sent.append(tag)
    if not sent:
        raise RuntimeError("[MGP] no MGP_ projector decals in this level - run mgp_ue_load.py first")
    log("sent %s to the editor (%s). In the editor press Reload on the rider page, then Save and Pack." % (", ".join(sent), PKG.split("/")[-1]))


load() if MODE == "load" else send()
'''

DEFAULT_DECAL_SIZE = "(50.0, 50.0, 50.0)"   # half-size: 100 cm box at scale 1, so the usual projector scale 0.16-0.2 gives a 16-20 cm number (friend: 16-20)


def _kept(path, name, default):
    """Value of `NAME = ...` in an earlier generated script, so the user's calibration survives a rewrite."""
    try:
        txt = open(path, encoding="utf-8").read()
    except OSError:
        return default
    m = re.search(r"^%s = (r?\"[^\"\n]*\"|\([^)\n]*\))" % name, txt, re.M)
    if not m:
        return default
    v = m.group(1)
    return v[2:-1] if v.startswith('r"') else v


def write_scripts(folder, url, token, pkg, projectors):
    """Writes mgp_ue_load.py and mgp_ue_send.py into `folder`; returns their paths.
    projectors: [dict(tag, loc[3], rot[pitch,yaw,roll], scale[3], priority)] as the rider page shows them."""
    os.makedirs(folder, exist_ok=True)
    old = os.path.join(folder, "mgp_ue_load.py")
    size = _kept(old, "DECAL_SIZE", DEFAULT_DECAL_SIZE)
    if not re.fullmatch(r"\(\s*[-\d.eE+]+\s*,\s*[-\d.eE+]+\s*,\s*[-\d.eE+]+\s*\)", size):
        size = DEFAULT_DECAL_SIZE
    png = _kept(old, "NUMBER_PNG", "")
    rows = [dict(tag=p["tag"], loc=list(p["loc"]), rot=list(p["rot"]), scale=list(p["scale"]), priority=p.get("priority")) for p in projectors]
    blob = json.dumps(rows)
    for s in (url, token, pkg, png):
        if '"' in s or "\n" in s:
            raise ValueError("unexpected character in %r" % s)
    out = []
    for mode in ("load", "send"):
        txt = TEMPLATE
        for k, v in (("@MODE@", mode), ("@URL@", url), ("@TOKEN@", token), ("@PKG@", pkg), ("@PROJECTORS@", blob),
                     ("@DECAL_SIZE@", size), ("@NUMBER_PNG@", png)):
            txt = txt.replace(k, v)
        path = os.path.join(folder, "mgp_ue_%s.py" % mode)
        with open(path, "w", encoding="utf-8") as f:
            f.write(txt)
        out.append(path)
    return out
