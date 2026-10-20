# Changelog (versions shipped as zips; bump `VERSION` in webui.py AND `HV` in webui.html)

- **v76** Blender add-on 1.1: "Show as" Plane (default; mesh square in local YZ, normal = arrow/local +X) or Box; size label "Size (cm at scale 1)"; tip when Parent is empty.
- **v75** Blender add-on `mgp24_projectors_addon.zip` (in the tool zip): show/move/rotate/scale bike number projectors on the model, write back, copy to another bike's projector file. `uprops` reads IntPoint/IntVector structs (`WidgetsDrawSize` was unreadable).
- **v74** Crash check before packing (`_crash_scan`, shared with "Check mod"): Pack refuses when a loose mod asset imports another game's module (`/Script/sbk1`, `motogpXX`, `rideN`, `mxgp`), a UI asset needs a motogp24 class no game UI asset uses, or a `Font` export's native part differs in size from the game's own Fonts (SBK Font, "Serial size mismatch"). Dialog lists files; "Pack anyway" (`force`) skips once. Non-UI assets with unknown classes are warnings only (class list is learned from UI assets). Font check untested on real files.
- **v73** Riding style: rider page has a "riding style" section for `Content/assets/data/datatables/Anim/RidingStyle_DT` (`mgp_core.StyleTable`, `/api/style`): edit the 8 fields, copy from a preset (Balanced/Centered/ElbowOut/ShouldersOut/BodyOut/OldSchool) or another rider, add a row for entries that lack one. "Copy look" has an optional "riding style" box. Unverified in game.
- **v72** Paks re-read automatically when a .pak is added/replaced/removed (fixes "bad magic" after repacking; no restart needed). HUD import never imports `ui/Fonts` files (shown greyed out; "Untick fonts" button removed); penalty files stay ticked. Speed: indexed + cached pak folder lookups, crash check scans only loose mod files, progress polling no longer waits on the global lock, HTTP keep-alive.
- **v71** Graft button always runs the hide step (idempotent), un-collapses grafted widgets, popup lists changed widgets. Fix for orange "+1.356" box left visible when the page was already grafted.
- **v70** HUD import: "Untick fonts" button; "Select all" skips `/ui/Fonts/` (SBK Font assets crash GP24).
- **v69** Fonts list shows scanned count, skipped assets + reasons, and origin (mod folder / game original).
- **v68** Graft and swap buttons always act on `RaceHud_BP` (`_race_target`); error messages name file + classes found.
- **v67** Swap-positions button is a toggle (works from either arrangement).
- **v66** "Replace fonts with TT Supermolot" (`/api/fonts/list`, `/api/fonts/apply`, `hudskin.retarget_font`).
- **v65** "Swap stewards box / jump-start & long-lap positions" (`hudskin.swap_widget_types`, `/api/hud/swappos`).
- **v64** Graft also retypes `WarningHUDSmallWidget` → `PlayerAlertsHUDWidget_BP_C`; hides other warn widgets.
- **v63** "Use GP24's penalty widget": `retype_widget` (`PenaltiesInfoWidgetManagerBP_C` → `WB_RacePenaltiesWidgetContainer_C`), `PakSet.read_base`.
- **v55–v62** Port-audio Gain dB; HUD "Show / hide widgets" (Visibility editor); "Untick penalty / warning"; extended crash check (any missing `/Script/<module>` class, base paks only); faster `staged_files`; Save no longer blocked during scans/crash checks; import result reports changed vs identical; page/server version mismatch banner; rename to MGP24 Master Editor; `[slow]` request logging.
- Earlier: bindings/clone/replace, audio port, locres, browse, replacement sheet, DB editor, pack mod, HUD skin + import, background jobs (see README.txt).
