#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import statistics
import zipfile

CFB_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
ZIP_MAGIC = b"PK\x03\x04"
TOKENS = [
    b"Name", b"Description", b"Gallery", b"Category", b"Keywords",
    b"ContentStore", b"BBStyle", b"desID", b"wid", b"GemeindebriefDruckerei",
]
STRING_STREAMS = {"\x01CompObj", "\x03Internal", "BBStoreInfo14"}
ASCII_RE = re.compile(rb"[\x20-\x7e]{3,}")
UTF16_ASCII_RE = re.compile(rb"(?:[\x20-\x7e]\x00){3,}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def magic_kind(data: bytes) -> str:
    if data.startswith(CFB_MAGIC):
        return "cfb"
    if data.startswith(ZIP_MAGIC):
        return "zip"
    stripped = data.lstrip()
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<"):
        return "xml_or_html"
    return "other"


def token_hits(data: bytes) -> dict[str, int]:
    hits = {}
    lower = data.lower()
    for token in TOKENS:
        ascii_count = lower.count(token.lower())
        utf16 = b"".join(bytes([b, 0]) for b in token)
        utf16_count = lower.count(utf16.lower())
        count = ascii_count + utf16_count
        if count:
            hits[token.decode("ascii", errors="replace")] = count
    return hits


def printable_strings(data: bytes, limit: int = 160) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()

    def accept(value: str) -> None:
        value = re.sub(r"\s+", " ", value).strip()
        if len(value) < 3 or len(value) > 300:
            return
        if sum(ch.isalnum() for ch in value) < 2:
            return
        if value not in seen:
            seen.add(value)
            values.append(value)

    for match in ASCII_RE.finditer(data):
        accept(match.group().decode("ascii", errors="replace"))
        if len(values) >= limit:
            break
    if len(values) < limit:
        for match in UTF16_ASCII_RE.finditer(data):
            accept(match.group().decode("utf-16le", errors="replace"))
            if len(values) >= limit:
                break
    return values


def safe_property(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return {
            "type": "bytes",
            "byte_len": len(value),
            "sha256": sha256_bytes(value),
        }
    return {
        "type": type(value).__name__,
        "repr": repr(value)[:200],
    }


def ole_inventory(path: Path) -> dict:
    try:
        import olefile
    except Exception as exc:
        return {"olefile_error": f"import failed: {exc}"}

    result = {"streams": [], "summary_properties": {}}
    try:
        with olefile.OleFileIO(str(path)) as ole:
            root = getattr(ole, "root", None)
            clsid = getattr(root, "clsid", None)
            if clsid:
                result["root_clsid"] = str(clsid)

            for entry in sorted(ole.listdir(streams=True, storages=False)):
                name = "/".join(entry)
                try:
                    size = ole.get_size(entry)
                except Exception:
                    size = None
                row = {"path": name, "size": size}
                try:
                    payload = ole.openstream(entry).read()
                    row["sha256"] = sha256_bytes(payload)
                    row["token_hits"] = token_hits(payload)
                    if name in STRING_STREAMS:
                        row["printable_strings"] = printable_strings(payload)
                except Exception as exc:
                    row["read_error"] = str(exc)
                result["streams"].append(row)

            for prop_stream in (["\x05SummaryInformation"], ["\x05DocumentSummaryInformation"]):
                if not ole.exists(prop_stream):
                    continue
                try:
                    props = ole.getproperties(prop_stream)
                    result["summary_properties"]["/".join(prop_stream)] = {
                        str(key): safe_property(value)
                        for key, value in sorted(props.items())
                    }
                except Exception as exc:
                    result["summary_properties"]["/".join(prop_stream)] = {"error": str(exc)}
    except Exception as exc:
        result["olefile_error"] = str(exc)
    return result


def zip_inventory(path: Path) -> dict:
    out = []
    with zipfile.ZipFile(path) as zf:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            out.append({
                "path": info.filename,
                "byte_len": info.file_size,
                "compressed_len": info.compress_size,
                "crc32": f"{info.CRC:08x}",
            })
    return {"entries": out}


def analyze_file(path: Path) -> dict:
    data = path.read_bytes()
    kind = magic_kind(data)
    row = {
        "filename": path.name,
        "byte_len": len(data),
        "sha256": sha256_bytes(data),
        "magic_hex16": data[:16].hex(),
        "container": kind,
        "top_level_token_hits": token_hits(data),
    }
    if kind == "cfb":
        row["cfb"] = ole_inventory(path)
    elif kind == "zip":
        row["zip"] = zip_inventory(path)
    return row


def summarize(rows: list[dict]) -> dict:
    sizes = [row["byte_len"] for row in rows]
    stream_presence = collections.Counter()
    stream_sizes: dict[str, list[int]] = collections.defaultdict(list)
    stream_hashes: dict[str, set[str]] = collections.defaultdict(set)
    stream_nonzero = collections.Counter()
    token_total = collections.Counter()
    token_files = collections.Counter()
    stream_profiles = collections.Counter()
    bb_strings = collections.Counter()
    compobj_strings = collections.Counter()

    for row in rows:
        cfb = row.get("cfb", {})
        streams = cfb.get("streams", [])
        stream_profiles[tuple(s["path"] for s in streams)] += 1
        per_file_tokens = set()
        for stream in streams:
            name = stream["path"]
            stream_presence[name] += 1
            size = stream.get("size")
            if isinstance(size, int):
                stream_sizes[name].append(size)
                if size:
                    stream_nonzero[name] += 1
            digest = stream.get("sha256")
            if digest:
                stream_hashes[name].add(digest)
            for token, count in stream.get("token_hits", {}).items():
                token_total[token] += count
                per_file_tokens.add(token)
            strings = stream.get("printable_strings", [])
            if name == "BBStoreInfo14":
                bb_strings.update(strings)
            elif name == "\x01CompObj":
                compobj_strings.update(strings)
        token_files.update(per_file_tokens)

    stream_summary = {}
    for name, count in sorted(stream_presence.items()):
        vals = stream_sizes[name]
        stream_summary[name] = {
            "file_count": count,
            "nonzero_file_count": stream_nonzero[name],
            "unique_sha256_count": len(stream_hashes[name]),
            "size_min": min(vals) if vals else None,
            "size_median": int(statistics.median(vals)) if vals else None,
            "size_max": max(vals) if vals else None,
        }

    profile_rows = []
    for profile, count in stream_profiles.most_common():
        profile_rows.append({"file_count": count, "streams": list(profile)})

    return {
        "file_size": {
            "min": min(sizes) if sizes else None,
            "median": int(statistics.median(sizes)) if sizes else None,
            "max": max(sizes) if sizes else None,
        },
        "stream_profile_count": len(stream_profiles),
        "stream_profiles": profile_rows,
        "streams": stream_summary,
        "token_total_counts": dict(sorted(token_total.items())),
        "token_file_counts": dict(sorted(token_files.items())),
        "bbstoreinfo14_common_strings": [
            {"value": value, "file_count": count}
            for value, count in bb_strings.most_common(100)
        ],
        "compobj_common_strings": [
            {"value": value, "file_count": count}
            for value, count in compobj_strings.most_common(50)
        ],
    }


def analyze_tree(root: Path) -> dict:
    pbb = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pbb")
    rows = [analyze_file(path) for path in pbb]
    containers = collections.Counter(row["container"] for row in rows)
    return {
        "schema_version": "chaptera.pbb.inventory.v2",
        "pbb_count": len(rows),
        "container_counts": dict(sorted(containers.items())),
        "corpus_summary": summarize(rows),
        "pbb": rows,
        "authority_fence": {
            "publisher_runtime_used": False,
            "add_building_block_semantics_proven": False,
            "raw_pbb_bytes_committed": False,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = analyze_tree(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "schema_version": result["schema_version"],
        "pbb_count": result["pbb_count"],
        "container_counts": result["container_counts"],
        "stream_profile_count": result["corpus_summary"]["stream_profile_count"],
        "token_file_counts": result["corpus_summary"]["token_file_counts"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
