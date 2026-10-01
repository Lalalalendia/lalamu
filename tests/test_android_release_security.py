import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "android_release_security.py"
spec = importlib.util.spec_from_file_location("android_release_security", MODULE_PATH)
ars = importlib.util.module_from_spec(spec)
sys.modules["android_release_security"] = ars
spec.loader.exec_module(ars)

class SecurityGateTests(unittest.TestCase):
    def test_source_scan_private_key(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "secret.env"
            p.write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n")
            findings = ars.scan_path(Path(td))
            self.assertTrue(any(f.rule == "private-key-pem" and f.severity == "high" for f in findings))

    def test_apk_scan_high_confidence_secret(self):
        with tempfile.TemporaryDirectory() as td:
            apk = Path(td) / "x.apk"
            with zipfile.ZipFile(apk, "w") as zf:
                zf.writestr("assets/config.txt", "token=ghp_" + "A" * 40)
            findings = ars.scan_apk(apk)
            self.assertTrue(any(f.rule == "github-token" for f in findings))

    def test_gradle_metadata_accepts_sha256(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "verification-metadata.xml"
            p.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<verification-metadata>
<configuration><verify-metadata>true</verify-metadata></configuration>
<components><component group="x" name="y" version="1"><artifact name="y-1.jar"><sha256 value="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/></artifact></component></components>
</verification-metadata>
""")
            result = ars.validate_gradle_metadata(p)
            self.assertEqual(result["components"], 1)
            self.assertEqual(result["strong_checksums"], 1)

    def test_gradle_metadata_missing_rejected(self):
        with self.assertRaises(ValueError):
            ars.validate_gradle_metadata(Path("/definitely/missing/verification-metadata.xml"))

if __name__ == "__main__":
    unittest.main()
