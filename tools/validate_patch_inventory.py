#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "research" / "patch-inventory-01" / "servicing-matrix.json"

EXPECTED_TARGETS = {
    "Publisher 97","Publisher 98","Publisher 2000","Publisher 2002",
    "Publisher 2003","Publisher 2007","Publisher 2010","Publisher 2013",
    "Publisher 2016","Publisher 2019","Publisher 2021","Publisher LTSC 2021",
    "Publisher for Microsoft 365",
}
EXPECTED_SP = {
    "Publisher 2002": {"Office XP SP1","Office XP SP2","Office XP SP3"},
    "Publisher 2003": {"Office 2003 SP1","Office 2003 SP2","Office 2003 SP3"},
    "Publisher 2007": {"Publisher/Office 2007 SP1","Publisher/Office 2007 SP2","Publisher/Office 2007 SP3"},
    "Publisher 2010": {"Office 2010 SP1","Office 2010 SP2"},
    "Publisher 2013": {"Office 2013 SP1"},
}


def main() -> int:
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert data["schema_version"] == "chaptera.publisher-servicing.v1"
    assert set(data["target_generations"]) == EXPECTED_TARGETS
    assert data["policy"]["office_suite_boundary_is_not_publisher_binary_delta"] is True
    assert data["policy"]["missing_kb_is_recorded_as_gap_not_guessed"] is True
    assert data["policy"]["update_package_execution_performed"] is False

    sources = data["sources"]
    assert sources
    for key, source in sources.items():
        parsed = urlparse(source["url"])
        assert parsed.scheme == "https", (key, source["url"])
        assert parsed.netloc, (key, source["url"])
        assert source["authority"].startswith("microsoft_"), (key, source["authority"])
        assert source["supports"], key

    rows = data["rows"]
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), "duplicate row id"

    by_generation: dict[str, list[dict]] = {}
    for item in rows:
        assert item["generation"] in EXPECTED_TARGETS, item["generation"]
        assert item["epoch_kind"] in {"rtm","service_pack","servicing_model","publisher_update"}
        assert item["publisher_module_impact"]
        assert item["publisher_scope"]
        for ref in item["source_refs"]:
            assert ref in sources, (item["id"], ref)
        if item["release_date"] is not None:
            parts = item["release_date"].split("-")
            assert len(parts) == 3 and all(part.isdigit() for part in parts), item["id"]
        by_generation.setdefault(item["generation"], []).append(item)

    gaps_by_generation = {}
    for gap in data["gaps"]:
        assert gap["generation"] in EXPECTED_TARGETS
        assert gap["detail"]
        gaps_by_generation.setdefault(gap["generation"], []).append(gap)

    for generation in EXPECTED_TARGETS:
        assert generation in by_generation or generation in gaps_by_generation, generation

    for generation, expected in EXPECTED_SP.items():
        actual = {
            row["epoch_label"]
            for row in by_generation[generation]
            if row["epoch_kind"] == "service_pack"
        }
        assert expected <= actual, (generation, expected - actual)

    # Never invent service-pack rows for post-2013 lines.
    for generation in (
        "Publisher 2016","Publisher 2019","Publisher 2021",
        "Publisher LTSC 2021","Publisher for Microsoft 365"
    ):
        assert not any(row["epoch_kind"] == "service_pack" for row in by_generation[generation]), generation

    rowmap = {row["id"]: row for row in rows}
    assert rowmap["pub2016-msi-servicing"]["epoch_label"].endswith("Service Pack = N/A")
    assert rowmap["pub2019-c2r-servicing"]["cumulative"] is True
    assert rowmap["pub2021-ltsc-servicing"]["cumulative"] is True
    assert rowmap["pub2010-sp1"]["kb_ids"] == ["2460049"]
    assert rowmap["pub2010-sp2"]["kb_ids"] == ["2687455"]
    assert rowmap["pub2013-sp1"]["kb_ids"] == ["2817430"]
    assert rowmap["pub2003-sp3"]["kb_ids"] == ["923618"]

    # Suite-level rows must not masquerade as proven Publisher binary deltas.
    for item in rows:
        if item["publisher_scope"] == "suite_boundary":
            assert "unknown" in item["publisher_module_impact"], item["id"]

    unresolved = {gap["generation"] for gap in data["gaps"] if gap["gap_kind"] == "servicing_skeleton_unresolved"}
    assert unresolved == {"Publisher 97","Publisher 98","Publisher 2000"}

    print(json.dumps({
        "rows": len(rows),
        "sources": len(sources),
        "gaps": len(data["gaps"]),
        "service_pack_generations": sorted(EXPECTED_SP),
        "unresolved_legacy_generations": sorted(unresolved),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
