import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from open_first_useful_page import (
    ReceiptError,
    build_receipt,
    build_run,
    dumps,
    sha256_file,
    validate_receipt,
)


class OpenFirstUsefulPageProofTests(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        path = root / "external-fixture.bin"
        path.write_bytes(b"source-free-fixture-v1\x00" + bytes(range(32)))
        return path

    def test_external_fixture_identity_is_hash_and_length_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self.fixture(root)
            digest = sha256_file(fixture)
            cold = [build_run(digest, fixture.stat().st_size, "cold", 0, process_mode="fresh_process")]
            warm = [build_run(digest, fixture.stat().st_size, "warm", 0, process_mode="same_process_series")]
            receipt = build_receipt(fixture, cold, warm)
            self.assertEqual(receipt["fixture_identity"]["sha256"], digest)
            self.assertEqual(receipt["fixture_identity"]["byte_len"], fixture.stat().st_size)
            self.assertIsNone(receipt["fixture_identity"]["raw_path"])
            self.assertNotIn(str(fixture), dumps(receipt))

    def test_strict_first_useful_page_flag_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self.fixture(root)
            digest = sha256_file(fixture)
            run = build_run(digest, fixture.stat().st_size, "cold", 0, process_mode="fresh_process")
            receipt = build_receipt(fixture, [run], [build_run(digest, fixture.stat().st_size, "warm", 0, process_mode="same_process_series")])
            receipt["runs"][0]["first_useful_page_definition"]["visible_resources_ready"] = False
            with self.assertRaises(ReceiptError):
                validate_receipt(receipt)

    def test_hosted_proof_never_authorizes_architecture_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self.fixture(root)
            digest = sha256_file(fixture)
            receipt = build_receipt(
                fixture,
                [build_run(digest, fixture.stat().st_size, "cold", 0, process_mode="fresh_process")],
                [build_run(digest, fixture.stat().st_size, "warm", 0, process_mode="same_process_series")],
            )
            self.assertFalse(receipt["evidence_authority"]["real_pub_runtime"])
            self.assertFalse(receipt["evidence_authority"]["architecture_decision_allowed"])

    def test_plain_and_instrumented_final_outputs_are_equivalent(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.fixture(Path(temp))
            digest = sha256_file(fixture)
            run = build_run(digest, fixture.stat().st_size, "cold", 1, process_mode="fresh_process")
            self.assertEqual(run["plain_output_sha256"], run["instrumented_output_sha256"])

    def test_cli_receipt_is_deterministic_and_cold_warm_modes_are_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self.fixture(root)
            first = root / "first.json"
            second = root / "second.json"
            cmd = [
                sys.executable,
                str(ROOT / "tools" / "run_open_first_useful_page_proof.py"),
                "--fixture",
                str(fixture),
                "--cold-runs",
                "2",
                "--warm-runs",
                "2",
            ]
            subprocess.run(cmd + ["--out", str(first)], check=True)
            subprocess.run(cmd + ["--out", str(second)], check=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            receipt = json.loads(first.read_text(encoding="utf-8"))
            cold = [r for r in receipt["runs"] if r["cache_state"] == "cold"]
            warm = [r for r in receipt["runs"] if r["cache_state"] == "warm"]
            self.assertTrue(all(r["process_mode"] == "fresh_process" for r in cold))
            self.assertTrue(all(r["process_mode"] == "same_process_series" for r in warm))
            self.assertEqual(
                receipt["runs"][0]["document_global_before_first_useful_page"],
                ["logical_stream_read", "parse_model_projection"],
            )


if __name__ == "__main__":
    unittest.main()
