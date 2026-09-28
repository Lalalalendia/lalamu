#!/usr/bin/env python3
"""Deterministic defensive fuzzing for public Chaptera PUB open/admission binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "corpus" / "native" / "unclassified"
SCHEMA = "lalamu.pub-fuzz-regression.v1"
CFB_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Failure:
    kind: str
    detail: str


def classify_process(
    returncode: int | None,
    timed_out: bool,
    stderr: bytes,
    target_kind: str,
) -> Failure | None:
    if timed_out:
        return Failure("timeout", "wall-clock timeout")
    if returncode is None:
        return Failure("spawn-failure", "no return code")
    if returncode < 0:
        return Failure("signal", str(-returncode))
    stderr_text = stderr.decode("utf-8", errors="replace").lower()
    if "panicked at" in stderr_text or returncode in (101, 134, 139):
        return Failure("crash-or-panic", str(returncode))
    if target_kind == "untrusted-worker" and returncode != 0:
        return Failure("unexpected-worker-nonzero", str(returncode))
    return None


def run_target(
    binary: str,
    target_kind: str,
    payload: bytes,
    timeout: float,
) -> tuple[Failure | None, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="lalamu-fuzz-") as tmp:
        root = Path(tmp)
        input_path = root / "case.pub"
        input_path.write_bytes(payload)
        env = os.environ.copy()

        if target_kind == "chaptera-viewer":
            argv = [binary, str(input_path)]
        elif target_kind == "untrusted-worker":
            output_dir = root / "out"
            output_dir.mkdir()
            env["CHAPTERA_WORKER_INPUT"] = str(input_path)
            env["CHAPTERA_WORKER_OUTPUT_DIR"] = str(output_dir)
            argv = [
                binary,
                "inspect",
                "--max-file-bytes",
                str(64 * 1024 * 1024),
                "--max-cfb-entries",
                "8192",
                "--max-declared-stream-bytes",
                str(512 * 1024 * 1024),
            ]
        else:
            raise ValueError(f"unknown target kind: {target_kind}")

        try:
            completed = subprocess.run(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=env,
                timeout=timeout,
                check=False,
            )
            failure = classify_process(
                completed.returncode, False, completed.stderr, target_kind
            )
            return failure, {
                "returncode": completed.returncode,
                "stderr_sha256": sha256_bytes(completed.stderr),
            }
        except subprocess.TimeoutExpired as exc:
            stderr = exc.stderr or b""
            failure = classify_process(None, True, stderr, target_kind)
            return failure, {
                "returncode": None,
                "stderr_sha256": sha256_bytes(stderr),
            }
        except OSError as exc:
            return Failure("spawn-failure", type(exc).__name__), {"returncode": None}


def mutate(seed: bytes, rng: random.Random, iteration: int) -> tuple[bytes, str]:
    if not seed:
        return b"\x00", "empty-seed-byte"
    data = bytearray(seed)
    variant = iteration % 9

    if variant == 0:
        limit = min(len(data), 512)
        for _ in range(1 + rng.randrange(8)):
            pos = rng.randrange(limit)
            data[pos] ^= 1 << rng.randrange(8)
        return bytes(data), "cfb-header-bitflip"

    if variant == 1 and len(data) > 520:
        cut = rng.randrange(512, len(data))
        return bytes(data[:cut]), "truncate-after-header"

    if variant == 2:
        width = min(64, len(data))
        start = rng.randrange(max(1, len(data) - width + 1))
        data[start : start + width] = b"\x00" * width
        return bytes(data), "zero-window"

    if variant == 3:
        width = min(64, len(data))
        start = rng.randrange(max(1, len(data) - width + 1))
        data[start : start + width] = b"\xff" * width
        return bytes(data), "ff-window"

    if variant == 4 and len(data) > 64:
        start = rng.randrange(len(data) - 32)
        chunk = bytes(data[start : start + rng.randrange(1, 33)])
        insert_at = rng.randrange(len(data) + 1)
        return bytes(data[:insert_at] + chunk + data[insert_at:]), "duplicate-slice"

    if variant == 5 and len(data) > 1024:
        width = rng.randrange(1, min(512, len(data) - 512))
        start = rng.randrange(512, len(data) - width + 1)
        return bytes(data[:start] + data[start + width :]), "delete-slice"

    if variant == 6 and len(data) >= 4:
        pos = rng.randrange(len(data) - 3)
        data[pos : pos + 4] = rng.choice(
            [b"\x00\x00\x00\x00", b"\xff\xff\xff\xff", b"\x00\x00\x00\x80"]
        )
        return bytes(data), "u32-extreme"

    if variant == 7:
        markers = [
            b"C\x00o\x00n\x00t\x00e\x00n\x00t\x00s\x00",
            b"Q\x00u\x00i\x00l\x00l\x00",
            b"E\x00s\x00c\x00h\x00e\x00r\x00",
        ]
        found = [seed.find(marker) for marker in markers if seed.find(marker) >= 0]
        if found:
            center = rng.choice(found)
            start = max(0, center - 32)
            end = min(len(data), center + 64)
            for _ in range(1 + rng.randrange(6)):
                pos = rng.randrange(start, end)
                data[pos] ^= rng.randrange(1, 256)
            return bytes(data), "directory-name-neighborhood"
        return bytes(data[::-1]), "reverse-fallback"

    pos = rng.randrange(len(data))
    data[pos] ^= rng.randrange(1, 256)
    return bytes(data), "single-byte-xor"


def minimize(
    binary: str,
    target_kind: str,
    payload: bytes,
    expected: Failure,
    timeout: float,
    max_attempts: int = 40,
) -> bytes:
    current = payload
    attempts = 0
    granularity = 2

    while len(current) > 1 and attempts < max_attempts:
        chunk = max(1, len(current) // granularity)
        reduced = False
        start = 0
        while start < len(current) and attempts < max_attempts:
            candidate = current[:start] + current[min(len(current), start + chunk) :]
            if not candidate:
                start += chunk
                continue
            attempts += 1
            failure, _ = run_target(binary, target_kind, candidate, timeout)
            if failure and failure.kind == expected.kind:
                current = candidate
                reduced = True
                break
            start += chunk
        if reduced:
            granularity = max(2, granularity - 1)
        else:
            if granularity >= min(len(current), 16):
                break
            granularity = min(len(current), granularity * 2)
    return current


def select_seeds(corpus: Path, max_seeds: int, max_seed_bytes: int) -> list[Path]:
    candidates: list[Path] = []
    for path in corpus.rglob("*.pub"):
        if path.stat().st_size > max_seed_bytes:
            continue
        with path.open("rb") as fh:
            if fh.read(8) == CFB_MAGIC:
                candidates.append(path)
    candidates.sort(key=lambda path: (path.stat().st_size, path.stem))
    if len(candidates) <= max_seeds:
        return candidates
    if max_seeds == 1:
        return [candidates[len(candidates) // 2]]
    indexes = {
        round(i * (len(candidates) - 1) / (max_seeds - 1))
        for i in range(max_seeds)
    }
    return [candidates[i] for i in sorted(indexes)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--target-bin", required=True)
    parser.add_argument(
        "--target-kind",
        choices=("chaptera-viewer", "untrusted-worker"),
        required=True,
    )
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260928)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--max-seeds", type=int, default=10)
    parser.add_argument("--max-seed-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--regression-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    binary = str(Path(args.target_bin).resolve())
    if not Path(binary).exists() and not shutil.which(binary):
        raise SystemExit(f"target binary not found: {binary}")

    seeds = select_seeds(args.corpus, args.max_seeds, args.max_seed_bytes)
    if not seeds:
        raise SystemExit("no admissible fuzz seeds found")

    args.regression_dir.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    retained: list[dict[str, Any]] = []
    outcome_counts: dict[str, int] = {}

    for iteration in range(args.iterations):
        seed_path = seeds[iteration % len(seeds)]
        seed_bytes = seed_path.read_bytes()
        mutated, mutation = mutate(seed_bytes, rng, iteration)
        failure, process = run_target(binary, args.target_kind, mutated, args.timeout)
        key = failure.kind if failure else "non-interesting"
        outcome_counts[key] = outcome_counts.get(key, 0) + 1
        if not failure:
            continue

        minimized = minimize(
            binary, args.target_kind, mutated, failure, args.timeout
        )
        first, _ = run_target(binary, args.target_kind, minimized, args.timeout)
        second, _ = run_target(binary, args.target_kind, minimized, args.timeout)
        if (
            not first
            or not second
            or first.kind != failure.kind
            or second.kind != failure.kind
        ):
            outcome_counts["non-reproducible-interesting"] = (
                outcome_counts.get("non-reproducible-interesting", 0) + 1
            )
            continue

        case_sha = sha256_bytes(minimized)
        pub_path = args.regression_dir / f"{case_sha}.pub"
        receipt_path = args.regression_dir / f"{case_sha}.json"
        if not pub_path.exists():
            pub_path.write_bytes(minimized)

        receipt = {
            "schema": SCHEMA,
            "target_kind": args.target_kind,
            "failure_kind": failure.kind,
            "failure_detail": failure.detail,
            "source_seed_sha256": seed_path.stem.lower(),
            "source_seed_bytes": len(seed_bytes),
            "mutation": mutation,
            "iteration": iteration,
            "mutated_bytes": len(mutated),
            "minimized_bytes": len(minimized),
            "minimized_sha256": case_sha,
            "process": process,
            "reproduced_twice": True,
        }
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        retained.append(receipt)

    summary = {
        "schema": SCHEMA,
        "target_kind": args.target_kind,
        "chaptera_upstream_commit": os.environ.get("CHAPTERA_UPSTREAM_COMMIT"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "seed": args.seed,
        "iterations": args.iterations,
        "seed_sha256s": [path.stem.lower() for path in seeds],
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "retained_regression_count": len(
            {row["minimized_sha256"] for row in retained}
        ),
        "retained": sorted(retained, key=lambda row: row["minimized_sha256"]),
    }
    args.summary.write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "target_kind",
                    "iterations",
                    "outcome_counts",
                    "retained_regression_count",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
