#!/usr/bin/env python3
"""Deep, source-free profile of the materialized PUB working corpus.

Reuses the pinned Rar structural novelty probe and the current Chaptera
corpus-reader-receipt binary. Retained outputs contain hashes/counts/diagnostics
only; no recovered document text or image bytes are written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_names(root: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}

    manifest = root / "data" / "manifest.jsonl"
    if manifest.exists():
        for raw in manifest.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            sha = str(row.get("sha256") or "").lower()
            if len(sha) != 64:
                continue
            out.setdefault(sha, {})
            for src, dst in (
                ("source_filename", "file_name"),
                ("source_type", "source_type"),
                ("source_url", "source_url"),
                ("candidate_id", "candidate_id"),
            ):
                value = str(row.get(src) or "").strip()
                if value:
                    out[sha][dst] = value

    rehydrated = root / "data" / "rar-cc-rehydrate" / "rehydrated-manifest.json"
    rows = load_json(rehydrated, [])
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            sha = str(row.get("sha256") or "").lower()
            if len(sha) != 64:
                continue
            out.setdefault(sha, {})
            name = str(row.get("candidate_filename") or "").strip()
            if name:
                out[sha]["file_name"] = name
            host = str(row.get("cc_source_host") or "").strip()
            if host:
                out[sha]["source_host"] = host
            crawl = str(row.get("cc_crawl") or "").strip()
            if crawl:
                out[sha]["source_crawl"] = crawl
            out[sha]["source_type"] = "common_crawl_exact_rehydrate"
    return out


def carrier_pattern(flags: dict[str, bool]) -> str:
    enabled = [key for key, value in sorted(flags.items()) if value]
    return "|".join(enabled) if enabled else "none"


def storage_feature_projection(probe: dict[str, Any]) -> dict[str, Any]:
    # Rar's bounded CFB probe deliberately retains stream descriptors rather
    # than the directory-storage list. Recover only bounded storage-like
    # features that are directly evidenced by retained stream paths.
    streams = [x for x in probe.get("streams") or [] if isinstance(x, dict)]
    stream_paths = [str(x.get("path") or "") for x in streams]

    object_roots: set[str] = set()
    for path in stream_paths:
        parts = [part for part in path.strip("/").split("/") if part]
        if (
            len(parts) >= 2
            and parts[0].casefold() == "objects"
            and re.fullmatch(r"object\s+\d+", parts[1], flags=re.I)
        ):
            object_roots.add("/".join(parts[:2]).casefold())

    ole_pres = [p for p in stream_paths if "olepres" in p.casefold()]
    return {
        "embedded_object_storage_count": len(object_roots),
        "ole_presentation_stream_count": len(ole_pres),
        "objects_storage_present": any(
            p.casefold().startswith("/objects/") for p in stream_paths
        ),
        "embedded_word_document_present": any(
            p.casefold().endswith("/worddocument") for p in stream_paths
        ),
        "msodatastore_present": any(
            "msodatastore" in p.casefold() for p in stream_paths
        ),
    }


def run_reader(exe: Path, source: Path, out_dir: Path) -> dict[str, Any]:
    sha = source.stem.lower()
    target = out_dir / f"{sha}.json"
    try:
        cp = subprocess.run(
            [str(exe), str(source), str(target)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=45,
            check=False,
        )
        if target.exists():
            row = json.loads(target.read_text(encoding="utf-8"))
            row["process_returncode"] = cp.returncode
            return row
        return {
            "schema": "chaptera.reader-corpus-structural-receipt.v1",
            "source_sha256": sha,
            "opened": False,
            "runner_error": "receipt_missing",
            "process_returncode": cp.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "schema": "chaptera.reader-corpus-structural-receipt.v1",
            "source_sha256": sha,
            "opened": False,
            "runner_error": "timeout",
        }
    except Exception as exc:
        return {
            "schema": "chaptera.reader-corpus-structural-receipt.v1",
            "source_sha256": sha,
            "opened": False,
            "runner_error": f"{type(exc).__name__}:{exc}",
        }


def max_row(rows: list[dict[str, Any]], field: str) -> dict[str, Any] | None:
    good = [r for r in rows if isinstance(r.get(field), int)]
    if not good:
        return None
    row = max(good, key=lambda r: (int(r[field]), str(r.get("source_sha256") or "")))
    return {"sha256": row.get("source_sha256"), field: row.get(field)}


def logical_groups(fingerprints: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fingerprints:
        key = str(row.get("content_topology_fingerprint_sha256") or "")
        if key:
            groups[key].append(row)
    return groups


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-root", type=Path, required=True)
    ap.add_argument("--rar-tools", type=Path, required=True)
    ap.add_argument("--reader-receipt-exe", type=Path, required=True)
    ap.add_argument("--rar-ref", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    sys.path.insert(0, str(args.rar_tools))
    import structural_novelty as novelty  # type: ignore

    corpus_dir = args.corpus_root / "corpus" / "native" / "unclassified"
    paths = sorted(corpus_dir.glob("*.pub"))
    if len(paths) < 300:
        raise SystemExit(f"expected >=300 corpus files, found {len(paths)}")

    names = load_names(args.corpus_root)
    fingerprints: list[dict[str, Any]] = []
    structural_errors: list[dict[str, str]] = []

    for path in paths:
        data = path.read_bytes()
        sha = path.stem.lower()
        try:
            probe = novelty.cfb_probe(data)
            if probe.get("source_sha256") != sha:
                raise ValueError("filename SHA != byte SHA")
            meta = names.get(sha, {})
            display_name = meta.get("file_name") or path.name
            row = {
                "sha256": sha,
                "status": "ok",
                "sources": [meta.get("source_type") or "materialized_working_corpus"],
                "filenames": [display_name],
                "source_meta": meta,
                **probe,
                **storage_feature_projection(probe),
            }
            fingerprints.append(row)
        except Exception as exc:
            structural_errors.append({"sha256": sha, "error": f"{type(exc).__name__}:{exc}"})

    fingerprints.sort(key=lambda r: r["sha256"])
    if structural_errors:
        raise SystemExit(f"structural probe errors: {structural_errors[:10]}")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "fingerprints.json").write_text(
        json.dumps(fingerprints, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    reader_dir = args.out / "reader-per-file"
    reader_dir.mkdir(parents=True, exist_ok=True)
    reader_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(run_reader, args.reader_receipt_exe, path, reader_dir): path.stem.lower()
            for path in paths
        }
        for future in as_completed(futures):
            reader_rows.append(future.result())
    reader_rows.sort(key=lambda r: str(r.get("source_sha256") or ""))

    by_sha = {r["sha256"]: r for r in fingerprints}
    for row in reader_rows:
        sha = str(row.get("source_sha256") or "").lower()
        profile = by_sha.get(sha)
        if profile:
            row["contents_family"] = profile.get("contents_family")
            row["contents_serialization_revision"] = profile.get("contents_serialization_revision")
            row["structural_fingerprint"] = profile.get("size_bucket_fingerprint_sha256")
            row["display_name"] = (profile.get("filenames") or [sha])[0]
    (args.out / "reader-records.json").write_text(
        json.dumps(reader_rows, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    groups = logical_groups(fingerprints)
    logical_rows = []
    for identity, members in sorted(groups.items()):
        families = {str(x.get("contents_family") or "unknown") for x in members}
        revisions = {x.get("contents_serialization_revision") for x in members}
        if len(families) != 1 or len(revisions) != 1:
            raise SystemExit(f"logical identity family/revision disagreement: {identity}")
        logical_rows.append(
            {
                "logical_identity": identity,
                "physical_sha_count": len(members),
                "sha256": sorted(x["sha256"] for x in members),
                "contents_family": next(iter(families)),
                "contents_serialization_revision": next(iter(revisions)),
            }
        )

    structural_clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    path_clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fingerprints:
        structural_clusters[str(row["size_bucket_fingerprint_sha256"])].append(row)
        path_clusters[str(row["path_fingerprint_sha256"])].append(row)

    family_physical = Counter(str(r.get("contents_family") or "unknown") for r in fingerprints)
    family_logical = Counter(str(r.get("contents_family") or "unknown") for r in logical_rows)
    revision_logical = Counter(
        f"{r.get('contents_family')}:{r.get('contents_serialization_revision') if r.get('contents_serialization_revision') is not None else 'unknown'}"
        for r in logical_rows
    )
    carrier_counts = Counter(carrier_pattern(r.get("carrier_flags") or {}) for r in fingerprints)

    opened = [r for r in reader_rows if r.get("opened") is True]
    failed = [r for r in reader_rows if r.get("opened") is not True]
    opened_by_family = Counter(str(r.get("contents_family") or "unknown") for r in opened)
    failed_by_family = Counter(str(r.get("contents_family") or "unknown") for r in failed)
    fidelity = Counter(str(r.get("fidelity_status") or "unknown") for r in opened)
    diagnostic_codes = Counter(
        code for r in opened for code in (r.get("diagnostic_codes") or [])
    )

    failure_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in failed:
        signature = str(row.get("open_error_signature_sha256") or row.get("runner_error") or "unknown")
        failure_groups[signature].append(row)
    failure_signature_groups = []
    for signature, members in sorted(
        failure_groups.items(), key=lambda item: (-len(item[1]), item[0])
    ):
        failure_signature_groups.append(
            {
                "signature": signature,
                "count": len(members),
                "families": dict(
                    sorted(Counter(str(x.get("contents_family") or "unknown") for x in members).items())
                ),
                "revisions": dict(
                    sorted(
                        Counter(
                            f"{x.get('contents_family')}:{x.get('contents_serialization_revision')}"
                            for x in members
                        ).items()
                    )
                ),
                "representatives": [
                    {
                        "sha256": x.get("source_sha256"),
                        "name": x.get("display_name"),
                    }
                    for x in members[:8]
                ],
            }
        )

    reader_summary = {
        "input_file_count": len(paths),
        "opened_count": len(opened),
        "failed_count": len(failed),
        "opened_by_family": dict(sorted(opened_by_family.items())),
        "failed_by_family": dict(sorted(failed_by_family.items())),
        "failure_signature_count": len(failure_signature_groups),
        "failure_signature_groups": failure_signature_groups,
        "fidelity_status_counts": dict(sorted(fidelity.items())),
        "diagnostic_code_counts": dict(diagnostic_codes.most_common()),
        "maxima": {
            field: max_row(opened, field)
            for field in (
                "viewer_page_count",
                "scene_node_count",
                "story_count",
                "story_frame_count",
                "text_fragment_count",
                "typography_run_count",
                "image_resource_count",
                "image_placement_count",
                "paint_node_count",
                "solid_fill_count",
                "solid_line_count",
            )
        },
    }
    (args.out / "reader-summary.json").write_text(
        json.dumps(reader_summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    revision_freq = Counter(
        (str(r.get("contents_family") or "unknown"), r.get("contents_serialization_revision"))
        for r in fingerprints
    )
    reader_by_sha = {
        str(r.get("source_sha256") or "").lower(): r for r in reader_rows
    }
    shortlist = []
    for row in fingerprints:
        sha = row["sha256"]
        rr = reader_by_sha.get(sha, {})
        reasons: list[str] = []
        score = 0
        sfp = str(row["size_bucket_fingerprint_sha256"])
        pfp = str(row["path_fingerprint_sha256"])
        family = str(row.get("contents_family") or "unknown")
        revision = row.get("contents_serialization_revision")

        if len(structural_clusters[sfp]) == 1:
            score += 7
            reasons.append("structural_singleton")
        if len(path_clusters[pfp]) == 1:
            score += 3
            reasons.append("stream_path_singleton")
        if family == "0x22":
            score += 6
            reasons.append("legacy_0x22")
        elif family not in {"0x2c"}:
            score += 8
            reasons.append(f"rare_or_unknown_family:{family}")
        freq = revision_freq[(family, revision)]
        if freq == 1:
            score += 5
            reasons.append("singleton_family_revision")
        elif freq <= 3:
            score += 3
            reasons.append("rare_family_revision")

        pattern = carrier_pattern(row.get("carrier_flags") or {})
        if pattern != "contents|escher|escher_delay|quill":
            score += 4
            reasons.append(f"nonstandard_carriers:{pattern}")

        obj_count = int(row.get("embedded_object_storage_count") or 0)
        if obj_count:
            score += min(5, 1 + obj_count)
            reasons.append(f"embedded_object_storages:{obj_count}")
        if row.get("ole_presentation_stream_count"):
            score += 2
            reasons.append("ole_presentation_streams")
        if row.get("embedded_word_document_present"):
            score += 3
            reasons.append("embedded_word_document")
        if row.get("msodatastore_present"):
            score += 1
            reasons.append("msodatastore")

        if rr.get("opened") is not True:
            score += 7
            reasons.append("reader_open_failed")
        else:
            if str(rr.get("fidelity_status") or "").lower() not in {"supported", ""}:
                score += 2
                reasons.append(f"reader_fidelity:{rr.get('fidelity_status')}")
            if int(rr.get("viewer_page_count") or 0) >= 10:
                score += 2
                reasons.append("many_pages")
            if int(rr.get("story_count") or 0) >= 10:
                score += 2
                reasons.append("many_stories")
            if int(rr.get("image_resource_count") or 0) >= 10:
                score += 2
                reasons.append("many_images")
            if int(rr.get("scene_node_count") or 0) >= 100:
                score += 2
                reasons.append("many_scene_nodes")
            if rr.get("diagnostic_codes"):
                score += min(3, len(rr.get("diagnostic_codes") or []))
                reasons.append("reader_diagnostics")

        if score:
            shortlist.append(
                {
                    "score": score,
                    "sha256": sha,
                    "name": (row.get("filenames") or [sha])[0],
                    "contents_family": family,
                    "contents_serialization_revision": revision,
                    "structural_cluster_size": len(structural_clusters[sfp]),
                    "path_cluster_size": len(path_clusters[pfp]),
                    "embedded_object_storage_count": obj_count,
                    "reader_opened": rr.get("opened"),
                    "viewer_page_count": rr.get("viewer_page_count"),
                    "scene_node_count": rr.get("scene_node_count"),
                    "story_count": rr.get("story_count"),
                    "image_resource_count": rr.get("image_resource_count"),
                    "fidelity_status": rr.get("fidelity_status"),
                    "diagnostic_codes": rr.get("diagnostic_codes") or [],
                    "reasons": reasons,
                }
            )

    shortlist.sort(key=lambda r: (-r["score"], r["sha256"]))
    (args.out / "shortlist.json").write_text(
        json.dumps(shortlist[:60], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    summary = {
        "schema": "chaptera.materialized-corpus-deep-profile.v1",
        "rar_ref": args.rar_ref,
        "corpus_file_count": len(paths),
        "structural_probe_error_count": 0,
        "logical_identity_count": len(groups),
        "duplicate_logical_group_count": sum(len(v) > 1 for v in groups.values()),
        "surplus_physical_sha_count": len(fingerprints) - len(groups),
        "contents_family_physical_counts": dict(sorted(family_physical.items())),
        "contents_family_logical_counts": dict(sorted(family_logical.items())),
        "contents_family_revision_logical_counts": dict(sorted(revision_logical.items())),
        "structural_cluster_count": len(structural_clusters),
        "structural_singleton_count": sum(len(v) == 1 for v in structural_clusters.values()),
        "structural_repeated_cluster_count": sum(len(v) > 1 for v in structural_clusters.values()),
        "largest_structural_cluster_size": max(len(v) for v in structural_clusters.values()),
        "path_cluster_count": len(path_clusters),
        "path_singleton_count": sum(len(v) == 1 for v in path_clusters.values()),
        "carrier_pattern_counts": dict(sorted(carrier_counts.items())),
        "files_with_embedded_object_storage": sum(int(r.get("embedded_object_storage_count") or 0) > 0 for r in fingerprints),
        "max_embedded_object_storage_count": max(int(r.get("embedded_object_storage_count") or 0) for r in fingerprints),
        "files_with_ole_presentation_streams": sum(int(r.get("ole_presentation_stream_count") or 0) > 0 for r in fingerprints),
        "files_with_embedded_word_document": sum(bool(r.get("embedded_word_document_present")) for r in fingerprints),
        "files_with_msodatastore": sum(bool(r.get("msodatastore_present")) for r in fingerprints),
        "reader": reader_summary,
        "shortlist_count": min(60, len(shortlist)),
        "evidence_boundary": (
            "structural family/revision is not an exact Publisher marketing-version label; "
            "Reader receipts are structural/product-open evidence, not Publisher-equivalent visual fidelity"
        ),
    }
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
