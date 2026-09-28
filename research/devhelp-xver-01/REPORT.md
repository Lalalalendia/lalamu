# DEVHELP-XVER-01 — Publisher 2002 → 2003 topic-surface partial diff

## Exact inputs

The analysis consumed only the already-pinned English `VBAPB10.CHM` artifacts. No new media search was performed and no CHM/media bytes are committed here.

- Publisher 2002: 656,752 bytes; SHA-256 `688a5a4c5ec209740ba2506e322fc9c8070747c0d9cc7b59560e0a0bea2acf51`; source artifact 10802143151.
- Publisher 2003: 1,180,470 bytes; SHA-256 `796e0a899e5b691d04895590206113f112816fe161250486b787f82af4ac5418`; source artifact 10809962912.

Both hashes and lengths were verified before interpretation.

## Proven topic-directory delta

The source-safe extractor reads only uncompressed CHM container paths matching `/html/pb*.htm`. This proves topic identities/categories, not topic-body semantics.

| Surface | Publisher 2002 | Publisher 2003 | Delta |
| --- | ---: | ---: | ---: |
| Unique topics | 692 | 892 | +200 net |
| Objects | 87 | 111 | +24 |
| Methods | 172 | 198 | +26 net |
| Properties | 406 | 550 | +144 net |
| Events | 22 | 21 | -1 |
| How-to | 3 | 4 | +1 |

Exact set comparison is stronger than the net counts: **207 topics were added, 7 removed, and 685 are common**.

### Added object topics

AdvancedPrintOptions, BorderArt, BorderArtFormat, BorderArts, CatalogMergeShapes, ColorsInUse, Documents, FindReplace, HeaderFooter, InlineShapes, Label, Labels, PageBackground, PrintablePlate, PrintablePlates, PrintableRect, Section, Sections, WebNavigationBarHyperlinks, WebNavigationBarSet, WebNavigationBarSets, WebOptions, WebPageOptions, and `pbobjtocPages`.

### Added method topics

AddCatalogMergeArea, AddEmptyPictureFrame, AddSet, AddToCatalogMergeArea, AddToEveryPage, AddWebNavigationBar, BeginCustomUndoAction, ChangeOrientation, ConvertPublicationType, ConvertToProcess, Create, DeleteSetAndInstances, EndCustomUndoAction, ExportEmailHTML, FindPlateByInkName, MoveIntoTextFlow, MoveOutOfTextFlow, Redo, RemoveCatalogMergeArea, RemoveFromCatalogMergeArea, Replace, RevertToDefaultWeight, RevertToOriginalColor, Set, SetBackgroundSoundRepeat, SetListType, Undo, and WebPagePreview.

### Removed topics

- event: `pbevtMailMergeWizardSendToCustom`
- methods: `pbmthDiscardConflict`, `pbmthOfflineConflict`
- properties: `pbproDestination`, `pbproMultiplePagesPerSheet`, `pbproPageHeight`, `pbproPageWidth`

The full 207-added / 7-removed topic-ID set is retained in `research/devhelp-xver-01/topic-surface-diff.json`.

## Evidence boundary

This is a **strong partial** result for DEVHELP-XVER-01, not task closure.

Proven:
- exact input identity;
- topic path identities;
- object/method/property/event category counts;
- exact added/removed topic-ID sets.

Not yet proven:
- topic body text;
- parameter signatures;
- return types;
- enum/type values;
- Help IDs beyond the path IDs;
- applicability/version prose;
- intra-help links;
- rename/move equivalence beyond exact topic IDs.

The current environment does not contain an admissible CHM/LZX decompressor, so compressed topic bodies were not decoded. This residual must remain explicit rather than approximated from filenames.

**No documentation delta in this report is a PUB wire-format claim.**
