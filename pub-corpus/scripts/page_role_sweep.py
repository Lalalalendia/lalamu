#!/usr/bin/env python3
"""Sweep Chaptera page-role observations over the public PUB corpus.

The heuristic scoreboard is discovery-only. It ranks simple source-observable
predicates by how often their selected-page count matches the external
libmspub-lineage page count. It does not promote those predicates to truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "corpus" / "native" / "unclassified"
DEFAULT_DIFF = ROOT / "data" / "oracle-differential" / "latest.json"
DEFAULT_OUTPUT = ROOT / "data" / "page-role-sweep" / "latest.json"
SCHEMA = "lalamu.pub-page-role-sweep.v1"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def clean_error(value: bytes) -> str:
    return value.decode("utf-8", errors="replace").strip()[:1000]


def run_probe(binary: Path, path: Path, timeout: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [str(binary), str(path)],
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except OSError as exc:
        return {"status": "spawn-failure", "error": f"{type(exc).__name__}: {exc}"}

    if completed.returncode != 0:
        return {
            "status": "rejected",
            "returncode": completed.returncode,
            "error": clean_error(completed.stderr),
        }
    try:
        receipt = json.loads(completed.stdout.decode("utf-8"))
    except Exception as exc:
        return {
            "status": "invalid-output",
            "error": f"{type(exc).__name__}: {exc}",
            "stdout_sha256": sha256_bytes(completed.stdout),
        }
    return {"status": "success", "receipt": receipt}


def load_differential(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(row.get("sha256") or "").lower(): row
        for row in payload.get("records") or []
        if row.get("sha256")
    }


def page_bool(page: dict[str, Any], name: str, pgt_value: int | None = None) -> bool:
    if name == "shape_child_count>0":
        return int(page.get("shape_child_count") or 0) > 0
    if name == "group_child_count>0":
        return int(page.get("group_child_count") or 0) > 0
    if name == "shape_or_group_child>0":
        return int(page.get("shape_child_count") or 0) > 0 or int(page.get("group_child_count") or 0) > 0
    if name == "content_oid_or_table":
        child_counts = page.get("child_raw_type_counts") or {}
        has_shape_or_group = (
            int(page.get("shape_child_count") or 0) > 0
            or int(page.get("group_child_count") or 0) > 0
        )
        oid_nonzero = (
            int(page.get("oid_dword0") or 0) != 0
            or int(page.get("oid_dword1") or 0) != 0
        )
        # Raw Contents type 0x10 is TABLE in libmspub's mature chunk registry.
        # This is a discovery predicate only, not a production page-role law.
        has_table_child = int(child_counts.get("16") or 0) > 0
        return (has_shape_or_group and oid_nonzero) or has_table_child
    if name == "applied_master_present":
        return page.get("applied_master_seq_num") is not None
    if name == "applied_master_absent":
        return page.get("applied_master_seq_num") is None
    if name == "oid_pair_complete":
        return page.get("oid_dword0") is not None and page.get("oid_dword1") is not None
    if name == "pgt_type_is_none":
        return page.get("pgt_type") is None
    if name == "pgt_type_equals":
        return page.get("pgt_type") == pgt_value
    if name == "pgt_type_not_equals":
        return page.get("pgt_type") is not None and page.get("pgt_type") != pgt_value
    if name == "pgt_and_shape":
        return page.get("pgt_type") == pgt_value and int(page.get("shape_child_count") or 0) > 0
    raise ValueError(name)


def predicate_specs(pgt_values: list[int]) -> list[tuple[str, str, int | None]]:
    specs: list[tuple[str, str, int | None]] = [
        ("shape_child_count>0", "shape_child_count>0", None),
        ("group_child_count>0", "group_child_count>0", None),
        ("shape_or_group_child>0", "shape_or_group_child>0", None),
        (
            "(shape_or_group_child>0 AND oid_nonzero) OR TABLE_child",
            "content_oid_or_table",
            None,
        ),
        ("applied_master_present", "applied_master_present", None),
        ("applied_master_absent", "applied_master_absent", None),
        ("oid_pair_complete", "oid_pair_complete", None),
        ("pgt_type_is_none", "pgt_type_is_none", None),
    ]
    for value in pgt_values:
        specs.extend(
            [
                (f"pgt_type=={value}", "pgt_type_equals", value),
                (f"pgt_type!={value}", "pgt_type_not_equals", value),
                (f"pgt_type=={value} AND shape_child_count>0", "pgt_and_shape", value),
            ]
        )
    return specs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-bin", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--differential", type=Path, default=DEFAULT_DIFF)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    probe = args.probe_bin.resolve()
    differential = load_differential(args.differential)
    records: list[dict[str, Any]] = []
    pgt_values: set[int] = set()
    status_counts: Counter[str] = Counter()

    for path in sorted(args.corpus.rglob("*.pub")):
        sha = path.stem.lower()
        observation = run_probe(probe, path, args.timeout)
        status_counts[observation["status"]] += 1
        diff = differential.get(sha) or {}
        engines = diff.get("engines") or {}
        external = engines.get("libmspub") or {}
        chaptera = engines.get("chaptera") or {}

        record: dict[str, Any] = {
            "sha256": sha,
            "byte_len": path.stat().st_size,
            "probe": observation,
            "chaptera_viewer_page_count": chaptera.get("page_count"),
            "libmspub_lineage_page_count": external.get("page_count"),
            "corpus_context": diff.get("corpus_context") or {},
        }
        if observation.get("status") == "success":
            receipt = observation["receipt"]
            for page in receipt.get("pages") or []:
                if isinstance(page.get("pgt_type"), int):
                    pgt_values.add(page["pgt_type"])
        records.append(record)

    scored_files = [
        row
        for row in records
        if row["probe"].get("status") == "success"
        and isinstance(row.get("libmspub_lineage_page_count"), int)
    ]

    scoreboard: list[dict[str, Any]] = []
    for display_name, predicate_name, value in predicate_specs(sorted(pgt_values)):
        exact = 0
        total_error = 0
        max_error = 0
        per_file: list[dict[str, Any]] = []
        for row in scored_files:
            pages = row["probe"]["receipt"].get("pages") or []
            selected = sum(
                1 for page in pages if page_bool(page, predicate_name, value)
            )
            external_count = int(row["libmspub_lineage_page_count"])
            error = abs(selected - external_count)
            total_error += error
            max_error = max(max_error, error)
            if error == 0:
                exact += 1
            per_file.append(
                {
                    "sha256": row["sha256"],
                    "selected_count": selected,
                    "libmspub_lineage_page_count": external_count,
                    "absolute_count_error": error,
                }
            )

        scoreboard.append(
            {
                "predicate": display_name,
                "exact_file_count": exact,
                "evaluated_file_count": len(scored_files),
                "total_absolute_count_error": total_error,
                "max_absolute_count_error": max_error,
                "per_file": per_file,
            }
        )

    scoreboard.sort(
        key=lambda row: (
            -row["exact_file_count"],
            row["total_absolute_count_error"],
            row["max_absolute_count_error"],
            row["predicate"],
        )
    )

    receipt = {
        "schema": SCHEMA,
        "chaptera_upstream_commit": __import__("os").environ.get("CHAPTERA_UPSTREAM_COMMIT"),
        "status_counts": dict(sorted(status_counts.items())),
        "scored_file_count": len(scored_files),
        "observed_pgt_types": sorted(pgt_values),
        "heuristic_warning": (
            "Predicate scores are discovery aids only. The comparison count comes from the "
            "libmspub parser lineage; LibreOffice is not an independent Publisher parser vote. "
            "A candidate predicate requires separate source-semantic validation before use. "
            "In particular, do not copy libmspub's historical hard-coded DUMMY_PAGE seqNums "
            "into Chaptera; those constants are oracle-mechanism evidence, not native semantics."
        ),
        "candidate_predicate_scoreboard": scoreboard[:30],
        "records": records,
    }
    receipt["receipt_sha256"] = stable_hash(receipt)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "status_counts": receipt["status_counts"],
                "scored_file_count": receipt["scored_file_count"],
                "top_predicates": [
                    {
                        "predicate": row["predicate"],
                        "exact_file_count": row["exact_file_count"],
                        "total_absolute_count_error": row["total_absolute_count_error"],
                    }
                    for row in scoreboard[:10]
                ],
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
