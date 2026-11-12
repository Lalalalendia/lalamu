#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from open_first_useful_page import build_receipt, build_run, dumps, sha256_file


def single_run(args: argparse.Namespace) -> int:
    fixture = args.fixture.resolve()
    row = build_run(
        sha256_file(fixture),
        fixture.stat().st_size,
        args.cache_state,
        args.run_index,
        process_mode=args.process_mode,
    )
    args.out.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def aggregate(args: argparse.Namespace) -> int:
    fixture = args.fixture.resolve()
    if not fixture.is_file():
        raise SystemExit(f"fixture missing: {fixture}")
    if args.cold_runs < 1 or args.warm_runs < 1:
        raise SystemExit("cold-runs and warm-runs must both be >= 1")

    cold_rows = []
    with tempfile.TemporaryDirectory(prefix="open-phase-proof-") as temp:
        temp_root = Path(temp)
        for index in range(args.cold_runs):
            out = temp_root / f"cold-{index}.json"
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--single-run",
                    "--fixture",
                    str(fixture),
                    "--cache-state",
                    "cold",
                    "--process-mode",
                    "fresh_process",
                    "--run-index",
                    str(index),
                    "--out",
                    str(out),
                ],
                check=True,
            )
            cold_rows.append(json.loads(out.read_text(encoding="utf-8")))

    fixture_hash = sha256_file(fixture)
    fixture_bytes = fixture.stat().st_size
    warm_rows = [
        build_run(
            fixture_hash,
            fixture_bytes,
            "warm",
            index,
            process_mode="same_process_series",
        )
        for index in range(args.warm_runs)
    ]

    receipt = build_receipt(fixture, cold_rows, warm_rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dumps(receipt), encoding="utf-8")
    print(
        json.dumps(
            {
                "receipt_version": receipt["receipt_version"],
                "fixture_sha256": receipt["fixture_identity"]["sha256"],
                "cold_runs": args.cold_runs,
                "warm_runs": args.warm_runs,
                "architecture_decision_allowed": False,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cold-runs", type=int, default=3)
    parser.add_argument("--warm-runs", type=int, default=3)
    parser.add_argument("--single-run", action="store_true")
    parser.add_argument("--cache-state", choices=["cold", "warm"])
    parser.add_argument("--process-mode", choices=["fresh_process", "same_process_series"])
    parser.add_argument("--run-index", type=int, default=0)
    args = parser.parse_args()

    if args.single_run:
        if args.cache_state is None or args.process_mode is None:
            raise SystemExit("--single-run requires --cache-state and --process-mode")
        return single_run(args)
    return aggregate(args)


if __name__ == "__main__":
    raise SystemExit(main())
