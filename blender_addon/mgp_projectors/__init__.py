"""MGP24 Projectors - show and edit MotoGP 24 bike number projectors (ProjectorCustomNNN_VVV) in Blender.

Load a projector .uasset (its .uexp must sit next to it): every projector becomes a small sphere (+ ray arrow) you can move,
rotate and scale; a square shows where its ray hits the bike (where the number should land). "Write back" saves the boxes' transforms into the file (same size, only those floats change).
"Write to another file" copies the placement onto another bike's projector file (matched by tag).
"""
bl_info = {
    "name": "MGP24 Projectors",
    "author": "MGP24 Master Editor",
    "version": (1, 3, 0),
    "blender": (3, 6, 0),
    "location": "3D View > Sidebar (N) > MGP24",
    "description": "Show/edit MotoGP 24 number projectors (ProjectorCustom*.uasset)",
    "category": "Import-Export",
}

import os, sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)          # bundled uprops.py / mgp_core.py

import bpy
from bpy.props import StringProperty, FloatProperty, BoolProperty, PointerProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Quaternion, Vector

import projfile


def _square_mesh():
    """1 x 1 square in the local YZ plane (facing local X). Shared by all number previews."""
    me = bpy.data.meshes.get("MGP_NumberSquare")
    if not me:
        me = bpy.data.meshes.new("MGP_NumberSquare")
        me.from_pydata([(0, -.5, -.5), (0, .5, -.5), (0, .5, .5), (0, -.5, .5)], [], [(0, 1, 2, 3)])
        me.update()
    return me


def _is_ours(o):
    return o is not None and ("mgp_tag" in o or "mgp_hit" in o)


def _ray_hit(scene, depsgraph, origin, direction, max_dist=5.0):
    """(location, normal, object name, distance) of the first hit: only the Target mesh if one is set,
    else any mesh except our own preview objects."""
    tgt = scene.mgp_proj.target
    if tgt:
        ev = tgt.evaluated_get(depsgraph)
        inv = ev.matrix_world.inverted()
        lo, ld = inv @ origin, (inv.to_3x3() @ direction).normalized()
        ok, loc, nrm, _i = ev.ray_cast(lo, ld, distance=max_dist * 100)
        if not ok:
            return None
        w = ev.matrix_world @ loc
        return w, nrm, tgt.name, (w - origin).length
    o = origin.copy()
    for _ in range(16):
        ok, loc, nrm, _i, obj, _m = scene.ray_cast(depsgraph, o, direction, distance=max_dist)
        if not ok:
            return None
        if not _is_ours(obj) and not (obj and obj.original and _is_ours(obj.original)):
            return loc, nrm, (obj.original.name if obj and obj.original else "?"), (loc - origin).length
        o = loc + direction * 1e-4
    return None


_busy = False


def update_previews(scene, depsgraph=None):
    """Put each projector's number square where its -X ray (the projection direction, our best reading) hits the bike."""
    global _busy
    if _busy:
        return
    _busy = True
    try:
        depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
        s = scene.mgp_proj
        for p in [o for o in scene.objects if "mgp_tag" in o]:
            hit_obj = bpy.data.objects.get(p.get("mgp_hit_name", ""))
            if not hit_obj:
                continue
            mw = p.matrix_world
            loc, rot, sc = mw.decompose()
            d = (rot @ Vector((1 if s.ray_plus_x else -1, 0, 0))).normalized()
            hit = _ray_hit(scene, depsgraph, loc, d)
            size = s.box_cm * s.unit
            info = "hits %s at %.0f cm" % (hit[2], hit[3] / s.unit) if hit else "hits nothing within 5 m"
            if p.get("mgp_hit_info") != info:
                p["mgp_hit_info"] = info
            if hit:
                pos = hit[0] - d * 0.002                    # a hair in front of the surface
                hit_obj.hide_viewport = False
            else:
                pos = loc + d * 0.3
                hit_obj.hide_viewport = not s.show_miss
            want = Matrix.LocRotScale(pos, rot, Vector((1, sc.y * size, sc.z * size)))
            if any(abs(a - b) > 1e-6 for ra, rb in zip(hit_obj.matrix_world, want) for a, b in zip(ra, rb)):
                hit_obj.matrix_world = want
    finally:
        _busy = False


def _flip_arrows(scene):
    for o in scene.objects:
        if o.name.endswith(" ray") and "mgp_hit" in o:
            o.rotation_euler = (0, 1.5707963 if scene.mgp_proj.ray_plus_x else -1.5707963, 0)
    update_previews(scene)


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    if any(isinstance(u.id, bpy.types.Object) and "mgp_tag" in u.id and u.is_updated_transform for u in depsgraph.updates):
        update_previews(scene, depsgraph)


def _settings(context):
    return context.scene.mgp_proj


def _boxes(coll):
    return [o for o in coll.objects if "mgp_tag" in o]


def _coll_for(path):
    for c in bpy.data.collections:
        if c.get("mgp_file") == path:
            return c
    return None


def _values_from(coll, s):
    vals = {}
    for o in _boxes(coll):
        loc, rot, sc = o.matrix_basis.decompose()          # local to the parent, whatever the rotation mode
        l, q, scl = projfile.blender_to_ue(tuple(loc), tuple(rot), tuple(sc), s.unit, s.flip_y)
        vals[o["mgp_tag"]] = dict(loc=l, quat=q, scale=scl)
    return vals


def _active_coll(context):
    o = context.active_object
    if o and o.get("mgp_tag") is not None:
        for c in o.users_collection:
            if c.get("mgp_file"):
                return c
    return None


class MGPProjSettings(bpy.types.PropertyGroup):
    unit: FloatProperty(name="Unit scale", default=0.01, min=1e-6, precision=4,
                        description="Blender units per UE centimetre (0.01 = model imported in metres)")
    flip_y: BoolProperty(name="Mirror Y", default=True,
                         description="UE is left-handed; most UE importers mirror Y. Turn off if boxes land on the wrong side")
    box_cm: FloatProperty(name="Number size (cm at scale 1)", default=100.0, min=0.1,
                          description="Display only (a guess): how big the number square is at projector scale 1. Not written to the file",
                          update=lambda self, ctx: update_previews(ctx.scene))
    ray_plus_x: BoolProperty(name="Ray along +X", default=False,
                             description="Projection direction is a guess (-X). Tick if the squares land on the wrong side of the bike",
                             update=lambda self, ctx: _flip_arrows(ctx.scene))
    target: PointerProperty(name="Target mesh", type=bpy.types.Object, poll=lambda self, o: o.type == "MESH" and not _is_ours(o),
                            description="Only this mesh catches the ray (the bodywork that carries the number, e.g. the nose). Empty = any mesh",
                            update=lambda self, ctx: update_previews(ctx.scene))
    show_miss: BoolProperty(name="Show misses", default=True,
                            description="Also show the square when the ray hits nothing (unused projectors)",
                            update=lambda self, ctx: update_previews(ctx.scene))
    parent: PointerProperty(name="Parent", type=bpy.types.Object,
                            description="Object whose origin is the bike's origin (e.g. the VEHICLE_BASE armature). Empty = world origin")


class MGP_OT_load(bpy.types.Operator, ImportHelper):
    """Load a ProjectorCustom*.uasset and show its projectors as boxes"""
    bl_idname = "mgp.proj_load"
    bl_label = "Load projector file"
    filename_ext = ".uasset"
    filter_glob: StringProperty(default="*.uasset", options={"HIDDEN"})

    def execute(self, context):
        s, path = _settings(context), os.path.abspath(self.filepath)
        try:
            _, projs = projfile.load(path)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        old = _coll_for(path)
        if old:                                            # reload: replace the previous boxes
            for o in list(old.objects):
                bpy.data.objects.remove(o, do_unlink=True)
            coll = old
        else:
            coll = bpy.data.collections.new("MGP " + os.path.splitext(os.path.basename(path))[0])
            coll["mgp_file"] = path
            context.scene.collection.children.link(coll)
        for p in projs:
            loc, quat, sc = projfile.ue_to_blender(p["loc"], p["quat"], p["scale"], s.unit, s.flip_y)
            box = bpy.data.objects.new(p["tag"], None)     # the projector itself: move/rotate/scale this
            box.empty_display_type = "SPHERE"
            box.empty_display_size = 0.03 / max(min(sc), 1e-3)  # ~3 cm whatever its scale
            box["mgp_tag"] = p["tag"]
            box["mgp_texture"] = p["texture"]
            coll.objects.link(box)
            if s.parent:
                box.parent = s.parent
            box.rotation_mode = "QUATERNION"
            box.location, box.rotation_quaternion, box.scale = loc, Quaternion(quat), sc
            arrow = bpy.data.objects.new(p["tag"] + " ray", None)   # local -X: the projection direction (our reading)
            arrow.empty_display_type = "SINGLE_ARROW"
            arrow.empty_display_size = 0.5 / max(min(sc), 1e-3)      # ~50 cm
            arrow.rotation_euler = (0, 1.5707963 if s.ray_plus_x else -1.5707963, 0)   # +Z arrow turned to -X (or +X)
            arrow.parent = box
            arrow.hide_select = True
            arrow["mgp_hit"] = 1
            coll.objects.link(arrow)
            num = bpy.data.objects.new(p["tag"] + " number", _square_mesh())   # preview where the number lands
            num["mgp_hit"] = 1
            num.hide_select = True
            num.show_wire = True
            num.color = (1, 0.8, 0, 1) if p["texture"] else (0.5, 0.5, 0.5, 1)
            coll.objects.link(num)
            box["mgp_hit_name"] = num.name
        context.view_layer.update()
        update_previews(context.scene)
        self.report({"INFO"}, "Loaded %d projector(s): %s" % (len(projs), ", ".join(p["tag"] for p in projs)))
        return {"FINISHED"}


class MGP_OT_write(bpy.types.Operator):
    """Write the boxes' position/rotation/scale back into the projector file they came from (a .bak copy is kept)"""
    bl_idname = "mgp.proj_write"
    bl_label = "Write back"

    def execute(self, context):
        coll = _active_coll(context)
        if not coll:
            self.report({"ERROR"}, "Select one of the projector boxes first")
            return {"CANCELLED"}
        try:
            done = projfile.save(coll["mgp_file"], _values_from(coll, _settings(context)))
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, "Wrote %s to %s" % (", ".join(done), os.path.basename(coll["mgp_file"])))
        return {"FINISHED"}


class MGP_OT_write_to(bpy.types.Operator, ImportHelper):
    """Copy these boxes' placement into ANOTHER projector file (projectors matched by tag; a .bak copy is kept)"""
    bl_idname = "mgp.proj_write_to"
    bl_label = "Write to another file"
    filename_ext = ".uasset"
    filter_glob: StringProperty(default="*.uasset", options={"HIDDEN"})

    def execute(self, context):
        coll = _active_coll(context)
        if not coll:
            self.report({"ERROR"}, "Select one of the projector boxes first")
            return {"CANCELLED"}
        vals = _values_from(coll, _settings(context))
        try:
            done = projfile.save(os.path.abspath(self.filepath), vals)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        miss = sorted(set(vals) - set(done))
        self.report({"WARNING"} if miss else {"INFO"},
                    "Wrote %s to %s%s" % (", ".join(done) or "nothing", os.path.basename(self.filepath),
                                          ("; not in that file: " + ", ".join(miss)) if miss else ""))
        return {"FINISHED"}


class MGP_PT_panel(bpy.types.Panel):
    bl_label = "MGP24 Projectors"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MGP24"

    def draw(self, context):
        s, lay = _settings(context), self.layout
        col = lay.column(align=True)
        col.prop(s, "parent")
        col.prop(s, "unit")
        col.prop(s, "flip_y")
        col.prop(s, "box_cm")
        col.prop(s, "target")
        col.prop(s, "ray_plus_x")
        col.prop(s, "show_miss")
        if not s.parent:
            lay.label(text="Tip: set Parent to the bike root (VEHICLE_BASE)", icon="INFO")
        lay.operator("mgp.proj_load", icon="IMPORT")
        coll = _active_coll(context)
        box = lay.box()
        if coll:
            box.label(text=os.path.basename(coll["mgp_file"]), icon="FILE")
            o = context.active_object
            box.label(text="Tag: %s" % o["mgp_tag"])
            box.label(text="Ray: %s" % o.get("mgp_hit_info", "-"))
            tex = o.get("mgp_texture") or "(no texture - probably unused)"
            box.label(text="Texture: %s" % tex.rsplit("/", 1)[-1])
            box.operator("mgp.proj_write", icon="FILE_TICK")
            box.operator("mgp.proj_write_to", icon="DUPLICATE")
        else:
            box.label(text="Select a projector box to write")


classes = (MGPProjSettings, MGP_OT_load, MGP_OT_write, MGP_OT_write_to, MGP_PT_panel)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.mgp_proj = PointerProperty(type=MGPProjSettings)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)


def unregister():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    del bpy.types.Scene.mgp_proj
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
