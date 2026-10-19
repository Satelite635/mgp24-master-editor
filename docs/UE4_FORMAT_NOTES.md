# UE4.27 / Wwise format notes (hard-won)

## .uasset / .uexp
- Import record `<iiiiiii>` = 28 bytes: ClassPackage(idx,num), ClassName(idx,num), Outer(int, negative = import), ObjectName(idx,num).
- Export record 104 bytes: ClassIndex@0, SuperIndex@4, TemplateIndex@8, OuterIndex@12, ObjectName idx@16 num@20, ObjectFlags@24, **SerialSize@28 (int64), SerialOffset@36 (int64)**, … dependency fields `[84:104]` (firstExportDependency + 4 counts).
- SerialOffset in split assets includes the header size, so appending names shifts all export offsets (`UAsset._shift_after` handles it); total header size field (`total`) must equal `len(uasset)`.
- Retyping a widget = repoint its class's 3 imports (Package, `WidgetBlueprintGeneratedClass`, `Default__X_C`); appended names preserve the name table's other indices.
- Property tag layout (EnumProperty `Visibility`): name, type, size=8, arrayIndex, enum name, guid byte 0, value FName. Insert before the terminating `None` FName, then bump the export's SerialSize and every later export's SerialOffset (and the `bulk` offset in the header).
- A widget export's property list ends with an 8-byte `None` FName followed by extra zero bytes (4). Fonts: Font export has 8 trailing bytes after the property list (both GP24 and SBK).
- `HUDRacePage` export: `NamedSlotBindings` array of (Name, Content ref). `WidgetTree` root is `CanvasPanel_0` (SBK) or `CanvasPanel_1` (GP24 — sometimes `_0`; check).
- C++ modules: GP24 `/Script/motogp24`; SBK `/Script/sbk1`. Missing classes → "Could not find SuperStruct". Font serial mismatch → "Serial size mismatch: Got N, Expected N+1".

## Pak
- `*_P.pak` patch paks override earlier ones; mount order matters. Output: v8, uncompressed, unencrypted (AES key setup only needed for reading encrypted base paks).
- Reading a pak that was rewritten while open returns garbage ("bad magic") — reopen. v72: `PakReader.read` checks the file size and `PakSet.refresh()` re-reads changed paks.

## Wwise (bank version 140)
- HIRC objects. Sound body: `id(4) | plugin(4) | streamType(1) | sourceID(4) | inMemSize(4) | sourceBits(1) | [if plugin&0xF==2: paramSize+data] | NodeBaseParams`. After the FX block, `DirectParentID` starts at FX end + 7. Volume = prop 0 (dB). GP24 bike containers sit around +3..+9 dB; SBK ones at 0 → ported bikes are quieter; `apply_gain(bnk, db)` shifts container volumes.
- Port refuses: names that already exist, different Wwise bank versions, missing plugins. Ported gear/backfire events go into a second bank `Ported_VehicleCommon`.

## Localization
`.locres` read/write only if a no-change rewrite is byte-identical; tested on synthetic files only.
