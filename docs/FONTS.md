# Fonts — replacing GP24 fonts with TT Supermolot

## Asset model (UE 4.27)
- `Font` asset (`MotoGPText_Regular`, `Geogrotesque_Regular`, …): export class `Font`, properties include `CompositeFont` → `DefaultTypeface` → `Fonts[]` (TypefaceEntry → FontData → **FontFace import**), plus `FallbackTypeface` (CJK: `ArialUnicodeMS_JAPMilestone`, `NotoSans-JPN`).
- `FontFace` asset (`MotoGPText-Regular`, `FF_TTSupermolotNeue-Regular_Mono`): the font data; sometimes with a `.ufont` file.
- Hyphen vs underscore: `X-Regular` is typically the FontFace, `X_Regular` the Font.
- Faizal's SBK-sourced assets: `F_TTSupermolotNeue-{Bold,Light,Regular}_Mono_Font` (Font) and `FF_TTSupermolotNeue-{Bold,Light,Regular}_Mono` (FontFace). The `FF_` ones work in GP24; the `F_…_Font` / `MotoGPText-*_Mono_Font` Font assets do **not** (serial size mismatch crash: file has 359 bytes, game's loader reads 358).

## Tool (v66→v70) — button hidden since v83 (Faizal copies the Fonts folder from his working pak instead)
`hudskin.font_faces`, `font_weight`, `retarget_font(ua, {old_face: new_face})`: repoints the Font asset's FontFace + package **import records** to `/Game/assets/ui/Fonts/FF_TTSupermolotNeue-<Weight>_Mono`, weight inferred from names (Bold/Black/Heavy→Bold, Light/Thin→Light, else Regular; italics fall back to Regular). Skips fallback CJK faces (`FONT_KEEP`). Endpoints `/api/fonts/list` (rows + skipped reasons + origin) and `/api/fonts/apply`. Verified offline on his `MotoGPText_Regular` (export size unchanged 2192, offsets consistent). **Not verified in game.**
Default-unticked in the list: Digital-7, Accelerator, Vehicle_*, American_Purpose, Characters_Font_Foundry, F_TTSupermolot*.

## What happened in the session
1. v66 applied; later the game crashed: `Font /Game/assets/ui/Fonts/MotoGPText-Regular_Mono_Font … Serial size mismatch: Got 358, Expected 359` (LowLevelFatalError, FAsyncLoadingThread). That asset was **not** produced by the tool: it's an SBK Font (359 B matches `F_TTSupermolotNeue-Regular_Mono_Font`), most likely arriving via "Import everything".
2. He deleted the MotoGPText fonts from the mod folder → the font list stopped showing them: skip reason "not a .uasset (bad magic)". Hypothesis: the tool still had his old pak open after a repack (stale offsets). Restart fixes.
3. His **own manual attempt worked flawlessly** (fonts incl. leaderboard). Current decision: **use the tool for the HUD only, and copy the Fonts folder from his working pak**; HUD import now has "Untick fonts" and Select all skips fonts (v70).
4. Last observation: in a HUD attempt, **leaderboard font still not replaced** → leaderboard widgets reference a Font asset the swap did not cover (or it wasn't listed). If revisiting: scan the leaderboard widgets' `Font.FontObject` imports to see which Font assets they use, add a "which fonts does this page use" report.

## Ideas
- "Fonts used by page X" report (resolve Font imports of widgets in HUDLeaderboardWidgetBP etc.).
- Rebuild SBK-style Font assets from GP24's own Font as donor (rename export/package names, repoint face) if a Font must exist at an SBK path.
