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

    # Endpoint manifest anchors for Publisher 2013/2016.
    assert data["policy"]["manifest_subset_must_be_labeled"] is True
    assert rowmap["pub2013-kb5002213"]["kb_ids"] == ["5002213"]
    assert rowmap["pub2013-kb5002213"]["replaces_kb_ids"] == ["4484347"]
    assert rowmap["pub2013-kb5002213"]["package_sha256"]["x86"] == "D27F70BA78B7A8B3BFE97D1BB644D480DB56EC6277A8DE88CB1C8C303B6E721F"
    assert rowmap["pub2013-kb5002213"]["package_sha256"]["x64"] == "513A10C7E3B6F55444AB6057B185B51C86F595328A0AAFE4E6F9E78A52333062"
    assert "subset" in rowmap["pub2013-kb5002213"]["file_manifest_scope"].lower()
    core2013 = {x["file"]: x for x in rowmap["pub2013-kb5002213"]["file_manifest_core"]["x86"]}
    assert core2013["mspub.exe"]["version"] == "15.0.5545.1000"
    assert core2013["pubconv.dll"]["version"] == "15.0.5545.1000"

    assert rowmap["pub2016-kb5002566"]["kb_ids"] == ["5002566"]
    assert rowmap["pub2016-kb5002566"]["replaces_kb_ids"] == ["5002492"]
    assert rowmap["pub2016-kb5002566"]["package_sha256"]["x86"] == "98D3616C39DDC89FAD7883FE28535841F32EB2BD932877C21632517AA8547807"
    assert rowmap["pub2016-kb5002566"]["package_sha256"]["x64"] == "CA5CA37A7B149DE8978EF85FC0951E989722CA6F7594C21CA8FB9A3DE53E0AEA"
    assert "subset" in rowmap["pub2016-kb5002566"]["file_manifest_scope"].lower()
    core2016x86 = {x["file"]: x for x in rowmap["pub2016-kb5002566"]["file_manifest_core"]["x86"]}
    core2016x64 = {x["file"]: x for x in rowmap["pub2016-kb5002566"]["file_manifest_core"]["x64"]}
    assert core2016x86["mspub.exe"]["version"] == "16.0.5460.1000"
    assert core2016x64["mspub.exe"]["version"] == "16.0.5460.1000"
    assert core2016x64["pubconv.dll"]["version"] == "16.0.5391.1000"

    assert rowmap["pub2016-kb5002644"]["kb_ids"] == ["5002644"]
    assert rowmap["pub2016-kb5002644"]["replaces_kb_ids"] == ["5002566"]
    assert rowmap["pub2016-kb5002644"]["package_sha256"]["x86"] == "BBD16AA927F5CF4663A9157C88519BD11349B6D9C42C840212FD97FBB2B5AED3"
    assert rowmap["pub2016-kb5002644"]["package_sha256"]["x64"] == "2A4A16F88B3EDBC14A86B3F6D42455AFB18D3A5F00ACEE23ABBFB16AC9593333"
    assert rowmap["pub2016-kb5002644"]["replaces_kb_ids"] == rowmap["pub2016-kb5002566"]["kb_ids"]
    assert "not normalize" in rowmap["pub2016-kb5002644"]["file_manifest_scope"].lower()

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
        "endpoint_manifest_rows": sum("file_manifest_core" in row for row in publisher_updates),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
