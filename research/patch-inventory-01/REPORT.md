# PATCH-INVENTORY-01 — Publisher servicing epoch matrix

## First tranche

This pass builds the **servicing skeleton first**. It does not attempt to enumerate every Publisher security update yet.

The retained matrix covers:
- RTM/original-release boundaries where primary Microsoft sources are available;
- all traditional service-pack boundaries for the Office XP / 2003 / 2007 / 2010 / 2013 generations;
- explicit transition away from service packs for Office 2016 MSI and later Click-to-Run lines;
- separate retail and LTSC Publisher 2021 servicing models;
- a continuous servicing-model row for Publisher in Microsoft 365;
- explicit gaps for Publisher 97, Publisher 98, Publisher 2000 and any service-pack KB identity not yet pinned.

## Critical interpretation rule

An Office suite service-pack row is **not** evidence that a particular Publisher binary changed.

The matrix separates:
- `publisher_scope`: whether Publisher itself is explicitly named/applicable;
- `publisher_module_impact`: whether a Publisher-specific package/file surface is actually proven or remains unknown.

This prevents the false inference "Office SP changed -> MSPUB.EXE changed."

## Anchored servicing boundaries

### Publisher 2002 / Office XP generation
Microsoft Lifecycle pins Office XP original release and SP1/SP2/SP3 dates. Microsoft security bulletin MS06-054 independently names Office Publisher 2002 under Office XP SP3, so SP3 Publisher applicability is explicit. SP1/SP2 individual KB identities remain a gap.

### Publisher 2003
Publisher 2003 RTM is pinned separately. Office 2003 Lifecycle pins SP1/SP2/SP3, Microsoft News independently confirms SP1 availability on 2004-07-27, MS06-054 names Publisher 2003 under SP1/SP2, and later Publisher security evidence names Publisher 2003 SP3. SP3 KB923618 is pinned through Microsoft Update Catalog.

### Publisher 2007
Microsoft's Publisher 2007 Lifecycle page itself records RTM plus SP1/SP2/SP3 dates, so these are Publisher-specific servicing boundaries rather than suite-only proxies. The Office 2007 SP3 support page establishes that SP3 is cumulative.

### Publisher 2010
Publisher 2010 RTM is pinned to 2010-07-15. Office 2010 Lifecycle pins SP1 2011-06-28 and SP2 2013-07-23. Microsoft Support pins KB2460049 for SP1 and KB2687455 for SP2. Publisher-specific security pages independently prove Publisher package/applicability on SP1 and SP2. This still does not say which exact binary changed in the service pack itself.

### Publisher 2013
Publisher 2013 RTM is pinned to 2013-01-09. Office 2013 SP1 is pinned to 2014-02-25 and package KB2817430. Publisher file-level SP1 impact remains unresolved.

### Publisher 2016
Publisher 2016 RTM is pinned to 2015-09-22. Microsoft's current Office MSI update index explicitly reports **Latest Service Pack = N/A** for Office 2016 MSI. Do not invent an SP1 boundary. The parallel Click-to-Run chronology is left as a specific gap for the next pass.

### Publisher 2019
Publisher 2019 RTM is pinned to 2018-09-24. Microsoft documents Office 2019 as Click-to-Run: CDN builds are cumulative and no separate service-pack application is required.

### Publisher 2021 / LTSC 2021
Publisher LTSC 2021 starts 2021-09-16; retail Publisher 2021 starts 2021-10-05. Microsoft documents LTSC 2021 as Click-to-Run with cumulative builds and no service-pack prerequisite, and publishes a combined retail/LTSC update history.

### Publisher for Microsoft 365
This is treated as a channel/build servicing line, not an RTM/SP ladder. The matrix records the Click-to-Run update model and leaves exact Publisher-bearing channel/build deltas for later work.

## Explicit legacy gaps

Publisher 97, Publisher 98 and Publisher 2000 are not silently filled from memory or third-party chronology. They remain explicit unresolved servicing-skeleton gaps until primary archival sources or exact update packages are pinned.

## Next tranche

After this skeleton is green, add **Publisher-specific** update rows:
1. MS10-103 as a multi-generation Publisher parser/converter update anchor;
2. MS13-042 for Publisher 2003/2007/2010;
3. post-SP2 Publisher 2010 packages;
4. later 2013/2016 Publisher-specific fixes;
5. file manifests/hashes where available, so `publisher_module_impact` can move from package applicability to actual binary delta.

The matrix is research metadata only. No update package is executed and no format behavior is inferred solely from servicing chronology.

## Second tranche — Publisher-specific update anchors

The second pass moves from suite-level chronology to update rows where Microsoft names **Publisher itself**.

### MS10-103 — 2010-12-14

MS10-103 is a strong cross-generation parser/update anchor. Microsoft states that the update corrects how Publisher parses specially crafted Publisher files and publishes separate Publisher component KBs:

- Publisher 2002 SP3 — KB2284692 — `officeXP-KB2284692-FullFile-ENU.exe`;
- Publisher 2003 SP3 — KB2284695 — `office2003-KB2284695-FullFile-ENU.exe`;
- Publisher 2007 SP2 — KB2284697 — `publisher2007-kb2284697-fullfile-x86-glb.exe`;
- Publisher 2010 x86/x64 — KB2409055 — architecture-specific full-file packages.

The bulletin also identifies `pubconv.dll` as the legacy Publisher converter surface used for older files. That makes it a causal parser/converter anchor, but not a complete package file manifest for every generation.

### MS13-042 — 2013-05-14

MS13-042 gives another exact Publisher-specific package wave:

- Publisher 2003 SP3 — KB2810047 — replaces KB2553084;
- Publisher 2007 SP3 — KB2597971 — replaces KB2596705;
- Publisher 2010 SP1 x86/x64 — KB2553147 — no replaced update listed.

A useful negative is explicit: **Publisher 2013 x86/x64 is listed as non-affected**. The matrix retains that negative applicability instead of inventing a 2013 update row.

### MS16-148 / KB3114395 — 2016-12-13

This is the first row in the current matrix with a full Publisher-specific binary-impact manifest.

The Publisher 2010 SP2 update:
- KB3114395;
- replaces KB2817478;
- ships x86 and x64 full-file packages;
- has Microsoft-published SHA-256 for both packages;
- lists exact Publisher binaries/files including `mspub.exe`, `pubconv.dll`, `ptxt9.dll`, `morph9.dll`, `prtf9.dll`, and `pubtrap.dll`.

This is materially stronger than suite applicability. It is direct evidence that those Publisher file versions belong to the update payload.

## Updated evidence ladder

The matrix now distinguishes four different claims:

1. **suite boundary** — Office SP/servicing event exists;
2. **Publisher applicability** — Microsoft names Publisher as affected/applicable;
3. **Publisher package identity** — exact Publisher KB/package is named;
4. **Publisher binary impact** — Microsoft publishes the actual Publisher file manifest/hashes.

Do not collapse these levels.

## Residual after second tranche

The matrix is still not complete:
- Publisher 97/98/2000 servicing chronology remains primary-source unresolved;
- Publisher 2013/2016 still need a denser Publisher-specific update/package layer;
- Click-to-Run generations need build-level Publisher binary change attribution rather than only servicing-model identity.
