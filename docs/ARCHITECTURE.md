# Architecture

## Process model
`python motogp_master_editor.py web` → `webui.py` runs a `ThreadingHTTPServer` on 127.0.0.1:8765 serving `webui.html` and `/api/*` JSON endpoints. Every API handler runs under the global `S.lock`. Auth: header `X-MGP-Token` (token injected into the page). Handlers are plain functions `fn(q, b)` (query dict, JSON body) registered in a dict near the end of `webui.py` as `("GET"|"POST", "/api/…"): fn`.
- State: `S.P` is the open `Project`; `S.need()` returns it or raises. Config persists in `mgp_config.json` (ignored by git).
- Slow requests are logged as `[slow] METHOD path took Ns` (>1 s, except `/api/pak/status`).
- Background jobs: `_job_start(title, work)`; progress in `S.pakjob`; front end polls `/api/pak/status` via `packTrack(title, onDone)` (toast with latest log line + "View log"). Save/Discard are blocked only for jobs titled `Packing` or `Importing`.

## Data layering (`mgp_core.Source`)
read order: **staging folder** (`base`, unsaved) → **mod folder** (`work`) → **paks** (`PakSet`: base paks, then `*_P.pak`). Writes go to `Source.loose(rel)`. `Source.find(dir, ext)` unions all layers. `Source.origin(rel)` = "unsaved" / "mod folder" / pak name. `Project._differs`/`staged_files()` decide what counts as an unsaved change (size-first cache keyed `(rel, size, mtime_ns, base stat)`; new files or any exception count as different).
Paths are project-relative: `Content/assets/ui/Pages/HUD/RaceHud_BP.uasset`.

## Modules
- **mgp_core.UAsset**: header editor for `.uasset` (names, imports, exports, offsets). Key: `texts()`, `append_name(s)`, `_shift_after`, `_get/_set` header ints (`importoff`, `exportoff`, `exportcount`, `total`, …), `EXPORT_SIZE=104`, `to_bytes()`. **After `append_name`, re-read `importoff`/`exportoff`.**
- **uprops.Asset(ua_bytes, ux_bytes)**: parse imports/exports and `.uexp` tagged properties (`parse_export(i)`); `uexp` may be `b""` when only imports/exports are needed (used for donors and font lists).
- **hudskin**: `widgets/compare/apply` (skin), `visibility_list/set_visibility`, `retype_widget`, `swap_widget_types`, `font_faces/font_weight/retarget_font`, `WARN_NAMES` regex `penal|warn|longlap|long_lap`.
- **audioport**: `port(P, path, bike_names, dry_run, gain)`; Wwise bank rewrite incl. `apply_gain`.
- **mgp_pak.PakSet**: `exists/read/find/which/size/read_base/base_readers`; entries have `usize`. Index map `self.map` (lowercase `motogp24/content/...` → reader); readers have `.files`.
- **mgp_pakwrite.write_pak(dest, [(name, path)])**: v8, key `"00"*32` for test fixtures.

## Front end (`webui.html`)
One file; tabs: Riders & bindings, Check, Port audio, Browse, HUD skin, Replacement sheet, Localization, Database, Setup. Helpers: `api(path, body)`, `guard(fn)` (toast on error), `toast(msg, kind)`, `refreshChanges()`, `huBody()` (`{target: #hu_target, source_dir: #hu_src}`), `packTrack`. HUD buttons: `#hu_vis`, `#hu_graft`, `#hu_swap`, `#fn_scan`, import table `#hi_*`.

## HUD import details
`hud_scan` builds items `{key,name,files,dest,replaces,warn,note,ok,crash,missing_deps,size}`; crash check compares `/Script/<module>` class refs of each asset with classes available in the game's base paks (`_game_classes`, `_script_refs`, `_missing`). `hud_import` writes into the staging area and returns `summary` (changed vs identical).
