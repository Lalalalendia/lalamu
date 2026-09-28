#!/usr/bin/env python3
"""Cross-engine observational differential for public Microsoft Publisher files."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "corpus" / "native" / "unclassified"
DEFAULT_INTELLIGENCE = ROOT / "data" / "intelligence" / "latest.json"
DEFAULT_OUTPUT = ROOT / "data" / "oracle-differential" / "latest.json"
SCHEMA = "lalamu.pub-oracle-differential.v1"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def text_facts(text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    return {
        "text_chars": len(normalized),
        "text_words": len(normalized.split()) if normalized else 0,
        "normalized_text_sha256": sha256_bytes(normalized.encode("utf-8")) if normalized else None,
    }


def clean_error(text: str, temp_root: str | None = None) -> str:
    value = text.strip()
    if temp_root:
        value = value.replace(temp_root, "<tmp>")
    value = re.sub(r"/tmp/[^\s:]+", "<tmp>", value)
    return value[:1000]


def run_command(
    argv: list[str],
    *,
    timeout: float,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=False,
            timeout=timeout,
            env=env,
            cwd=str(cwd) if cwd else None,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": None,
            "stdout": exc.stdout or b"",
            "stderr": exc.stderr or b"",
            "timed_out": True,
        }
    except OSError as exc:
        return {
            "returncode": None,
            "stdout": b"",
            "stderr": str(exc).encode("utf-8", errors="replace"),
            "timed_out": False,
            "os_error": type(exc).__name__,
        }


def executable_version(argv: list[str]) -> str | None:
    result = run_command(argv, timeout=20)
    raw = (result.get("stdout") or b"") + b"\n" + (result.get("stderr") or b"")
    text = raw.decode("utf-8", errors="replace").strip()
    return text.splitlines()[0][:300] if text else None


def select_files(corpus: Path, intelligence: Path, max_files: int) -> list[Path]:
    by_sha = {path.stem.lower(): path for path in corpus.rglob("*.pub")}
    if not intelligence.exists():
        return [by_sha[key] for key in sorted(by_sha)[:max_files]]

    payload = json.loads(intelligence.read_text(encoding="utf-8"))
    records = sorted(payload.get("records") or [], key=lambda row: row.get("sha256", ""))
    chosen: list[str] = []
    seen: set[tuple[str, str]] = set()

    for row in records:
        sha = str(row.get("sha256", "")).lower()
        if sha not in by_sha:
            continue
        source_type = str((row.get("source") or {}).get("source_type") or "unknown")
        key = (str(row.get("coarse_structure_fingerprint") or ""), source_type)
        if key in seen:
            continue
        seen.add(key)
        chosen.append(sha)
        if len(chosen) >= max_files:
            break

    for sha in sorted(by_sha):
        if len(chosen) >= max_files:
            break
        if sha not in chosen:
            chosen.append(sha)

    return [by_sha[sha] for sha in chosen]


def chaptera_observation(binary: str | None, path: Path, timeout: float) -> dict[str, Any]:
    if not binary or (not shutil.which(binary) and not Path(binary).exists()):
        return {"status": "unavailable"}

    result = run_command([binary, str(path)], timeout=timeout)
    if result["timed_out"]:
        return {"status": "timeout"}
    if result["returncode"] != 0:
        return {
            "status": "rejected",
            "returncode": result["returncode"],
            "error": clean_error((result["stderr"] or b"").decode("utf-8", errors="replace")),
        }
    try:
        payload = json.loads((result["stdout"] or b"").decode("utf-8"))
    except Exception as exc:
        return {
            "status": "invalid-output",
            "error": f"{type(exc).__name__}: {exc}",
            "stdout_sha256": sha256_bytes(result["stdout"] or b""),
        }

    document = payload.get("document") or {}
    stories = document.get("stories") or []
    story_text = "\n".join(
        str(story.get("text") or "") for story in stories if isinstance(story, dict)
    )
    scene = payload.get("scene") or {}

    observation = {
        "status": "success",
        "page_count": len(document.get("pages") or []),
        "story_count": len(stories),
        "scene_surface_count": len(scene.get("surfaces") or []),
        "scene_node_count": len(scene.get("nodes") or []),
        "image_count": len(payload.get("images") or []),
        "diagnostic_count": len(document.get("diagnostics") or []),
    }
    observation.update(text_facts(story_text))
    return observation


def libmspub_observation(binary: str | None, path: Path, timeout: float) -> dict[str, Any]:
    if not binary or not shutil.which(binary):
        return {"status": "unavailable"}

    with tempfile.TemporaryDirectory(prefix="lalamu-libmspub-") as tmp:
        out = Path(tmp) / "out.xhtml"
        result = run_command([binary, str(path), str(out)], timeout=timeout)
        if result["timed_out"]:
            return {"status": "timeout"}
        if result["returncode"] != 0 or not out.exists():
            return {
                "status": "rejected",
                "returncode": result["returncode"],
                "error": clean_error(
                    (result["stderr"] or b"").decode("utf-8", errors="replace"), tmp
                ),
            }

        raw = out.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        page_count = 0
        extracted: list[str] = []
        try:
            root = ET.fromstring(text)
            for element in root.iter():
                local = element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""
                if local == "svg":
                    page_count += 1
                elif local == "text":
                    extracted.append("".join(element.itertext()))
        except ET.ParseError:
            page_count = len(re.findall(r"<svg(?:\s|>)", text, flags=re.IGNORECASE))
            extracted = [
                html.unescape(re.sub(r"<[^>]+>", " ", chunk))
                for chunk in re.findall(
                    r"<text\b[^>]*>(.*?)</text>",
                    text,
                    flags=re.IGNORECASE | re.DOTALL,
                )
            ]

        observation = {
            "status": "success",
            "page_count": page_count,
            "xhtml_bytes": len(raw),
        }
        observation.update(text_facts("\n".join(extracted)))
        return observation


def libreoffice_observation(
    binary: str | None,
    pdfinfo_bin: str | None,
    pdftotext_bin: str | None,
    path: Path,
    timeout: float,
) -> dict[str, Any]:
    if not binary or not shutil.which(binary):
        return {"status": "unavailable"}

    with tempfile.TemporaryDirectory(prefix="lalamu-lo-") as tmp:
        root = Path(tmp)
        outdir = root / "out"
        profile = root / "profile"
        outdir.mkdir()
        profile.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(root / "home")
        Path(env["HOME"]).mkdir()

        result = run_command(
            [
                binary,
                "--headless",
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                str(path),
            ],
            timeout=timeout,
            env=env,
        )
        pdf = outdir / f"{path.stem}.pdf"
        if result["timed_out"]:
            return {"status": "timeout"}
        if result["returncode"] != 0 or not pdf.exists():
            return {
                "status": "rejected",
                "returncode": result["returncode"],
                "error": clean_error(
                    ((result["stderr"] or b"") + b"\n" + (result["stdout"] or b"")).decode(
                        "utf-8", errors="replace"
                    ),
                    tmp,
                ),
            }

        page_count: int | None = None
        if pdfinfo_bin and shutil.which(pdfinfo_bin):
            info = run_command([pdfinfo_bin, str(pdf)], timeout=20)
            info_text = (info.get("stdout") or b"").decode("utf-8", errors="replace")
            match = re.search(r"^Pages:\s+(\d+)", info_text, flags=re.MULTILINE)
            if match:
                page_count = int(match.group(1))

        extracted = ""
        if pdftotext_bin and shutil.which(pdftotext_bin):
            txt = run_command([pdftotext_bin, "-layout", str(pdf), "-"], timeout=30)
            if txt["returncode"] == 0:
                extracted = (txt.get("stdout") or b"").decode("utf-8", errors="replace")

        observation = {"status": "success", "page_count": page_count}
        observation.update(text_facts(extracted))
        return observation


def disagreement_rows(engines: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    names = sorted(engines)
    for i, left_name in enumerate(names):
        for right_name in names[i + 1 :]:
            left = engines[left_name]
            right = engines[right_name]
            left_ok = left.get("status") == "success"
            right_ok = right.get("status") == "success"
            if left_ok != right_ok:
                rows.append(
                    {
                        "kind": "engine_acceptance_mismatch",
                        "left": left_name,
                        "left_status": left.get("status"),
                        "right": right_name,
                        "right_status": right.get("status"),
                    }
                )
                continue
            if not left_ok or not right_ok:
                continue
            for field, kind in (
                ("page_count", "page_count_mismatch"),
                ("normalized_text_sha256", "normalized_text_mismatch"),
            ):
                lv = left.get(field)
                rv = right.get(field)
                if lv is not None and rv is not None and lv != rv:
                    rows.append(
                        {
                            "kind": kind,
                            "field": field,
                            "left": left_name,
                            "left_value": lv,
                            "right": right_name,
                            "right_value": rv,
                        }
                    )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--intelligence", type=Path, default=DEFAULT_INTELLIGENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-files", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--chaptera-bin")
    parser.add_argument("--libmspub-bin", default="pub2xhtml")
    parser.add_argument("--libreoffice-bin", default="soffice")
    parser.add_argument("--pdfinfo-bin", default="pdfinfo")
    parser.add_argument("--pdftotext-bin", default="pdftotext")
    args = parser.parse_args()

    selected = select_files(args.corpus, args.intelligence, args.max_files)
    tool_versions = {
        "chaptera": os.environ.get("CHAPTERA_UPSTREAM_COMMIT"),
        "libmspub": executable_version([args.libmspub_bin, "--version"])
        if shutil.which(args.libmspub_bin)
        else None,
        "libreoffice": executable_version([args.libreoffice_bin, "--version"])
        if shutil.which(args.libreoffice_bin)
        else None,
    }

    records: list[dict[str, Any]] = []
    issue_counter: Counter[str] = Counter()
    for path in selected:
        engines = {
            "chaptera": chaptera_observation(args.chaptera_bin, path, args.timeout),
            "libmspub": libmspub_observation(args.libmspub_bin, path, args.timeout),
            "libreoffice": libreoffice_observation(
                args.libreoffice_bin,
                args.pdfinfo_bin,
                args.pdftotext_bin,
                path,
                args.timeout,
            ),
        }
        disagreements = disagreement_rows(engines)
        issue_counter.update(row["kind"] for row in disagreements)
        records.append(
            {
                "sha256": path.stem.lower(),
                "byte_len": path.stat().st_size,
                "engines": engines,
                "disagreements": disagreements,
            }
        )

    receipt = {
        "schema": SCHEMA,
        "selection_policy": "one-per-coarse-structure-and-source-type-then-sha-fill",
        "selected_file_count": len(records),
        "tool_versions": tool_versions,
        "issue_counts": dict(sorted(issue_counter.items())),
        "records": records,
    }
    receipt["receipt_sha256"] = stable_hash(receipt)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "selected_file_count": len(records),
                "issue_counts": receipt["issue_counts"],
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
