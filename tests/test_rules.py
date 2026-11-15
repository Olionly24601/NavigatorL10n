import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestTranslationRules(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rules = json.loads(
            (ROOT / "patches" / "2.7.1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.locale = json.loads(
            (ROOT / "locales" / "zh_CN.json").read_text(
                encoding="utf-8"
            )
        )

    def test_version(self):
        self.assertEqual(self.rules["version"], "2.7.1")

    def test_language(self):
        self.assertEqual(self.locale["language"], "zh_CN")

    def test_unique_paths(self):
        paths = [item["path"] for item in self.rules["files"]]
        self.assertEqual(len(paths), len(set(paths)))

    def test_unique_ids(self):
        ids = [
            rule["id"]
            for entry in self.rules["files"]
            for rule in entry["rules"]
        ]
        self.assertEqual({k: ids.count(k) for k in set(ids) if ids.count(k) > 1}, {'packages.filter_labels': 2})

    def test_translation_completeness(self):
        messages = self.locale["messages"]

        for entry in self.rules["files"]:
            for rule in entry["rules"]:
                with self.subTest(rule=rule["id"]):
                    self.assertIn(rule["id"], messages)

    def test_template_rendering(self):
        messages = self.locale["messages"]

        for entry in self.rules["files"]:
            for rule in entry["rules"]:
                with self.subTest(rule=rule["id"]):
                    translated = json.dumps(
                        messages[rule["id"]],
                        ensure_ascii=False,
                    )

                    output = rule["template"].format(
                        text=translated
                    )

                    self.assertIsInstance(output, str)
                    self.assertTrue(output)

    def test_positive_match_counts(self):
        for entry in self.rules["files"]:
            for rule in entry["rules"]:
                with self.subTest(rule=rule["id"]):
                    self.assertGreater(rule["count"], 0)


if __name__ == "__main__":
    unittest.main()
