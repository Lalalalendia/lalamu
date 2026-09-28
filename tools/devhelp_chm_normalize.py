#!/usr/bin/env python3
"""Normalize extracted Publisher VBAPB10.CHM help topics without retaining full body text."""

from __future__ import annotations

import argparse
import collections
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any

SCHEMA = "chaptera.devhelp-xver.normalized.v1"
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
WS_RE = re.compile(r"\s+")
LOCAL_TOPIC_RE = re.compile(r"(pb[A-Za-z0-9_-]+)\.htm", re.IGNORECASE)
NUMERIC_RE = re.compile(r"^[+-]?(?:0x[0-9a-f]+|\d+)(?:\.\d+)?$", re.IGNORECASE)


def norm(value: str) -> str:
    return WS_RE.sub(" ", value.replace("\xa0", " ")).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def classify_topic(topic_id: str) -> tuple[str, str]:
    lower = topic_id.lower()
    for prefix, category in PREFIXES:
        if lower.startswith(prefix):
            return category, topic_id[len(prefix):]
    return "other", topic_id


class TopicParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.in_title = False
        self.heading_level: str | None = None
        self.heading_parts: list[str] = []
        self.current_section = "__preamble__"
        self.sections: dict[str, list[str]] = collections.defaultdict(list)
        self.links: set[str] = set()
        self.meta: dict[str, str] = {}
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.current_row: list[str] | None = None
        self.tables: list[list[str]] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag in {"script", "style"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = True
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_level = tag
            self.heading_parts = []
        if tag == "a":
            href = attrs_dict.get("href", "")
            match = LOCAL_TOPIC_RE.search(href)
            if match:
                self.links.add(match.group(1))
        if tag == "meta":
            key = norm(
                attrs_dict.get("name")
                or attrs_dict.get("http-equiv")
                or attrs_dict.get("property")
                or ""
            )
            value = norm(attrs_dict.get("content", ""))
            if key and value:
                self.meta[key] = value
        if tag == "tr":
            self.current_row = []
        if tag in {"td", "th"}:
            self.in_cell = True
            self.cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = False
        if self.heading_level == tag:
            heading = norm(" ".join(self.heading_parts))
            if heading:
                self.current_section = heading
            self.heading_level = None
            self.heading_parts = []
        if tag in {"td", "th"} and self.in_cell:
            value = norm(" ".join(self.cell_parts))
            if self.current_row is not None:
                self.current_row.append(value)
            self.in_cell = False
            self.cell_parts = []
        if tag == "tr" and self.current_row is not None:
            if any(self.current_row):
                self.tables.append(self.current_row)
            self.current_row = None

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        value = norm(data)
        if not value:
            return
        if self.in_title:
            self.title_parts.append(value)
        if self.heading_level:
            self.heading_parts.append(value)
        else:
            self.sections[self.current_section].append(value)
        if self.in_cell:
            self.cell_parts.append(value)


def read_html(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8", "windows-1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", errors="replace")


def section_map(parser: TopicParser) -> dict[str, str]:
    result: dict[str, str] = {}
    for heading, chunks in parser.sections.items():
        value = norm(" ".join(chunks))
        if value:
            result[heading] = value
    return result


def find_section(sections: dict[str, str], *needles: str) -> str | None:
    for heading, value in sections.items():
        lower = heading.lower()
        if any(needle in lower for needle in needles):
            return value
    return None


def parse_parameters(signature: str | None) -> list[str]:
    if not signature:
        return []
    open_at = signature.find("(")
    close_at = signature.rfind(")")
    if open_at < 0 or close_at <= open_at:
        return []
    body = signature[open_at + 1 : close_at]
    params = []
    for raw in body.split(","):
        token = norm(raw)
        if not token:
            continue
        token = token.lstrip("[").rstrip("]")
        token = token.split(":=", 1)[0].strip()
        token = token.split(" As ", 1)[0].strip()
        token = token.split(" as ", 1)[0].strip()
        token = token.split(" ", 1)[0].strip()
        if token:
            params.append(token)
    return params


def constant_candidates(rows: list[list[str]]) -> list[dict[str, str]]:
    candidates = []
    for row in rows:
        cleaned = [norm(cell) for cell in row if norm(cell)]
        if len(cleaned) < 2:
            continue
        name, value = cleaned[0], cleaned[1]
        if NUMERIC_RE.match(value) or re.match(r"^pb[A-Z][A-Za-z0-9_]+$", name):
            candidates.append(
                {
                    "name": name[:200],
                    "value": value[:200],
                    "description_hash": hashlib.sha256(
                        " | ".join(cleaned[2:]).encode("utf-8")
                    ).hexdigest()
                    if len(cleaned) > 2
                    else "",
                }
            )
    return candidates[:200]


def normalized_meta(meta: dict[str, str]) -> dict[str, str]:
    keep = {}
    for key, value in meta.items():
        lower = key.lower()
        if any(token in lower for token in ("help", "keyword", "api", "id", "context", "version")):
            keep[key] = value[:500]
    return dict(sorted(keep.items()))


def normalize_topic(path: Path) -> dict[str, Any]:
    topic_id = path.stem
    category, member_name = classify_topic(topic_id)
    parser = TopicParser()
    parser.feed(read_html(path))
    sections = section_map(parser)

    syntax = find_section(sections, "syntax")
    returns = find_section(sections, "return value", "return")
    applies = find_section(sections, "applies to", "applicability")
    version = find_section(sections, "version", "availability", "introduced")
    remarks = find_section(sections, "remarks")

    title = norm(" ".join(parser.title_parts))
    section_fingerprints = {
        heading: hashlib.sha256(value.encode("utf-8")).hexdigest()
        for heading, value in sorted(sections.items())
    }

    return {
        "topic_id": topic_id,
        "category": category,
        "member_name": member_name,
        "title": title[:500],
        "syntax": syntax[:2000] if syntax else None,
        "parameters": parse_parameters(syntax),
        "return_value": returns[:2000] if returns else None,
        "applies_to": applies[:2000] if applies else None,
        "version_note": version[:2000] if version else None,
        "remarks_hash": hashlib.sha256(remarks.encode("utf-8")).hexdigest() if remarks else None,
        "help_meta": normalized_meta(parser.meta),
        "links": sorted(parser.links),
        "constant_candidates": constant_candidates(parser.tables),
        "section_fingerprints": section_fingerprints,
        "body_fingerprint": hashlib.sha256(
            json.dumps(section_fingerprints, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def find_topic_files(root: Path) -> dict[str, Path]:
    result = {}
    for path in root.rglob("*.htm"):
        if not path.stem.lower().startswith("pb"):
            continue
        result[path.stem] = path
    return result


def normalize_version(root: Path, source_chm: Path) -> dict[str, Any]:
    files = find_topic_files(root)
    topics = [normalize_topic(files[key]) for key in sorted(files)]
    coverage = collections.Counter()
    for row in topics:
        for field in (
            "syntax",
            "return_value",
            "applies_to",
            "version_note",
            "remarks_hash",
        ):
            if row[field]:
                coverage[field] += 1
        if row["parameters"]:
            coverage["parameters"] += 1
        if row["help_meta"]:
            coverage["help_meta"] += 1
        if row["links"]:
            coverage["links"] += 1
        if row["constant_candidates"]:
            coverage["constant_candidates"] += 1
    return {
        "chm_byte_len": source_chm.stat().st_size,
        "chm_sha256": sha256_file(source_chm),
        "topic_count": len(topics),
        "coverage": dict(sorted(coverage.items())),
        "topics": topics,
    }


def changed_field(a: dict[str, Any], b: dict[str, Any], field: str) -> bool:
    return a.get(field) != b.get(field)


def build_diff(p2002: dict[str, Any], p2003: dict[str, Any]) -> dict[str, Any]:
    by2 = {row["topic_id"]: row for row in p2002["topics"]}
    by3 = {row["topic_id"]: row for row in p2003["topics"]}
    ids2, ids3 = set(by2), set(by3)
    common = sorted(ids2 & ids3)
    fields = (
        "title",
        "syntax",
        "parameters",
        "return_value",
        "applies_to",
        "version_note",
        "help_meta",
        "links",
        "constant_candidates",
        "body_fingerprint",
    )
    changed = {}
    for field in fields:
        changed[field] = [
            topic_id
            for topic_id in common
            if changed_field(by2[topic_id], by3[topic_id], field)
        ]

    return {
        "schema_version": SCHEMA,
        "source_2002": {
            key: p2002[key] for key in ("chm_byte_len", "chm_sha256", "topic_count", "coverage")
        },
        "source_2003": {
            key: p2003[key] for key in ("chm_byte_len", "chm_sha256", "topic_count", "coverage")
        },
        "added_topic_ids": sorted(ids3 - ids2),
        "removed_topic_ids": sorted(ids2 - ids3),
        "common_count": len(common),
        "changed_common_topic_ids": changed,
        "topics_2002": p2002["topics"],
        "topics_2003": p2003["topics"],
        "evidence_boundary": {
            "topic_body_text_retained": False,
            "topic_body_structure_extracted": True,
            "parameter_signatures_extracted_when_present": True,
            "return_sections_extracted_when_present": True,
            "constant_candidates_extracted_when_present": True,
            "help_metadata_extracted_when_present": True,
            "intra_help_links_extracted": True,
            "pub_wire_format_claims_allowed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p2002-root", type=Path, required=True)
    parser.add_argument("--p2002-chm", type=Path, required=True)
    parser.add_argument("--p2003-root", type=Path, required=True)
    parser.add_argument("--p2003-chm", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    p2002 = normalize_version(args.p2002_root, args.p2002_chm)
    p2003 = normalize_version(args.p2003_root, args.p2003_chm)
    diff = build_diff(p2002, p2003)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(diff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": SCHEMA,
                "p2002_topics": p2002["topic_count"],
                "p2003_topics": p2003["topic_count"],
                "added": len(diff["added_topic_ids"]),
                "removed": len(diff["removed_topic_ids"]),
                "coverage_2002": p2002["coverage"],
                "coverage_2003": p2003["coverage"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
