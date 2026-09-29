#!/usr/bin/env python3
"""Materialize a bounded, exact-SHA subset of Rar's retained container delta.

The source roots and target SHA authority come from pinned Rar code/receipts.
Only strict Publisher CFB members are written to the working corpus. Existing
SHA files are never rewritten. Output provenance is source-safe and contains no
recovered document text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

import olefile

CFB = bytes.fromhex("d0cf11e0a1b11ae1")
ROOT_LABELS = {
    0: "publisher_3_windows95_media",
    1: "publisher_2_media",
    2: "publisher_97_deluxe_media",
    3: "publisher_97_pub40_media",
    4: "publisher_97_pub40_alt_media",
    5: "video_professor_publisher_media",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_existing(corpus: Path) -> set[str]:
    out: set[str] = set()
    for path in sorted(corpus.glob("*.pub")):
        stem = path.stem.lower()
        data = path.read_bytes()
        actual = sha256(data)
        if actual != stem:
            raise ValueError(f"working corpus filename/hash mismatch: {path.name}")
        out.add(actual)
    return out


def strict_publisher_cfb(data: bytes, harvest_pub) -> tuple[bool, str]:
    if data[:8] != CFB:
        return False, "not_cfb"
    try:
        with olefile.OleFileIO(data) as ole:
            paths = {"/" + "/".join(parts) for parts in ole.listdir(streams=True, storages=False)}
            if "/Contents" not in paths:
                return False, "contents_missing"
            # Force directory + key streams to parse, not just header admission.
            ole.openstream(["Contents"]).read(64)
    except Exception as exc:
        return False, f"ole_parse:{type(exc).__name__}"
    classification, _ = harvest_pub.classify(data)
    if classification != "cfb_publisher_hint":
        return False, f"classification:{classification}"
    return True, "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-root", type=Path, required=True)
    ap.add_argument("--rar-tools", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--target-minimum", type=int, default=625)
    ap.add_argument("--root-order", default="1,2,3,0,4")
    ap.add_argument("--max-file-bytes", type=int, default=32 * 1024 * 1024)
    ap.add_argument("--max-container-bytes", type=int, default=320 * 1024 * 1024)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--command-timeout", type=int, default=60)
    args = ap.parse_args()

    sys.path.insert(0, str(args.rar_tools))
    import harvest_pub  # type: ignore
    import structural_novelty_container_delta as delta  # type: ignore

    corpus = args.corpus_root / "corpus" / "native" / "unclassified"
    corpus.mkdir(parents=True, exist_ok=True)
    existing = validate_existing(corpus)
    before = len(existing)
    if before >= args.target_minimum:
        raise SystemExit(f"working corpus already >= target: {before}")

    target = delta.load_target_shas()
    delta.validate_roots()
    order = [int(x) for x in args.root_order.split(",") if x.strip()]
    if len(order) != len(set(order)) or any(i < 0 or i >= len(delta.ROOTS) for i in order):
        raise ValueError("invalid root order")

    args.out.mkdir(parents=True, exist_ok=True)
    observations = []
    rejected = []
    added: set[str] = set()
    by_root = Counter()
    total_added_bytes = 0

    with tempfile.TemporaryDirectory(prefix="lalamu-container-materialize-") as raw:
        td = Path(raw)
        for root_index in order:
            if len(existing) + len(added) >= args.target_minimum:
                break
            root = delta.ROOTS[root_index]
            archive = td / f"root-{root_index}.bin"
            meta = delta.fetch_root(
                str(root["url"]), archive, args.timeout, args.max_container_bytes
            )
            if meta["sha256"] != root["sha256"] or int(meta["size"]) != int(root["size_bytes"]):
                raise ValueError(f"root identity mismatch at index {root_index}")

            matches = []
            for member, declared_size in delta.candidate_members(
                archive, args.command_timeout, args.max_file_bytes
            ):
                data = delta.extract_member_bytes(
                    archive, member, declared_size, td,
                    args.command_timeout, args.max_file_bytes
                )
                member_sha = sha256(data)
                if member_sha not in target or member_sha in existing or member_sha in added:
                    continue
                ok, reason = strict_publisher_cfb(data, harvest_pub)
                if not ok:
                    rejected.append({
                        "sha256": member_sha,
                        "root_index": root_index,
                        "archive_member": member,
                        "reason": reason,
                    })
                    continue
                matches.append((len(data), member_sha, member, data))

            # Prefer smaller exact-authority members inside each source root to
            # keep the public working repo bounded while preserving root diversity.
            matches.sort(key=lambda x: (x[0], x[1]))
            for byte_len, member_sha, member, data in matches:
                if len(existing) + len(added) >= args.target_minimum:
                    break
                path = corpus / f"{member_sha}.pub"
                if path.exists():
                    continue
                path.write_bytes(data)
                added.add(member_sha)
                by_root[str(root_index)] += 1
                total_added_bytes += byte_len
                observations.append({
                    "sha256": member_sha,
                    "byte_len": byte_len,
                    "filename": Path(member).name,
                    "archive_member": member,
                    "root_index": root_index,
                    "root_label": ROOT_LABELS[root_index],
                    "root_sha256": root["sha256"],
                    "source_url": root["url"],
                })
            archive.unlink(missing_ok=True)

    after = len(existing) + len(added)
    if after < args.target_minimum:
        raise ValueError(
            f"target not reached: before={before} added={len(added)} after={after} target={args.target_minimum}"
        )

    observations.sort(key=lambda r: r["sha256"])
    rejected.sort(key=lambda r: (r["root_index"], r["sha256"]))
    summary = {
        "schema": "lalamu.rar-container-delta-materialize.v1",
        "existing_strict_unique_before": before,
        "new_strict_unique": len(added),
        "strict_unique_after": after,
        "target_minimum": args.target_minimum,
        "target_met": after >= args.target_minimum,
        "selection_policy": "exact Rar 407-SHA authority; root-diverse order; strict Publisher CFB; smallest unseen members first within each root",
        "root_order": order,
        "added_by_root_index": dict(sorted(by_root.items(), key=lambda item: int(item[0]))),
        "added_total_bytes": total_added_bytes,
        "rejected_count": len(rejected),
        "rar_target_authority_count": len(target),
    }
    (args.out / "latest.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (args.out / "materialized-manifest.json").write_text(
        json.dumps(observations, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (args.out / "strict-rejections.json").write_text(
        json.dumps(rejected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
