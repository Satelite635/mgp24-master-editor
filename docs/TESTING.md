# Testing

No real game data ships with this repo; the maintainer (Faizal) tests in the game. Offline checks:

## Python
- `python -c "import ast;ast.parse(open('webui.py').read())"` (syntax), same for other modules.
- `test_core.py`, `test_pak.py`, `test_audio.py` etc. take **command-line arguments** (a mod folder / Paks folder / audio folder). Running without them is not a real failure. `test_pakwrite.py <work dir>` builds its own data; `test_locres.py` and `test_resize.py` also need a path argument.
- Synthetic paks: `mgp_pakwrite.write_pak(dest, [(name, path)])`, AES key `"00"*32`. I used a 6000-file synthetic pak to profile `staged_files`.
- Smoke-test the server: start `webui.py`, send a real HTTP request with header `X-MGP-Token` (token printed/embedded in the page). A past bug (`time` not imported) only showed up this way.

## Front end
- Syntax-check the page script: extract the largest `<script>` block of `webui.html` to a file and run `node --check` on it (regex `<script>(.*?)</script>`, pick the longest match).
- `tests/jsd/*.js` are jsdom harnesses (`npm i jsdom` in that folder). **They hardcode `/home/claude/mgp_editor/webui.html`** — change the path. `hi3.js` is the current HUD-import one; `hi.js` was stale and removed from this repo.

## Offline proofs for HUD/font edits
Parse the result with `uprops.Asset(ua, ux)` and `parse_export(i)` for every export; check header `total == len(ua)`, `SerialSize` unchanged where expected, `SerialOffset` == header length for first export. These prove consistency only — **in-game behavior must be tested by the user**.

## Fixtures I used (not in repo — recreate)
GP24 originals of `RaceHud_BP`/`HUDRacePage` (supplied by user), SBK versions imported, `PenaltyTime`, `TimedSessionPenaltiesInfoWidgetManagerBP`, `MotoGPText_Regular` (Font), `F_TTSupermolotNeue-Regular_Mono_Font`. Ask Faizal to re-upload if needed.
