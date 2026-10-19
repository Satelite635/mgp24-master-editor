# HUD penalties — the active problem (read this first)

## Situation
Faizal imported SBK's `RaceHud_BP` (+ `HUDRacePage`) into GP24 to get SBK's HUD layout. SBK's penalty widgets rely on SBK game logic, so in GP24 they show wrongly: an **orange "+1.356" box** (design-time placeholder of `PenaltyTime_C`) stays on screen and real penalties don't show. Goal: **SBK layout + GP24's working penalty/steward/alert widgets**.

## What I learned (facts)
- SBK `RaceHud_BP` has: `PenaltiesInfoWidgetManagerBP` (in `VerticalBox_1`, slot `VerticalBoxSlot_0`), `PenaltyTime` (`PenaltyTime_C`), `WarningHUDSmallWidget`, `LongLapHUDWidget_189`, `LongLapRemainingLapsHUDWidget`, `FlagsManagerWidget_BP` (flags work fine from the start — never touch), `RaceDirectorHUDNoTimerWidget_2020`. `HUDRacePage` export has `NamedSlotBindings` (Penalty, WarningSmall, LongLapSmall, LongLapRemainingLap, PenaltiesManager…).
- GP24 `RaceHud_BP` has instead: `WB_RacePenaltiesWidgetContainer` (canvas child, `CanvasPanelSlot_11`, bAutoSize) = the "MotoGP Stewards / UNDER INVESTIGATION / Warning / CRASH" box, and `PlayerAlertsHUDWidget_BP` (in a VerticalBox) = the player's own alerts ("Jump start", "Long Lap Penalty x2").
- `PenaltyTime_C` extends C++ `TimePenaltyWidget`; SBK versions of some classes need C++ classes GP24 lacks (e.g. `InvalidLapWidget`) → crash on load. `TimedSessionPenaltiesInfoWidgetManagerBP` crashed with "Could not find SuperStruct PenaltiesInfoWidgetManager".

## Solution implemented: "retype" graft (no new exports/slots needed)
`hudskin.retype_widget(ua, ux, donor_ua, from_cls, to_cls)` repoints the **three import records** of the SBK widget class (package, class `WidgetBlueprintGeneratedClass`, `Default__` object) to the GP24 class's package/name (names appended with `append_name`). Export indices, sizes and dependency lists don't change. Donor = the game's own `RaceHud_BP` via `PakSet.read_base`.
`/api/hud/graft` (`hud_graft`, button "Use GP24's penalty widget (RaceHud_BP)") does:
1. `PenaltiesInfoWidgetManagerBP_C` → `WB_RacePenaltiesWidgetContainer_C`
2. `WarningHUDSmallWidget_C` → `PlayerAlertsHUDWidget_BP_C`
3. Collapses the other warn-ish widgets (`PenaltyTime`, long-lap ones) via `set_visibility`, un-collapses the two grafted ones (`SelfHitTestInvisible`), never touches flags.
4. v71: idempotent — runs the hide step even if nothing needed swapping; only errors if truly nothing to change; popup lists which widgets changed.
`_race_target()` forces the target to `RaceHud_BP` regardless of the dropdown (v68 fix; the dropdown was the cause of confusing "already done"/"run first" errors).

`/api/hud/swappos` (`hud_swappos`, "Swap stewards box / jump-start & long-lap positions"): `hudskin.swap_widget_types` exchanges export-record fields `[0:12]` (class, super, template) and `[84:104]` (dependency fields) of `PenaltiesInfoWidgetManagerBP` and `WarningHUDSmallWidget`, so each keeps its slot but shows the other widget. It is a **toggle** (works either way round). Added because after the graft the stewards box and the alerts appeared in each other's expected places.

## In-game results so far
- v63/v64 graft: stewards box + warnings + crash entries + green flag appear; alerts initially missing → v64 grafted `PlayerAlertsHUDWidget_BP`; then "everything shows up" (screens: Jump start / Long Lap Penalty x2 at bottom-right, "UNDER INVESTIGATION" top-centre) but **inverted** vs what he wants → swap button (v65). After swap (screenshot) the alerts are top-centre and it looks right.
- Last screenshot (Oct 19, 22:xx): he started from his *own attempt's pak*, clicked only "Use GP24's penalty widget" (v70 or earlier) and the **orange +1.356 box was still visible**. Hypothesis: the pak's `RaceHud_BP` was already grafted, the button stopped at "already done" and never ran the hide step. **v71 fixes that; not yet confirmed by him.** If the box is still there after v71, ask for the popup text: it lists which widgets were changed — check whether `PenaltyTime` is in the list; if not, the widget may have another name/class in that file (inspect with the "Show / hide widgets" table; `PenaltyTime` column "Now").

## Things that were wrong earlier (don't repeat)
- I claimed the mod folder still held SBK `RaceHud_BP` (Explorer showed otherwise).
- Skin "Compare" shows 0 patchable because it skips slot layout.
- Flag widgets were wrongly in the penalty regex (flags worked; removed). Collapse button over-collapsed manager widgets.
- The visibility "Apply" once appeared to reset dropdowns (UI re-render after refresh); fixed.
- GP24's `PlayerAlertsHUDWidget_BP` normally lives in a VerticalBox bound to PenaltiesManager — here it sits in SBK's `WarningSmall` slot, so sizing/position may need tuning.

## Possible next steps
- Confirm v71 in game; if layout is off, add a "copy slot layout" tool (slots of the 8 widgets both pages share: leaderboard, race pace, raise-bike, a few dev ones) or tune slots directly.
- A true graft (adding widget + slot + imports to the page) is only needed if retyping proves insufficient.
- Idea: let the HUD import skip all penalty/warning files by default and run the graft automatically after import.
