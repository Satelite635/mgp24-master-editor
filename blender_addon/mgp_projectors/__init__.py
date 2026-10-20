"""MGP24 Projectors - show and edit MotoGP 24 bike number projectors (ProjectorCustomNNN_VVV) in Blender.

Load a projector .uasset (its .uexp must sit next to it): every projector becomes a box (empty) you can move,
rotate and scale. "Write back" saves the boxes' transforms into the file (same size, only those floats change).
"Write to another file" copies the placement onto another bike's projector file (matched by tag).
"""
bl_info = {
    "name": "MGP24 Projectors",
    "author": "MGP24 Master Editor",
    "version": (1, 1, 0),
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
from mathutils import Quaternion

import projfile


def _plane_mesh(size):
    """Square in the local YZ plane (normal = local +X, the arrow), `size` wide. Shared per size."""
    name = "MGP_ProjPlane_%.4f" % size
    me = bpy.data.meshes.get(name)
    if not me:
        h = size / 2
        me = bpy.data.meshes.new(name)
        me.from_pydata([(0, -h, -h), (0, h, -h), (0, h, h), (0, -h, h)], [], [(0, 1, 2, 3)])
        me.update()
    return me


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
    shape: bpy.props.EnumProperty(name="Show as", default="PLANE", items=[
        ("PLANE", "Plane", "A flat square facing along the arrow (where the number lands)"),
        ("BOX", "Box", "The projector volume (decal-style box)")])
    box_cm: FloatProperty(name="Size (cm at scale 1)", default=100.0, min=0.1,
                          description="Display only - how big a projector of scale 1 is drawn. Not written to the file")
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
            if s.shape == "PLANE":
                box = bpy.data.objects.new(p["tag"], _plane_mesh(s.box_cm * s.unit))
                box.show_wire = True
            else:
                box = bpy.data.objects.new(p["tag"], None)
                box.empty_display_type = "CUBE"
                box.empty_display_size = s.box_cm * s.unit / 2
            box["mgp_tag"] = p["tag"]
            box["mgp_texture"] = p["texture"]
            coll.objects.link(box)
            if s.parent:
                box.parent = s.parent
            box.rotation_mode = "QUATERNION"
            box.location, box.rotation_quaternion, box.scale = loc, Quaternion(quat), sc
            arrow = bpy.data.objects.new(p["tag"] + " dir", None)   # local +X: likely the projection axis (unverified)
            arrow.empty_display_type = "SINGLE_ARROW"
            arrow.empty_display_size = s.box_cm * s.unit
            arrow.rotation_euler = (0, 1.5707963, 0)               # arrow points along +Z; turn it to +X
            arrow.parent = box
            arrow.hide_select = True
            coll.objects.link(arrow)
            if not p["texture"]:
                box.color = (0.5, 0.5, 0.5, 1)
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
        col.prop(s, "shape")
        col.prop(s, "box_cm")
        if not s.parent:
            lay.label(text="Tip: set Parent to the bike root (VEHICLE_BASE)", icon="INFO")
        lay.operator("mgp.proj_load", icon="IMPORT")
        coll = _active_coll(context)
        box = lay.box()
        if coll:
            box.label(text=os.path.basename(coll["mgp_file"]), icon="FILE")
            o = context.active_object
            box.label(text="Tag: %s" % o["mgp_tag"])
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


def unregister():
    del bpy.types.Scene.mgp_proj
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
