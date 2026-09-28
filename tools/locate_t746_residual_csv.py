#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable

SCHEMA = "chaptera.t746-residual-csv-locator-receipt.v1"
TARGET_ROWS = 176
ALTERNATE_ROWS = 183
TARGET_RAW29 = 171
TARGET_RAW1E = 5

MARKER_CANDIDATES = (
    "raw_type",
    "raw_marker",
    "marker",
    "chunk_type",
    "type",
    "rawType",
    "rawMarker",
)

ID_LIST_CANDIDATES = (
    "object_id",
    "object_identity",
    "identity",
    "chunk_id",
    "id",
    "seq_num",
    "seqNum",
    "handle",
    "list_id",
    "listId",
    "list_index",
    "item_id",
    "parent_id",
    "parent_seq_num",
)


@dataclass(frozen=True)
class Candidate:
    path: Path
    sha256: str
    row_count: int
    score: int
    marker_column: str | None
    marker_counts: dict[str, int]
    id_list_header_count: int
    encoding: str

    def receipt_row(self, rank: int) -> dict[str, object]:
        # Deliberately path/header-free. Keep this list closed unless the
        # privacy contract is explicitly versioned.
        return {
            "rank": rank,
            "sha256": self.sha256,
            "row_count": self.row_count,
            "score": self.score,
        }


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def find_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    exact = {name.lower(): name for name in fieldnames}
    for candidate in candidates:
        if candidate.lower() in exact:
            return exact[candidate.lower()]
    normalized = {normalize_header(name): name for name in fieldnames}
    for candidate in candidates:
        key = normalize_header(candidate)
        if key in normalized:
            return normalized[key]
    return None


def parse_marker(value: str) -> str:
    # Keep this behavior aligned with verify_t746_residual_composition.py.
    s = value.strip().lower()
    if not s:
        return "unknown"
    if s.startswith("raw"):
        s = s[3:]
    try:
        if s.startswith("0x"):
            n = int(s, 16)
        elif re.fullmatch(r"[0-9a-f]+h", s):
            n = int(s[:-1], 16)
        elif re.fullmatch(r"[0-9]+", s):
            n = int(s, 10)
        elif re.fullmatch(r"[0-9a-f]+", s):
            n = int(s, 16)
        else:
            match = re.search(r"0x([0-9a-f]+)", s)
            if not match:
                return "unknown"
            n = int(match.group(1), 16)
    except ValueError:
        return "unknown"
    return f"0x{n:02x}"


def decode_csv(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def id_list_header_count(fieldnames: list[str]) -> int:
    normalized = {normalize_header(name) for name in fieldnames}
    wanted = {normalize_header(name) for name in ID_LIST_CANDIDATES}
    hits = normalized & wanted
    hits.update(name for name in normalized if "list" in name)
    return len(hits)


def score_candidate(
    row_count: int,
    marker_column: str | None,
    marker_counts: Counter[str],
    header_signal_count: int,
) -> int:
    score = 0

    if row_count == TARGET_ROWS:
        score += 60
    elif row_count == ALTERNATE_ROWS:
        score += 30

    if marker_column is not None:
        score += 20
        if (
            row_count == TARGET_ROWS
            and marker_counts.get("0x29", 0) == TARGET_RAW29
            and marker_counts.get("0x1e", 0) == TARGET_RAW1E
            and sum(
                count
                for marker, count in marker_counts.items()
                if marker not in {"0x29", "0x1e"}
            )
            == 0
        ):
            score += 80

    score += min(header_signal_count * 10, 30)
    return score


def inspect_csv(path: Path) -> Candidate:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    text, encoding = decode_csv(data)

    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ValueError("missing CSV header")

    fieldnames = [name.strip() for name in reader.fieldnames if name is not None]
    marker_column = find_column(fieldnames, MARKER_CANDIDATES)
    rows = list(reader)
    marker_counts: Counter[str] = Counter()
    if marker_column is not None:
        for row in rows:
            marker_counts[parse_marker((row.get(marker_column) or "").strip())] += 1

    signals = id_list_header_count(fieldnames)
    score = score_candidate(len(rows), marker_column, marker_counts, signals)

    return Candidate(
        path=path,
        sha256=digest,
        row_count=len(rows),
        score=score,
        marker_column=marker_column,
        marker_counts=dict(sorted(marker_counts.items())),
        id_list_header_count=signals,
        encoding=encoding,
    )


def iter_csv_paths(roots: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for root in roots:
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            resolved = root.expanduser().absolute()

        if resolved.is_file():
            paths = [resolved] if resolved.suffix.lower() == ".csv" else []
        elif resolved.is_dir():
            try:
                paths = sorted(
                    p for p in resolved.rglob("*")
                    if p.is_file() and p.suffix.lower() == ".csv"
                )
            except OSError as exc:
                print(f"warning: cannot scan {resolved}: {exc}", file=sys.stderr)
                continue
        else:
            print(f"warning: root does not exist: {resolved}", file=sys.stderr)
            continue

        for path in paths:
            try:
                canonical = path.resolve()
            except OSError:
                canonical = path.absolute()
            if canonical in seen:
                continue
            seen.add(canonical)
            yield canonical


def rank_candidates(roots: Iterable[Path]) -> list[Candidate]:
    candidates: list[Candidate] = []
    for path in iter_csv_paths(roots):
        try:
            candidates.append(inspect_csv(path))
        except (OSError, csv.Error, ValueError) as exc:
            print(f"warning: skipped {path}: {exc}", file=sys.stderr)

    candidates.sort(
        key=lambda c: (
            -c.score,
            0 if c.row_count == TARGET_ROWS else 1,
            c.sha256,
            str(c.path),
        )
    )
    return candidates


def build_receipt(candidates: list[Candidate], limit: int) -> dict[str, object]:
    selected = candidates[:limit]
    return {
        "schema": SCHEMA,
        "candidate_count": len(selected),
        "candidates": [
            candidate.receipt_row(rank)
            for rank, candidate in enumerate(selected, start=1)
        ],
        "privacy": {
            "local_paths_emitted": False,
            "headers_emitted": False,
            "csv_rows_emitted": False,
            "pub_bytes_emitted": False,
            "document_text_emitted": False,
        },
    }


def print_candidates(candidates: list[Candidate], limit: int) -> None:
    for rank, candidate in enumerate(candidates[:limit], start=1):
        marker = candidate.marker_column or "-"
        counts = (
            ",".join(f"{key}:{value}" for key, value in candidate.marker_counts.items())
            if candidate.marker_counts
            else "-"
        )
        print(
            f"rank={rank} score={candidate.score} rows={candidate.row_count} "
            f"sha256={candidate.sha256} marker_column={marker} "
            f"marker_counts={counts} id_list_headers={candidate.id_list_header_count} "
            f"encoding={candidate.encoding} path={candidate.path}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recursively rank local CSV candidates for the private T733/T746 "
            "residual set without uploading local paths or rows."
        )
    )
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="file or directory roots to inspect recursively",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="maximum ranked candidates to print/store (default: 20)",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        help="optional path-free JSON receipt",
    )
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit must be >= 1")

    candidates = rank_candidates(args.roots)
    print_candidates(candidates, args.limit)

    if args.receipt is not None:
        receipt = build_receipt(candidates, args.limit)
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return 0 if candidates else 4


if __name__ == "__main__":
    raise SystemExit(main())
