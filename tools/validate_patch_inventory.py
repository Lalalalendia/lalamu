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

    # Publisher-specific update wave must stay distinct from suite boundaries.
    publisher_updates = [row for row in rows if row["epoch_kind"] == "publisher_update"]
    update_ids = {row["id"] for row in publisher_updates}
    expected_update_ids = {
        "pub2002-ms10-103", "pub2003-ms10-103", "pub2007-ms10-103", "pub2010-ms10-103",
        "pub2003-ms13-042", "pub2007-ms13-042", "pub2010-ms13-042",
        "pub2010-ms16-148",
    }
    assert expected_update_ids <= update_ids, sorted(expected_update_ids - update_ids)

    expected_kbs = {
        "pub2002-ms10-103": ["2284692"],
        "pub2003-ms10-103": ["2284695"],
        "pub2007-ms10-103": ["2284697"],
        "pub2010-ms10-103": ["2409055"],
        "pub2003-ms13-042": ["2810047"],
        "pub2007-ms13-042": ["2597971"],
        "pub2010-ms13-042": ["2553147"],
        "pub2010-ms16-148": ["3114395"],
    }
    for row_id, kb_ids in expected_kbs.items():
        assert rowmap[row_id]["kb_ids"] == kb_ids, row_id
        assert rowmap[row_id]["package_names"], row_id
        assert rowmap[row_id]["publisher_scope"] == "publisher_specific_security_update", row_id
        assert "suite_level_unknown" not in rowmap[row_id]["publisher_module_impact"], row_id

    assert rowmap["pub2003-ms13-042"]["replaces_kb_ids"] == ["2553084"]
    assert rowmap["pub2007-ms13-042"]["replaces_kb_ids"] == ["2596705"]
    assert rowmap["pub2010-ms13-042"]["replaces_kb_ids"] == []
    assert rowmap["pub2010-ms16-148"]["replaces_kb_ids"] == ["2817478"]
    assert rowmap["pub2010-ms16-148"]["package_sha256"] == {
        "x86": "9BF8C3771B133781B29FFE24A913D62FD9A009A8C5DA46A80E192805759063D8",
        "x64": "0E832B9654556C8B43ADC128A6E85B4412FDA6B7989AFD7CA1FBEEB8B69774A4",
    }

    manifest = rowmap["pub2010-ms16-148"]["file_manifest"]
    for arch in ("x86", "x64"):
        names = {item["file"] for item in manifest[arch]}
        assert {"mspub.exe", "pubconv.dll", "ptxt9.dll", "morph9.dll", "prtf9.dll", "pubtrap.dll"} <= names
    assert next(x for x in manifest["x86"] if x["file"] == "mspub.exe")["version"] == "14.0.7162.5000"
    assert next(x for x in manifest["x64"] if x["file"] == "mspub.exe")["version"] == "14.0.7162.5000"
    assert next(x for x in manifest["x86"] if x["file"] == "ptxt9.dll")["version"] == "14.0.7177.5000"

    negative = {
        (item["event"], item["generation"], item["status"])
        for item in data.get("negative_applicability", [])
    }
    assert ("MS13-042", "Publisher 2013", "explicitly_non_affected") in negative

    unresolved = {gap["generation"] for gap in data["gaps"] if gap["gap_kind"] == "servicing_skeleton_unresolved"}
    assert unresolved == {"Publisher 97","Publisher 98","Publisher 2000"}

    print(json.dumps({
        "rows": len(rows),
        "sources": len(sources),
        "gaps": len(data["gaps"]),
        "service_pack_generations": sorted(EXPECTED_SP),
        "unresolved_legacy_generations": sorted(unresolved),
        "publisher_update_rows": len(publisher_updates),
        "exact_binary_manifest_rows": sum("file_manifest" in row for row in publisher_updates),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
