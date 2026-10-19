# Project context

## Goal
Faizal mods **MotoGP 24** (Steam, UE 4.27). He sells livery mods (Patreon/Trakteer) and is building a larger mod (working name "GP24 Mod sbk26") that brings **Superbike (SBK 22/25-era) HUD, sounds, fonts and tracks** into MotoGP 24. The tool automates the tedious asset surgery that UAssetGUI/FModel can't do in bulk.

Workflow: tool opens a **mod folder** (loose `Content/...` files) layered over the game's paks → edits are *staged* → **Save** writes them to the mod folder → **Pack mod** writes one `*_P.pak` (v8, uncompressed, unencrypted) → copy to the game's `Paks` folder → test in game.

## Feature inventory (all built; see README.txt for user-facing docs)
- Riders & bindings: replace / copy look / clone entries; edit assets via UAssetGUI; clone audit.
- Check tab: bindings check, team sync, clone audit.
- Port audio: copy a bike's Wwise bank + events + BikeAudio from another game (Wwise bank v140). Has **Gain dB** (v55): GP24 containers sit +3..+9 dB, SBK at 0, so ported bikes sound quieter; +6 was the suggested start (untested by the user).
- Browse (FModel-lite), Localization (.locres), Replacement sheet (CSV in/out), Database editor (sqlite from paks), Setup.
- Pack mod / Launch game; background jobs with toast + "View log".
- **HUD skin tab** (the most active area — see below):
  - Skin compare/apply (copy colours/fonts/brushes of same-named widgets; never touches slots/positions).
  - Import whole files from another game's extracted folder (+ crash scan for classes the game lacks; "Untick penalty / warning"; font files are never imported since v72).
  - "Check my mod for crashes": any `/Script/<module>` class the game lacks, using **base paks only**.
  - Show/hide widgets (Visibility editor) for any page.
  - **Use GP24's penalty widget (RaceHud_BP)** — retype graft (v63/64/71).
  - **Swap stewards box / jump-start & long-lap positions** (v65–68).
  - **Replace fonts with TT Supermolot** (v66–70) — see `FONTS.md`.

## Session history (condensed)
1. v55–v62: audio gain, visibility tool, untick penalty, extended crash check, perf fixes (staged_files size-first cache), import "changed vs identical" summary, version-mismatch banner, rename to MGP24, `[slow]` request logging.
2. v63–v71: HUD penalty graft (see `HUD_PENALTIES.md`), fonts, import safety for fonts.
3. User asked to carry the project into Claude Code; this repo is that hand-off.

## Who Faizal is (relevant bits)
19, Indonesia, 3D artist / livery modder, self-taught; uses Windows, Chrome, UAssetGUI, Blender, Photoshop. Game path example: `F:\SteamLibrary\steamapps\common\MotoGP™24\motogp24\Content\Paks`. Writes casually; "bruh/argh" = frustrated, wants the shortest path to something working.
