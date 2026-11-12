"""Deterministic source-free proof for OPEN-FIRST-USEFUL-PAGE-HARNESS-01."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

RECEIPT_VERSION = "chaptera.open-first-useful-page.proof.v1"
PHASE_IDS = [
    "source_container_open",
    "profile_classification",
    "logical_stream_read",
    "parse_model_projection",
    "first_page_dependency_resolution",
    "first_page_layout_scene",
    "visible_resource_decode",
    "first_paint",
    "background_remaining_document",
    "search_index_ready",
]
SCOPES = {"first_page_only", "bounded_dependencies", "document_global", "background"}
USEFUL_FLAGS = [
    "page_geometry_present",
    "fidelity_diagnostics_present",
    "visible_resources_ready",
    "current_text_layout_present",
    "non_empty_visible_content",
]


class ReceiptError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _phase(
    phase_id: str,
    start_ms: int,
    end_ms: int,
    scope: str,
    *,
    bytes_read: int = 0,
    bytes_materialized: int = 0,
    pages_touched: int = 0,
    stories_touched: int = 0,
    resources_touched: int = 0,
) -> dict[str, Any]:
    return {
        "phase_id": phase_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "scope": scope,
        "bytes_read": bytes_read,
        "bytes_materialized": bytes_materialized,
        "pages_touched": pages_touched,
        "stories_touched": stories_touched,
        "resources_touched": resources_touched,
    }


def build_run(
    fixture_hash: str,
    fixture_bytes: int,
    cache_state: str,
    run_index: int,
    *,
    process_mode: str,
) -> dict[str, Any]:
    if cache_state not in {"cold", "warm"}:
        raise ReceiptError("cache_state must be cold or warm")
    if process_mode not in {"fresh_process", "same_process_series"}:
        raise ReceiptError("unsupported process_mode")

    # Logical ticks prove phase ordering/orchestration only. They are intentionally
    # not wall-clock observations and cannot justify product latency decisions.
    scale_num = 100 if cache_state == "cold" else 70
    jitter = run_index % 3

    def t(base: int) -> int:
        return (base * scale_num) // 100 + jitter

    size = max(fixture_bytes, 1)
    phases = [
        _phase("source_container_open", 0, t(8), "bounded_dependencies", bytes_read=min(size, 4096)),
        _phase("profile_classification", t(8), t(10), "bounded_dependencies"),
        _phase(
            "logical_stream_read",
            t(10),
            t(28),
            "document_global",
            bytes_read=size,
            bytes_materialized=size,
        ),
        _phase(
            "parse_model_projection",
            t(28),
            t(52),
            "document_global",
            pages_touched=3,
            stories_touched=2,
        ),
        _phase(
            "first_page_dependency_resolution",
            t(52),
            t(60),
            "bounded_dependencies",
            pages_touched=1,
            stories_touched=1,
            resources_touched=2,
        ),
        _phase(
            "first_page_layout_scene",
            t(60),
            t(72),
            "first_page_only",
            pages_touched=1,
            stories_touched=1,
        ),
        _phase(
            "visible_resource_decode",
            t(72),
            t(80),
            "bounded_dependencies",
            resources_touched=2,
        ),
        _phase("first_paint", t(80), t(84), "first_page_only", pages_touched=1),
        _phase(
            "background_remaining_document",
            t(84),
            t(118),
            "background",
            pages_touched=2,
            stories_touched=1,
        ),
        _phase("search_index_ready", t(92), t(124), "background", stories_touched=2),
    ]

    first_useful = phases[7]["end_ms"]
    useful = {flag: True for flag in USEFUL_FLAGS}
    global_before_first = [
        phase["phase_id"]
        for phase in phases
        if phase["scope"] == "document_global" and phase["start_ms"] < first_useful
    ]
    canonical_output = hashlib.sha256(
        ("canonical:" + fixture_hash).encode("ascii")
    ).hexdigest()

    return {
        "cache_state": cache_state,
        "process_mode": process_mode,
        "fixture_hash": fixture_hash,
        "fixture_bytes": fixture_bytes,
        "first_useful_page_ms": first_useful,
        "fully_ready_ms": max(phase["end_ms"] for phase in phases),
        "first_useful_page_definition": useful,
        "phases": phases,
        "document_global_before_first_useful_page": global_before_first,
        "plain_output_sha256": canonical_output,
        "instrumented_output_sha256": canonical_output,
    }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cache_state in ("cold", "warm"):
        rows = [run for run in runs if run["cache_state"] == cache_state]
        if not rows:
            continue
        result[cache_state] = {
            "sample_count": len(rows),
            "first_useful_page_min_ms": min(run["first_useful_page_ms"] for run in rows),
            "first_useful_page_max_ms": max(run["first_useful_page_ms"] for run in rows),
            "fully_ready_min_ms": min(run["fully_ready_ms"] for run in rows),
            "fully_ready_max_ms": max(run["fully_ready_ms"] for run in rows),
            "process_modes": sorted({run["process_mode"] for run in rows}),
        }
    return result


def build_receipt(
    fixture: Path,
    cold_runs: list[dict[str, Any]],
    warm_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    fixture_hash = sha256_file(fixture)
    fixture_bytes = fixture.stat().st_size
    runs = cold_runs + warm_runs

    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "measurement_class": "synthetic_contract_fixture",
        "timing_semantics": "deterministic_logical_ticks_not_wall_clock",
        "fixture_identity": {
            "sha256": fixture_hash,
            "byte_len": fixture_bytes,
            "raw_path": None,
        },
        "runs": runs,
        "summary": summarize_runs(runs),
        "final_equivalence": {
            "canonical_document_equal": True,
            "final_scene_equal": True,
            "final_search_projection_equal": True,
        },
        "evidence_authority": {
            "real_pub_runtime": False,
            "architecture_decision_allowed": False,
            "blocker": "clean hosted proof validates mechanics only, not product latency or Reader integration",
        },
        "limitations": [
            "Logical ticks are deterministic contract data, not wall-clock timing.",
            "Document-global work before first useful page is reported, not optimized.",
            "Canonical Reader integration remains a separate replay step.",
        ],
    }
    validate_receipt(receipt)
    return receipt


def validate_run(run: dict[str, Any]) -> None:
    if run.get("cache_state") not in {"cold", "warm"}:
        raise ReceiptError("invalid cache_state")
    if run.get("process_mode") not in {"fresh_process", "same_process_series"}:
        raise ReceiptError("invalid process_mode")
    if run.get("fixture_bytes", -1) < 0:
        raise ReceiptError("invalid fixture_bytes")
    if not isinstance(run.get("fixture_hash"), str) or len(run["fixture_hash"]) != 64:
        raise ReceiptError("invalid fixture_hash")

    useful = run.get("first_useful_page_definition")
    if not isinstance(useful, dict):
        raise ReceiptError("first_useful_page_definition required")
    for flag in USEFUL_FLAGS:
        if useful.get(flag) is not True:
            raise ReceiptError(f"first useful page flag must be true: {flag}")

    phases = run.get("phases")
    if not isinstance(phases, list) or [p.get("phase_id") for p in phases] != PHASE_IDS:
        raise ReceiptError("phase order mismatch")

    for phase in phases:
        if phase["scope"] not in SCOPES:
            raise ReceiptError("invalid phase scope")
        if phase["end_ms"] < phase["start_ms"]:
            raise ReceiptError("phase end precedes start")
        for key in (
            "bytes_read",
            "bytes_materialized",
            "pages_touched",
            "stories_touched",
            "resources_touched",
        ):
            if not isinstance(phase[key], int) or phase[key] < 0:
                raise ReceiptError(f"invalid counter: {key}")

    first_useful = run["first_useful_page_ms"]
    if first_useful != phases[7]["end_ms"]:
        raise ReceiptError("first useful page must end at first_paint")
    if run["fully_ready_ms"] < first_useful:
        raise ReceiptError("fully ready precedes first useful page")

    expected_global = [
        phase["phase_id"]
        for phase in phases
        if phase["scope"] == "document_global" and phase["start_ms"] < first_useful
    ]
    if run["document_global_before_first_useful_page"] != expected_global:
        raise ReceiptError("document-global pre-first declaration mismatch")

    if run["plain_output_sha256"] != run["instrumented_output_sha256"]:
        raise ReceiptError("instrumented/plain final output drift")


def validate_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("receipt_version") != RECEIPT_VERSION:
        raise ReceiptError("receipt version mismatch")
    if receipt.get("measurement_class") != "synthetic_contract_fixture":
        raise ReceiptError("proof must remain synthetic_contract_fixture")
    if receipt.get("timing_semantics") != "deterministic_logical_ticks_not_wall_clock":
        raise ReceiptError("timing semantics mismatch")

    fixture = receipt.get("fixture_identity")
    if not isinstance(fixture, dict):
        raise ReceiptError("fixture_identity required")
    if fixture.get("raw_path") is not None:
        raise ReceiptError("raw fixture path must not enter receipt")
    if not isinstance(fixture.get("sha256"), str) or len(fixture["sha256"]) != 64:
        raise ReceiptError("fixture sha256 required")
    if not isinstance(fixture.get("byte_len"), int) or fixture["byte_len"] < 0:
        raise ReceiptError("fixture byte_len invalid")

    runs = receipt.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ReceiptError("runs required")
    for run in runs:
        validate_run(run)
        if run["fixture_hash"] != fixture["sha256"] or run["fixture_bytes"] != fixture["byte_len"]:
            raise ReceiptError("run fixture identity mismatch")

    cold = [run for run in runs if run["cache_state"] == "cold"]
    warm = [run for run in runs if run["cache_state"] == "warm"]
    if cold and any(run["process_mode"] != "fresh_process" for run in cold):
        raise ReceiptError("cold runs must be fresh_process")
    if warm and any(run["process_mode"] != "same_process_series" for run in warm):
        raise ReceiptError("warm runs must be same_process_series")

    if receipt.get("summary") != summarize_runs(runs):
        raise ReceiptError("summary mismatch")

    equivalence = receipt.get("final_equivalence")
    if not isinstance(equivalence, dict) or not all(
        equivalence.get(key) is True
        for key in (
            "canonical_document_equal",
            "final_scene_equal",
            "final_search_projection_equal",
        )
    ):
        raise ReceiptError("final equivalence must be true")

    authority = receipt.get("evidence_authority")
    if not isinstance(authority, dict):
        raise ReceiptError("evidence_authority required")
    if authority.get("real_pub_runtime") is not False:
        raise ReceiptError("clean proof is not real PUB runtime")
    if authority.get("architecture_decision_allowed") is not False:
        raise ReceiptError("hosted proof must not authorize architecture decisions")


def dumps(receipt: dict[str, Any]) -> str:
    return json.dumps(receipt, indent=2, sort_keys=True) + "\n"
