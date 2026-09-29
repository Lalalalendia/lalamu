#!/usr/bin/env python3
"""Bounded static anchor/xref census for legacy Publisher OleData in PUBCONV.

This tool records machine-code/data co-location only. It never assigns semantic
meaning to OleData.f1/F or claims that a candidate routine consumes that field.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from capstone.x86 import X86_OP_IMM, X86_OP_MEM

SCHEMA = "chaptera.pubconv-oledata-f-static.v1"
CONSTANTS = {
    "legacy_child_type_0x22": 0x22,
    "oledata_mo_u16_0x4f4d": 0x4F4D,
    "observed_flag_0x8000": 0x8000,
}
BYTE_PATTERNS = {
    "legacy_oledata_prefix": bytes.fromhex("220000080a0000004d4f"),
    "wordart2_clsid": bytes.fromhex("f012020000000000c000000000000046"),
    "ascii_MO": b"MO",
}
TEXT_PATTERNS = ("OlePres", "CompObj", "WordArt", "Objects", "OleData")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def executable_sections(pe: pefile.PE) -> list[tuple[int, int, bytes]]:
    rows = []
    for sec in pe.sections:
        if not (sec.Characteristics & 0x20000000):
            continue
        rva = int(sec.VirtualAddress)
        raw = bytes(sec.get_data())
        rows.append((rva, rva + len(raw), raw))
    return rows


def file_offset_to_rva(pe: pefile.PE, offset: int) -> int | None:
    try:
        return int(pe.get_rva_from_offset(offset))
    except Exception:
        return None


def find_all(raw: bytes, needle: bytes) -> list[int]:
    out = []
    start = 0
    while True:
        pos = raw.find(needle, start)
        if pos < 0:
            return out
        out.append(pos)
        start = pos + 1


def scan_data_anchors(pe: pefile.PE, raw: bytes) -> dict[str, list[int]]:
    anchors: dict[str, list[int]] = {}
    for name, needle in BYTE_PATTERNS.items():
        anchors[name] = [
            rva for off in find_all(raw, needle)
            if (rva := file_offset_to_rva(pe, off)) is not None
        ]
    for text in TEXT_PATTERNS:
        for encoding, needle in (
            ("ascii", text.encode("ascii")),
            ("utf16le", text.encode("utf-16le")),
        ):
            name = f"text_{text}_{encoding}"
            anchors[name] = [
                rva for off in find_all(raw, needle)
                if (rva := file_offset_to_rva(pe, off)) is not None
            ]
    return anchors


def scan_code(pe: pefile.PE, data_anchors: dict[str, list[int]]) -> list[dict[str, Any]]:
    image_base = int(pe.OPTIONAL_HEADER.ImageBase)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    # Executable PE sections can contain alignment/data islands. Keep scanning
    # past undecodable bytes rather than silently truncating the section.
    md.skipdata = True

    va_to_names: dict[int, list[str]] = defaultdict(list)
    for name, rvas in data_anchors.items():
        for rva in rvas:
            va_to_names[image_base + rva].append(name)

    rows: list[dict[str, Any]] = []
    for section_start, _, raw in executable_sections(pe):
        for insn in md.disasm(raw, image_base + section_start):
            rva = int(insn.address - image_base)
            anchors: set[str] = set()
            evidence: list[dict[str, Any]] = []

            for op in insn.operands:
                if op.type == X86_OP_IMM:
                    value = int(op.imm) & 0xFFFFFFFF
                    for name, expected in CONSTANTS.items():
                        if value == expected:
                            anchors.add(name)
                            evidence.append({"kind": "immediate", "anchor": name, "value": value})
                    for name in va_to_names.get(value, []):
                        anchors.add(name)
                        evidence.append({"kind": "data_va_immediate", "anchor": name, "value": value})
                elif op.type == X86_OP_MEM:
                    mem = op.mem
                    if mem.base == 0 and mem.index == 0:
                        value = int(mem.disp) & 0xFFFFFFFF
                        for name in va_to_names.get(value, []):
                            anchors.add(name)
                            evidence.append({"kind": "absolute_memory_xref", "anchor": name, "value": value})

            if anchors:
                rows.append({
                    "rva": rva,
                    "bytes": insn.bytes.hex(),
                    "mnemonic": insn.mnemonic,
                    "op_str": insn.op_str,
                    "anchors": sorted(anchors),
                    "evidence": evidence,
                })
    return rows


def cluster_hits(hits: list[dict[str, Any]], gap: int = 0x100) -> list[dict[str, Any]]:
    ordered = sorted(hits, key=lambda row: row["rva"])
    clusters: list[list[dict[str, Any]]] = []
    for row in ordered:
        if not clusters or row["rva"] - clusters[-1][-1]["rva"] > gap:
            clusters.append([row])
        else:
            clusters[-1].append(row)

    out = []
    for rows in clusters:
        anchors = sorted({a for row in rows for a in row["anchors"]})
        out.append({
            "start_rva": rows[0]["rva"],
            "end_rva": rows[-1]["rva"],
            "hit_count": len(rows),
            "distinct_anchor_count": len(anchors),
            "anchors": anchors,
            "hits": rows,
        })
    out.sort(key=lambda row: (-row["distinct_anchor_count"], -row["hit_count"], row["start_rva"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dll", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    raw = args.dll.read_bytes()
    pe = pefile.PE(str(args.dll), fast_load=False)
    pe.parse_data_directories()
    if pe.FILE_HEADER.Machine != 0x14C:
        raise SystemExit(f"expected i386 PE, got 0x{pe.FILE_HEADER.Machine:04x}")

    data_anchors = scan_data_anchors(pe, raw)
    code_hits = scan_code(pe, data_anchors)
    clusters = cluster_hits(code_hits)

    result = {
        "schema_version": SCHEMA,
        "source": {
            "filename": args.dll.name,
            "byte_len": len(raw),
            "sha256": sha256_file(args.dll),
            "image_base": int(pe.OPTIONAL_HEADER.ImageBase),
            "machine": "i386",
        },
        "static_inputs": {
            "immediate_constants": {k: hex(v) for k, v in CONSTANTS.items()},
            "byte_patterns_hex": {k: v.hex() for k, v in BYTE_PATTERNS.items()},
            "text_patterns": list(TEXT_PATTERNS),
        },
        "data_anchor_rvas": {
            name: [hex(v) for v in values]
            for name, values in sorted(data_anchors.items())
        },
        "data_anchor_counts": {
            name: len(values) for name, values in sorted(data_anchors.items())
        },
        "code_hit_count": len(code_hits),
        "cluster_count": len(clusters),
        "clusters": clusters,
        "bounded_interpretation": {
            "oledata_f_semantics_assigned": False,
            "candidate_routine_claim_authorized": False,
            "runtime_activation_observed": False,
            "publisher2000_writer_behavior_claimed": False,
            "raw_microsoft_bytes_retained": False,
            "ranking_meaning": "distinct static anchor co-location only",
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "data_anchor_counts": result["data_anchor_counts"],
        "code_hit_count": len(code_hits),
        "cluster_count": len(clusters),
        "top_clusters": [
            {
                "start_rva": hex(row["start_rva"]),
                "end_rva": hex(row["end_rva"]),
                "hit_count": row["hit_count"],
                "anchors": row["anchors"],
            }
            for row in clusters[:12]
        ],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
