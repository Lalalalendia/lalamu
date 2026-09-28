#!/usr/bin/env python3
"""Capability-aware triage for Lalamu's raw cross-engine PUB observations.

This layer deliberately does not alter the raw oracle receipt. It classifies
each disagreement using explicit engine capability, metric semantics and
parser-lineage metadata so numeric disagreement is not mistaken for a bug.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "oracle-differential" / "latest.json"
DEFAULT_CONTRACT = ROOT / "data" / "oracle-differential" / "capability-contract.json"
DEFAULT_OUTPUT = ROOT / "data" / "oracle-differential" / "capability-triage.json"
SCHEMA = "lalamu.pub-capability-triage.v1"
ALLOWED_CLASSIFICATIONS = {
    "comparable",
    "correlated-oracle",
    "engine-unsupported",
    "semantic-mismatch",
    "needs-native-oracle",
}
ALLOWED_CAPABILITIES = {"supported", "partial", "unknown", "unsupported"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return sha256_bytes(raw)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def metric_id(row: dict[str, Any]) -> str:
    if row.get("kind") == "engine_acceptance_mismatch":
        return "open_acceptance"
    field = row.get("field")
    return str(field) if field else "unknown"


def engine_contract(
    contract: dict[str, Any], engine_id: str, metric: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    engine = (contract.get("engines") or {}).get(engine_id)
    if not isinstance(engine, dict):
        engine = {
            "lineage_group": "unknown",
            "role": "unknown",
            "invocation_mode": "unknown",
            "metrics": {},
        }
    metric_spec = (engine.get("metrics") or {}).get(metric)
    if not isinstance(metric_spec, dict):
        metric_spec = {
            "capability": "unknown",
            "semantics": "unknown",
            "normalization": "unknown",
        }
    capability = str(metric_spec.get("capability") or "unknown")
    if capability not in ALLOWED_CAPABILITIES:
        raise ValueError(
            f"invalid capability {capability!r} for engine={engine_id} metric={metric}"
        )
    return engine, metric_spec


def known_rejection(
    record: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any] | None:
    error = str(((record.get("engines") or {}).get("chaptera") or {}).get("error") or "")
    for rule in contract.get("known_chaptera_rejections") or []:
        marker = str(rule.get("error_contains") or "")
        if marker and marker in error:
            return rule
    return None


def structural_context(
    record: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    known = known_rejection(record, contract)
    corpus = record.get("corpus_context") or {}
    if known:
        family = str(known.get("structural_family") or "unknown")
        authority = "chaptera-bounded-rejection-signature"
    else:
        chaptera = (record.get("engines") or {}).get("chaptera") or {}
        error = str(chaptera.get("error") or "")
        if chaptera.get("status") == "success":
            family = "mature-0x2c"
            authority = "chaptera-mature-viewer-success"
        elif "mature-0x2c" in error.lower() or "mature Story catalog" in error:
            family = "mature-0x2c"
            authority = "chaptera-mature-pipeline-reached"
        else:
            family = "unknown"
            authority = "not-established"

    return {
        "family": family,
        "family_authority": authority,
        "coarse_structure_fingerprint": corpus.get("coarse_structure_fingerprint"),
        "topology_fingerprint": corpus.get("topology_fingerprint"),
    }


def classify_pair(
    row: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    metric = metric_id(row)
    left_id = str(row.get("left") or "")
    right_id = str(row.get("right") or "")
    left_engine, left_metric = engine_contract(contract, left_id, metric)
    right_engine, right_metric = engine_contract(contract, right_id, metric)

    left_lineage = str(left_engine.get("lineage_group") or "unknown")
    right_lineage = str(right_engine.get("lineage_group") or "unknown")
    left_role = str(left_engine.get("role") or "unknown")
    right_role = str(right_engine.get("role") or "unknown")
    left_capability = str(left_metric.get("capability") or "unknown")
    right_capability = str(right_metric.get("capability") or "unknown")
    left_semantics = str(left_metric.get("semantics") or "unknown")
    right_semantics = str(right_metric.get("semantics") or "unknown")

    downstream = "downstream-consumer" in left_role or "downstream-consumer" in right_role
    if "unsupported" in {left_capability, right_capability}:
        classification = "engine-unsupported"
        reason = "metric-explicitly-unsupported"
    elif "unknown" in {left_capability, right_capability}:
        classification = "needs-native-oracle"
        reason = "metric-capability-unknown"
    elif left_lineage == right_lineage or downstream:
        classification = "correlated-oracle"
        reason = "dependent-parser-lineage"
    elif left_semantics != right_semantics:
        classification = "semantic-mismatch"
        reason = "metric-semantics-not-proven-equivalent"
    else:
        classification = "comparable"
        reason = "capability-and-metric-semantics-align"

    if classification not in ALLOWED_CLASSIFICATIONS:
        raise AssertionError(classification)

    return {
        "raw_kind": row.get("kind"),
        "metric_id": metric,
        "classification": classification,
        "reason_code": reason,
        "left": {
            "engine_id": left_id,
            "lineage_group": left_lineage,
            "role": left_role,
            "capability": left_capability,
            "metric_semantics_version": left_semantics,
            "normalization_method": left_metric.get("normalization"),
        },
        "right": {
            "engine_id": right_id,
            "lineage_group": right_lineage,
            "role": right_role,
            "capability": right_capability,
            "metric_semantics_version": right_semantics,
            "normalization_method": right_metric.get("normalization"),
        },
    }


def promotion_disposition(
    row: dict[str, Any],
    classification: dict[str, Any],
    record: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[bool, str | None, list[str]]:
    if row.get("kind") != "engine_acceptance_mismatch":
        return False, None, []
    if classification.get("classification") != "comparable":
        return False, None, []

    pair = {str(row.get("left") or ""), str(row.get("right") or "")}
    if pair != {"chaptera", "libmspub"}:
        return False, None, []

    chaptera_status = ((record.get("engines") or {}).get("chaptera") or {}).get("status")
    libmspub_status = ((record.get("engines") or {}).get("libmspub") or {}).get("status")
    if chaptera_status != "rejected" or libmspub_status != "success":
        return False, None, []

    known = known_rejection(record, contract)
    if known:
        return (
            True,
            str(known.get("reason_code") or "chaptera-bounded-acceptance-asymmetry"),
            [str(value) for value in known.get("linked_owners") or []],
        )
    return True, "chaptera-bounded-acceptance-asymmetry", []


def build_receipt(
    source: dict[str, Any],
    contract: dict[str, Any],
    *,
    input_locator: str,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    classification_counter: Counter[str] = Counter()
    metric_counter: Counter[str] = Counter()
    promotion_candidates: list[dict[str, Any]] = []

    tool_versions = source.get("tool_versions") or {}
    engines_contract = contract.get("engines") or {}

    for record_index, record in enumerate(source.get("records") or []):
        engines = record.get("engines") or {}
        engine_observations: dict[str, Any] = {}
        for engine_id, observation in sorted(engines.items()):
            engine_spec = engines_contract.get(engine_id) or {}
            engine_observations[engine_id] = {
                "engine_id": engine_id,
                "exact_version": tool_versions.get(engine_id),
                "invocation_mode": engine_spec.get("invocation_mode"),
                "lineage_group": engine_spec.get("lineage_group"),
                "role": engine_spec.get("role"),
                "raw_normalized_observation": observation,
                "raw_normalized_observation_sha256": stable_hash(observation),
            }

        classified: list[dict[str, Any]] = []
        for raw_index, row in enumerate(record.get("raw_pairwise_disagreements") or []):
            result = classify_pair(row, contract)
            result["raw_disagreement_index"] = raw_index
            result["raw_disagreement_sha256"] = stable_hash(row)
            result["left"]["observation_sha256"] = (
                engine_observations.get(result["left"]["engine_id"]) or {}
            ).get("raw_normalized_observation_sha256")
            result["right"]["observation_sha256"] = (
                engine_observations.get(result["right"]["engine_id"]) or {}
            ).get("raw_normalized_observation_sha256")

            promote, promotion_reason, linked_owners = promotion_disposition(
                row, result, record, contract
            )
            result["promotion_candidate"] = promote
            if promotion_reason:
                result["promotion_reason_code"] = promotion_reason
            if linked_owners:
                result["linked_owners"] = linked_owners

            classification_counter.update([str(result["classification"])])
            metric_counter.update([str(result["metric_id"])])
            classified.append(result)

            if promote:
                promotion_candidates.append(
                    {
                        "fixture_sha256": record.get("sha256"),
                        "record_locator": f"{input_locator}#records/{record_index}",
                        "raw_disagreement_index": raw_index,
                        "reason_code": promotion_reason,
                        "linked_owners": linked_owners,
                    }
                )

        corpus = record.get("corpus_context") or {}
        source_meta = corpus.get("source") or {}
        records.append(
            {
                "fixture_sha256": record.get("sha256"),
                "byte_len": record.get("byte_len"),
                "record_locator": f"{input_locator}#records/{record_index}",
                "structural_context": structural_context(record, contract),
                "source_provenance": {
                    "source_type": source_meta.get("source_type"),
                    "candidate_id": source_meta.get("candidate_id"),
                    "source_repo": source_meta.get("source_repo"),
                    "source_filename": source_meta.get("source_filename"),
                },
                "engine_observations": engine_observations,
                "classifications": classified,
            }
        )

    page_count_classifications = Counter()
    for record in records:
        for row in record["classifications"]:
            if row.get("metric_id") == "page_count":
                page_count_classifications.update([str(row.get("classification"))])

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "contract_schema": contract.get("schema"),
        "input_schema": source.get("schema"),
        "input_receipt_sha256": source.get("receipt_sha256") or stable_hash(source),
        "input_locator": input_locator,
        "selected_file_count": source.get("selected_file_count"),
        "raw_pairwise_issue_counts": source.get("raw_pairwise_issue_counts") or {},
        "classification_counts": dict(sorted(classification_counter.items())),
        "metric_counts": dict(sorted(metric_counter.items())),
        "page_count_classification_counts": dict(sorted(page_count_classifications.items())),
        "promotion_candidate_count": len(promotion_candidates),
        "promotion_candidates": promotion_candidates,
        "interpretation": (
            "Raw observations are preserved. Classifications depend on explicit engine capability, "
            "metric semantics and lineage. Numeric disagreement is not a vote and is not a bug "
            "candidate unless the compared capability/semantics are aligned."
        ),
        "records": records,
    }
    receipt["receipt_sha256"] = stable_hash(receipt)
    return receipt


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("schema") != "lalamu.pub-differential-capability-contract.v1":
        raise ValueError("unexpected capability contract schema")
    engines = contract.get("engines")
    if not isinstance(engines, dict) or not engines:
        raise ValueError("capability contract must define engines")
    for engine_id, engine in engines.items():
        if not isinstance(engine, dict):
            raise ValueError(f"engine contract {engine_id} must be an object")
        metrics = engine.get("metrics")
        if not isinstance(metrics, dict) or "open_acceptance" not in metrics:
            raise ValueError(f"engine contract {engine_id} lacks open_acceptance")
        for metric_id_value, metric in metrics.items():
            capability = str((metric or {}).get("capability") or "unknown")
            if capability not in ALLOWED_CAPABILITIES:
                raise ValueError(
                    f"invalid capability {capability!r} for {engine_id}/{metric_id_value}"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source = load_json(args.input)
    contract = load_json(args.contract)
    validate_contract(contract)
    receipt = build_receipt(
        source,
        contract,
        input_locator="pub-corpus/data/oracle-differential/latest.json",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "schema": receipt["schema"],
                "selected_file_count": receipt["selected_file_count"],
                "classification_counts": receipt["classification_counts"],
                "page_count_classification_counts": receipt[
                    "page_count_classification_counts"
                ],
                "promotion_candidate_count": receipt["promotion_candidate_count"],
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
