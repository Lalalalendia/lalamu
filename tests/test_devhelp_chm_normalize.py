import tempfile
import unittest
from pathlib import Path

from tools.devhelp_chm_normalize import (
    build_diff,
    normalize_topic,
    normalize_version,
    signature_parameters,
)


METHOD_2002 = """<html><head><title>Foo Method</title>
<meta name="Tnum" content="123"/>
</head><body>
<p class="SYN">expression.Foo(Name, Count)</p>
<p class="ofvbaArgDesc">Name Required String. The name to use.</p>
<table><tr><th>PbFooType can be one of these PbFooType constants.</th></tr>
<tr><td>pbFooOne</td><td>1</td></tr></table>
<p>Returns a Shape object.</p>
<a href="pbobjDocument.htm">Document</a>
</body></html>"""

METHOD_2003 = METHOD_2002.replace(
    "expression.Foo(Name, Count)",
    "expression.Foo(Name, [Count], [Mode])",
).replace(
    "</head>",
    '<meta name="assetid" content="HV123"/></head>',
).replace(
    "</table>",
    "<tr><td>pbFooTwo</td><td>2</td></tr></table>",
)


class DevhelpNormalizeTests(unittest.TestCase):
    def make_tree(self, root: Path, html: str, *, alias: bool = False) -> Path:
        (root / "html").mkdir(parents=True)
        (root / "links").mkdir(parents=True)
        topic = root / "html" / "pbmthFoo.htm"
        topic.write_text(html, encoding="utf-8")
        (root / "links" / "pbmthFoo_L.htm").write_text(
            '<html><div id="appliesto"><a href="../html/pbobjDocument.htm">Document</a></div></html>',
            encoding="utf-8",
        )
        if alias:
            (root / "links" / "pbmthAlias.htm").write_text(
                "<html><title>Alias helper</title></html>",
                encoding="utf-8",
            )
        return topic

    def test_signature_parameters(self):
        self.assertEqual(
            signature_parameters("expression.Foo(Name, [Count], [Mode])"),
            ["Name", "Count", "Mode"],
        )

    def test_normalize_topic_extracts_structure_without_prose(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            topic = self.make_tree(root, METHOD_2003)
            row = normalize_topic(root, topic)
            self.assertEqual(row["category"], "method")
            self.assertEqual(row["signatures"], ["expression.Foo(Name, [Count], [Mode])"])
            self.assertEqual(row["arguments"][0]["name"], "Name")
            self.assertEqual(row["return_type_candidates"], ["Shape object"])
            self.assertEqual(
                row["applies_to"],
                [{"topic_id": "pbobjdocument", "label": "Document"}],
            )
            self.assertEqual(row["links"], ["pbobjdocument"])
            self.assertEqual(row["enum_groups"][0]["type"], "PbFooType")
            self.assertEqual(
                [item["name"] for item in row["enum_groups"][0]["constants"]],
                ["pbFooOne", "pbFooTwo"],
            )
            self.assertNotIn("The name to use.", str(row))

    def test_version_uses_only_canonical_html_namespace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_tree(root, METHOD_2002, alias=True)
            chm = root / "source.chm"
            chm.write_bytes(b"chm")
            result = normalize_version(root, chm)
            self.assertEqual(result["topic_count"], 1)
            self.assertEqual(result["topics"][0]["topic_id"], "pbmthFoo")

    def test_cross_version_diff_detects_signature_and_enum_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a, b = root / "p2002", root / "p2003"
            self.make_tree(a, METHOD_2002)
            self.make_tree(b, METHOD_2003)
            chm2, chm3 = root / "2.chm", root / "3.chm"
            chm2.write_bytes(b"two")
            chm3.write_bytes(b"three")
            diff = build_diff(
                normalize_version(a, chm2),
                normalize_version(b, chm3),
            )
            self.assertEqual(diff["added_topic_ids"], [])
            self.assertEqual(diff["removed_topic_ids"], [])
            self.assertIn("pbmthFoo", diff["changed_common_topic_ids"]["signatures"])
            self.assertIn("pbmthFoo", diff["changed_common_topic_ids"]["enum_groups"])
            self.assertTrue(diff["evidence_boundary"]["canonical_html_namespace_only"])
            self.assertFalse(diff["evidence_boundary"]["topic_body_text_retained"])


if __name__ == "__main__":
    unittest.main()
