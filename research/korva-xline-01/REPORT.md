# KORVA-XLINE-01 — bounded recovery differential

## Outcome

The bounded GitHub-hosted pass is **runtime-blocked on Korva 1.8.7**.

The exact pinned Korva build was successfully acquired and started on Ubuntu 24.04 under Xvfb with all dynamic libraries resolved. However, no reproducible machine-readable runtime import entrypoint was established:

- `Korva --help` remained in the GUI event loop until timeout: exit **124**;
- `Korva --version` likewise timed out: exit **124**;
- direct `Korva Sample.pub` likewise timed out: exit **124**;
- all three emitted no useful stdout/stderr result;
- the isolated Korva HOME produced no observed `.pwl`/`.kva` document artifact;
- `ldd` reported **zero missing libraries** after the runtime dependency fix.

This satisfies the task's fail-honest stop rule: **do not replace a missing runtime observation with the previously reconstructed static algorithm**. The full Korva/libmspub/Chaptera three-way vote therefore remains unexecuted.

## Exact identities

- Korva: `1.8.7`, DEB SHA-256 `e0a2abde284c4c714262c07afab168659387a797f033a869d0db1b1f4bfa010c`.
- libmspub-tools: `0.1.4-3build7`.
- Chaptera/Rar revision: `46459108710350280f0c2761e9c8435899734bd2`.
- Apache POI fixture source commit: `942d95d85b15d0dfdb3bc9ba1b4f273f277757c8`.
- Clean execution: issue #15, PR #16, head `dc5a3688d32408194b3d56f235ad86007735e1fd`.
- GitHub Actions run: `36423531958`.
- Evidence artifact: `10970109954`, digest `sha256:62ecfb92b084be47cb7612999bff0c7d58a03ebc66c7c39a1e45aa5088964975`.

## Public fixtures

| Fixture | Bytes | SHA-256 |
| --- | ---: | --- |
| `Sample.pub` | 72,192 | `6fefdef46b87c767150878dc384549cb2d2ec2ac54de25f8ddb3a5628301107e` |
| `SampleBrochure.pub` | 161,792 | `ffed034ac87e679f0bd08ff9cf74ad11c0e0e510a42b1bc1a7502415f6c29c87` |
| `SampleNewsletter.pub` | 291,840 | `6a825ba26ba35d6e885acdc62e859591ed37cb0ff7480b554b9cb362b644dfcf` |

No private PUB bytes were used.

## Secondary two-lineage observations

These are retained because they are useful, but they **do not substitute for the missing Korva runtime arm**.

### Sample.pub — text-content agrees, ordering differs

Chaptera and libmspub both open the fixture.

- Chaptera: 6 recovered stories, 0 images.
- libmspub: successful `pub2xhtml`, 0 images.
- normalized concatenated text length: **487** on both.
- token/word count: **103** on both.
- word multiset: **identical**.
- normalized ordering: **different**.

The observed order difference is deliberately **not promoted** to a model discriminator in this run because we did not independently join the competing orderings to raw Quill story/page ordering.

### SampleBrochure.pub — raw image arbitration

- Chaptera opens the file, recovers 20 stories and one JPEG.
- libmspub `pub2xhtml` exits 1 with `ERROR: SVG Generation failed!`.
- Chaptera JPEG: 11,516 bytes, SHA-256 `2fbfcdaeb1376c41beb523e48d0e1205b398b8fe81417ebdcd49c541d35e8b50`.
- independent raw scan finds a JPEG at byte offset **103,505**, exactly 11,516 bytes, with the **same SHA-256**.

Therefore the Chaptera image recovery on this fixture is independently byte-validated against the PUB payload. This is an image-recovery observation only, not a layout or wire-semantic claim.

### SampleNewsletter.pub — raw image arbitration

- Chaptera opens the file, recovers 44 stories and one JPEG.
- libmspub `pub2xhtml` exits 1 with `ERROR: SVG Generation failed!`.
- Chaptera JPEG: 36,497 bytes, SHA-256 `2478d1169c54e19bced4ab07d558ef4ca98cd27c21187a2654c253018c10e841`.
- independent raw scan finds a JPEG at byte offset **100,261**, exactly 36,497 bytes, with the **same SHA-256**.

Again, this independently validates exact Chaptera image-byte recovery for that fixture.

## Korva authority fence

Korva receives **no vote** on:

- page count;
- layout;
- object geometry;
- margins;
- typography;
- wrapping;
- styles.

Only text and JPEG/PNG recovery would have been scored if a reproducible runtime result had been obtained.

The binary still exposes 308 static resource/import string hits relevant to import behavior, but those are **not runtime observations** and are not substituted into the differential.

## Closure

This bounded run closes as **runtime-blocked**, exactly as allowed by KORVA-XLINE-01's stop condition.

The exact blocker is:

> Exact Korva 1.8.7 runs with its dynamic dependencies resolved, but the available desktop binary exposes no reproducible headless/machine-readable import result through `--help`, `--version`, or direct `.pub` argv execution under Xvfb. Each invocation stays in the GUI event loop until bounded timeout, and no output document is observed.

No Chaptera model change is authorized from this run. No PUB wire-format claim is authorized.
