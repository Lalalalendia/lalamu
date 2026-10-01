#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

SKIP_DIRS = {".git", ".gradle", "build", "target", "node_modules", ".idea"}
TEXT_EXTS = {
    ".gradle", ".kts", ".kt", ".java", ".xml", ".json", ".yaml", ".yml", ".toml",
    ".properties", ".txt", ".md", ".cfg", ".conf", ".ini", ".env", ".sh", ".ps1",
    ".cmd", ".bat", ".py", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".swift",
}
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_ENTRY_BYTES = 32 * 1024 * 1024
ASCII_MIN = 6

@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    location: str
    evidence: str

RULES = [
    ("high", "private-key-pem", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("high", "github-token", re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{40,255})")),
    ("high", "slack-token", re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,255}")),
    ("high", "stripe-secret", re.compile(rb"sk_(?:live|test)_[A-Za-z0-9]{20,255}")),
    ("medium", "google-api-key", re.compile(rb"AIza[0-9A-Za-z_-]{35}")),
    ("medium", "jwt-like-token", re.compile(rb"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("medium", "generic-secret-assignment", re.compile(
        rb"(?i)(?:client_secret|api_secret|secret_key|password|passwd|private_key|access_token|refresh_token)\s*[:=]\s*[\"'][^\"'\r\n]{8,}[\"']"
    )),
]
SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3}

def _redact(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace").strip().replace("\n", "\\n").replace("\r", "")
    if len(text) <= 18:
        return "<redacted>"
    return f"{text[:8]}...{text[-6:]}"

def _ascii_strings(data: bytes) -> bytes:
    parts = []
    start = None
    for i, b in enumerate(data):
        if 32 <= b <= 126:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= ASCII_MIN:
                parts.append(data[start:i])
            start = None
    if start is not None and len(data) - start >= ASCII_MIN:
        parts.append(data[start:])
    return b"\n".join(parts)

def _scan_bytes(data: bytes, location: str) -> list[Finding]:
    findings: list[Finding] = []
    for severity, rule, pattern in RULES:
        for match in pattern.finditer(data):
            findings.append(Finding(severity, rule, location, _redact(match.group(0))))
    return findings

def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            yield Path(base) / name

def scan_path(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    for file_path in _iter_files(path):
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE_BYTES:
            continue
        if file_path.suffix.lower() == ".apk":
            findings.extend(scan_apk(file_path))
            continue
        if file_path.suffix.lower() not in TEXT_EXTS and file_path.name not in {".env", "gradle.properties"}:
            continue
        try:
            findings.extend(_scan_bytes(file_path.read_bytes(), str(file_path)))
        except OSError:
            continue
    return findings

def scan_apk(apk: Path) -> list[Finding]:
    findings: list[Finding] = []
    with zipfile.ZipFile(apk) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.file_size > MAX_ARCHIVE_ENTRY_BYTES:
                continue
            try:
                data = zf.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile):
                continue
            location = f"{apk}!/{info.filename}"
            findings.extend(_scan_bytes(data, location))
            if Path(info.filename).suffix.lower() in {".dex", ".so"}:
                findings.extend(_scan_bytes(_ascii_strings(data), location + ":strings"))
    return findings

def fail_threshold(findings: list[Finding], threshold: str) -> bool:
    limit = SEVERITY_ORDER[threshold]
    return any(SEVERITY_ORDER[f.severity] >= limit for f in findings)

def write_report(findings: list[Finding], report: Path | None) -> None:
    payload = {"findings": [asdict(f) for f in findings], "count": len(findings)}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)

def validate_gradle_metadata(path: Path) -> dict[str, int | bool]:
    if not path.is_file():
        raise ValueError(f"missing Gradle verification metadata: {path}")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"invalid Gradle verification metadata XML: {exc}") from exc
    if root.tag.rsplit("}", 1)[-1] != "verification-metadata":
        raise ValueError(f"unexpected root element: {root.tag}")

    components = 0
    checksums = 0
    strong_checksums = 0
    verify_metadata = None
    for elem in root.iter():
        local = elem.tag.rsplit("}", 1)[-1]
        if local == "component":
            components += 1
        elif local in {"sha256", "sha512", "sha1", "md5"}:
            checksums += 1
            if local in {"sha256", "sha512"}:
                strong_checksums += 1
        elif local == "verify-metadata" and elem.text is not None:
            verify_metadata = elem.text.strip().lower() == "true"

    if components == 0:
        raise ValueError("verification metadata contains no components")
    if strong_checksums == 0:
        raise ValueError("verification metadata contains no SHA-256/SHA-512 checksums")
    if verify_metadata is False:
        raise ValueError("verification metadata explicitly disables metadata verification")
    return {
        "components": components,
        "checksums": checksums,
        "strong_checksums": strong_checksums,
        "verify_metadata": verify_metadata is not False,
    }

def _find_apksigner(explicit: str | None) -> str:
    if explicit:
        return explicit
    android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if android_home:
        build_tools = Path(android_home) / "build-tools"
        if build_tools.is_dir():
            name = "apksigner.bat" if os.name == "nt" else "apksigner"
            for child in sorted(build_tools.iterdir(), reverse=True):
                candidate = child / name
                if candidate.is_file():
                    return str(candidate)
    return "apksigner"

def inspect_apk_signer(apk: Path, expected_sha256: str | None, apksigner: str | None, reject_debug: bool) -> dict[str, str | bool]:
    tool = _find_apksigner(apksigner)
    try:
        proc = subprocess.run(
            [tool, "verify", "--print-certs", str(apk)],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ValueError(f"apksigner not found: {tool}") from exc

    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        raise ValueError(f"apksigner verification failed: {output.strip()}")

    digest_match = re.search(r"certificate SHA-256 digest:\s*([0-9a-fA-F:]+)", output)
    dn_match = re.search(r"certificate DN:\s*(.+)", output)
    if not digest_match:
        raise ValueError("could not parse signer SHA-256 fingerprint from apksigner output")

    actual = re.sub(r"[^0-9a-fA-F]", "", digest_match.group(1)).lower()
    dn = dn_match.group(1).strip() if dn_match else ""
    debug = "CN=Android Debug" in dn

    if reject_debug and debug:
        raise ValueError(f"debug signing certificate rejected: {dn}")

    if expected_sha256:
        expected = re.sub(r"[^0-9a-fA-F]", "", expected_sha256).lower()
        if len(expected) != 64:
            raise ValueError("expected SHA-256 fingerprint must contain 64 hex characters")
        if actual != expected:
            raise ValueError(f"signer fingerprint mismatch: expected {expected}, got {actual}")

    return {"sha256": actual, "dn": dn, "debug": debug, "verified": True}

def cmd_scan(args: argparse.Namespace) -> int:
    path = Path(args.path)
    findings = scan_apk(path) if args.apk else scan_path(path)
    write_report(findings, Path(args.report) if args.report else None)
    return 2 if fail_threshold(findings, args.fail_on) else 0

def cmd_gradle(args: argparse.Namespace) -> int:
    try:
        result = validate_gradle_metadata(Path(args.file))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0

def cmd_signer(args: argparse.Namespace) -> int:
    try:
        result = inspect_apk_signer(Path(args.apk), args.expected_sha256, args.apksigner, args.reject_debug)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Android release security gates")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="scan source tree or APK for likely embedded secrets")
    scan.add_argument("--path", required=True)
    scan.add_argument("--apk", action="store_true", help="treat --path as APK archive")
    scan.add_argument("--fail-on", choices=("medium", "high"), default="high")
    scan.add_argument("--report")
    scan.set_defaults(func=cmd_scan)

    gradle = sub.add_parser("gradle-metadata", help="validate Gradle dependency verification metadata")
    gradle.add_argument("--file", required=True)
    gradle.set_defaults(func=cmd_gradle)

    signer = sub.add_parser("apk-signer", help="verify APK signature and optional expected signer fingerprint")
    signer.add_argument("--apk", required=True)
    signer.add_argument("--expected-sha256")
    signer.add_argument("--apksigner")
    signer.add_argument("--reject-debug", action="store_true", default=False)
    signer.set_defaults(func=cmd_signer)
    return parser

def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
