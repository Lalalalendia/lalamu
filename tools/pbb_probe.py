#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

CFB_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
ZIP_MAGIC = b"PK\x03\x04"
TOKENS = [
    b"Name", b"Description", b"Gallery", b"Category", b"Keywords",
    b"ContentStore", b"BBStyle", b"desID", b"wid", b"GemeindebriefDruckerei",
]


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
    for token in TOKENS:
        ascii_count = data.lower().count(token.lower())
        utf16 = b"".join(bytes([b, 0]) for b in token)
        utf16_count = data.lower().count(utf16.lower())
        count = ascii_count + utf16_count
        if count:
            hits[token.decode("ascii", errors="replace")] = count
    return hits


def ole_inventory(path: Path) -> dict:
    try:
        import olefile
    except Exception as exc:
        return {"olefile_error": f"import failed: {exc}"}

    result = {"streams": [], "summary_properties": {}}
    try:
        with olefile.OleFileIO(str(path)) as ole:
            for entry in sorted(ole.listdir(streams=True, storages=False)):
                name = "/".join(entry)
                try:
                    size = ole.get_size(entry)
                except Exception:
                    size = None
                row = {"path": name, "size": size}
                try:
                    payload = ole.openstream(entry).read()
                    row["sha256"] = hashlib.sha256(payload).hexdigest()
                    row["token_hits"] = token_hits(payload)
                except Exception as exc:
                    row["read_error"] = str(exc)
                result["streams"].append(row)

            for prop_stream in (["\x05SummaryInformation"], ["\x05DocumentSummaryInformation"]):
                if not ole.exists(prop_stream):
                    continue
                try:
                    props = ole.getproperties(prop_stream)
                    safe = {}
                    for key, value in props.items():
                        if isinstance(value, (str, int, float, bool)) or value is None:
                            safe[str(key)] = value
                        else:
                            safe[str(key)] = repr(value)[:500]
                    result["summary_properties"]["/".join(prop_stream)] = safe
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
        "sha256": hashlib.sha256(data).hexdigest(),
        "magic_hex16": data[:16].hex(),
        "container": kind,
        "top_level_token_hits": token_hits(data),
    }
    if kind == "cfb":
        row["cfb"] = ole_inventory(path)
    elif kind == "zip":
        row["zip"] = zip_inventory(path)
    return row


def analyze_tree(root: Path) -> dict:
    pbb = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pbb")
    rows = [analyze_file(path) for path in pbb]
    containers = {}
    for row in rows:
        containers[row["container"]] = containers.get(row["container"], 0) + 1
    return {
        "schema_version": "chaptera.pbb.inventory.v1",
        "pbb_count": len(rows),
        "container_counts": containers,
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
        "pbb_count": result["pbb_count"],
        "container_counts": result["container_counts"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
