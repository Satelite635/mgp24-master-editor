# Number projectors (ProjectorCustomNNN_VVV) + Blender add-on

## File format (verified on ProjectorCustom104_003 / _006, custom-rider bikes)
`customization_data/ProjectorCustomNNN_VVV`, class `ProjectorsDataSource_C`. `TaggedProjectors[]` of
`IgnitionTaggedProjectorData {Tag, Projector: VehicleCustomizationProjectorData {Priority, Transform{Rotation Quat, Translation Vector (cm), Scale3D}, Layers[] {BaseColorMap, ..., TextProjectorData, ProjectableWidgetData{WidgetsDrawSize IntPoint}, Tags[]=Number}}}`.
104_003/006: tags SidePlateRight (x81 y0 z96.5/98.0, pitch 37 yaw 180, scale 0.14, texture bikeShared/textures/47), FrontPlate and SidePlateLeft (x≈155, z0, scale 1, no texture → probably unused). 003 vs 006 differ only in that z.
Guesses (unverified): texture 47 is a placeholder replaced by the rider's number.

## How placement works (v77 reading, being verified)
- First reading (3D plane at the transform) put the number inside the bike - wrong. UV-space reading also ruled out: the number lives on UVChannel_2 (the livery UV), nose island centre ≈ (0.22, 0.54), not rotated; doesn't match 81/96.5/37°.
- Current reading: decal-style projector. It sits inside the bike (x81 z96.5 cm) and projects along local -X, which for this quat is forward and 37° UP (UE +X of quat (0.317,0,-0.948,0) = (-0.8,0,-0.6)). Faizal: the number is on the front nose just under the windscreen. Ray direction may be +X instead -> add-on toggle.
- v77 in Blender: square ended inside the bike - ray hit internal meshes first (reproduced headless). v78 adds Target mesh + hit readout.
- Number size at scale 1 still a guess (100 cm).
- **In-game test (Oct 20): SidePlateRight x+20, z+20, scale x2 in ProjectorCustom104_006 -> number did NOT change at all.** So this file/projector is not what places that front number (or the file is not loaded for that rider). v79 adds Browse "Used by" to find what references ProjectorCustom104_006 and which projector file the bike really uses. All add-on placement readings so far are unconfirmed.

## Copy between files (v80, editor)
Browse → a `Projector*` asset → "Copy projectors from…". Copies Translation/Rotation/Scale3D/Priority per tag; textures/layers untouched. Verified offline only (003→006 SidePlateRight z 98→96.5, staged).
**Status:** placement editing paused by Faizal (Oct 20) after the in-game test showed 104_006 SidePlateRight edits change nothing. Next if resumed: Browse "Used by" on that file.

## Blender add-on (`blender_addon/mgp_projectors`, shipped as `mgp24_projectors_addon.zip` inside the tool zip)
- `projfile.py` (no bpy): `load`, `save` (in-place float patch via `uprops.Asset.set_value`, first save keeps `.bak`), `ue_to_blender`/`blender_to_ue` (cm→unit, Y mirrored; quat (x,y,z,w) ↔ (w,-x,y,-z)).
- `__init__.py`: N-panel "MGP24": Parent (bike origin object), Unit scale (0.01), Mirror Y, Box size (display only, guess 100 cm at scale 1). Load → one object per projector ("Show as": Plane = shared mesh square in local YZ facing local +X, default since v76; Box = CUBE empty) + child arrow along local +X (projection axis = guess). Write back / Write to another file (matched by tag). Uses `matrix_basis.decompose()` so any rotation mode works.
- Tested with `pip install bpy==4.5.*` (py3.11) headless: load → move/scale → write → re-read OK; no-op save byte-identical.
- **Unverified**: axis/units convention vs Faizal's imported model, origin of the bike, box size, projection axis. Calibrate once against a bike whose number placement is known in game.
- Build: `./build_zip.sh` (vendors uprops.py + mgp_core.py into the add-on zip).
