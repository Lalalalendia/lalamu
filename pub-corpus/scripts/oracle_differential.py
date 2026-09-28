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
SCHEMA = "lalamu.pub-oracle-differential.v2"

ENGINE_LINEAGES = {
    "chaptera": {
        "parser_lineage": "chaptera",
        "role": "canonical-public-consumer-under-test",
    },
    "libmspub": {
        "parser_lineage": "libmspub",
        "role": "independent-open-source-parser",
    },
    "libreoffice": {
        "parser_lineage": "libmspub",
        "role": "downstream-consumer-of-libmspub-import-filter",
    },
}

METRIC_SEMANTICS_VERSION = "2026-09-28.v1"

ENGINE_FIELD_CAPABILITIES = {
    "chaptera": {
        "engine_acceptance": "supported",
        "page_count": "partial",
        "normalized_text_sha256": "partial",
    },
    "libmspub": {
        "engine_acceptance": "supported",
        "page_count": "partial",
        "normalized_text_sha256": "partial",
    },
    "libreoffice": {
        "engine_acceptance": "partial",
        "page_count": "partial",
        "normalized_text_sha256": "partial",
    },
}

METRIC_SEMANTICS = {
    "engine_acceptance": {
        "chaptera": "same input bytes accepted or rejected by the Chaptera public consumer",
        "libmspub": "same input bytes accepted or rejected by libmspub",
        "libreoffice": "same input bytes accepted or rejected after LibreOffice Publisher import",
        "comparability": "direct acceptance status is comparable; LibreOffice is correlated with libmspub",
    },
    "page_count": {
        "chaptera": "Viewer projected scene surface count",
        "libmspub": "libmspub imported publication page count",
        "libreoffice": "PDF page count after LibreOffice Publisher import/export",
        "comparability": "customer-page semantic equivalence is not established; native or exhaustive paired oracle required",
    },
    "normalized_text_sha256": {
        "chaptera": "hash of normalized Chaptera-extracted text serialization",
        "libmspub": "hash of normalized libmspub-extracted text serialization",
        "libreoffice": "hash of normalized text extracted after LibreOffice PDF export",
        "comparability": "serialization/order is not semantic truth; token/content equivalence needs explicit evidence",
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def text_facts(text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    tokens = sorted(re.findall(r"\w+", normalized.casefold(), flags=re.UNICODE))
    token_material = "\n".join(tokens)
    return {
        "text_chars": len(normalized),
        "text_words": len(normalized.split()) if normalized else 0,
        "normalized_text_sha256": sha256_bytes(normalized.encode("utf-8")) if normalized else None,
        "token_multiset_sha256": sha256_bytes(token_material.encode("utf-8")) if tokens else None,
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


def intelligence_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict[str, Any]] = {}
    for row in payload.get("records") or []:
        sha = str(row.get("sha256") or "").lower()
        if not sha:
            continue
        result[sha] = {
            "topology_fingerprint": row.get("topology_fingerprint"),
            "coarse_structure_fingerprint": row.get("coarse_structure_fingerprint"),
            "provenance_document_hint": row.get("provenance_document_hint"),
            "source": row.get("source") or {},
        }
    return result


def classify_pairwise_disagreements(
    engines: dict[str, dict[str, Any]],
    disagreements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Classify raw pairwise observations without turning correlated importers into votes."""

    rows: list[dict[str, Any]] = []
    for raw in disagreements:
        row = dict(raw)
        left = str(row.get("left") or "")
        right = str(row.get("right") or "")
        field = row.get("field") or (
            "engine_acceptance" if row.get("kind") == "engine_acceptance_mismatch" else None
        )
        pair = {left, right}
        left_lineage = (ENGINE_LINEAGES.get(left) or {}).get("parser_lineage")
        right_lineage = (ENGINE_LINEAGES.get(right) or {}).get("parser_lineage")
        row["metric_semantics_version"] = METRIC_SEMANTICS_VERSION
        row["left_parser_lineage"] = left_lineage
        row["right_parser_lineage"] = right_lineage
        row["left_capability"] = (
            ENGINE_FIELD_CAPABILITIES.get(left, {}).get(str(field), "unknown")
        )
        row["right_capability"] = (
            ENGINE_FIELD_CAPABILITIES.get(right, {}).get(str(field), "unknown")
        )

        if "libreoffice" in pair:
            row["classification"] = "correlated-oracle"
            if row.get("kind") == "engine_acceptance_mismatch":
                row["underlying_semantic_classification"] = "comparable"
            elif field == "page_count":
                row["underlying_semantic_classification"] = "needs-native-oracle"
            else:
                row["underlying_semantic_classification"] = "needs-native-oracle"
            row["classification_note"] = (
                "LibreOffice Publisher import is downstream of the libmspub parser lineage; "
                "retain the observation for reproducibility but do not count it as an independent vote."
            )
        elif pair == {"chaptera", "libmspub"} and row.get("kind") == "engine_acceptance_mismatch":
            row["classification"] = "comparable"
            row["classification_note"] = (
                "Acceptance/rejection of the same exact input bytes is directly comparable. "
                "Promotion still requires the corpus admission/structural-validity gate."
            )
        elif pair == {"chaptera", "libmspub"} and field == "page_count":
            row["classification"] = "needs-native-oracle"
            row["classification_note"] = (
                "Chaptera Viewer surfaces and libmspub imported pages are not proven to denote "
                "the same customer-page concept."
            )
        elif pair == {"chaptera", "libmspub"} and field == "normalized_text_sha256":
            left_tokens = (engines.get(left) or {}).get("token_multiset_sha256")
            right_tokens = (engines.get(right) or {}).get("token_multiset_sha256")
            if (
                left_tokens is not None
                and right_tokens is not None
                and left_tokens == right_tokens
            ):
                row["classification"] = "semantic-mismatch"
                row["classification_note"] = (
                    "Order-insensitive token inventories match while normalized serialization differs."
                )
            else:
                row["classification"] = "needs-native-oracle"
                row["classification_note"] = (
                    "Normalized text serialization differs and token equivalence is not established."
                )
        elif left_lineage == right_lineage and left_lineage is not None:
            row["classification"] = "correlated-oracle"
            row["classification_note"] = "Both observations share the same parser lineage."
        else:
            row["classification"] = "needs-native-oracle"
            row["classification_note"] = "No bounded semantic-equivalence rule promotes this comparison."

        rows.append(row)
    return rows


def triage_rows(engines: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Interpret high-value Chaptera-vs-external gaps without majority voting.

    LibreOffice Publisher import is a downstream consumer of libmspub, so it
    may confirm downstream behavior but must not be counted as an independent
    parser lineage.
    """

    rows: list[dict[str, Any]] = []
    chaptera = engines.get("chaptera") or {}
    external = engines.get("libmspub") or {}
    downstream = engines.get("libreoffice") or {}

    chaptera_ok = chaptera.get("status") == "success"
    external_ok = external.get("status") == "success"
    downstream_ok = downstream.get("status") == "success"

    if chaptera_ok != external_ok:
        rows.append(
            {
                "kind": "chaptera_acceptance_gap",
                "classification": "comparable",
                "priority": "high",
                "chaptera_status": chaptera.get("status"),
                "external_parser_lineage": "libmspub",
                "external_status": external.get("status"),
                "libreoffice_downstream_status": downstream.get("status"),
                "note": "LibreOffice shares the libmspub parser lineage and is not a second independent parser vote.",
            }
        )
        return rows

    if not chaptera_ok or not external_ok:
        return rows

    chaptera_pages = chaptera.get("page_count")
    external_pages = external.get("page_count")
    if (
        isinstance(chaptera_pages, int)
        and isinstance(external_pages, int)
        and chaptera_pages != external_pages
    ):
        rows.append(
            {
                "kind": "chaptera_page_projection_gap",
                "classification": "needs-native-oracle",
                "priority": "high",
                "chaptera_page_count": chaptera_pages,
                "libmspub_page_count": external_pages,
                "page_delta": chaptera_pages - external_pages,
                "libreoffice_downstream_page_count": downstream.get("page_count")
                if downstream_ok
                else None,
                "downstream_matches_libmspub": downstream_ok
                and downstream.get("page_count") == external_pages,
                "note": "Treat as a page-role/projection research target, not proof that either lineage is semantically correct.",
            }
        )

    chaptera_tokens = chaptera.get("token_multiset_sha256")
    external_tokens = external.get("token_multiset_sha256")
    chaptera_chars = chaptera.get("text_chars")
    external_chars = external.get("text_chars")
    chaptera_words = chaptera.get("text_words")
    external_words = external.get("text_words")

    if chaptera_tokens != external_tokens and (
        chaptera_tokens is not None or external_tokens is not None
    ):
        char_delta = None
        relative_char_gap = None
        if isinstance(chaptera_chars, int) and isinstance(external_chars, int):
            char_delta = chaptera_chars - external_chars
            relative_char_gap = abs(char_delta) / max(1, external_chars)

        priority = "medium"
        kind = "chaptera_text_content_gap"
        if (
            relative_char_gap is not None
            and relative_char_gap >= 0.20
            and abs(char_delta or 0) >= 32
        ):
            priority = "high"
            kind = "chaptera_text_inventory_gap"

        rows.append(
            {
                "kind": kind,
                "classification": "needs-native-oracle",
                "priority": priority,
                "chaptera_text_chars": chaptera_chars,
                "libmspub_text_chars": external_chars,
                "chaptera_text_words": chaptera_words,
                "libmspub_text_words": external_words,
                "text_char_delta": char_delta,
                "relative_text_char_gap": relative_char_gap,
            }
        )
    elif (
        chaptera_tokens is not None
        and external_tokens is not None
        and chaptera_tokens == external_tokens
        and chaptera.get("normalized_text_sha256")
        != external.get("normalized_text_sha256")
        and chaptera.get("normalized_text_sha256") is not None
        and external.get("normalized_text_sha256") is not None
    ):
        rows.append(
            {
                "kind": "chaptera_text_order_or_punctuation_divergence",
                "classification": "semantic-mismatch",
                "priority": "low",
                "note": "Order-insensitive token inventory matches; exact normalized serialization differs.",
            }
        )
    elif (
        chaptera.get("normalized_text_sha256")
        != external.get("normalized_text_sha256")
        and chaptera.get("normalized_text_sha256") is not None
        and external.get("normalized_text_sha256") is not None
    ):
        rows.append(
            {
                "kind": "chaptera_text_serialization_unresolved",
                "classification": "needs-native-oracle",
                "priority": "medium",
                "note": "Normalized text differs, but token-multiset equivalence is unavailable or not equal.",
            }
        )

    if downstream_ok:
        downstream_tokens = downstream.get("token_multiset_sha256")
        if external_tokens != downstream_tokens and (
            external_tokens is not None or downstream_tokens is not None
        ):
            rows.append(
                {
                    "kind": "shared_lineage_downstream_text_divergence",
                    "classification": "correlated-oracle",
                    "priority": "low",
                    "note": "libmspub and LibreOffice share the PUB parser lineage; this difference is downstream extraction/render serialization, not an independent parser disagreement.",
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
    corpus_context = intelligence_index(args.intelligence)
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
    classification_counter: Counter[str] = Counter()
    triage_counter: Counter[str] = Counter()
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
        classified_disagreements = classify_pairwise_disagreements(engines, disagreements)
        triage = triage_rows(engines)
        issue_counter.update(row["kind"] for row in disagreements)
        classification_counter.update(
            row["classification"] for row in classified_disagreements
        )
        triage_counter.update(row["kind"] for row in triage)
        sha = path.stem.lower()
        records.append(
            {
                "sha256": sha,
                "byte_len": path.stat().st_size,
                "corpus_context": corpus_context.get(sha) or {},
                "engines": engines,
                "raw_pairwise_disagreements": disagreements,
                "classified_pairwise_disagreements": classified_disagreements,
                "triage": triage,
            }
        )

    receipt = {
        "schema": SCHEMA,
        "selection_policy": "one-per-coarse-structure-and-source-type-then-sha-fill",
        "selected_file_count": len(records),
        "tool_versions": tool_versions,
        "engine_lineages": ENGINE_LINEAGES,
        "engine_field_capabilities": ENGINE_FIELD_CAPABILITIES,
        "metric_semantics_version": METRIC_SEMANTICS_VERSION,
        "metric_semantics": METRIC_SEMANTICS,
        "interpretation": "Pairwise observations are not votes. LibreOffice Publisher import uses the libmspub parser lineage, so LibreOffice may confirm downstream behavior but is not an independent parser lineage.",
        "raw_pairwise_issue_counts": dict(sorted(issue_counter.items())),
        "classified_pairwise_counts": dict(sorted(classification_counter.items())),
        "triage_counts": dict(sorted(triage_counter.items())),
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
                "raw_pairwise_issue_counts": receipt["raw_pairwise_issue_counts"],
                "classified_pairwise_counts": receipt["classified_pairwise_counts"],
                "triage_counts": receipt["triage_counts"],
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
