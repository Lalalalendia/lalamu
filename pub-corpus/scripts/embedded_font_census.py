#!/usr/bin/env python3
"""Direct binary census of Embedded OpenType (EOT) fonts inside PUB CFB streams.

The probe follows the public W3C EOT structure rather than depending on
libmspub textual generator output. It records metadata and hashes only.
Font program bytes are never written to disk by this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import olefile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "corpus" / "native" / "unclassified"
DEFAULT_OUTPUT = ROOT / "data" / "embedded-font-census" / "latest.json"

SCHEMA = "lalamu.pub-embedded-font-census.v2"
EOT_MAGIC = 0x504C
EOT_MAGIC_LE = b"\x4c\x50"
EOT_FIXED_HEADER = 82
EOT_VERSIONS = {0x00010000, 0x00020001, 0x00020002}
TTEMBED_SUBSET = 0x00000001
TTEMBED_TTCOMPRESSED = 0x00000004
TTEMBED_EMBEDEUDC = 0x00000020
TTEMBED_XORENCRYPTDATA = 0x10000000
SFNT_SIGNATURES = {
    b"\x00\x01\x00\x00": "TrueType",
    b"OTTO": "OpenType-CFF",
    b"ttcf": "TrueType-collection",
    b"true": "Apple-TrueType",
    b"typ1": "Type1-sfnt",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_utf16le(raw: bytes) -> str:
    return raw.decode("utf-16le", errors="replace").rstrip("\x00")


def parse_name_fields(payload: bytes, start: int, font_data_start: int) -> dict[str, Any]:
    cursor = start + EOT_FIXED_HEADER
    names: dict[str, str] = {}
    paddings: dict[str, int] = {}

    for idx, key in enumerate(("family_name", "style_name", "version_name", "full_name"), start=2):
        if cursor + 2 > font_data_start:
            raise ValueError(f"{key}: missing size")
        size = u16(payload, cursor)
        cursor += 2
        if size % 2:
            raise ValueError(f"{key}: odd UTF-16 byte length {size}")
        if cursor + size > font_data_start:
            raise ValueError(f"{key}: out of bounds")
        names[key] = decode_utf16le(payload[cursor : cursor + size])
        cursor += size
        if key != "full_name":
            if cursor + 2 > font_data_start:
                raise ValueError(f"padding{idx}: missing")
            paddings[f"padding{idx}"] = u16(payload, cursor)
            cursor += 2

    return {
        **names,
        "name_fields_end": cursor,
        "name_padding_values": paddings,
    }


def validate_candidate(payload: bytes, start: int) -> dict[str, Any] | None:
    if start < 0 or start + EOT_FIXED_HEADER > len(payload):
        return None

    eot_size = u32(payload, start + 0)
    font_data_size = u32(payload, start + 4)
    version = u32(payload, start + 8)
    flags = u32(payload, start + 12)
    charset = payload[start + 26]
    italic = payload[start + 27]
    weight = u32(payload, start + 28)
    fs_type = u16(payload, start + 32)
    magic = u16(payload, start + 34)
    reserved = [u32(payload, start + off) for off in (64, 68, 72, 76)]
    padding1 = u16(payload, start + 80)

    if magic != EOT_MAGIC or version not in EOT_VERSIONS:
        return None
    if eot_size < EOT_FIXED_HEADER or start + eot_size > len(payload):
        return None
    if font_data_size <= 0 or font_data_size >= eot_size:
        return None
    if reserved != [0, 0, 0, 0] or padding1 != 0:
        return None

    font_data_start = start + eot_size - font_data_size
    if font_data_start < start + EOT_FIXED_HEADER:
        return None

    try:
        name_info = parse_name_fields(payload, start, font_data_start)
    except ValueError:
        return None

    eot_bytes = payload[start : start + eot_size]
    font_data = payload[font_data_start : start + eot_size]

    processed = font_data
    xor_applied = bool(flags & TTEMBED_XORENCRYPTDATA)
    compressed = bool(flags & TTEMBED_TTCOMPRESSED)
    if xor_applied:
        processed = bytes(b ^ 0x50 for b in processed)

    processed_signature = processed[:4].hex()
    sfnt_type = SFNT_SIGNATURES.get(processed[:4])
    usable_without_microtype = (not compressed) and sfnt_type is not None

    return {
        "stream_offset": start,
        "eot_size": eot_size,
        "font_data_size": font_data_size,
        "font_data_offset": font_data_start,
        "version": f"0x{version:08x}",
        "flags": f"0x{flags:08x}",
        "subset": bool(flags & TTEMBED_SUBSET),
        "microtype_compressed": compressed,
        "embedded_eudc": bool(flags & TTEMBED_EMBEDEUDC),
        "xor_encrypted": xor_applied,
        "charset": charset,
        "italic": italic,
        "weight": weight,
        "fs_type": f"0x{fs_type:04x}",
        "magic_number": "0x504c",
        "eot_sha256": sha256_bytes(eot_bytes),
        "font_data_sha256": sha256_bytes(font_data),
        "processed_font_data_sha256": sha256_bytes(processed),
        "processed_font_signature_hex": processed_signature,
        "processed_sfnt_type": sfnt_type,
        "usable_without_microtype_decompression": usable_without_microtype,
        **name_info,
    }


def scan_stream(payload: bytes) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    seen_starts: set[int] = set()
    pos = 0
    while True:
        magic_pos = payload.find(EOT_MAGIC_LE, pos)
        if magic_pos < 0:
            break
        start = magic_pos - 34
        if start not in seen_starts:
            candidate = validate_candidate(payload, start)
            if candidate is not None:
                hits.append(candidate)
                seen_starts.add(start)
        pos = magic_pos + 2
    return hits


def inspect_pub(path: Path) -> dict[str, Any]:
    sha = sha256_file(path)
    fonts: list[dict[str, Any]] = []
    streams_scanned = 0
    stream_bytes_scanned = 0
    parse_error: str | None = None

    try:
        ole = olefile.OleFileIO(str(path))
        try:
            for parts in sorted(ole.listdir(streams=True, storages=False)):
                stream_path = "/".join(parts)
                payload = ole.openstream(parts).read()
                streams_scanned += 1
                stream_bytes_scanned += len(payload)
                for hit in scan_stream(payload):
                    hit["stream_path"] = stream_path
                    fonts.append(hit)
        finally:
            ole.close()
    except Exception as exc:
        parse_error = f"{type(exc).__name__}: {exc}"

    fonts.sort(key=lambda x: (x["stream_path"], x["stream_offset"]))
    return {
        "sha256": sha,
        "file_name": path.name,
        "byte_len": path.stat().st_size,
        "cfb_parse_error": parse_error,
        "streams_scanned": streams_scanned,
        "stream_bytes_scanned": stream_bytes_scanned,
        "embedded_font_count": len(fonts),
        "embedded_fonts": fonts,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    paths = sorted(args.corpus.rglob("*.pub"))
    records = [inspect_pub(path) for path in paths]
    hits = [r for r in records if r["embedded_font_count"] > 0]
    errors = [r for r in records if r["cfb_parse_error"]]

    receipt = {
        "schema": SCHEMA,
        "method": "direct W3C EOT header scan across all CFB streams",
        "evidence_boundary": (
            "A hit is accepted only when EOT magic/version/bounds/reserved fields "
            "and variable name fields validate. Font bytes remain transient; only "
            "metadata and hashes are recorded."
        ),
        "corpus_file_count": len(records),
        "cfb_parse_error_count": len(errors),
        "embedded_font_file_count": len(hits),
        "embedded_font_count": sum(r["embedded_font_count"] for r in records),
        "usable_without_microtype_file_count": sum(
            1
            for r in records
            if any(f["usable_without_microtype_decompression"] for f in r["embedded_fonts"])
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
        "schema": receipt["schema"],
        "corpus_file_count": receipt["corpus_file_count"],
        "cfb_parse_error_count": receipt["cfb_parse_error_count"],
        "embedded_font_file_count": receipt["embedded_font_file_count"],
        "embedded_font_count": receipt["embedded_font_count"],
        "usable_without_microtype_file_count": receipt["usable_without_microtype_file_count"],
        "hit_sha256": receipt["hit_sha256"],
    }, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
