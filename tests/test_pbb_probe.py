import unittest

from tools.pbb_probe import parse_bbstoreinfo14


class PbbProbeTests(unittest.TestCase):
    def test_parse_bbstoreinfo14(self):
        xml = b'''<?xml version="1.0"?>
<BBStore version="2"><BBItems><Item>
<Title>DS00B001</Title>
<Description>Example description</Description>
<Category>GemeindebriefDruckerei</Category>
<Keywords/>
<Type>1</Type>
<InsertGallery>4</InsertGallery>
<ShowInGallery>1</ShowInGallery>
<Filename>DS00B001</Filename>
</Item></BBItems></BBStore>'''
        result = parse_bbstoreinfo14(xml)
        self.assertTrue(result["parsed"])
        self.assertEqual(result["version"], "2")
        self.assertEqual(result["item_count"], 1)
        item = result["items"][0]
        self.assertEqual(item["Title"], "DS00B001")
        self.assertEqual(item["Description"], "Example description")
        self.assertEqual(item["Category"], "GemeindebriefDruckerei")
        self.assertEqual(item["Keywords"], "")
        self.assertEqual(item["Type"], "1")
        self.assertEqual(item["InsertGallery"], "4")
        self.assertEqual(item["ShowInGallery"], "1")
        self.assertEqual(item["Filename"], "DS00B001")

    def test_parse_bbstoreinfo14_windows_1252(self):
        xml = '''<?xml version="1.0"?>
<BBStore version="2"><BBItems><Item>
<Title>Test</Title><Description>große Fläche</Description>
</Item></BBItems></BBStore>'''.encode("windows-1252")
        result = parse_bbstoreinfo14(xml)
        self.assertTrue(result["parsed"])
        self.assertEqual(result["items"][0]["Description"], "große Fläche")


if __name__ == "__main__":
    unittest.main()
