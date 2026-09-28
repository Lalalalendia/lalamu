import tempfile
import unittest
from pathlib import Path

from tools.devhelp_chm_normalize import (
    build_diff,
    normalize_topic,
    normalize_version,
    parse_parameters,
)


HTML = """<html><head><title>Foo Method</title>
<meta name="Microsoft.Help.Keywords" content="Foo"/>
</head><body>
<h1>Foo Method</h1>
<h2>Syntax</h2><p>expression.Foo(Name As String, [Count As Long])</p>
<h2>Return Value</h2><p>Shape</p>
<h2>Applies To</h2><p>Document</p>
<h2>Version</h2><p>Publisher 2003</p>
<h2>Remarks</h2><p>Long body not retained.</p>
<p><a href="pbobjDocument.htm">Document</a></p>
<table><tr><th>Name</th><th>Value</th></tr>
<tr><td>pbFooOne</td><td>1</td><td>First value</td></tr></table>
</body></html>"""


class DevhelpNormalizeTests(unittest.TestCase):
    def test_parameters(self):
        self.assertEqual(parse_parameters("expression.Foo(Name As String, [Count As Long])"), ["Name", "Count"])

    def test_normalize_topic_extracts_structure_without_full_body(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "pbmthFoo.htm"
            p.write_text(HTML, encoding="utf-8")
            row = normalize_topic(p)
            self.assertEqual(row["category"], "method")
            self.assertEqual(row["parameters"], ["Name", "Count"])
            self.assertEqual(row["return_value"], "Shape")
            self.assertEqual(row["applies_to"], "Document")
            self.assertEqual(row["version_note"], "Publisher 2003")
            self.assertEqual(row["links"], ["pbobjDocument"])
            self.assertEqual(row["constant_candidates"][0]["name"], "pbFooOne")
            self.assertIn("remarks_hash", row)
            self.assertNotIn("Long body not retained.", str(row))

    def test_version_and_diff(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a = root / "a"; b = root / "b"
            a.mkdir(); b.mkdir()
            (a / "pbmthFoo.htm").write_text(HTML, encoding="utf-8")
            (b / "pbmthFoo.htm").write_text(HTML.replace("Shape</p>", "Document</p>"), encoding="utf-8")
            (b / "pbproBar.htm").write_text("<html><title>Bar Property</title><h2>Syntax</h2><p>expression.Bar</p></html>", encoding="utf-8")
            chm2 = root / "2.chm"; chm3 = root / "3.chm"
            chm2.write_bytes(b"two"); chm3.write_bytes(b"three")
            v2 = normalize_version(a, chm2)
            v3 = normalize_version(b, chm3)
            diff = build_diff(v2, v3)
            self.assertEqual(diff["added_topic_ids"], ["pbproBar"])
            self.assertEqual(diff["removed_topic_ids"], [])
            self.assertIn("pbmthFoo", diff["changed_common_topic_ids"]["return_value"])
            self.assertFalse(diff["evidence_boundary"]["topic_body_text_retained"])


if __name__ == "__main__":
    unittest.main()
