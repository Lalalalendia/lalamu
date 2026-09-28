#!/usr/bin/env python3
"""Source-safe Publisher VBAPB10.CHM topic-directory surface extractor.

This intentionally proves only uncompressed /html/pb*.htm topic paths found in
CHM container bytes. It does not decompress topic bodies and must not be used to
claim signatures, return types, enum values, links, or PUB wire-format semantics.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

SCHEMA_VERSION = "chaptera.devhelp-xver.topic-surface.v1"
TOPIC_RE = re.compile(rb"/html/(pb[A-Za-z0-9_-]+)\.htm")
PREFIXES = (
    ("pbhidden", "hidden"),
    ("pbevt", "event"),
    ("pbmth", "method"),
    ("pbobj", "object"),
    ("pbpro", "property"),
    ("pbhow", "howto"),
    ("pbmsc", "misc"),
    ("pbtoc", "toc"),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def classify_topic(topic_id: str) -> tuple[str, str]:
    lower = topic_id.lower()
    for prefix, category in PREFIXES:
        if lower.startswith(prefix):
            return category, topic_id[len(prefix):]
    return "other", topic_id


def extract_topic_rows(data: bytes) -> list[dict[str, str]]:
    names = sorted({match.decode("ascii") for match in TOPIC_RE.findall(data)})
    rows = []
    for topic_id in names:
        category, name = classify_topic(topic_id)
        rows.append({"topic_id": topic_id, "category": category, "name": name})
    return rows


def category_counts(rows: Iterable[dict[str, str]]) -> dict[str, int]:
    counter = collections.Counter(row["category"] for row in rows)
    return dict(sorted(counter.items()))


def build_diff(
    p2002: bytes,
    p2003: bytes,
    *,
    expected_2002_sha256: str | None = None,
    expected_2003_sha256: str | None = None,
) -> dict:
    hash_2002 = sha256_bytes(p2002)
    hash_2003 = sha256_bytes(p2003)
    if expected_2002_sha256 and hash_2002 != expected_2002_sha256.lower():
        raise ValueError(f"P2002 SHA-256 mismatch: {hash_2002}")
    if expected_2003_sha256 and hash_2003 != expected_2003_sha256.lower():
        raise ValueError(f"P2003 SHA-256 mismatch: {hash_2003}")

    rows_2002 = extract_topic_rows(p2002)
    rows_2003 = extract_topic_rows(p2003)
    by_id_2002 = {row["topic_id"]: row for row in rows_2002}
    by_id_2003 = {row["topic_id"]: row for row in rows_2003}
    ids_2002 = set(by_id_2002)
    ids_2003 = set(by_id_2003)

    added = [by_id_2003[key] for key in sorted(ids_2003 - ids_2002)]
    removed = [by_id_2002[key] for key in sorted(ids_2002 - ids_2003)]
    common = sorted(ids_2002 & ids_2003)

    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "uncompressed_chm_topic_directory_only",
        "source_2002": {
            "byte_len": len(p2002),
            "sha256": hash_2002,
            "unique_topics": len(rows_2002),
            "category_counts": category_counts(rows_2002),
        },
        "source_2003": {
            "byte_len": len(p2003),
            "sha256": hash_2003,
            "unique_topics": len(rows_2003),
            "category_counts": category_counts(rows_2003),
        },
        "diff": {
            "common_count": len(common),
            "added_count": len(added),
            "removed_count": len(removed),
            "added_category_counts": category_counts(added),
            "removed_category_counts": category_counts(removed),
            "added": added,
            "removed": removed,
        },
        "evidence_boundary": {
            "topic_ids_and_categories_proven": True,
            "topic_body_text_extracted": False,
            "parameter_signatures_extracted": False,
            "return_types_extracted": False,
            "enum_values_extracted": False,
            "help_topic_ids_beyond_paths_extracted": False,
            "intra_help_links_extracted": False,
            "pub_wire_format_claims_allowed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("p2002", type=Path)
    parser.add_argument("p2003", type=Path)
    parser.add_argument("--expected-2002-sha256")
    parser.add_argument("--expected-2003-sha256")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    result = build_diff(
        args.p2002.read_bytes(),
        args.p2003.read_bytes(),
        expected_2002_sha256=args.expected_2002_sha256,
        expected_2003_sha256=args.expected_2003_sha256,
    )
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
