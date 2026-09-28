# HTML-VECTOR-01 — exact Publisher 2003 setup static discriminator

## Result

The hosted/static arm is **bounded-negative** on the exact Publisher 2003 media and does not prove the pub / pub11 IE Version Vector setup write.

The exact X10-14992 ISO was reacquired and hash-verified, then its complete MSI setup surface was inspected without installing or executing Publisher/Office.

## Exact provenance

- Media: X10-14992.ISO
- Size: **191,750,144 bytes**
- SHA-256: 23c495d63e2d4f4486dd28cbeebf423518d7af77f28f9abdae8484da2de13036
- SHA-1: a108158fe57f7bf0ff5b45c34fe4593acf320454
- MD5: c3d3ee8e2257f5d01a53019238346a0a
- ISO volume: OFFICE11
- Exact media contains **one MSI**: PUB11N.MSI
- FILES/SETUP/SETUP.INI points to MSI=PUB11N.MSI

Publisher MSI identity:

- SHA-256: a1af606676a1911004788def2e5d5124693550aec6ba77501197658a3695e982
- Size: **2,285,568 bytes**
- Product: Microsoft Office Publisher 2003
- Version: **11.0.5614.0**
- ProductLanguage: **1033**
- ProductCode: {91190409-6000-11D3-8CFE-0150048383C9}

## Static MSI result

The MSI exposes **76 tables**. The workflow exported **74 text-safe tables** and inspected **19,367 rows**.

There are:

- **0** direct Registry rows writing pub or pub11 under Software\\Microsoft\\Internet Explorer\\Version Vector;
- **0** matching CustomAction rows;
- **0** matching Property rows;
- **0** matching InstallExecuteSequence / InstallUISequence rows;
- exactly **1** table-level pub11 signal: a Shortcut row named Pub11|Microsoft Office Publisher 2003, which is ordinary product shortcut naming and not Version Vector evidence.

A static scan of the exact media found seven files containing either Publisher-11 naming or generic Internet Explorer strings. None contains Version Vector. The setup metadata hits are limited to normal product/package naming such as PUB11N.MSI; generic IE strings occur in unrelated readme/cleanup/error-reporting surfaces.

## Interpretation

This falsifies the **simple MSI Registry-table hypothesis** for the exact X10-14992 Publisher 2003 media.

It does **not** universally falsify that some install-time/native mechanism may create the IE Version Vector token, because a setup executable or runtime operation could perform a write without carrying an obvious static string/table row.

Therefore the parent task must move to its already-defined fallback discriminator:

1. provenance-closed pre/post install registry snapshot, or
2. era-appropriate IE conditional-comment behavior with manual pub / pub11 Version Vector creation/removal.

Until one of those runs, the semantic chain remains a strong hypothesis rather than confirmed Publisher setup behavior.

## Evidence receipt

- Clean issue: lalamu#19
- PR: lalamu#20
- Evidence run: 36426424200
- Artifact: 10970624614
- Artifact digest: sha256:10e7e811dd63962a5dff6aece1dd99c1ca36eed6c498a7678cb28d25c48437d1

## Authority fence

No Publisher/Office installation occurred. No Publisher executable was run. No Microsoft media/MSI bytes are committed or retained in this repository. No PUB wire-format claim or Chaptera model change is authorized by this result.
