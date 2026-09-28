#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any

IE_VERSION_VECTOR = re.compile(r"internet[ \\]+explorer[ \\]+version[ \\]+vector", re.I)
VERSION_VECTOR = re.compile(r"version[ \\]+vector", re.I)
PUB11 = re.compile(r"(?<![a-z0-9])pub11(?![a-z0-9])", re.I)
PUB = re.compile(r"(?<![a-z0-9])pub(?![a-z0-9])", re.I)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_idt(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 3:
        return [], []
    header = lines[0].split("\t")
    rows: list[dict[str, str]] = []
    for raw in lines[3:]:
        fields = raw.split("\t")
        if len(fields) < len(header):
            fields.extend([""] * (len(header) - len(fields)))
        row = {name: fields[i] if i < len(fields) else "" for i, name in enumerate(header)}
        row["_raw"] = raw
        rows.append(row)
    return header, rows


def exact_pub_token(value: str) -> bool:
    return value.strip().lower() in {"pub", "pub11"}


def row_has_signal(raw: str) -> bool:
    return bool(PUB11.search(raw) or VERSION_VECTOR.search(raw) or IE_VERSION_VECTOR.search(raw))


def analyze(root: Path, media: dict[str, Any]) -> dict[str, Any]:
    msi_root = root / "msi"
    direct_registry: list[dict[str, Any]] = []
    indirect_custom_actions: list[dict[str, Any]] = []
    sequence_refs: list[dict[str, Any]] = []
    property_hits: list[dict[str, Any]] = []
    all_signal_rows: list[dict[str, Any]] = []
    msi_summaries: list[dict[str, Any]] = []

    for msi_dir in sorted(p for p in msi_root.iterdir() if p.is_dir()):
        meta_path = msi_dir / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"safe_id": msi_dir.name}
        tables_dir = msi_dir / "tables"
        table_names = []
        table_row_count = 0

        if tables_dir.exists():
            for idt in sorted(tables_dir.glob("*.idt")):
                table = idt.stem
                table_names.append(table)
                _, rows = read_idt(idt)
                table_row_count += len(rows)
                for idx, row in enumerate(rows, start=1):
                    raw = row.get("_raw", "")
                    if row_has_signal(raw):
                        all_signal_rows.append({
                            "msi": meta.get("path"),
                            "msi_sha256": meta.get("sha256"),
                            "table": table,
                            "row_index": idx,
                            "row": {k: v for k, v in row.items() if k != "_raw"},
                        })

                    if table.lower() == "registry":
                        key = row.get("Key", "")
                        name = row.get("Name", "")
                        if IE_VERSION_VECTOR.search(key) and exact_pub_token(name):
                            direct_registry.append({
                                "msi": meta.get("path"),
                                "msi_sha256": meta.get("sha256"),
                                "row_index": idx,
                                "registry_id": row.get("Registry", ""),
                                "root": row.get("Root", ""),
                                "key": key,
                                "name": name,
                                "value": row.get("Value", ""),
                                "component": row.get("Component_", ""),
                            })
                    elif table.lower() == "customaction" and row_has_signal(raw):
                        indirect_custom_actions.append({
                            "msi": meta.get("path"),
                            "msi_sha256": meta.get("sha256"),
                            "row_index": idx,
                            "row": {k: v for k, v in row.items() if k != "_raw"},
                        })
                    elif table.lower() in {"installexecutesequence", "installuisequence"} and row_has_signal(raw):
                        sequence_refs.append({
                            "msi": meta.get("path"),
                            "table": table,
                            "row_index": idx,
                            "row": {k: v for k, v in row.items() if k != "_raw"},
                        })
                    elif table.lower() == "property" and row_has_signal(raw):
                        property_hits.append({
                            "msi": meta.get("path"),
                            "msi_sha256": meta.get("sha256"),
                            "row_index": idx,
                            "row": {k: v for k, v in row.items() if k != "_raw"},
                        })

        msi_summaries.append({
            **meta,
            "exported_table_count": len(table_names),
            "exported_row_count": table_row_count,
            "exported_tables": table_names,
        })

    static_scan_path = root / "static-scan.json"
    static_scan = json.loads(static_scan_path.read_text()) if static_scan_path.exists() else {}

    if direct_registry:
        verdict = "direct_setup_write_proven"
        setup_write_proven = True
        native_registry_diff_required = False
    elif indirect_custom_actions:
        verdict = "indirect_setup_write_candidate_requires_bounded_followup"
        setup_write_proven = False
        native_registry_diff_required = True
    else:
        verdict = "bounded_exact_media_negative_native_registry_diff_still_required"
        setup_write_proven = False
        native_registry_diff_required = True

    return {
        "schema_version": "chaptera.html-vector.msi-static.v1",
        "task": "HTML-VECTOR-01",
        "authority": "PUB-T-233",
        "media": media,
        "scope": {
            "publisher_or_office_installed": False,
            "publisher_executed": False,
            "static_exact_media_only": True,
            "generic_web_search_performed": False,
            "pub_wire_format_claim_authorized": False,
        },
        "coverage": {
            "msi_count": len(msi_summaries),
            "all_msis_on_exact_media_scanned": True,
            "registry_tables_checked": True,
            "custom_action_tables_checked": True,
            "install_sequence_tables_checked": True,
            "property_tables_checked": True,
            "static_disc_token_scan_included": True,
        },
        "msis": msi_summaries,
        "evidence": {
            "direct_registry_rows": direct_registry,
            "indirect_custom_action_rows": indirect_custom_actions,
            "sequence_signal_rows": sequence_refs,
            "property_signal_rows": property_hits,
            "all_signal_rows": all_signal_rows,
            "static_disc_scan": static_scan,
        },
        "conclusion": {
            "verdict": verdict,
            "setup_write_proven": setup_write_proven,
            "native_registry_diff_required": native_registry_diff_required,
            "direct_registry_row_count": len(direct_registry),
            "indirect_custom_action_row_count": len(indirect_custom_actions),
            "signal_row_count": len(all_signal_rows),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    media = json.loads((args.root / "media.json").read_text())
    receipt = analyze(args.root, media)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt["conclusion"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
