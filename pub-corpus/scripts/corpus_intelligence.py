#!/usr/bin/env python3
"""Deterministic structural intelligence pass over the admitted public PUB corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any

import olefile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "corpus" / "native" / "unclassified"
DEFAULT_MANIFEST = ROOT / "data" / "manifest.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "intelligence" / "latest.json"
DEFAULT_RECORDS = ROOT / "data" / "intelligence" / "records.jsonl"

SCHEMA = "lalamu.pub-corpus-intelligence.v1"
CFB_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def decode_metadata_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        for encoding in ("utf-8", "utf-16le", "cp1252", "latin1"):
            try:
                return value.decode(encoding).rstrip("\x00")
            except UnicodeDecodeError:
                pass
        return value.decode("latin1", errors="replace").rstrip("\x00")
    return str(value)


def load_manifest(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    rows: dict[str, dict[str, Any]] = {}
    raw = path.read_bytes() if path.exists() else b""
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        sha = str(row.get("sha256", "")).lower()
        if len(sha) == 64:
            rows[sha] = row
    return rows, sha256_bytes(raw)


def size_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    return f"2^{int(math.log2(value))}"


def provenance_document_hint(row: dict[str, Any]) -> str:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("source_filename", "anchor_text", "source_path", "candidate_id")
    ).lower()
    for label, words in (
        ("newsletter", ("newsletter", "nieuwsbrief")),
        ("poster", ("poster", "affiche")),
        ("brochure", ("brochure", "trifold", "tri-fold")),
        ("booklet", ("booklet",)),
        ("manual", ("manual",)),
        ("business-card", ("business card", "businesscard")),
        ("template", ("template", "sjabloon")),
        ("advertisement", ("advert", "auction ad", "senior ad")),
    ):
        if any(word in text for word in words):
            return label
    return "other-or-unknown"


def inspect_pub(path: Path, manifest_row: dict[str, Any]) -> dict[str, Any]:
    data = path.read_bytes()
    sha = sha256_bytes(data)
    header: dict[str, Any] = {"magic": data[:8].hex()}
    if len(data) >= 34 and data.startswith(CFB_MAGIC):
        header.update(
            {
                "minor_version": struct.unpack_from("<H", data, 24)[0],
                "major_version": struct.unpack_from("<H", data, 26)[0],
                "byte_order": struct.unpack_from("<H", data, 28)[0],
                "sector_shift": struct.unpack_from("<H", data, 30)[0],
                "mini_sector_shift": struct.unpack_from("<H", data, 32)[0],
            }
        )

    streams: list[dict[str, Any]] = []
    storages: list[str] = []
    app = ""
    parse_error: str | None = None

    try:
        ole = olefile.OleFileIO(str(path))
        try:
            storages.extend(
                sorted("/".join(parts) for parts in ole.listdir(streams=False, storages=True))
            )
            for parts in sorted(ole.listdir(streams=True, storages=False)):
                name = "/".join(parts)
                payload = ole.openstream(parts).read()
                streams.append(
                    {
                        "path": name,
                        "size": len(payload),
                        "sha256": sha256_bytes(payload),
                        "size_bucket": size_bucket(len(payload)),
                    }
                )
            metadata = ole.get_metadata()
            app = decode_metadata_value(getattr(metadata, "creating_application", None))
        finally:
            ole.close()
    except Exception as exc:
        parse_error = f"{type(exc).__name__}: {exc}"

    lower_leafs = {entry["path"].split("/")[-1].lower() for entry in streams}
    hints = [name for name in ("contents", "quill", "escher") if name in lower_leafs]
    topology_material = {
        "cfb_major": header.get("major_version"),
        "sector_shift": header.get("sector_shift"),
        "storages": storages,
        "streams": [{"path": x["path"], "size": x["size"]} for x in streams],
    }
    coarse_material = {
        "cfb_major": header.get("major_version"),
        "sector_shift": header.get("sector_shift"),
        "storages": storages,
        "streams": [{"path": x["path"], "size_bucket": x["size_bucket"]} for x in streams],
    }

    source = {
        key: manifest_row.get(key)
        for key in (
            "candidate_id",
            "source_filename",
            "source_type",
            "source_repo",
            "source_path",
            "source_url",
            "locator_snapshot",
            "anchor_text",
            "sibling_oracle",
        )
        if manifest_row.get(key) is not None
    }

    return {
        "sha256": sha,
        "file_name": path.name,
        "file_name_matches_sha": path.stem.lower() == sha,
        "byte_len": len(data),
        "file_size_bucket": size_bucket(len(data)),
        "cfb_header": header,
        "cfb_parse_error": parse_error,
        "stream_count": len(streams),
        "storage_count": len(storages),
        "declared_stream_bytes": sum(x["size"] for x in streams),
        "publisher_hints": hints,
        "creating_application": app,
        "streams": streams,
        "storages": storages,
        "topology_fingerprint": stable_hash(topology_material),
        "coarse_structure_fingerprint": stable_hash(coarse_material),
        "provenance_document_hint": provenance_document_hint(manifest_row),
        "source": source,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--records-output", type=Path, default=DEFAULT_RECORDS)
    args = parser.parse_args()

    manifest, manifest_digest = load_manifest(args.manifest)
    paths = sorted(args.corpus.rglob("*.pub"))
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for path in paths:
        sha = sha256_file(path)
        record = inspect_pub(path, manifest.get(sha, {}))
        records.append(record)
        if record["cfb_parse_error"]:
            errors.append({"sha256": sha, "error": record["cfb_parse_error"]})

    records.sort(key=lambda row: row["sha256"])
    corpus_hashes = [row["sha256"] for row in records]

    topology_counts = Counter(row["topology_fingerprint"] for row in records)
    coarse_counts = Counter(row["coarse_structure_fingerprint"] for row in records)
    source_counts = Counter((row["source"].get("source_type") or "unknown") for row in records)
    document_hints = Counter(row["provenance_document_hint"] for row in records)

    receipt = {
        "schema": SCHEMA,
        "manifest_sha256": manifest_digest,
        "corpus_set_sha256": sha256_bytes(("\n".join(corpus_hashes) + "\n").encode("ascii")),
        "corpus_file_count": len(records),
        "manifest_row_count": len(manifest),
        "unique_topology_count": len(topology_counts),
        "unique_coarse_structure_count": len(coarse_counts),
        "source_type_counts": dict(sorted(source_counts.items())),
        "provenance_document_hint_counts": dict(sorted(document_hints.items())),
        "largest_topology_clusters": [
            {"fingerprint": fp, "count": count}
            for fp, count in topology_counts.most_common(20)
        ],
        "largest_coarse_structure_clusters": [
            {"fingerprint": fp, "count": count}
            for fp, count in coarse_counts.most_common(20)
        ],
        "errors": errors,
        "records": records,
    }
    receipt["receipt_sha256"] = stable_hash(receipt)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.records_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    args.records_output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "corpus_file_count": len(records),
                "unique_topology_count": len(topology_counts),
                "unique_coarse_structure_count": len(coarse_counts),
                "errors": len(errors),
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
