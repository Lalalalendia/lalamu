#!/usr/bin/env python3
import json
from pathlib import Path
import sys

ALLOWED = {"MATCH", "MISMATCH", "UNKNOWN", "CHAPTERA-ONLY"}


def validate(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "chaptera.publisher-parity.tranche.v1":
        raise ValueError("schema version mismatch")
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows required")

    counts = {key: 0 for key in ALLOWED}
    seen = set()
    for row in rows:
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id or row_id in seen:
            raise ValueError("row ids must be unique non-empty strings")
        seen.add(row_id)
        verdict = row.get("verdict")
        if verdict not in ALLOWED:
            raise ValueError(f"invalid verdict: {verdict}")
        counts[verdict] += 1
        if not row.get("chaptera_evidence"):
            raise ValueError(f"Chaptera evidence missing: {row_id}")
        if not row.get("publisher_source"):
            raise ValueError(f"Publisher source missing: {row_id}")
        if verdict == "MISMATCH" and not row.get("owner"):
            raise ValueError(f"MISMATCH must have existing owner: {row_id}")

    expected = data.get("summary", {})
    mapping = {
        "MATCH": "match",
        "MISMATCH": "mismatch",
        "UNKNOWN": "unknown",
        "CHAPTERA-ONLY": "chaptera_only",
    }
    for verdict, key in mapping.items():
        if expected.get(key) != counts[verdict]:
            raise ValueError(f"summary mismatch for {key}")

    if expected.get("duplicate_owners_created") != 0:
        raise ValueError("tranche must not claim duplicate owner creation")
    guardrails = data.get("guardrails", {})
    if guardrails.get("pub_wire_format_claims_allowed") is not False:
        raise ValueError("wire-format claim fence must remain false")
    if guardrails.get("full_sweep_complete") is not False:
        raise ValueError("this tranche must not claim full sweep closure")
    if guardrails.get("ctrl_u_ctrl_j_ctrl_m_new_bindings_authorized") is not False:
        raise ValueError("gated bindings must remain unauthorized")
    return data


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "research/air-editor-parity/tranche-1.json")
    data = validate(path)
    print(json.dumps({
        "rows": len(data["rows"]),
        "match": data["summary"]["match"],
        "mismatch": data["summary"]["mismatch"],
        "full_sweep_complete": data["guardrails"]["full_sweep_complete"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
