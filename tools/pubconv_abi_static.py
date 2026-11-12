#!/usr/bin/env python3
"""Bounded static ABI fingerprinting for exact x86 PUBCONV exports.

Records only observable machine-code facts: export identity/RVA, reachable
return cleanup immediates, positive EBP/ESP stack references, and call targets.
It does not infer prototypes, argument meanings/types, activation, or semantics.
"""

from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
from typing import Any

import pefile
from capstone import Cs, CS_ARCH_X86, CS_GRP_JUMP, CS_MODE_32
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_REG_EBP, X86_REG_ESP

SCHEMA_VERSION = "chaptera.pubconv-abi-static.v2"
TARGET_EXPORTS = (
    "HrGetInboundConverter",
    "HrGetOutboundConverter",
    "HrInitFileConverterDll",
    "TerminateFileConverterDll",
)
MAX_BLOCKS = 64
MAX_INSTRUCTIONS = 2048
MAX_BLOCK_BYTES = 512
ENTRY_PREVIEW_BYTES = 64
ENTRY_PREVIEW_INSNS = 32


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def decode_version_strings(pe: pefile.PE) -> dict[str, str]:
    result: dict[str, str] = {}
    for group in getattr(pe, "FileInfo", []) or []:
        for entry in group:
            if getattr(entry, "Key", b"") != b"StringFileInfo":
                continue
            for table in entry.StringTable:
                for key, value in table.entries.items():
                    k = key.decode(errors="replace") if isinstance(key, bytes) else str(key)
                    v = value.decode(errors="replace") if isinstance(value, bytes) else str(value)
                    result[k] = v
    return result


def executable_ranges(pe: pefile.PE) -> list[tuple[int, int, str]]:
    ranges = []
    for section in pe.sections:
        if not (section.Characteristics & 0x20000000):
            continue
        start = int(section.VirtualAddress)
        size = max(int(section.Misc_VirtualSize), int(section.SizeOfRawData))
        name = section.Name.rstrip(b"\x00").decode("ascii", errors="replace")
        ranges.append((start, start + size, name))
    return ranges


def is_exec_rva(rva: int, ranges: list[tuple[int, int, str]]) -> bool:
    return any(start <= rva < end for start, end, _ in ranges)


def section_for_rva(rva: int, ranges: list[tuple[int, int, str]]) -> str | None:
    for start, end, name in ranges:
        if start <= rva < end:
            return name
    return None


def import_map(pe: pefile.PE) -> dict[int, str]:
    result: dict[int, str] = {}
    for desc in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []:
        dll = desc.dll.decode("ascii", errors="replace")
        for imp in desc.imports:
            name = (
                imp.name.decode("ascii", errors="replace")
                if imp.name
                else f"ordinal:{imp.ordinal}"
            )
            result[int(imp.address)] = f"{dll}!{name}"
    return result


def export_map(pe: pefile.PE) -> dict[str, dict[str, int]]:
    if not hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        raise ValueError("PE has no export directory")
    result: dict[str, dict[str, int]] = {}
    for sym in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if not sym.name:
            continue
        name = sym.name.decode("ascii", errors="replace")
        result[name] = {"ordinal": int(sym.ordinal), "rva": int(sym.address)}
    return result


def rva_slice(pe: pefile.PE, rva: int, size: int) -> bytes:
    offset = pe.get_offset_from_rva(rva)
    return bytes(pe.__data__[offset : offset + size])


def normalize_va_to_rva(value: int, image_base: int, image_size: int) -> int | None:
    if image_base <= value < image_base + image_size:
        return value - image_base
    if 0 <= value < image_size:
        return value
    return None


def preview_instructions(pe: pefile.PE, md: Cs, rva: int, image_base: int) -> list[dict[str, Any]]:
    rows = []
    for insn in md.disasm(rva_slice(pe, rva, ENTRY_PREVIEW_BYTES), image_base + rva):
        rows.append(
            {
                "rva": int(insn.address - image_base),
                "bytes": insn.bytes.hex(),
                "mnemonic": insn.mnemonic,
                "op_str": insn.op_str,
            }
        )
        if len(rows) >= ENTRY_PREVIEW_INSNS:
            break
    return rows


def analyze_export(
    pe: pefile.PE,
    md: Cs,
    *,
    name: str,
    ordinal: int,
    entry_rva: int,
    exec_ranges: list[tuple[int, int, str]],
    imports: dict[int, str],
) -> dict[str, Any]:
    image_base = int(pe.OPTIONAL_HEADER.ImageBase)
    image_size = int(pe.OPTIONAL_HEADER.SizeOfImage)

    queue: deque[int] = deque([entry_rva])
    seen_blocks: set[int] = set()
    decoded: set[int] = set()
    block_summaries: list[dict[str, Any]] = []
    ret_cleanups: list[int] = []
    ret_sites: list[dict[str, Any]] = []
    ebp_offsets: Counter[int] = Counter()
    esp_offsets: Counter[int] = Counter()
    ebp_sites: list[dict[str, Any]] = []
    esp_sites: list[dict[str, Any]] = []
    direct_calls: Counter[int] = Counter()
    direct_call_sites: list[dict[str, Any]] = []
    import_calls: Counter[str] = Counter()
    import_call_sites: list[dict[str, Any]] = []
    unresolved_indirect_calls = 0
    bounds_hit = False

    while queue:
        if len(seen_blocks) >= MAX_BLOCKS or len(decoded) >= MAX_INSTRUCTIONS:
            bounds_hit = True
            break

        block_rva = queue.popleft()
        if block_rva in seen_blocks or not is_exec_rva(block_rva, exec_ranges):
            continue
        seen_blocks.add(block_rva)

        try:
            data = rva_slice(pe, block_rva, MAX_BLOCK_BYTES)
        except (pefile.PEFormatError, ValueError):
            continue

        insn_count = 0
        termination = "decode_end"
        successors: list[int] = []

        for insn in md.disasm(data, image_base + block_rva):
            insn_rva = int(insn.address - image_base)
            if not is_exec_rva(insn_rva, exec_ranges):
                termination = "left_executable_range"
                break
            if insn_rva in decoded:
                termination = "joined_existing_block"
                successors.append(insn_rva)
                break

            decoded.add(insn_rva)
            insn_count += 1
            if len(decoded) >= MAX_INSTRUCTIONS:
                bounds_hit = True
                termination = "instruction_bound"
                break

            for op in insn.operands:
                if op.type != X86_OP_MEM:
                    continue
                mem = op.mem
                if mem.base == X86_REG_EBP and mem.disp > 0:
                    offset = int(mem.disp)
                    ebp_offsets[offset] += 1
                    ebp_sites.append({
                        "rva": insn_rva,
                        "offset": offset,
                        "mnemonic": insn.mnemonic,
                        "op_str": insn.op_str,
                    })
                if mem.base == X86_REG_ESP and mem.disp > 0:
                    offset = int(mem.disp)
                    esp_offsets[offset] += 1
                    esp_sites.append({
                        "rva": insn_rva,
                        "offset": offset,
                        "mnemonic": insn.mnemonic,
                        "op_str": insn.op_str,
                    })

            if insn.mnemonic.startswith("ret"):
                cleanup = 0
                if insn.operands and insn.operands[0].type == X86_OP_IMM:
                    cleanup = int(insn.operands[0].imm)
                ret_cleanups.append(cleanup)
                ret_sites.append({
                    "rva": insn_rva,
                    "cleanup": cleanup,
                    "bytes": insn.bytes.hex(),
                    "mnemonic": insn.mnemonic,
                    "op_str": insn.op_str,
                })
                termination = "return"
                break

            if insn.mnemonic == "call" and insn.operands:
                op = insn.operands[0]
                if op.type == X86_OP_IMM:
                    target = normalize_va_to_rva(int(op.imm), image_base, image_size)
                    if target is not None:
                        direct_calls[target] += 1
                        direct_call_sites.append({
                            "rva": insn_rva,
                            "target_rva": target,
                            "bytes": insn.bytes.hex(),
                        })
                elif op.type == X86_OP_MEM:
                    mem = op.mem
                    if mem.base == 0 and mem.index == 0:
                        imported = imports.get(int(mem.disp))
                        if imported:
                            import_calls[imported] += 1
                            import_call_sites.append({
                                "rva": insn_rva,
                                "target": imported,
                                "bytes": insn.bytes.hex(),
                            })
                        else:
                            unresolved_indirect_calls += 1
                    else:
                        unresolved_indirect_calls += 1

            if insn.group(CS_GRP_JUMP):
                target = None
                if insn.operands and insn.operands[0].type == X86_OP_IMM:
                    target = normalize_va_to_rva(
                        int(insn.operands[0].imm), image_base, image_size
                    )
                fallthrough = int(insn.address + insn.size - image_base)

                if insn.mnemonic == "jmp":
                    termination = "unconditional_jump"
                    if target is not None and is_exec_rva(target, exec_ranges):
                        successors.append(target)
                        queue.append(target)
                    break

                termination = "conditional_jump"
                if target is not None and is_exec_rva(target, exec_ranges):
                    successors.append(target)
                    queue.append(target)
                if is_exec_rva(fallthrough, exec_ranges):
                    successors.append(fallthrough)
                    queue.append(fallthrough)
                break

        block_summaries.append(
            {
                "rva": block_rva,
                "section": section_for_rva(block_rva, exec_ranges),
                "instruction_count": insn_count,
                "termination": termination,
                "successors": sorted(set(successors)),
            }
        )

    entry_bytes = rva_slice(pe, entry_rva, ENTRY_PREVIEW_BYTES)
    entry_preview = preview_instructions(pe, md, entry_rva, image_base)
    entry_direct_jump_target_rva = None
    first = next(iter(md.disasm(entry_bytes, image_base + entry_rva)), None)
    if (
        first is not None
        and first.mnemonic == "jmp"
        and first.operands
        and first.operands[0].type == X86_OP_IMM
    ):
        candidate = normalize_va_to_rva(int(first.operands[0].imm), image_base, image_size)
        if candidate is not None and is_exec_rva(candidate, exec_ranges):
            entry_direct_jump_target_rva = candidate

    normalized = {
        "name": name,
        "ordinal": ordinal,
        "entry_rva": entry_rva,
        "ret_cleanup": sorted(set(ret_cleanups)),
        "ebp_offsets": sorted(ebp_offsets),
        "esp_offsets": sorted(esp_offsets),
        "direct_calls": sorted(direct_calls),
        "import_calls": sorted(import_calls),
    }

    return {
        "name": name,
        "ordinal": ordinal,
        "entry_rva": entry_rva,
        "entry_section": section_for_rva(entry_rva, exec_ranges),
        "entry_preview_bytes": entry_bytes.hex(),
        "entry_preview_sha256": sha256_bytes(entry_bytes),
        "entry_direct_jump_target_rva": entry_direct_jump_target_rva,
        "entry_instructions": entry_preview,
        "reachable_cfg": {
            "blocks_decoded": len(seen_blocks),
            "instructions_decoded": len(decoded),
            "bounds_hit": bounds_hit,
            "block_summaries": sorted(block_summaries, key=lambda row: row["rva"]),
        },
        "reachable_returns": {
            "observed_count": len(ret_cleanups),
            "cleanup_immediates": sorted(set(ret_cleanups)),
            "cleanup_counts": {
                str(k): v for k, v in sorted(Counter(ret_cleanups).items())
            },
            "sites": sorted(ret_sites, key=lambda row: row["rva"]),
        },
        "stack_references": {
            "positive_ebp_offsets": [
                {"offset": k, "references": v} for k, v in sorted(ebp_offsets.items())
            ],
            "positive_esp_offsets": [
                {"offset": k, "references": v} for k, v in sorted(esp_offsets.items())
            ],
            "positive_ebp_sites": sorted(ebp_sites, key=lambda row: (row["rva"], row["offset"])),
            "positive_esp_sites": sorted(esp_sites, key=lambda row: (row["rva"], row["offset"])),
        },
        "calls": {
            "direct_internal_targets": [
                {
                    "rva": k,
                    "section": section_for_rva(k, exec_ranges),
                    "calls": v,
                }
                for k, v in sorted(direct_calls.items())
            ],
            "import_targets": [
                {"name": k, "calls": v} for k, v in sorted(import_calls.items())
            ],
            "direct_call_sites": sorted(direct_call_sites, key=lambda row: row["rva"]),
            "import_call_sites": sorted(import_call_sites, key=lambda row: row["rva"]),
            "unresolved_indirect_call_count": unresolved_indirect_calls,
        },
        "normalized_abi_fingerprint_sha256": sha256_bytes(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        ),
        "interpretation_boundary": {
            "prototype_inferred": False,
            "argument_meanings_inferred": False,
            "argument_types_inferred": False,
            "activation_observed": False,
            "reader_writer_role_inferred": False,
            "pub_wire_format_claim_allowed": False,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dll", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    pe = pefile.PE(str(args.dll), fast_load=False)
    pe.parse_data_directories()
    if pe.FILE_HEADER.Machine != 0x14C:
        raise SystemExit(f"expected i386 PE, got 0x{pe.FILE_HEADER.Machine:04x}")

    exports = export_map(pe)
    missing = [name for name in TARGET_EXPORTS if name not in exports]
    if missing:
        raise SystemExit(f"missing required exports: {missing}")

    versions = decode_version_strings(pe)
    exec_ranges = executable_ranges(pe)
    imports = import_map(pe)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True

    analyses = [
        analyze_export(
            pe,
            md,
            name=name,
            ordinal=exports[name]["ordinal"],
            entry_rva=exports[name]["rva"],
            exec_ranges=exec_ranges,
            imports=imports,
        )
        for name in TARGET_EXPORTS
    ]

    result = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "filename": args.dll.name,
            "byte_len": args.dll.stat().st_size,
            "sha256": sha256_file(args.dll),
            "machine": "i386",
            "image_base": int(pe.OPTIONAL_HEADER.ImageBase),
            "image_size": int(pe.OPTIONAL_HEADER.SizeOfImage),
            "pe_checksum_header": int(pe.OPTIONAL_HEADER.CheckSum),
            "pe_checksum_generated": int(pe.generate_checksum()),
            "file_version": versions.get("FileVersion", ""),
            "product_version": versions.get("ProductVersion", ""),
            "original_filename": versions.get("OriginalFilename", ""),
            "company_name": versions.get("CompanyName", ""),
        },
        "analysis_bounds": {
            "max_blocks_per_export": MAX_BLOCKS,
            "max_instructions_per_export": MAX_INSTRUCTIONS,
            "max_block_bytes": MAX_BLOCK_BYTES,
            "calls_followed": False,
            "direct_intra_image_jumps_followed": True,
        },
        "exports": analyses,
        "global_interpretation_boundary": {
            "static_export_inventory_only": True,
            "prototype_inference_authorized": False,
            "runtime_activation_observed": False,
            "reader_writer_role_inference_authorized": False,
            "pub_wire_format_claim_authorized": False,
            "parent_pub_t_64_closed_by_this_report": False,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        row["name"]: {
            "ordinal": row["ordinal"],
            "entry_rva": row["entry_rva"],
            "ret_cleanup": row["reachable_returns"]["cleanup_immediates"],
            "ebp_offsets": [x["offset"] for x in row["stack_references"]["positive_ebp_offsets"]],
            "imports": [x["name"] for x in row["calls"]["import_targets"]],
            "bounds_hit": row["reachable_cfg"]["bounds_hit"],
        }
        for row in analyses
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
