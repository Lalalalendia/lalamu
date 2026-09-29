#!/usr/bin/env python3
"""Bounded disassembly context for exact PUBCONV OleData candidate RVAs.

Candidate RVAs come from PUBCONV-OLEDATA-F-STATIC-01's source-free anchor
census on the same exact DLL. This tool records nearby instructions/calls only;
it does not assign OleData semantics to any routine.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from capstone.x86 import X86_OP_IMM

SCHEMA = "chaptera.pubconv-oledata-candidate-context.v1"
CANDIDATES = {
    "type22_flag8000_offset6": 0x69866,
    "type22_flag8000_offset0a": 0x1D5CB,
    "type22_mo_signature": 0x772C8,
    # Direct callees/helpers from the three exact anchor neighborhoods above.
    "oledata_mo_body_consumer": 0x72026,
    "oledata_type_lookup_helper": 0x770BA,
    "flag_candidate_helper": 0x4CAC6,
}


def disassemble_sections(pe: pefile.PE):
    base = int(pe.OPTIONAL_HEADER.ImageBase)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    md.skipdata = True
    rows = {}
    ordered = []
    for sec in pe.sections:
        if not (sec.Characteristics & 0x20000000):
            continue
        start = int(sec.VirtualAddress)
        raw = bytes(sec.get_data())
        for insn in md.disasm(raw, base + start):
            if insn.id == 0:
                continue
            rva = int(insn.address - base)
            row = {
                "rva": rva,
                "bytes": insn.bytes.hex(),
                "mnemonic": insn.mnemonic,
                "op_str": insn.op_str,
            }
            if insn.mnemonic == "call" and insn.operands and insn.operands[0].type == X86_OP_IMM:
                target = int(insn.operands[0].imm) - base
                row["direct_call_target_rva"] = target
            rows[rva] = row
            ordered.append(rva)
    ordered.sort()
    return rows, ordered


def context(rows, ordered, target, radius=18):
    try:
        i = ordered.index(target)
    except ValueError:
        raise SystemExit(f"candidate RVA 0x{target:x} is not an instruction boundary")
    lo = max(0, i - radius)
    hi = min(len(ordered), i + radius + 1)
    return [rows[rva] for rva in ordered[lo:hi]]


def assert_exact_anchors(rows):
    expected = {
        0x69866: ("test", "word ptr [eax + 6], 0x8000"),
        0x69878: ("cmp", "esi, 0x22"),
        0x6988E: ("or", "word ptr [eax], 0x8000"),
        0x1D5CB: ("cmp", "eax, 0x22"),
        0x1D5DD: ("test", "word ptr [ebx + 0xa], 0x8000"),
        0x772C8: ("push", "0x22"),
        0x772DB: ("cmp", "word ptr [edi], 0x4f4d"),
    }
    for rva, (mnemonic, op_str) in expected.items():
        row = rows.get(rva)
        if not row:
            raise SystemExit(f"missing exact anchor instruction 0x{rva:x}")
        if row["mnemonic"] != mnemonic or row["op_str"] != op_str:
            raise SystemExit(
                f"anchor drift 0x{rva:x}: got {row['mnemonic']} {row['op_str']}, "
                f"expected {mnemonic} {op_str}"
            )
    return expected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dll", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    pe = pefile.PE(str(args.dll), fast_load=False)
    rows, ordered = disassemble_sections(pe)
    expected = assert_exact_anchors(rows)

    candidates = {}
    for name, rva in CANDIDATES.items():
        ctx = context(rows, ordered, rva)
        candidates[name] = {
            "anchor_rva": rva,
            "context": ctx,
            "direct_call_targets": sorted({
                row["direct_call_target_rva"]
                for row in ctx
                if "direct_call_target_rva" in row
            }),
        }

    result = {
        "schema_version": SCHEMA,
        "candidate_count": len(candidates),
        "exact_anchor_instructions": {
            hex(rva): {"mnemonic": m, "op_str": op}
            for rva, (m, op) in sorted(expected.items())
        },
        "candidates": candidates,
        "bounded_interpretation": {
            "function_boundaries_claimed": False,
            "field_semantics_assigned": False,
            "candidate_is_confirmed_oledata_consumer": False,
            "publisher2000_behavior_claimed": False,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        name: {
            "anchor_rva": hex(row["anchor_rva"]),
            "direct_call_targets": [hex(x) for x in row["direct_call_targets"]],
            "instruction_count": len(row["context"]),
        }
        for name, row in candidates.items()
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
