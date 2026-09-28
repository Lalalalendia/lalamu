#!/usr/bin/env python3
"""Bounded public PUB candidate ingester for lalamu."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import olefile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES = ROOT / "data" / "candidates.json"
DEFAULT_MANIFEST = ROOT / "data" / "manifest.jsonl"
DEFAULT_CORPUS = ROOT / "corpus" / "native" / "unclassified"

AUTHORITY_COMMIT = "8751688f1509397f4d2c591e6f7b12d6a9fed4a5"
AUTHORITY_URL = (
    "https://raw.githubusercontent.com/HeisLuka/rar/"
    + AUTHORITY_COMMIT
    + "/tools/corpus/receipts/current-rar-1521.sha256.txt"
)
AUTHORITY_EXPECTED_COUNT = 1521

CFB_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
USER_AGENT = "lalamu-pub-corpus/1.0 (+https://github.com/Lalalalendia/lalamu)"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def fetch_bytes(
    url: str,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    timeout: float = 45,
) -> tuple[bytes, str, str | None]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(req, timeout=timeout) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError(f"declared Content-Length {content_length} exceeds {max_bytes}")

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"download exceeded {max_bytes} bytes")
            chunks.append(chunk)

        return b"".join(chunks), response.geturl(), response.headers.get("Content-Type")


def load_authority() -> set[str]:
    raw, final_url, _ = fetch_bytes(AUTHORITY_URL, max_bytes=2 * 1024 * 1024)
    text = raw.decode("ascii", errors="strict")
    hashes = {line.strip().lower() for line in text.splitlines() if SHA256_RE.fullmatch(line.strip().lower())}
    if len(hashes) != AUTHORITY_EXPECTED_COUNT:
        raise RuntimeError(
            f"authority mismatch: expected {AUTHORITY_EXPECTED_COUNT} distinct SHA-256 values, "
            f"got {len(hashes)} from {final_url}"
        )
    return hashes


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


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


def validate_cfb_pub(data: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {
        "cfb_magic": data.startswith(CFB_MAGIC),
        "cfb_parseable": False,
        "all_streams_readable": False,
        "sector_aligned": False,
        "publisher_hint": False,
        "creating_application": "",
        "stream_count": 0,
        "storage_count": 0,
        "hints": [],
    }

    if not result["cfb_magic"] or len(data) < 512:
        return result

    sector_shift = struct.unpack_from("<H", data, 30)[0]
    if sector_shift in (9, 12):
        sector_size = 1 << sector_shift
        result["sector_size"] = sector_size
        result["sector_aligned"] = len(data) % sector_size == 0
    else:
        result["sector_size"] = None

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="lalamu-", suffix=".pub", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        ole = olefile.OleFileIO(tmp_path)
        try:
            streams = ole.listdir(streams=True, storages=False)
            storages = ole.listdir(streams=False, storages=True)
            all_entries = streams + storages
            result["stream_count"] = len(streams)
            result["storage_count"] = len(storages)

            readable = True
            mismatches: list[str] = []
            for stream_path in streams:
                declared = ole.get_size(stream_path)
                actual = len(ole.openstream(stream_path).read())
                if actual != declared:
                    readable = False
                    mismatches.append("/".join(stream_path))
            result["all_streams_readable"] = readable
            if mismatches:
                result["stream_size_mismatches"] = mismatches[:20]

            metadata = ole.get_metadata()
            app = decode_metadata_value(getattr(metadata, "creating_application", None))
            result["creating_application"] = app

            names = {part.lower() for entry in all_entries for part in entry}
            hints: list[str] = []
            if "contents" in names:
                hints.append("contents")
            if "quill" in names:
                hints.append("quill")
            if "escher" in names:
                hints.append("escher")
            if "publisher" in app.lower():
                hints.append("metadata-publisher")
            result["hints"] = hints

            result["publisher_hint"] = (
                "contents" in hints
                and any(h in hints for h in ("quill", "escher", "metadata-publisher"))
            )
            result["cfb_parseable"] = True
        finally:
            ole.close()
    except Exception as exc:
        result["validation_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    return result


def cfb_admissible(validation: dict[str, Any]) -> bool:
    return bool(
        validation.get("cfb_magic")
        and validation.get("cfb_parseable")
        and validation.get("all_streams_readable")
        and validation.get("sector_aligned")
        and validation.get("publisher_hint")
    )


def load_local_hashes(corpus_dir: Path) -> set[str]:
    hashes: set[str] = set()
    if not corpus_dir.exists():
        return hashes
    for path in corpus_dir.rglob("*.pub"):
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        hashes.add(h.hexdigest())
    return hashes


def load_manifest_hashes(manifest_path: Path) -> set[str]:
    hashes: set[str] = set()
    if not manifest_path.exists():
        return hashes
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        sha = str(row.get("sha256", "")).lower()
        if SHA256_RE.fullmatch(sha):
            hashes.add(sha)
    return hashes


def wayback_candidates(url: str) -> list[str]:
    out: list[str] = []

    cdx = (
        "https://web.archive.org/cdx/search/cdx?url="
        + quote(url, safe="")
        + "&output=json&filter=statuscode:200&collapse=digest"
        + "&fl=timestamp,original&limit=10"
    )
    try:
        raw, _, _ = fetch_bytes(cdx, max_bytes=512 * 1024, timeout=12)
        rows = json.loads(raw.decode("utf-8", errors="replace"))
        for row in rows[1:] if isinstance(rows, list) else []:
            if not isinstance(row, list) or len(row) < 2:
                continue
            timestamp, original = row[0], row[1]
            out.append(f"https://web.archive.org/web/{timestamp}id_/{original}")
    except Exception as exc:
        print(f"  wayback CDX lookup failed for {url}: {type(exc).__name__}: {exc}")

    # CDX is intermittently unavailable from hosted runners. The official
    # availability endpoint is a second bounded locator for the nearest known
    # snapshot; convert its replay URL to an id_ raw-byte replay when possible.
    availability = "https://archive.org/wayback/available?url=" + quote(url, safe="")
    try:
        raw, _, _ = fetch_bytes(availability, max_bytes=512 * 1024, timeout=12)
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        closest = (payload.get("archived_snapshots") or {}).get("closest") or {}
        replay = str(closest.get("url") or "")
        if closest.get("available") and str(closest.get("status")) == "200" and replay:
            match = re.search(r"/web/(\\d+)(?:[a-zA-Z_]+)?/(.+)$", replay)
            if match:
                out.append(
                    f"https://web.archive.org/web/{match.group(1)}id_/{match.group(2)}"
                )
            else:
                out.append(replay.replace("http://web.archive.org/", "https://web.archive.org/"))
    except Exception as exc:
        print(f"  wayback availability lookup failed for {url}: {type(exc).__name__}: {exc}")

    return list(dict.fromkeys(out))


def fetch_candidate(candidate: dict[str, Any]) -> tuple[bytes, str] | None:
    urls = list(candidate.get("urls") or [])
    attempted: set[str] = set()

    for url in urls:
        if url in attempted:
            continue
        attempted.add(url)
        try:
            data, final_url, _ = fetch_bytes(url)
            if candidate.get("recover_wayback") and not data.startswith(CFB_MAGIC):
                print(
                    f"  fetched non-CFB payload: {url} :: "
                    f"{len(data)} bytes; trying remaining/archive sources"
                )
                continue
            return data, final_url
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            print(f"  fetch failed: {url} :: {type(exc).__name__}: {exc}")

    if candidate.get("recover_wayback"):
        for original in urls:
            for archived in wayback_candidates(original):
                if archived in attempted:
                    continue
                attempted.add(archived)
                try:
                    data, final_url, _ = fetch_bytes(archived)
                    return data, final_url
                except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                    print(f"  archived fetch failed: {archived} :: {type(exc).__name__}: {exc}")

    return None


def append_manifest(manifest_path: Path, row: dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def process_candidate(
    candidate: dict[str, Any],
    authority: set[str],
    local_hashes: set[str],
    manifest_hashes: set[str],
    corpus_dir: Path,
    manifest_path: Path,
) -> str:
    cid = candidate["id"]
    print(f"[candidate] {cid}")

    fetched = fetch_candidate(candidate)
    if fetched is None:
        print("  result: not recovered")
        return "not-recovered"

    data, final_url = fetched
    sha256 = hashlib.sha256(data).hexdigest()
    blob_sha1 = git_blob_sha1(data)
    print(f"  bytes={len(data)} sha256={sha256}")

    expected_size = candidate.get("expected_size")
    if expected_size is not None and len(data) != int(expected_size):
        print(f"  result: rejected (size mismatch: expected {expected_size})")
        return "rejected-size"

    expected_blob = str(candidate.get("expected_git_blob_sha1") or "").lower()
    if expected_blob and blob_sha1 != expected_blob:
        print(f"  result: rejected (Git blob SHA-1 mismatch: {blob_sha1} != {expected_blob})")
        return "rejected-git-blob"

    if sha256 in authority:
        print("  result: known external authority duplicate")
        return "known-authority"

    if sha256 in local_hashes or sha256 in manifest_hashes:
        print("  result: known local duplicate")
        return "known-local"

    validation = validate_cfb_pub(data)
    print(
        "  validation:",
        json.dumps(
            {
                "cfb_magic": validation.get("cfb_magic"),
                "cfb_parseable": validation.get("cfb_parseable"),
                "all_streams_readable": validation.get("all_streams_readable"),
                "sector_aligned": validation.get("sector_aligned"),
                "publisher_hint": validation.get("publisher_hint"),
                "hints": validation.get("hints"),
                "creating_application": validation.get("creating_application"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )

    if not cfb_admissible(validation):
        print("  result: rejected (validation gate)")
        return "rejected-validation"

    corpus_dir.mkdir(parents=True, exist_ok=True)
    destination = corpus_dir / f"{sha256}.pub"
    destination.write_bytes(data)

    row: dict[str, Any] = {
        "candidate_id": cid,
        "sha256": sha256,
        "git_blob_sha1": blob_sha1,
        "size": len(data),
        "source_url": final_url,
        "source_filename": candidate.get("source_filename"),
        "source_type": candidate.get("source_type"),
        "source_repo": candidate.get("source_repo"),
        "source_path": candidate.get("source_path"),
        "first_seen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "external_authority_commit": AUTHORITY_COMMIT,
        "external_authority_count": AUTHORITY_EXPECTED_COUNT,
        "validation": validation,
    }
    if candidate.get("sibling_oracle"):
        row["sibling_oracle"] = candidate["sibling_oracle"]
    if candidate.get("locator_snapshot"):
        row["locator_snapshot"] = candidate["locator_snapshot"]
    if candidate.get("anchor_text"):
        row["anchor_text"] = candidate["anchor_text"]

    append_manifest(manifest_path, row)
    local_hashes.add(sha256)
    manifest_hashes.add(sha256)
    print(f"  result: admitted -> {destination.relative_to(ROOT)}")
    return "admitted"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args()

    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    if not isinstance(candidates, list):
        raise SystemExit("candidate file must contain a JSON array")

    authority = load_authority()
    print(f"[authority] loaded {len(authority)} pinned SHA-256 values")

    local_hashes = load_local_hashes(args.corpus_dir)
    manifest_hashes = load_manifest_hashes(args.manifest)

    counts: dict[str, int] = {}
    for candidate in candidates:
        status = process_candidate(
            candidate,
            authority,
            local_hashes,
            manifest_hashes,
            args.corpus_dir,
            args.manifest,
        )
        counts[status] = counts.get(status, 0) + 1

    print("[summary] " + json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
