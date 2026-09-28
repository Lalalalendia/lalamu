from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "pub-corpus" / "scripts" / "page_role_sweep.py"
    spec = importlib.util.spec_from_file_location("page_role_sweep", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


page_role = load_module()


def page(ordinal: int, seq: int, oid0: int, oid1: int) -> dict:
    return {
        "document_ordinal": ordinal,
        "contents_seq_num": seq,
        "oid_dword0": oid0,
        "oid_dword1": oid1,
    }


def controlling(seq: int, pgids: list[list[int]]) -> dict:
    return {
        "contents_seq_num": seq,
        "parent_seq_num": None,
        "fully_decoded": True,
        "fields": [{"id": 6, "block_type": 136, "pgids": pgids}],
    }


class ScenarioProjectionTests(unittest.TestCase):
    def test_resolves_pgid_membership_but_preserves_document_order(self):
        receipt = {
            "pages": [
                page(0, 263, 2, 2),
                page(1, 266, 1, 0),
                page(2, 358, 1, 1),
                page(3, 269, 2, 1),
            ],
            "controlling": [
                controlling(445, [[1, 1], [1, 0]]),
                controlling(446, [[1, 1], [1, 0]]),
            ],
        }
        result = page_role.derive_scenario_projection(receipt)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["pgid_order_resolved_seq_nums"], [358, 266])
        self.assertEqual(result["document_order_projected_seq_nums"], [266, 358])

    def test_rejects_disagreeing_controlling_lists(self):
        receipt = {
            "pages": [page(0, 266, 1, 0), page(1, 358, 1, 1)],
            "controlling": [
                controlling(445, [[1, 0], [1, 1]]),
                controlling(446, [[1, 1], [1, 0]]),
            ],
        }
        result = page_role.derive_scenario_projection(receipt)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "controlling_page_lists_disagree")

    def test_rejects_ambiguous_page_oid(self):
        receipt = {
            "pages": [page(0, 266, 1, 0), page(1, 358, 1, 0)],
            "controlling": [controlling(445, [[1, 0]])],
        }
        result = page_role.derive_scenario_projection(receipt)
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(result["reason"].startswith("pgid_is_ambiguous:"))

    def test_missing_scenario_state_is_explicitly_unavailable(self):
        result = page_role.derive_scenario_projection(
            {"pages": [page(0, 266, 1, 0)], "controlling": []}
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "no_controlling_page_list")


if __name__ == "__main__":
    unittest.main()
