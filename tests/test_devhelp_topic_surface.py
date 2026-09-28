import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from devhelp_topic_surface import build_diff, classify_topic, extract_topic_rows


class DevHelpTopicSurfaceTests(unittest.TestCase):
    def test_classification_uses_full_prefix_length(self):
        self.assertEqual(classify_topic("pbobjDocuments"), ("object", "Documents"))
        self.assertEqual(classify_topic("pbhiddenFoo"), ("hidden", "Foo"))

    def test_unique_topic_paths_and_categories(self):
        data = (
            b"junk/html/pbobjDocuments.htm more /html/pbmthUndo.htm "
            b"/html/pbobjDocuments.htm"
        )
        self.assertEqual(
            extract_topic_rows(data),
            [
                {"topic_id": "pbmthUndo", "category": "method", "name": "Undo"},
                {"topic_id": "pbobjDocuments", "category": "object", "name": "Documents"},
            ],
        )

    def test_diff_is_fail_closed_and_source_safe(self):
        p2002 = b"/html/pbobjA.htm /html/pbproSame.htm"
        p2003 = b"/html/pbobjA.htm /html/pbobjB.htm /html/pbproSame.htm"
        result = build_diff(p2002, p2003)
        self.assertEqual(result["diff"]["common_count"], 2)
        self.assertEqual(result["diff"]["added_count"], 1)
        self.assertEqual(result["diff"]["removed_count"], 0)
        self.assertEqual(result["diff"]["added"][0]["topic_id"], "pbobjB")
        boundary = result["evidence_boundary"]
        self.assertTrue(boundary["topic_ids_and_categories_proven"])
        self.assertFalse(boundary["parameter_signatures_extracted"])
        self.assertFalse(boundary["pub_wire_format_claims_allowed"])

    def test_expected_hash_mismatch_fails(self):
        with self.assertRaises(ValueError):
            build_diff(b"a", b"b", expected_2002_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
