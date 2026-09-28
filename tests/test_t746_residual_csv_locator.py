from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "locate_t746_residual_csv.py"

spec = importlib.util.spec_from_file_location("t746_locator", TOOL)
locator = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = locator
spec.loader.exec_module(locator)


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class LocatorTests(unittest.TestCase):
    def test_exact_profile_ranks_first(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exact = root / "deep" / "candidate.csv"
            alternate = root / "alternate.csv"
            noise = root / "noise.csv"

            rows = [
                {
                    "raw_type": "0x29" if i < 171 else "0x1E",
                    "source_sha256": f"{i:064x}",
                    "seq_num": str(i),
                    "list_id": "7",
                }
                for i in range(176)
            ]
            write_csv(exact, rows, ["raw_type", "source_sha256", "seq_num", "list_id"])

            write_csv(
                alternate,
                [{"marker": "0x29", "id": str(i)} for i in range(183)],
                ["marker", "id"],
            )
            write_csv(
                noise,
                [{"name": f"row-{i}"} for i in range(176)],
                ["name"],
            )

            ranked = locator.rank_candidates([root])
            self.assertEqual(ranked[0].path, exact.resolve())
            self.assertEqual(ranked[0].row_count, 176)
            self.assertEqual(ranked[0].marker_counts, {"0x1e": 5, "0x29": 171})
            self.assertGreater(ranked[0].score, ranked[1].score)

    def test_marker_aliases_match_verifier_contract(self) -> None:
        aliases = [
            "raw_type",
            "raw_marker",
            "marker",
            "chunk_type",
            "type",
            "rawType",
            "rawMarker",
        ]
        for alias in aliases:
            self.assertEqual(locator.find_column([alias], locator.MARKER_CANDIDATES), alias)
        self.assertEqual(locator.parse_marker("raw0x29"), "0x29")
        self.assertEqual(locator.parse_marker("1Eh"), "0x1e")
        self.assertEqual(locator.parse_marker("29"), "0x1d")

    def test_overlapping_roots_are_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "nested" / "candidate.csv"
            write_csv(
                path,
                [{"raw_type": "0x1e", "id": str(i)} for i in range(5)],
                ["raw_type", "id"],
            )
            ranked = locator.rank_candidates([root, root / "nested", path])
            self.assertEqual(len(ranked), 1)

    def test_receipt_is_path_and_header_free(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private_name = "TOP_SECRET_T733_residual.csv"
            path = root / "private-user-root" / private_name
            rows = [
                {
                    "rawType": "0x29" if i < 171 else "0x1e",
                    "object_identity": f"object-{i}",
                    "list_index": str(i),
                }
                for i in range(176)
            ]
            write_csv(path, rows, ["rawType", "object_identity", "list_index"])

            ranked = locator.rank_candidates([root])
            receipt = locator.build_receipt(ranked, 20)
            encoded = json.dumps(receipt, sort_keys=True)

            self.assertNotIn(private_name, encoded)
            self.assertNotIn("private-user-root", encoded)
            self.assertNotIn("rawType", encoded)
            self.assertNotIn("object_identity", encoded)
            self.assertEqual(
                set(receipt["candidates"][0]),
                {"rank", "sha256", "row_count", "score"},
            )
            self.assertFalse(receipt["privacy"]["local_paths_emitted"])
            self.assertFalse(receipt["privacy"]["csv_rows_emitted"])

    def test_cli_stdout_has_path_but_receipt_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "private" / "residual.csv"
            receipt_path = root / "receipt.json"
            rows = [
                {
                    "marker": "0x29" if i < 171 else "0x1e",
                    "seq_num": str(i),
                    "list_id": "3",
                }
                for i in range(176)
            ]
            write_csv(path, rows, ["marker", "seq_num", "list_id"])

            proc = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    str(root),
                    "--receipt",
                    str(receipt_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn(str(path.resolve()), proc.stdout)

            receipt_text = receipt_path.read_text()
            self.assertNotIn(str(path.resolve()), receipt_text)
            self.assertNotIn("residual.csv", receipt_text)
            self.assertIn('"row_count": 176', receipt_text)

    def test_no_csv_returns_four_and_empty_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipt_path = root / "receipt.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    str(root),
                    "--receipt",
                    str(receipt_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 4)
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["candidate_count"], 0)
            self.assertEqual(receipt["candidates"], [])


if __name__ == "__main__":
    unittest.main()
