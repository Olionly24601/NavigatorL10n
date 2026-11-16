import json
import unittest
from pathlib import Path

from tools import build_rules


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ("2.7.1", "2.7.4")


class TestTranslationRules(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.configs = {
            version: json.loads(
                (ROOT / "patches" / f"{version}.json").read_text(
                    encoding="utf-8"
                )
            )
            for version in VERSIONS
        }
        cls.locale = json.loads(
            (ROOT / "locales" / "zh_CN.json").read_text(
                encoding="utf-8"
            )
        )

    def test_versions(self):
        self.assertEqual(
            set(build_rules.available_versions()), set(VERSIONS)
        )
        for version, config in self.configs.items():
            with self.subTest(version=version):
                self.assertEqual(config["version"], version)

    def test_language(self):
        self.assertEqual(self.locale["language"], "zh_CN")

    def test_unique_paths(self):
        for version, config in self.configs.items():
            paths = [item["path"] for item in config["files"]]
            with self.subTest(version=version):
                self.assertEqual(len(paths), len(set(paths)))

    def test_rule_ids_unique_within_each_file(self):
        for version, config in self.configs.items():
            for entry in config["files"]:
                ids = [rule["id"] for rule in entry["rules"]]
                with self.subTest(version=version, path=entry["path"]):
                    self.assertEqual(len(ids), len(set(ids)))

    def test_translation_completeness(self):
        messages = self.locale["messages"]
        for version, config in self.configs.items():
            for entry in config["files"]:
                for rule in entry["rules"]:
                    with self.subTest(version=version, rule=rule["id"]):
                        self.assertIn(rule["id"], messages)

    def test_template_rendering(self):
        messages = self.locale["messages"]
        for version, config in self.configs.items():
            for entry in config["files"]:
                for rule in entry["rules"]:
                    with self.subTest(version=version, rule=rule["id"]):
                        translated = json.dumps(
                            messages[rule["id"]], ensure_ascii=False
                        )
                        output = rule["template"].format(text=translated)
                        self.assertIsInstance(output, str)
                        self.assertTrue(output)

    def test_positive_match_counts(self):
        for version, config in self.configs.items():
            for entry in config["files"]:
                for rule in entry["rules"]:
                    with self.subTest(version=version, rule=rule["id"]):
                        self.assertIs(type(rule["count"]), int)
                        self.assertGreater(rule["count"], 0)

    def test_shared_locale_references(self):
        results = build_rules.validate_all(
            list(self.configs.values()), self.locale
        )
        self.assertEqual(set(results), set(VERSIONS))
        self.assertEqual(results["2.7.1"], (27, 223, 222))
        self.assertEqual(results["2.7.4"], (31, 256, 255))

    def test_274_preserves_existing_271_rules(self):
        def indexed(config):
            return {
                (entry["path"], rule["id"]): rule
                for entry in config["files"]
                for rule in entry["rules"]
            }

        original = indexed(self.configs["2.7.1"])
        updated = indexed(self.configs["2.7.4"])
        for key, rule in original.items():
            with self.subTest(path=key[0], rule=key[1]):
                self.assertEqual(updated.get(key), rule)


if __name__ == "__main__":
    unittest.main()
