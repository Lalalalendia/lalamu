# PUBCONV-ABI-STATIC-01 — exact RTM export-entrypoint fingerprints

## Scope

This is a **static-only auxiliary slice** under PUB-T-64. It does not execute the converter exports and cannot close the parent runtime task.

GitHub Actions reacquired the provenance-pinned Microsoft Publisher 2007 RTM package and extracted the exact converter DLL without committing or retaining Microsoft binary bytes in the repository/artifact.

- Package: `X12-30247.exe`, 233,139,240 bytes, SHA-256 `6caa1d57b0b91485beb7cfbd38a44ab723043651a117223ef7ac735bf920c6dd`.
- DLL: `PUBCONV.DLL`, 590,144 bytes, SHA-256 `124f5b115979f4e4c0aab882851c399228174482bb124b8309860567a5980dbc`.
- File/Product version: `12.0.4518.1014`.
- PE checksum: `652414`, regenerated checksum identical.
- Machine: i386.
- Measurement run: `36425916359`, head `bd88a1306f5a010c2bf1247003462f5e2da4172c`.
- Machine-readable artifact: `10971209011`, digest `sha256:b07a42fa413328ff2fa82f182d7b4b77278385524edbd0ea55521578a62ce77b`.

The bounded CFG analyzer follows direct intra-image jumps but **never follows calls**. All four export analyses completed inside the configured bounds.

## Export ABI-shape observations

| Export | Ordinal | Entry RVA | Reachable return | Positive frame stack refs |
| --- | ---: | ---: | --- | --- |
| `HrGetInboundConverter` | 1 | `0x2042B` | `ret 4` at `0x20491` | one `[ebp+8]` ref at `0x2047A` |
| `HrGetOutboundConverter` | 2 | `0x20494` | `ret 4` at `0x204E1` | one `[ebp+8]` ref at `0x204CC` |
| `HrInitFileConverterDll` | 3 | `0x1FC15` | `ret 4` at `0x1FC5D` | one `[ebp+8]` ref at `0x1FC3D` |
| `TerminateFileConverterDll` | 4 | `0x1FB48` | `ret` / cleanup 0 at `0x6D1B7` | none on the reachable thunk target |

For exports 1–3, the pair of observations “one positive `[ebp+8]` reference” + reachable `ret 4` is **compatible with one observed positive frame stack slot and callee cleanup of four bytes**. It is not promoted into a C/C++ prototype, argument name, argument type, or COM/interface claim.

`TerminateFileConverterDll` has a different entry shape: its export entry is a direct jump thunk from `0x1FB48` to `0x6D19F`; the reachable target returns with plain `ret` and contains no positive EBP/ESP stack reference in the bounded CFG. The target also reaches an import call to `USER32.dll!ReleaseDC` at `0x6D1B1`.

## Shared initialization gate

A stronger static lifecycle relation appears across the exports.

- `HrGetInboundConverter` checks absolute global `0x3456A674` for zero at entry RVA `0x2042F`.
- `HrGetOutboundConverter` checks the **same** global at entry RVA `0x20497`.
- `HrInitFileConverterDll` reads through its observed `[ebp+8]` slot and stores the resulting value into **that same global** at RVA `0x1FC43`.

So the RTM binary itself gives a precise static instrumentation anchor:

`HrInitFileConverterDll` write → global `0x3456A674` → both `HrGet*Converter` entry guards.

This is a lifecycle/guard relation in machine code. It is **not** evidence that any of the exports were activated during Open/SaveAs.

## Inbound vs outbound implementation difference

The two getter exports are not aliases of one entrypoint. They share the same direct internal call target `RVA 0x71478`, but the surrounding machine-code footprint differs:

- inbound: pushes immediate `0x0C` at `0x20440`, calls `0x71478` at `0x20442`, then writes `[eax+4]=0`, `[eax+8]=0`, and `[eax]=0x344E39BC`;
- outbound: pushes immediate `0x08` at `0x204A7`, calls the same `0x71478` at `0x204A9`, then writes `[eax+4]=0` and `[eax]=0x344E39E8`.

This is useful future tracing evidence: the two public getters have distinct state-initialization footprints even though they share one internal direct-call target. The immediate values and pointer constants are recorded as raw implementation observations only; they are not assigned object/type semantics here.

## Exact fingerprints

Normalized static fingerprints:

- `HrGetInboundConverter`: `9892510106583c8ea2aee69a17712908846929f9017c2f862347955f407c307f`
- `HrGetOutboundConverter`: `b98ec1f1ae6bd4af243822c52d3eb599d0867d06f72efbe4daca6f33d4519a49`
- `HrInitFileConverterDll`: `6a9ca9a8f795007a7dd38178baa05f0f3a0f0aea33d65bd2e4be9f24e360ae81`
- `TerminateFileConverterDll`: `6cc84e42156b0b311fad6ab7be1312ffd8fa582d0fea3b5d1898d2db910715d9`

## Use for PUB-T-64

The immediate value is narrower instrumentation, not closure:

- exact RTM export RVAs are pinned;
- the Init→shared-global→Getters relation gives a concrete breakpoint/watchpoint target;
- inbound and outbound have distinct constructor/state-init footprints that can be distinguished if runtime T55 tracing later observes the entries.

PUB-T-64 still requires the registered T47 stream/root provenance envelope and **observed** inbound/outbound activation plus format-specific caller stacks.

## Evidence boundary

This report does **not** infer:

- function prototypes;
- semantic argument names or types;
- which getter owns old-PUB read vs legacy SaveAs write;
- activation under any Publisher scenario;
- any PUB field or wire-format semantic.

Raw Microsoft package/DLL bytes are not committed and are explicitly removed before artifact upload.
