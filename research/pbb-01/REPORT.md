# PBB-01 — first real Publisher Building Blocks corpus

## Hosted/static result

The previously known GemeindebriefDruckerei Publisher Page Parts package is live and recoverable. The exact HTTPS target returned HTTP 200 as `application/zip` with no redirect.

- ZIP: **7,593,658 bytes**
- SHA-256: `752a519f01d2fd24ed019c547b7dff27b1509150fdce2b1a6f84e093e694f32f`
- ZIP entries: **94**
- `.pbb` entries: **94**

The HTTP form redirects once to the same HTTPS object and yields byte-identical content.

No raw ZIP or PBB bytes are committed to this repository.

## Container identity

All **94/94** recovered PBB files are Microsoft Compound File Binary containers.

Across this corpus:

- CFB magic is `D0 CF 11 E0 A1 B1 1A E1`;
- root CLSID is always `00021201-0000-0000-00C0-000000000046`;
- root `CompObj` always exposes `Microsoft Publisher 3.0` / `MSPublisher.3`;
- ordinary Publisher-family streams are present: `Contents`, `Escher/EscherStm`, `Quill/QuillSub/CONTENTS`;
- every file additionally has a non-empty **`BBStoreInfo14`** stream.

This establishes a bounded physical model for this real corpus: the building-block files are Publisher CFB documents carrying an explicit building-block metadata stream, not a new unrelated container family.

File sizes range from **599,040** to **1,369,088** bytes, median **1,167,872**.

## Stream grammar across 94 files

Ten streams are present in every sample:

- `\x01CompObj`
- `\x03Internal`
- `\x05SummaryInformation`
- `BBStoreInfo14`
- `Contents`
- `Envelope`
- `Escher/EscherDelayStm`
- `Escher/EscherStm`
- `Quill/QuillSub/\x01CompObj`
- `Quill/QuillSub/CONTENTS`

`\x05DocumentSummaryInformation` is present in **91/94**. It is absent only from:

- `DS00B001.pbb`
- `ES01B002.pbb`
- `ES01B003.pbb`

`Escher/EscherDelayStm` is non-empty in **89/94**; it is empty in `DS00B001.pbb` and `ES00B001..004.pbb`.

The content-bearing families vary per building block:

- `Contents`: 94 unique hashes, 7,160–15,154 bytes;
- `Escher/EscherStm`: 94 unique hashes, 1,658–16,864 bytes;
- `Quill/QuillSub/CONTENTS`: 94 unique hashes, 2,048–13,824 bytes;
- `BBStoreInfo14`: 94 unique hashes, 1,242–1,432 bytes.

## BBStoreInfo14 metadata

Every `BBStoreInfo14` exposes the same bounded metadata grammar:

- `BBStore version="2"`;
- exactly **one Item per PBB**;
- fields `Title`, `Size`, `Description`, `Category`, `Keywords`, `Type`, `CreationTime`, `LastUseTime`, `Filename`, `PreviewText`, `InsertGallery`, `ShowInGallery`, `Cct`, `IsLinkedPicture`, `IsRTLTextbox`, `IsDownloaded`, `IsBuiltIn`.

Corpus invariants:

- `Title` matches the PBB filename stem in **94/94**;
- `Filename` matches the PBB filename stem in **94/94**;
- `Category = GemeindebriefDruckerei` in **94/94**;
- `Type = 1` in **94/94**;
- `InsertGallery = 4` in **94/94**;
- `ShowInGallery = 1` in **94/94**;
- `Cct = 33456232` in **94/94**;
- `IsLinkedPicture = IsRTLTextbox = IsDownloaded = IsBuiltIn = 0` in **94/94**;
- `Keywords`, `LastUseTime`, and `PreviewText` are empty in **94/94**.

`CreationTime` is unique for all 94 samples. `Description` has 66 distinct values and is empty in 29 files. `Size` has 42 distinct values.

The numeric gallery values are recorded as observed metadata only; this static pass does not universalize their enum meaning without the native/API join.

## Negative discriminator

A byte/token scan across all 94 samples found the ordinary metadata names above, but **no occurrence in any file** of:

- `ContentStore`
- `BBStyle`
- `desID`
- `wid`

That is a corpus-bounded negative only. It does not prove those concepts cannot appear in another Publisher-generated PBB generation.

## What this closes

The hosted/public acquisition seam and the first physical/container inventory are closed:

- real PBB bytes recovered;
- exact package provenance and hash pinned;
- container/signature identified;
- common and exceptional stream layouts inventoried;
- building-block metadata carrier identified and normalized.

## What remains

The parent PBB-01 definition of done also requires one **PBB → AddBuildingBlock → PUB** native comparison. That is intentionally not simulated here.

The next discriminator is therefore a Publisher 2010+ runtime arm:

1. select one recovered sentinel PBB;
2. add it through the native Building Block API/UI;
3. save and reopen the resulting PUB;
4. join the PBB's `Contents` / Quill / Escher / `BBStoreInfo14` metadata to the materialized Shape/object graph in PUB;
5. record which metadata survives, which only drives insertion, and which identifiers are regenerated.

Until that native arm is completed, this task must remain open/blocked rather than be marked Done.

## Authority fence

No Publisher executable was run in this hosted pass. No AddBuildingBlock semantic claim is made. No PUB wire-format field is inferred solely from PBB metadata.
