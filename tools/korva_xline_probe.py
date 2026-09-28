#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import struct
from typing import Any

PNG_SIG = b"\x89PNG\r\n\x1a\n"
JPEG_SIG = b"\xff\xd8\xff"
WS = re.compile(r"\s+")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm_text(value: str) -> str:
    return WS.sub(" ", value.replace("\ufffd", " ")).strip()


def png_len(data: bytes, start: int) -> int | None:
    if data[start : start + 8] != PNG_SIG:
        return None
    pos = start + 8
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(data):
            return None
        pos = end
        if ctype == b"IEND":
            return pos - start
    return None


def jpeg_len(data: bytes, start: int) -> int | None:
    if data[start : start + 3] != JPEG_SIG:
        return None
    end = data.find(b"\xff\xd9", start + 3)
    if end < 0:
        return None
    return end + 2 - start


def carve_images(data: bytes) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for signature, mime, length_fn in (
        (PNG_SIG, "image/png", png_len),
        (JPEG_SIG, "image/jpeg", jpeg_len),
    ):
        pos = 0
        while True:
            at = data.find(signature, pos)
            if at < 0:
                break
            length = length_fn(data, at)
            if length and length >= len(signature):
                payload = data[at : at + length]
                key = (at, length, sha256(payload))
                if key not in seen:
                    seen.add(key)
                    rows.append(
                        {
                            "offset": at,
                            "byte_len": length,
                            "mime": mime,
                            "sha256": key[2],
                        }
                    )
                pos = at + max(1, length)
            else:
                pos = at + 1
    rows.sort(key=lambda row: (row["offset"], row["mime"]))
    return rows


class XhtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text = []
        self.images = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style"}:
            self.skip += 1
            return
        if tag == "img":
            values = dict(attrs)
            src = values.get("src", "")
            if src:
                self.images.append(src)

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            value = norm_text(data)
            if value:
                self.text.append(value)


def xhtml_observation(path: Path, asset_root: Path | None) -> dict[str, Any]:
    parser = XhtmlParser()
    raw = path.read_bytes()
    parser.feed(raw.decode("utf-8", errors="replace"))
    text = norm_text(" ".join(parser.text))
    images = []

    def add_image(payload: bytes, mime: str, origin: str):
        images.append(
            {
                "origin": origin,
                "mime": mime,
                "byte_len": len(payload),
                "sha256": sha256(payload),
            }
        )

    for src in parser.images:
        if src.startswith("data:image/") and ";base64," in src:
            head, encoded = src.split(",", 1)
            mime = head.split(":", 1)[1].split(";", 1)[0]
            try:
                add_image(base64.b64decode(encoded), mime, "data_uri")
            except Exception:
                pass
        elif asset_root:
            candidate = (asset_root / src).resolve()
            try:
                candidate.relative_to(asset_root.resolve())
            except ValueError:
                continue
            if candidate.is_file():
                suffix = candidate.suffix.lower()
                mime = "image/png" if suffix == ".png" else "image/jpeg" if suffix in {".jpg", ".jpeg"} else "application/octet-stream"
                add_image(candidate.read_bytes(), mime, "file")

    if asset_root:
        existing = {row["sha256"] for row in images}
        for candidate in sorted(asset_root.rglob("*")):
            if not candidate.is_file() or candidate == path:
                continue
            suffix = candidate.suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg"}:
                continue
            payload = candidate.read_bytes()
            digest = sha256(payload)
            if digest in existing:
                continue
            existing.add(digest)
            mime = "image/png" if suffix == ".png" else "image/jpeg"
            add_image(payload, mime, "discovered_file")

    return {
        "schema_version": "chaptera.korva-xline.libmspub-observation.v1",
        "engine": "libmspub",
        "xhtml_sha256": sha256(raw),
        "normalized_text": text,
        "normalized_text_sha256": sha256(text.encode()),
        "images": images,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    raw = sub.add_parser("raw")
    raw.add_argument("pub", type=Path)

    xhtml = sub.add_parser("xhtml")
    xhtml.add_argument("file", type=Path)
    xhtml.add_argument("--asset-root", type=Path)

    args = ap.parse_args()
    if args.cmd == "raw":
        data = args.pub.read_bytes()
        print(json.dumps({
            "schema_version": "chaptera.korva-xline.raw-arbitration.v1",
            "source_byte_len": len(data),
            "source_sha256": sha256(data),
            "carved_images": carve_images(data),
        }, indent=2, sort_keys=True))
    else:
        print(json.dumps(xhtml_observation(args.file, args.asset_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
