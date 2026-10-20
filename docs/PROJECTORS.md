# Number projectors (ProjectorCustomNNN_VVV) + Blender add-on

## File format (verified on ProjectorCustom104_003 / _006, custom-rider bikes)
`customization_data/ProjectorCustomNNN_VVV`, class `ProjectorsDataSource_C`. `TaggedProjectors[]` of
`IgnitionTaggedProjectorData {Tag, Projector: VehicleCustomizationProjectorData {Priority, Transform{Rotation Quat, Translation Vector (cm), Scale3D}, Layers[] {BaseColorMap, ..., TextProjectorData, ProjectableWidgetData{WidgetsDrawSize IntPoint}, Tags[]=Number}}}`.
104_003/006: tags SidePlateRight (x81 y0 z96.5/98.0, pitch 37 yaw 180, scale 0.14, texture bikeShared/textures/47), FrontPlate and SidePlateLeft (x≈155, z0, scale 1, no texture → probably unused). 003 vs 006 differ only in that z.
Guesses (unverified): texture 47 is a placeholder replaced by the rider's number; the projection is baked into the mesh's separate number UV channel.

## Blender add-on (`blender_addon/mgp_projectors`, shipped as `mgp24_projectors_addon.zip` inside the tool zip)
- `projfile.py` (no bpy): `load`, `save` (in-place float patch via `uprops.Asset.set_value`, first save keeps `.bak`), `ue_to_blender`/`blender_to_ue` (cm→unit, Y mirrored; quat (x,y,z,w) ↔ (w,-x,y,-z)).
- `__init__.py`: N-panel "MGP24": Parent (bike origin object), Unit scale (0.01), Mirror Y, Box size (display only, guess 100 cm at scale 1). Load → one CUBE empty per projector + child arrow along local +X (projection axis = guess). Write back / Write to another file (matched by tag). Uses `matrix_basis.decompose()` so any rotation mode works.
- Tested with `pip install bpy==4.5.*` (py3.11) headless: load → move/scale → write → re-read OK; no-op save byte-identical.
- **Unverified**: axis/units convention vs Faizal's imported model, origin of the bike, box size, projection axis. Calibrate once against a bike whose number placement is known in game.
- Build: `./build_zip.sh` (vendors uprops.py + mgp_core.py into the add-on zip).
