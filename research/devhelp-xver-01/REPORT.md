# DEVHELP-XVER-01 — Publisher 2002 → 2003 structured developer-help diff

## Result

The exact English Publisher 2002 and Publisher 2003 `VBAPB10.CHM` pair has now been provenance-pinned, decompressed offline, normalized, and compared at both topic-directory and topic-body-structure levels.

This is no longer a topic-name-only partial. The retained evidence covers:

- canonical object/method/property/event/help topic identities;
- signatures and overloads;
- argument names, optionality and types where help exposes them;
- return-type candidates where recoverable without retaining prose;
- enum/type constant groups and numeric values where present;
- Help/topic metadata;
- applicability helper links;
- intra-help links;
- strong rename/move candidates;
- independent continuity checks against current Publisher documentation and the existing Publisher TLB/PIA evidence.

No full CHM help prose and no raw CHM/media bytes are committed to this repository.

## Exact provenance

### Publisher 2002 / Office10

The Publisher 2002 side comes from the provenance-pinned `X08-20172` physical-media identity.

- source family: Publisher 2002 / Office10 English media;
- recovered media container: `X08-20172`, volume `OFFICE10`;
- converted ISO: 265,431,040 bytes;
- converted ISO SHA-256: `2f0b7e4fa0a536f126ff4f63b7c2669cd31fba8adc744cfcc68eb780ee784c8d`;
- Publisher MSI File table maps `VBAPB10.CHM` at 656,752 bytes;
- Publisher MSI Media table maps the payload to `OFFICE1.CAB`;
- exact extracted English/1033 CHM: 656,752 bytes;
- CHM SHA-256: `688a5a4c5ec209740ba2506e322fc9c8070747c0d9cc7b59560e0a0bea2acf51`;
- retained source artifact: GitHub Actions artifact `10802143151`.

Historical install-path evidence places this carrier at `Office10\1033\VBAPB10.CHM`.

### Publisher 2003 / Office11

The Publisher 2003 side comes from Internet Archive item `X10-14992`, selected as Microsoft Publisher 2003 English media.

- selected media: `X10-14992.ISO`;
- volume: `OFFICE11`;
- media size: 191,750,144 bytes;
- media SHA-256: `23c495d63e2d4f4486dd28cbeebf423518d7af77f28f9abdae8484da2de13036`;
- Publisher MSI: `PUB11N.MSI`;
- MSI File row identifies English/1033 `VBAPB10.CHM` at 1,180,470 bytes;
- exact CHM SHA-256: `796e0a899e5b691d04895590206113f112816fe161250486b787f82af4ac5418`;
- retained source artifact: GitHub Actions artifact `10809962912`.

Historical install-path evidence places this carrier at `Office11\1033\VBAPB10.CHM`.

## Extraction boundary

GitHub Actions run `36418154234` built a source-safe read-only CHM extractor runtime and uploaded artifact `10968014431`. The exact pinned CHMs were decompressed offline with that runtime.

A critical container detail was found during extraction: the CHMs contain both canonical `html/pb*.htm` topics and a `links/` helper/alias namespace. Counting every `pb*.htm` would roughly double the surface and create false differences.

The final normalizer therefore:

- counts only `html/pb*.htm` as canonical topics;
- uses `links/*_L.htm` only for applicability relationships;
- canonicalizes local topic links case-insensitively;
- extracts structural API metadata;
- hashes body sections rather than retaining help prose.

## Surface delta

Canonical topic counts:

| Surface | Publisher 2002 | Publisher 2003 |
| --- | ---: | ---: |
| Canonical topics | 692 | 892 |
| Common topic IDs | 685 | 685 |
| Added in 2003 | — | 207 |
| Removed from 2002 surface | 7 | — |

The exact 207-added and 7-removed sets are in `added-removed.json`.

The seven removed topic IDs are:

- `pbevtMailMergeWizardSendToCustom`
- `pbmthDiscardConflict`
- `pbmthOfflineConflict`
- `pbproDestination`
- `pbproMultiplePagesPerSheet`
- `pbproPageHeight`
- `pbproPageWidth`

## Signature changes on common topics

Eight common topic IDs have normalized signature changes:

1. `pbmthAdd` — Page add gains optional `AddHyperlinkToWebNavBar`; a second Add family exposes `IsTwoPageMaster`, `Abbreviation`, and `Description`.
2. `pbmthAddWizardPage` — adds optional `AddHyperLinkToWebNavBar`.
3. `pbmthDelete` — adds `Delete(PlateReplaceWith, ReplaceTint)`.
4. `pbmthExecute` — Publisher 2003 exposes `Execute` and `Execute(Pause, Destination, Filename)` where 2002 exposed `Execute(Pause)`.
5. `pbmthInsert` — adds `Insert(Range)`.
6. `pbmthMove` — adds `Move(Page, [After])`.
7. `pbmthSaveAs` — `FileName`, `Format`, and `AddToRecentFiles` become optional in the documented signature.
8. `pbproRange` — adds indexed `Range(Index)`.

The exact before/after signatures are retained in `signature-argument-diff.json`.

## Argument changes

Eight common topics have material argument metadata changes.

Notable examples:

- `pbmthAddWizardPage`: optional Boolean `AddHyperLinkToWebNavBar`;
- `pbmthDelete`: optional `PlateReplaceWith: Plate` and `ReplaceTint: pbReplaceTint`;
- `pbmthExecute`: optional `Destination: PbMailMergeDestination` and `Filename: String`;
- `pbmthFindRecord`: `Field: String` changes from required to optional;
- `pbmthInsert`: optional `Range: TextRange`;
- `pbmthMove`: required `Page: Long` plus optional `After: Boolean`;
- `pbproRange`: optional `Index: Long`.

## Enum/type-group changes

Eight common topics expose changed enum/type constant surfaces. The retained `enum-diff.json` records the exact small deltas and a hashed/sample representation for the large `MsoLanguageID` expansion.

Material examples:

- `PbWebControlType` adds `pbWebControlHotSpot`;
- `ReplaceTint` appears with `pbReplaceTintKeepTints`, `pbReplaceTintMaintainLuminosity`, and `pbReplaceTintUseDefault`;
- `PbMailMergeDestination` appears with `pbMergeToExistingPublication`, `pbMergeToNewPublication`, and `pbSendToPrinter`;
- `PbHelpType` loses three documented constants;
- `PbFileFormat` adds `pbFileHTMLFiltered`;
- `PbOrientationType` appears with landscape/portrait;
- `PbShapeType` adds CatalogMerge/WebNavigationBar-related constants;
- the `Language` topic gains a large `MsoLanguageID` table.

Numeric enum values are retained only where the help table actually exposes them; missing values are not invented.

## Object-title changes

Three common object topics change their documented kind from “Object” to “Collection”:

- `pbobjMailMergeFilters`
- `pbobjObjectVerbs`
- `pbobjWebHiddenFields`

## Rename/move candidates

Three removed 2002 property-topic IDs have new 2003 IDs with identical titles and identical normalized signatures:

- `pbproMultiplePagesPerSheet` → `pbproMultiplePagesPerSheet1`
- `pbproPageHeight` → `pbproPageHeight1`
- `pbproPageWidth` → `pbproPageWidth1`

These are retained as **strong rename/move candidates**, not as proven historical typelib renames. Exact 2002/2003 PIA member identity is required to upgrade that interpretation.

## Independent TLB/PIA cross-check

The existing semantic-namespace evidence independently pins:

- Publisher 2002 PIA: `Microsoft.Office.Interop.Publisher 10.0.4504.0`;
- Publisher 2003 PIA: assembly `11.0.0.0`;
- Publisher 2007 PIA: assembly `12.0.0.0`.

A particularly relevant independent discriminator is `Plate.Delete`: the same Plate IID survives, but `Delete` changes from DISPID 9 in PIA10 to DISPID 10 in PIA11. That independently confirms a versioned `Plate.Delete` semantic-surface change across the same 2002→2003 boundary where the CHM adds the `PlateReplaceWith, ReplaceTint` overload.

The current installed Publisher16 `MSPUB.TLB` inventory is also exact and provenance-pinned:

- library GUID `{0002123C-0000-0000-C000-000000000046}`;
- typelib version 2.3;
- 237 types;
- 3,015 FUNCDESC;
- 1,129 VARDESC;
- zero extraction/type-decode errors;
- file SHA-256 `7a831d3eabf88bc7c11fd4fd6eff4b75638d8bb5097eb3c5279332260153a3c9`.

Current Microsoft Publisher VBA documentation additionally corroborates continued existence of representative changed/new surfaces:

- `Document.BeginCustomUndoAction(ActionName)` and `EndCustomUndoAction`;
- `Pages.Add(... AddHyperlinkToWebNavBar)`;
- `Pages.AddWizardPage(... AddHyperlinkToWebNavBar)`;
- `MailMerge.Execute(Pause, Destination, FileName)` with `PbMailMergeDestination`;
- `Document.SaveAs(... Format:=pbFileHTMLFiltered)`.

These current sources corroborate continuity only. They do not replace the pinned Publisher 2002/2003 pair for historical introduction dating.

## Help/topic identity

The two generations also change help metadata style across nearly all 685 common topics:

- Publisher 2002 commonly exposes `Tnum`, `Filename`, `Ver`, and `ProjApp`;
- Publisher 2003 commonly exposes `assetid` and `lcid`.

This is preserved as help identity/version metadata, not treated as Object Model semantic change by itself.

## Evidence files

- `topic-surface-diff.json` — original source-safe topic-directory set diff;
- `body-structure-summary.json` — canonical counts, coverage, rename candidates, boundaries;
- `added-removed.json` — exact 207 added / 7 removed topic IDs grouped by category;
- `signature-argument-diff.json` — normalized signature and argument deltas;
- `enum-diff.json` — normalized enum/type-group deltas;
- `continuity-crosscheck.json` — PIA/TLB/current-documentation continuity boundary.

## Interpretation boundary

This result is documentation/Object Model evidence.

It does **not** establish:

- a PUB wire-format field;
- a serializer change;
- that every 2003-added API creates new persisted state;
- that a renamed help topic implies a renamed typelib member;
- that a current TLB member existed in 2003.

Any claimed persistence implication must become a separate bounded experiment joining a versioned Object Model operation to observed/reopened Publisher state and exact PUB byte deltas.
