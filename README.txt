MGP24 Master Editor
=======================
Easiest:        double-click MGP24MasterEditor.exe (no Python needed; Python + pycryptodome are inside it).
                It opens a console window (keep it open while you use the tool) and the editor in your browser.
                mgp_config.json is saved next to the exe. If Windows SmartScreen/antivirus warns about it, that's
                a common false positive for PyInstaller exes ("More info" -> "Run anyway").
From source:    pip install pycryptodome, then double-click start.bat
Check the pak reader on your game (do this first):
    python motogp_master_editor.py selftest --paks "F:\SteamLibrary\steamapps\common\MotoGP24\motogp24\Content\Paks"
Web UI:         python motogp_master_editor.py        (opens http://127.0.0.1:8765 in your browser)
                Tabs: Riders & bindings (replace / copy look / clone), Database (click a cell to edit),
                Setup (mod folder, Paks folder, AES key). Old tkinter window: python motogp_master_editor.py gui
    1) "Game paks..."      pick the Paks folder (remembered in mgp_config.json)
    2) "Open mod folder..." any folder; edits and cloned files are written there (Content/...),
                            the DB is copied there from the paks on first use.
Reads: mod folder first, then game paks (base paks, then *_P patch/mod paks on top).
Untick "include *_P paks" to start from the vanilla game instead of your own mod pak.
Your output = the mod folder: repack it into a pak yourself.

Copy values from another .uasset (Browse -> "Copy values from...")
-----------------------------------------------------------------
Keeps the chosen asset's own file (header, names, imports, texture/material paths) and overwrites only
numbers, bools, vectors, colours and transforms that match by property name (projectors by tag, material
parameters by name, DataTable rows by row name). Nothing is added or removed: the file size stays the same.
Source: a .uasset on your PC (its .uexp next to it) or a /Game/... path, from GP24, GP25 or GP26.
MotoGP 25/26 files have no property names inside: set the game's .usmap (Setup, or in the dialog);
for a MotoGP 26 source also give MotoGP 26's .usmap. Press Preview first: it lists what would change,
what was skipped and why (not stored in the target, different type, reference/text).

Rider gear / all bindings
-------------------------
Select a pilot: the lower panel lists every binding table that has a row for that rider (helmet, suit, gloves,
boots, buttpatch, face/hair, bike extras). "Repoint selected" takes the target from another rider's row
(same table); "Copy look from rider" does that for several categories at once. Cloning NEW gear sets
(new helmet/suit assets) is not implemented yet - bikes only.
Teams view: a team's page also lists "team suits - custom riders": the suits a custom/career rider wears on
that team (rows keyed SU_<class>_<maker>_<model>_<team>, from the game database TeamSuits). Replace/Edit/
Clone/Copy values work on them like on an official rider's suit.
CLI: bindings <folder> <PilotKey> | copy-look <folder> <PilotKey> <DonorKey> [--only helmet,gloves]
dt_inspect.py <bindings folder> <db.sqlite3>   dumps every DataTable's layout and which DB column its keys match.

Replacing entries (no cloning needed)
-------------------------------------
Select a pilot, pick a row in the bindings list, "Replace selected...": choose any existing asset of the same kind
from the list (or type another rider's name / a full /Game/... path). Works for every binding table, any path length.
CLI:  choices <folder> <PilotKey> <TableName>     list assets that could replace a row
      replace <folder> <PilotKey> <TableName> <rider | /Game/pkg | /Game/pkg.obj>
Only the binding file for that table is rewritten (backup in _mgp_backup); the new files are not touched.

If the replacement asset does not exist
---------------------------------------
GUI: you are asked whether to create it as a copy of the row's CURRENT asset:
  - Copy this asset only: one data asset under the new name (any name length); it keeps using the original's
    materials/textures. Textures (.ubulk assets) cannot be copied on their own.
  - Copy full set: also copies the variant's materials/textures. Needs the new name to differ only by a
    same-length variant number in the same folder (bike103_001 -> bike103_905, helmet_109 -> helmet_900).
  - Point anyway: just change the entry (warning shown).
CLI: replace ... <target> --copy asset|set

Editing assets (customization_data, materials, ...)
---------------------------------------------------
Riders tab -> "Edit..." on a row lists that asset (and, for bike customization_data, every material/texture of the
variant). Click one: its files are extracted into the unsaved-changes folder and opened in UAssetGUI.
Set the UAssetGUI.exe path on the Setup tab (or leave it empty to use Windows' default app for .uasset).
In UAssetGUI pick the UE 4.27 version, edit, Save (Ctrl+S) - then come back and press Save here.
Extracting alone changes nothing; only files that really differ count as unsaved.

Clone any entry
---------------
Riders tab -> "Clone..." on any row (any table, Official/Custom/Teams): gives that entry its own copy of its asset.
  Full set  = also copies the variant's materials/textures (customization_data only; same-length number change).
  This asset only = one data asset, keeps the original's materials/textures (works for everything except textures).
The name is proposed automatically (last number -> a free 9xx one, or _2 if the name has no number); you can type another.
Check tab -> "Clone audit": dry-runs a copy of every distinct asset and lists what cannot be cloned and why.

Editing customization_data and material instances
-------------------------------------------------
Riders tab -> "Edit..." on a row lists the row's asset (star) and every material instance it references.
Click one: it is extracted from the paks into the unsaved-changes folder and opened in UAssetGUI
(set the UAssetGUI.exe path on the Setup tab). Edit and save there, come back, press Save in the header.
Materials in a "shared" folder are flagged: other riders may use them too.

Skeletal mesh / skeleton / physics asset
----------------------------------------
"Edit..." also lists the skeletal mesh the asset references, and from the mesh its skeleton and physics asset
(followed up to 3 levels), next to the material instances. Click one to extract it (with its .ubulk, if any) and open it
in UAssetGUI. Items not found in the mod folder or paks are greyed out. Shared parents (folders named "shared")
are flagged and listed last.

Class filter (Check tab)
------------------------
"Check bindings" and "Match riders to their team" have a class filter (All / MotoGP / Moto2 / Moto3). Winter-test (carbon)
bikes only exist for MotoGP (cat001), so for WinterTest tables use "MotoGP only": the Moto2/Moto3 rows pointing at
missing carbon assets are expected, not errors.

PORT AUDIO TAB
  Copies a bike's sound from another game (e.g. MotoGP 22, SBK 22) into this one: the Wwise bank (.bnk), its
  events, the bank asset and the BikeAudio asset, rebuilt in this game's layout, plus any Init.bnk objects the
  bank needs. Give it the other game's extracted Audio folder, Scan, tick bikes, Check (dry run), then Port.
  Files are staged; Save writes them. Then use Replace on the rider/team audio row and paste the new
  BikeAudio path. Refuses: names that already exist in the game, different Wwise bank versions, missing plugins.
  Not verified by the tool: whether the sound's parameters suit this game's engine model - test in game.

PACK MOD (button in the header, next to Save; greyed out while there are unsaved changes)
  Writes the mod folder's Content into one *_P.pak (version 8, uncompressed, unencrypted). Save first.
  Output goes to <mod folder>\_mgp_pak unless you give another folder; copy it into the game yourself. Tested with this editor's own pak reader;
  if the game ignores the pak, tell me which UE4 pak tool works for you and I'll compare the output.

PORTED GEAR / BACKFIRE EVENTS
  If a source bike uses backfire or gear-change events that this game lacks (e.g. SBK 22's GearUp_YamahaR1), the
  tool also needs the source's Events/COMMON/... assets and its VehicleCommon.bnk. The bank is added as a second
  bank named Ported_VehicleCommon (the game's own VehicleCommon has other events and stays untouched); only the
  missing events point at it. Events the game already has keep using the game's version.

LOCALIZATION TAB
  Lists the game's .locres files (mod folder and paks), lets you search and edit existing texts; edits are staged
  like everything else (Save writes the changed .locres into the mod folder, which the pak then overrides).
  A file is only opened for editing if rewriting it unchanged gives back identical bytes; otherwise the tab refuses.
  Written from the documented format and tested on synthetic files only - tell me if a real file is refused.

BROWSE TAB
  Folder browser over the paks and the mod folder (like FModel/UModel, without previews). Search inside a folder
  and below. Per asset: Edit (stages a copy and opens it in UAssetGUI), Clone (copies a data asset to a new name
  in the same folder; textures with .ubulk data are refused), Extract (copies the files straight into the
  mod folder, no Save needed). .locres files have an "Open in Localization" button.

Replacement sheet tab
  Lists every base-game rider, team, bike and track (from the DB in the paks). Type what each is replaced with in your mod, plus notes; saved to _mgp_replacement_sheet.json in the mod folder (never packed). 'DB changes' shows where your mod's DB already differs. Export CSV per category; 'Import CSV / save' reads back an exported CSV (any category; rows are matched by Key) or the .json save, merging into the sheet (blank cells never erase existing entries). Display names are looked up in a .locres (pick which one next to the filter) by matching the DB key against localization keys; hover the key to see which entry matched and how many candidates. No match: the DB key prettified.

HUD skin tab
  Copies the look of another game's widget onto the game's own widget (layout and logic stay the game's). Extract the other game's widget (.uasset + .uexp, same file name) into a folder, pick the game's widget, Compare. Widgets are matched by name and class; colours, font size/face, shadow/outline, brush images and (optionally) sizes/margins are listed. Only same-size patches are made: values copied as they are, or fonts/images the target already references. 'needs import' rows (a font or image the target does not reference yet) are not copied yet. Slots (positions) are never touched. Review in-game; keep the original in the paks.

Pack progress
  Pack mod now runs in the background: a toast shows 'Packing...' with the latest log line; 'View log' opens the full live log (also after it finishes, until the next pack). The window can be used meanwhile; avoid Save while a pack runs.

Launch game
  Setup > 'Game' takes the game's .exe or a shortcut to it (.lnk, or a Steam .url); Browse and Open in Explorer work like the other paths. The header's 'Launch game' button starts it (an .exe is started in its own folder; a .lnk uses its target, arguments and start-in folder). Unsaved changes are not in the game - the toast says so.

HUD: import whole files
  HUD skin tab > 'Import whole files': point it at a folder of the other game's extracted files, Scan, tick what to import, Import selected. Files are placed where the game's file of that name lives (or by their Content/... folders) and replace the game's own, staged until Save - the same as swapping files by hand. Everything is ticked by default; penalty/warning widgets are marked and ask for confirmation, because they rely on game logic and can stay on screen with a fixed value when taken from another game.

Background tasks
  Pack mod and HUD 'Import selected' now run in the background with the same toast (latest log line) and 'View log'. Save/Discard/Pack are disabled while one runs, and only one task runs at a time. The header no longer wraps the Pack mod / Launch game labels; on narrow windows the buttons move to a second row.

Import safety check
  Scan folder now reads the game's own UI assets to learn which C++ classes (/Script/motogp24) this game build has. A widget that needs a class the game lacks (e.g. SBK's PenaltyTime needs InvalidLapWidget) is marked 'will crash on load' and left unticked: the game stops with 'Could not find SuperStruct ...'. It also lists assets a file references that neither the game nor your folder has. The first scan takes longer (it runs as a background task with the log); later scans reuse the result.

Replacement sheet - names from localization
  The dropdown now defaults to 'All Italian (it/) localization files' (the language the game uses; falls back to every file if there is no it/ folder) (it used to pick whichever file came first, e.g. a German dialogs file). The base-game name comes from the game's original .locres; if your mod's .locres has a different text for the same entry, that text shows as the placeholder in 'Replaced with' and 'Fill from mod' copies all of them into the sheet. The summary shows how many names were found.

Blender add-on: bike number projectors (mgp24_projectors_addon.zip, inside this zip)
  Install: Blender > Edit > Preferences > Add-ons > (arrow menu) Install from Disk > pick mgp24_projectors_addon.zip, tick "MGP24 Projectors".
  Use: 3D View > N panel > MGP24. Set Parent to your bike's root (e.g. VEHICLE_BASE), Load a ProjectorCustomNNN_VVV.uasset (its .uexp must be next to it).
  Each projector shows as a box (+ arrow). Move/rotate/scale it, select it, click Write back. "Write to another file" copies the placement to another bike's projector file.
  The first write keeps a .bak copy. Boxes with no texture are probably unused. Axis/scale conventions are a first guess: check once against a bike you know.
