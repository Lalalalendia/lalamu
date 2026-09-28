from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


triage = load_module(
    "capability_triage",
    ROOT / "pub-corpus" / "scripts" / "capability_triage.py",
)
oracle = load_module(
    "oracle_differential",
    ROOT / "pub-corpus" / "scripts" / "oracle_differential.py",
)


class CapabilityTriageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(
            (
                ROOT
                / "pub-corpus"
                / "data"
                / "oracle-differential"
                / "capability-contract.json"
            ).read_text(encoding="utf-8")
        )

    def receipt_for(self, record):
        source = {
            "schema": "lalamu.pub-oracle-differential.v2",
            "receipt_sha256": "a" * 64,
            "selected_file_count": 1,
            "tool_versions": {
                "chaptera": "chaptera-test",
                "libmspub": "libmspub-test",
                "libreoffice": "libreoffice-test",
            },
            "raw_pairwise_issue_counts": {},
            "records": [record],
        }
        return triage.build_receipt(
            source,
            self.contract,
            input_locator="fixture.json",
        )

    def test_page_count_is_not_comparable_across_different_projection_semantics(self):
        record = {
            "sha256": "1" * 64,
            "byte_len": 100,
            "corpus_context": {
                "coarse_structure_fingerprint": "coarse",
                "topology_fingerprint": "topology",
                "source": {"source_type": "test", "candidate_id": "page-count"},
            },
            "engines": {
                "chaptera": {"status": "success", "page_count": 6},
                "libmspub": {"status": "success", "page_count": 1},
                "libreoffice": {"status": "success", "page_count": 1},
            },
            "raw_pairwise_disagreements": [
                {
                    "kind": "page_count_mismatch",
                    "field": "page_count",
                    "left": "chaptera",
                    "left_value": 6,
                    "right": "libmspub",
                    "right_value": 1,
                },
                {
                    "kind": "page_count_mismatch",
                    "field": "page_count",
                    "left": "chaptera",
                    "left_value": 6,
                    "right": "libreoffice",
                    "right_value": 1,
                },
            ],
        }
        receipt = self.receipt_for(record)
        rows = receipt["records"][0]["classifications"]
        self.assertEqual(rows[0]["classification"], "semantic-mismatch")
        self.assertEqual(rows[1]["classification"], "correlated-oracle")
        self.assertEqual(receipt["promotion_candidate_count"], 0)

    def test_family22_acceptance_asymmetry_is_promotable_once(self):
        error = (
            "parse mature-0x2C Contents header -> "
            "UnexpectedFamily { expected: Family0x2c, found: Family0x22 }"
        )
        record = {
            "sha256": "2" * 64,
            "byte_len": 342016,
            "corpus_context": {
                "coarse_structure_fingerprint": "coarse",
                "topology_fingerprint": "topology",
                "source": {
                    "source_type": "github",
                    "candidate_id": "clubbooklet",
                },
            },
            "engines": {
                "chaptera": {"status": "rejected", "error": error},
                "libmspub": {"status": "success", "page_count": 21},
                "libreoffice": {"status": "success", "page_count": 21},
            },
            "raw_pairwise_disagreements": [
                {
                    "kind": "engine_acceptance_mismatch",
                    "left": "chaptera",
                    "left_status": "rejected",
                    "right": "libmspub",
                    "right_status": "success",
                },
                {
                    "kind": "engine_acceptance_mismatch",
                    "left": "chaptera",
                    "left_status": "rejected",
                    "right": "libreoffice",
                    "right_status": "success",
                },
            ],
        }
        receipt = self.receipt_for(record)
        rows = receipt["records"][0]["classifications"]
        self.assertEqual(rows[0]["classification"], "comparable")
        self.assertTrue(rows[0]["promotion_candidate"])
        self.assertEqual(
            rows[0]["linked_owners"],
            ["HeisLuka/rar#1098", "HeisLuka/rar#1153"],
        )
        self.assertEqual(rows[1]["classification"], "correlated-oracle")
        self.assertFalse(rows[1]["promotion_candidate"])
        self.assertEqual(
            receipt["records"][0]["structural_context"]["family"],
            "0x22",
        )
        self.assertEqual(receipt["promotion_candidate_count"], 1)

    def test_story65_acceptance_asymmetry_keeps_dedicated_owner(self):
        record = {
            "sha256": "3" * 64,
            "byte_len": 97792,
            "corpus_context": {
                "source": {
                    "source_type": "github",
                    "candidate_id": "shape-test",
                }
            },
            "engines": {
                "chaptera": {
                    "status": "rejected",
                    "error": "parse mature Story catalog 0x65 -> MissingDeclaredCount",
                },
                "libmspub": {"status": "success", "page_count": 1},
                "libreoffice": {"status": "success", "page_count": 1},
            },
            "raw_pairwise_disagreements": [
                {
                    "kind": "engine_acceptance_mismatch",
                    "left": "chaptera",
                    "left_status": "rejected",
                    "right": "libmspub",
                    "right_status": "success",
                }
            ],
        }
        receipt = self.receipt_for(record)
        row = receipt["records"][0]["classifications"][0]
        self.assertEqual(row["promotion_reason_code"], "chaptera-story65-missing-declared-count")
        self.assertEqual(row["linked_owners"], ["HeisLuka/rar#1156"])
        self.assertEqual(
            receipt["records"][0]["structural_context"]["family"],
            "mature-0x2c",
        )

    def test_current_snapshot_reclassifies_all_page_count_noise(self):
        source = json.loads(
            (
                ROOT
                / "pub-corpus"
                / "data"
                / "oracle-differential"
                / "latest.json"
            ).read_text(encoding="utf-8")
        )
        receipt = triage.build_receipt(
            source,
            self.contract,
            input_locator="pub-corpus/data/oracle-differential/latest.json",
        )
        raw_page_count = source["raw_pairwise_issue_counts"]["page_count_mismatch"]
        self.assertEqual(
            sum(receipt["page_count_classification_counts"].values()),
            raw_page_count,
        )
        self.assertNotIn("comparable", receipt["page_count_classification_counts"])
        # The checked-in snapshot currently carries 36 raw page-count rows.
        # Do not freeze that count: parser/corpus improvements are expected to change it.
        if raw_page_count:
            self.assertTrue(receipt["page_count_classification_counts"])

    def test_token_multiset_is_real_and_order_insensitive(self):
        facts = oracle.text_facts("Beta alpha alpha")
        expected = hashlib.sha256(b"alpha\nalpha\nbeta").hexdigest()
        self.assertEqual(facts["token_multiset_sha256"], expected)
        self.assertEqual(
            oracle.text_facts("alpha BETA alpha")["token_multiset_sha256"],
            expected,
        )


if __name__ == "__main__":
    unittest.main()
