#!/usr/bin/env python3
"""Normalize extracted Publisher VBAPB10.CHM structure without retaining help prose."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup

SCHEMA_VERSION = "chaptera.devhelp-xver.normalized.v2"
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
TOPIC_LINK_RE = re.compile(r"(pb[A-Za-z0-9_-]+)\.htm", re.IGNORECASE)
ENUM_HEAD_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9_]*)\s+can be one of these\s+"
    r"([A-Za-z][A-Za-z0-9_]*)\s+constants?\.?$",
    re.IGNORECASE,
)
CONST_NAME_RE = re.compile(r"^(?:pb|mso)[A-Za-z0-9_]+$")
ARG_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s+(Required|Optional)\s+(.+?)(?:\.|$)",
    re.IGNORECASE,
)
RETURN_PATTERNS = (
    re.compile(
        r"\breturns?\s+(?:a\s+new|an\s+new|the\s+new|a|an|the|new)?\s*"
        r"([A-Za-z_][A-Za-z0-9_]*)\s+(object|collection|constant)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\breturns?\s+(String|Long|Boolean|Variant|Integer|Single|Double)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\breturns?\s+one of the\s+([A-Za-z_][A-Za-z0-9_]*)\s+constants",
        re.IGNORECASE,
    ),
)


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def classify_topic(topic_id: str) -> tuple[str, str]:
    lower = topic_id.lower()
    for prefix, category in PREFIXES:
        if lower.startswith(prefix):
            return category, topic_id[len(prefix):]
    return "other", topic_id


def decode_html(path: Path) -> str:
    payload = path.read_bytes()
    for encoding in ("utf-8-sig", "windows-1252", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("latin-1", errors="replace")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_topic_files(root: Path) -> dict[str, Path]:
    """Only /html/pb*.htm is the canonical topic namespace.

    The CHMs also contain /links/* helper/alias files. Those files may provide
    applicability data but must never count as separate API topics.
    """
    html_root = root / "html"
    return {path.stem: path for path in html_root.glob("pb*.htm")}


def find_link_file(root: Path, topic_id: str) -> Path | None:
    link_root = root / "links"
    for candidate in (
        link_root / f"{topic_id}_L.htm",
        link_root / f"{topic_id}_l.htm",
        link_root / f"{topic_id.lower()}_L.htm",
        link_root / f"{topic_id.lower()}_l.htm",
    ):
        if candidate.exists():
            return candidate

    target = f"{topic_id}_l.htm".lower()
    for path in link_root.glob("*.htm"):
        if path.name.lower() == target:
            return path
    return None


def classes(tag) -> set[str]:
    return {str(value).lower() for value in (tag.get("class") or [])}


def topic_links(soup: BeautifulSoup) -> list[str]:
    result = set()
    for anchor in soup.find_all("a", href=True):
        match = TOPIC_LINK_RE.search(anchor["href"])
        if match:
            result.add(match.group(1).lower())
    return sorted(result)


def canonical_signature(value: str) -> str:
    value = norm(value)
    value = re.sub(r"\s*\.\s*", ".", value)
    value = re.sub(r"\(\s*", "(", value)
    value = re.sub(r"\s*\)", ")", value)
    value = re.sub(r"\s*,\s*", ", ", value)
    value = re.sub(r"\[\s*", "[", value)
    value = re.sub(r"\s*\]", "]", value)
    return value


def extract_signatures(soup: BeautifulSoup) -> list[str]:
    result = []
    for tag in soup.find_all(["p", "div"]):
        tag_classes = classes(tag)
        if not ({"signature", "syn", "ofvbasyn"} & tag_classes):
            continue
        value = canonical_signature(tag.get_text(" ", strip=True))
        if value and value not in result:
            result.append(value)
    return sorted(result)


def signature_parameters(signature: str) -> list[str]:
    start = signature.find("(")
    end = signature.rfind(")")
    if start < 0 or end <= start:
        return []
    result = []
    for raw in signature[start + 1 : end].split(","):
        token = norm(raw).strip("[]").split(":=", 1)[0].strip()
        token = re.split(r"\s+[Aa][Ss]\s+", token, maxsplit=1)[0].strip()
        token = token.split(" ", 1)[0]
        if token:
            result.append(token)
    return result


def argument_descriptions(soup: BeautifulSoup) -> list[dict]:
    candidates = []
    for paragraph in soup.find_all("p"):
        value = norm(paragraph.get_text(" ", strip=True))
        if not value:
            continue
        if "ofvbaargdesc" in classes(paragraph) or ARG_RE.match(value):
            candidates.append(value)

    rows = []
    seen = set()
    for value in candidates:
        match = ARG_RE.match(value)
        if not match:
            continue
        name, requirement, type_text = match.group(1), match.group(2).lower(), norm(match.group(3))
        type_text = re.split(
            r"\b(?:The|A|An|Specifies|Determines|If|When)\b",
            type_text,
            maxsplit=1,
        )[0].strip(" ,;")
        key = (name.lower(), requirement, type_text.lower())
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "name": name,
                "required": requirement == "required",
                "type": type_text[:160],
            }
        )
    return sorted(rows, key=lambda row: (row["name"].lower(), row["required"], row["type"].lower()))


def enum_groups(soup: BeautifulSoup) -> list[dict]:
    groups = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [norm(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(cells)
        if not rows:
            continue

        header = " ".join(rows[0])
        header_match = ENUM_HEAD_RE.match(header)
        enum_name = header_match.group(1) if header_match else None
        constants = []
        for row in rows[1:] if enum_name else rows:
            first = row[0]
            token = first.split()[0] if first else ""
            if not CONST_NAME_RE.match(token):
                continue
            value = None
            if len(row) >= 2 and re.match(r"^[+-]?(?:\d+|0x[0-9a-f]+)$", row[1], re.IGNORECASE):
                value = row[1]
            constants.append({"name": token, "value": value})
        if enum_name and constants:
            groups.append({"type": enum_name, "constants": constants})
    return groups


def help_metadata(soup: BeautifulSoup) -> dict[str, str]:
    result = {}
    for meta in soup.find_all("meta"):
        key = norm(meta.get("name") or meta.get("http-equiv") or meta.get("property") or "")
        value = norm(meta.get("content") or "")
        if not key or not value:
            continue
        lower = key.lower()
        if (
            lower in {"filename", "ver", "tnum", "assetid", "lcid", "projapp", "languagespecific"}
            or any(token in lower for token in ("help", "keyword", "context", "version"))
        ):
            result[key] = value[:500]
    return dict(sorted(result.items()))


def applicability(root: Path, topic_id: str) -> list[dict]:
    link_file = find_link_file(root, topic_id)
    if link_file is None:
        return []
    soup = BeautifulSoup(decode_html(link_file), "html.parser")
    container = soup.find(id="appliesto")
    if container is None:
        return []

    result = []
    for anchor in container.find_all("a", href=True):
        match = TOPIC_LINK_RE.search(anchor["href"])
        result.append(
            {
                "topic_id": match.group(1).lower() if match else None,
                "label": norm(anchor.get_text(" ", strip=True))[:200],
            }
        )
    return result


def intro_paragraphs(soup: BeautifulSoup, limit: int = 8) -> list[str]:
    result = []
    for paragraph in soup.find_all("p"):
        paragraph_classes = classes(paragraph)
        if {"signature", "syn", "ofvbaargdesc"} & paragraph_classes:
            continue
        value = norm(paragraph.get_text(" ", strip=True))
        if not value or value.lower() == "show all":
            continue
        result.append(value)
        if len(result) >= limit:
            break
    return result


def return_type_candidates(paragraphs: list[str]) -> list[str]:
    result = []
    for paragraph in paragraphs:
        for pattern in RETURN_PATTERNS:
            match = pattern.search(paragraph)
            if not match:
                continue
            if len(match.groups()) >= 2 and match.group(2):
                value = norm(match.group(1) + " " + match.group(2))
            else:
                value = norm(match.group(1))
            if value.lower() in {"new", "one"}:
                continue
            if value and value not in result:
                result.append(value)
    return sorted(result)[:10]


def section_fingerprints(soup: BeautifulSoup) -> dict[str, str]:
    current = "__preamble__"
    chunks = collections.defaultdict(list)
    body = soup.body or soup
    for node in body.descendants:
        if getattr(node, "name", None) in ("h2", "h3"):
            current = norm(node.get_text(" ", strip=True)) or current
        elif isinstance(node, str):
            parent = getattr(node, "parent", None)
            if parent and parent.name not in ("script", "style"):
                value = norm(str(node))
                if value:
                    chunks[current].append(value)

    result = {}
    for heading, values in chunks.items():
        text = norm(" ".join(values))
        if text:
            result[heading] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return dict(sorted(result.items()))


def normalize_topic(root: Path, path: Path) -> dict:
    topic_id = path.stem
    category, member_name = classify_topic(topic_id)
    soup = BeautifulSoup(decode_html(path), "html.parser")
    for element in soup(["script", "style"]):
        element.decompose()

    signatures = extract_signatures(soup)
    sections = section_fingerprints(soup)
    return {
        "topic_id": topic_id,
        "category": category,
        "member_name": member_name,
        "title": norm(soup.title.get_text(" ", strip=True))[:500] if soup.title else "",
        "signatures": signatures,
        "signature_parameters": [signature_parameters(value) for value in signatures],
        "arguments": argument_descriptions(soup),
        "return_type_candidates": return_type_candidates(intro_paragraphs(soup)),
        "applies_to": applicability(root, topic_id),
        "help_meta": help_metadata(soup),
        "links": topic_links(soup),
        "enum_groups": enum_groups(soup),
        "section_fingerprints": sections,
        "body_fingerprint": hashlib.sha256(
            json.dumps(sections, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def normalize_version(root: Path, source_chm: Path) -> dict:
    files = canonical_topic_files(root)
    topics = [normalize_topic(root, files[key]) for key in sorted(files)]
    coverage = collections.Counter()
    for row in topics:
        for field in (
            "signatures",
            "arguments",
            "return_type_candidates",
            "applies_to",
            "help_meta",
            "links",
            "enum_groups",
        ):
            if row[field]:
                coverage[field] += 1
    return {
        "chm_byte_len": source_chm.stat().st_size,
        "chm_sha256": sha256_file(source_chm),
        "topic_count": len(topics),
        "coverage": dict(sorted(coverage.items())),
        "topics": topics,
    }


def build_diff(p2002: dict, p2003: dict) -> dict:
    by2002 = {row["topic_id"]: row for row in p2002["topics"]}
    by2003 = {row["topic_id"]: row for row in p2003["topics"]}
    ids2002, ids2003 = set(by2002), set(by2003)
    common = sorted(ids2002 & ids2003)
    fields = (
        "title",
        "signatures",
        "signature_parameters",
        "arguments",
        "return_type_candidates",
        "applies_to",
        "help_meta",
        "links",
        "enum_groups",
        "body_fingerprint",
    )
    changed = {
        field: [
            topic_id
            for topic_id in common
            if by2002[topic_id].get(field) != by2003[topic_id].get(field)
        ]
        for field in fields
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "source_2002": {
            key: p2002[key]
            for key in ("chm_byte_len", "chm_sha256", "topic_count", "coverage")
        },
        "source_2003": {
            key: p2003[key]
            for key in ("chm_byte_len", "chm_sha256", "topic_count", "coverage")
        },
        "added_topic_ids": sorted(ids2003 - ids2002),
        "removed_topic_ids": sorted(ids2002 - ids2003),
        "common_count": len(common),
        "changed_common_topic_ids": changed,
        "topics_2002": p2002["topics"],
        "topics_2003": p2003["topics"],
        "evidence_boundary": {
            "topic_body_text_retained": False,
            "canonical_html_namespace_only": True,
            "signatures_extracted": True,
            "argument_types_extracted_when_present": True,
            "return_type_candidates_extracted": True,
            "enum_type_and_constant_names_extracted": True,
            "numeric_enum_values_only_when_present": True,
            "help_topic_ids_and_metadata_extracted": True,
            "applicability_links_extracted": True,
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
    result = build_diff(p2002, p2003)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "p2002": p2002["topic_count"],
                "p2003": p2003["topic_count"],
                "coverage_2002": p2002["coverage"],
                "coverage_2003": p2003["coverage"],
                "added": len(result["added_topic_ids"]),
                "removed": len(result["removed_topic_ids"]),
                "changed": {
                    key: len(value)
                    for key, value in result["changed_common_topic_ids"].items()
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
