# MGP24 Master Editor — project guide for Claude Code

A local web tool (Python stdlib server + one `webui.html`) for modding **MotoGP 24** (Unreal Engine 4.27, Windows).
Owner: **Faizal** (sells MotoGP livery mods; tests everything in the real game and reports back with screenshots/crash logs).
Start it with `start.bat` (or `python motogp_master_editor.py web`) → http://127.0.0.1:8765. Only dependency: `pycryptodome`.

## How to work with Faizal
- **Keep answers short. Be honest and unbiased, even when it's uncomfortable.** If a result is unverified, say so.
- He tests in the real game; you can't. Offline you can only prove "file re-parses, sizes/offsets are consistent". Never claim a game-side fix works.
- Several of my past diagnoses were wrong (see `docs/HUD_PENALTIES.md`). State guesses as guesses; prefer adding diagnostics (what was skipped/why) over speculating.
- After each change: bump the version, rebuild the zip, send it. Version lives in TWO places and must match:
  `VERSION = "vNN"` in `webui.py` and `HV="vNN"` in `webui.html` (page shows a red "close the tool and start it again" if they differ).
  Current: **v100**.
- Deliverable convention: `./build_zip.sh` (builds `../motogp_master_editor.zip` incl. the Blender add-on zip), then send the zip.

## Layout (flat; imports are top-level)
| File | Role |
|---|---|
| `motogp_master_editor.py` | CLI entry (`web`, `gui`, `selftest`, `bindings`, `replace`, …) |
| `webui.py` | HTTP server + all `/api/*` endpoints (≈1.5k lines), job runner, global lock |
| `webui.html` | Entire front end (vanilla JS, one file) |
| `mgp_core.py` | `UAsset` header editing, `BindingTable`, `StyleTable` (RidingStyle_DT), `Source` (layered read), `Project`, `Db`, clone logic |
| `uprops.py` | Read-only `.uexp` property parser (`Asset`) |
| `hudskin.py` | HUD tools: skin compare/apply, visibility, **retype_widget**, **swap_widget_types**, font retarget |
| `audioport.py` | Wwise bank port from other games (with `apply_gain`) |
| `mgp_pak.py` / `mgp_pakwrite.py` | Pak reader (`PakSet`) / writer (v8 uncompressed) |
| `mgp_locres.py` | `.locres` read/write |
| `fontswap.py` | Font swap: read a .ttf/.otf/.ufont's names; the editor writes it as `<FontFace>.ufont` |
| `projfile.py` | Projector files (`ProjectorsDataSource`): parse/patch transforms; shared by the editor and the Blender add-on |
| `blender_addon/mgp_projectors/` | Blender add-on for number projectors (see `docs/PROJECTORS.md`) |
| `test_*.py` | Offline tests (most need CLI args — see `docs/TESTING.md`) |
| `tests/jsd/*.js` | jsdom front-end harnesses (paths hardcoded; see docs) |

## Hard rules / gotchas
- **Never use a Font/widget asset from SBK (Superbike) as-is in GP24.** SBK C++ module is `/Script/sbk1`; GP24's is `/Script/motogp24`. Classes from sbk1 crash the game ("Could not find SuperStruct X"). SBK-made `Font` assets crash with "Serial size mismatch: Got 358, Expected 359".
- Edits are **staged** and written only on Save; Save/Discard are blocked only while a job titled `Packing` or `Importing` runs.
- All API calls take a global `S.lock` (except `LOCK_FREE` = `/api/pak/status`); long work uses `_job_start(title, work)` + `/api/pak/status` polling.
- `PakSet` layers base paks, then `*_P.pak`; `include_patch=True` also includes the user's own mod pak. `PakSet.read_base(rel)` reads the game's own copy only. Since v72 `PakSet.refresh()` (called before every API request, max once/s, via `Project.refresh_paks`) re-reads any pak whose size/mtime changed, so a repacked mod pak no longer reads garbage ("bad magic"). Caches tied to pak contents key on `PakSet.gen`.
- When you append names to a `UAsset`, offsets move: compute `importoff`/`exportoff` **after** `append_name` (a past bug).
- Editing a file that already has Visibility etc.: patch in place; otherwise insert tag and bump export size, later export offsets and the bulk offset.
- Use Edit/regex on `webui.html` carefully: it's a single 760-line file with long lines.

## Read next
`docs/PROJECT_CONTEXT.md` (what's been built and why) → `docs/HUD_PENALTIES.md` (the active problem) → `docs/OPEN_ITEMS.md` (what to do next).
Other docs: `PROJECTORS.md`, `ARCHITECTURE.md`, `UE4_FORMAT_NOTES.md`, `FONTS.md`, `CHANGELOG.md`, `TESTING.md`.
