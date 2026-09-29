#!/usr/bin/env python3
"""Census embedded font evidence in admitted PUB corpus via libmspub pub2raw.

This is intentionally an evidence probe, not a Chaptera parser implementation.
It asks a known external parser whether a PUB exposes defineEmbeddedFont /
application/vnd.ms-fontobject records and preserves bounded raw snippets for
manual follow-up. libmspub is correlated evidence, not an independent oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "corpus" / "native" / "unclassified"
DEFAULT_OUTPUT = ROOT / "data" / "embedded-font-census" / "latest.json"
DEFAULT_RAW_DIR = ROOT / "data" / "embedded-font-census" / "raw"

SCHEMA = "lalamu.pub-embedded-font-census.v1"
MARKERS = (
    "defineEmbeddedFont",
    "application/vnd.ms-fontobject",
)
NAME_PATTERNS = (
    re.compile(r'librevenge:name[^\n\r]*?["\']([^"\']{1,200})["\']', re.I),
    re.compile(r'librevenge:name\s*[:=]\s*([^,}\n\r]{1,200})', re.I),
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def tool_version(tool: str) -> str:
    proc = subprocess.run(
        [tool, "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    return proc.stdout.strip()


def extract_names(raw: str) -> list[str]:
    names: set[str] = set()
    for pattern in NAME_PATTERNS:
        for match in pattern.finditer(raw):
            value = match.group(1).strip().strip('"\'')
            if value and "binary" not in value.lower():
                names.add(value)
    return sorted(names)


def marker_snippets(raw: str, radius: int = 1200) -> list[str]:
    out: list[str] = []
    lower = raw.lower()
    seen: set[tuple[int, int]] = set()
    for marker in MARKERS:
        needle = marker.lower()
        start = 0
        while True:
            idx = lower.find(needle, start)
            if idx < 0:
                break
            a = max(0, idx - radius)
            b = min(len(raw), idx + len(marker) + radius)
            key = (a, b)
            if key not in seen:
                out.append(raw[a:b])
                seen.add(key)
            start = idx + len(needle)
    return out


def inspect(path: Path, pub2raw: str, raw_dir: Path, timeout: int) -> dict[str, Any]:
    sha = sha256_file(path)
    try:
        proc = subprocess.run(
            [pub2raw, str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            errors="replace",
        )
        stdout = proc.stdout
        stderr = proc.stderr
        combined = stdout + "\n" + stderr
        hits = {
            marker: combined.lower().count(marker.lower())
            for marker in MARKERS
        }
        detected = any(hits.values())
        names = extract_names(combined) if detected else []
        snippets = marker_snippets(combined) if detected else []

        raw_rel = None
        if detected:
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{sha}.txt"
            raw_path.write_text(combined, encoding="utf-8")
            raw_rel = str(raw_path.relative_to(ROOT))

        return {
            "sha256": sha,
            "file_name": path.name,
            "byte_len": path.stat().st_size,
            "pub2raw_exit": proc.returncode,
            "supported_by_libmspub": proc.returncode == 0,
            "embedded_font_detected": detected,
            "marker_counts": hits,
            "font_names": names,
            "raw_output_path": raw_rel,
            "snippets": snippets,
            "stdout_len": len(stdout),
            "stderr_len": len(stderr),
            "stderr_tail": stderr[-2000:] if stderr else "",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "sha256": sha,
            "file_name": path.name,
            "byte_len": path.stat().st_size,
            "pub2raw_exit": None,
            "supported_by_libmspub": False,
            "embedded_font_detected": False,
            "marker_counts": {marker: 0 for marker in MARKERS},
            "font_names": [],
            "raw_output_path": None,
            "snippets": [],
            "timeout": True,
            "stderr_tail": str(exc),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    ap.add_argument("--pub2raw", default="pub2raw")
    ap.add_argument("--timeout", type=int, default=45)
    args = ap.parse_args()

    paths = sorted(args.corpus.rglob("*.pub"))
    records = [
        inspect(path, args.pub2raw, args.raw_dir, args.timeout)
        for path in paths
    ]

    hits = [r for r in records if r["embedded_font_detected"]]
    unsupported = [r for r in records if not r["supported_by_libmspub"]]

    receipt = {
        "schema": SCHEMA,
        "method": "libmspub pub2raw RVNGRawDrawingGenerator marker census",
        "evidence_boundary": (
            "libmspub is correlated implementation evidence; detection proves "
            "that libmspub surfaced an embedded-font record, not Publisher parity"
        ),
        "pub2raw_version": tool_version(args.pub2raw),
        "corpus_file_count": len(records),
        "libmspub_supported_count": len(records) - len(unsupported),
        "libmspub_unsupported_or_error_count": len(unsupported),
        "embedded_font_file_count": len(hits),
        "embedded_font_record_marker_count": sum(
            r["marker_counts"].get("defineEmbeddedFont", 0) for r in hits
        ),
        "hit_sha256": [r["sha256"] for r in hits],
        "records": records,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "schema": SCHEMA,
        "corpus_file_count": receipt["corpus_file_count"],
        "libmspub_supported_count": receipt["libmspub_supported_count"],
        "embedded_font_file_count": receipt["embedded_font_file_count"],
        "hit_sha256": receipt["hit_sha256"],
        "pub2raw_version": receipt["pub2raw_version"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
