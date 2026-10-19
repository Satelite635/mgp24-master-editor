# Open items / next steps (priority order)

## Waiting on Faizal's in-game results
1. **v71 penalty graft**: does the orange "+1.356" box disappear when starting from his working pak and clicking only "Use GP24's penalty widget"? If not → get the popup text; inspect `PenaltyTime` visibility via "Show / hide widgets".
2. **Layout check** of the swapped steward box / alerts (sizes may be off because each widget sits in the other's slot). Possible tool: copy slot layout between widgets.
3. **Port audio Gain** (+6 dB suggested) — untested.
4. **Fonts**: decision was "tool for HUD only, copy Fonts folder from his working pak". The retarget tool's output is unverified in game. If he wants it to work: find why the **leaderboard font** wasn't replaced (which Font asset do `HUDLeaderboardWidgetBP` texts use?). Consider a "fonts used by this page" report. Also determine whether the game's original `MotoGPText_*` fonts are really in the base paks (his list stopped showing them after he deleted loose copies; skip reason was "bad magic" — likely stale pak handle; v72 re-reads changed paks automatically).

## Tool improvements worth doing
- ~~Reopen/refresh `PakSet` after Pack mod~~ done in v72 (auto refresh); unconfirmed in game.
- Make HUD import smarter: skip fonts and penalty/warning files by default; offer to run the graft right after import.
- Crash scan: detect SBK-format Font assets (serial size mismatch) — currently only missing `/Script` classes are detected.
- Optionally move heavy actions (Port audio, extract) onto the background job log.
- Slot-position copy tool for the 8 widgets the two pages share (leaderboard, race pace, raise-bike + a few dev ones).

## Riding style (v73) — waiting on Faizal
- Check in game that an edited/copied riding style changes the rider's animation, and that a row added for a rider without one doesn't crash. Field meanings (SubRidingStyle 0-6, RidingStyle 6 has no preset row, LegOutType, StartLeg -1/0/1) are not known — only numbers shown.

## Feature ideas agreed to keep (Oct 19)
- Customer pack export (one-click pak + readme), before/after preview sheet, `~mods` conflict checker.
- Pre-pack crash check (refuse to pack on missing `/Script` classes / SBK Fonts), snapshots/undo, pak diff, HUD widget-tree viewer.
- Cross-game: compatibility report for another Milestone game's pak/map (what's missing in GP24), generalized `/Script/motogpXX` → `/Script/motogp24` import retyping, rider/team data editor, bike sound port per bike, gear port from other games. Track import: visual-only swaps realistic; full tracks need AI lines/timing/DataTables + game-specific Blueprints.

## Feature requests not started
- **Track variant import from GP22** (same layout, different variant): needs the track name and GP22 files from Faizal; proposed a diff-based audit tool (compare GP22 vs GP24 assets to show what differs).
- **SBK-style weekend format** and full-season helpers.
- Cloning NEW gear sets (helmet/suit) — only bikes are cloneable.
