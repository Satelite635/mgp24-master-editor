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

## MotoGP 26 banks (Wwise v154) → GP24 (v140), see `bnkport.py`
- GP26 bike banks keep GP24's Sound/source/media ids, so only media + REV settings are swapped into GP24's bank. A v154 bank itself is rejected by GP24.
- `.wem`: v154 adds a 16-byte `hash` chunk; drop it, pad RIFF to even. Audio data is identical otherwise.
- Engine = CrankcaseAudio REV (plugin 0x01a01052, in GP24's Init.bnk too). Model media: GP26 `PLUG` (hash, junk, data) around `ADM3` v7; GP24 raw `ADM3` v6. ADM3 version = u16 @10. Each `SMP2` entry: version u16 @10 (5 → 4), size u32 @0x24, absolute offset u32 @0x2c (16-byte aligned). Sample data = ADPCM blocks of 64 samples: v7 35 bytes (s16 big-endian predictor, u8 step, 32 nibble bytes), v6 34 bytes (`q=(pred+64)>>7` as 9 bits: `q>>1`, `(q&1)<<7 | step`, same 32 bytes). A v7 model in a GP24 bank plays silent (tested).
- REV settings: HIRC FxCustom (type 17) with the REV source's id; its 212-byte param block is copied, GP24's RTPC tail kept.

## Localization
`.locres` read/write only if a no-change rewrite is byte-identical; tested on synthetic files only.
