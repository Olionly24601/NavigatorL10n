import json
import re
import string
import unittest
from collections import Counter
from pathlib import Path

from core.translation_validation import validate_messages
from tools import build_rules


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ("2.7.1", "2.7.4")


class TestJapaneseLocale(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.japanese = json.loads(
            (ROOT / "locales" / "ja_JP.json").read_text(encoding="utf-8")
        )
        cls.chinese = json.loads(
            (ROOT / "locales" / "zh_CN.json").read_text(encoding="utf-8")
        )
        cls.configs = [
            json.loads(
                (ROOT / "patches" / f"{version}.json").read_text(encoding="utf-8")
            )
            for version in VERSIONS
        ]

    def test_language_and_structure(self):
        self.assertEqual(self.japanese["language"], "ja_JP")
        self.assertEqual(set(self.japanese["messages"]), set(self.chinese["messages"]))
        validate_messages(self.japanese["messages"])
        for key, chinese in self.chinese["messages"].items():
            japanese = self.japanese["messages"][key]
            with self.subTest(key=key):
                self.assertIs(type(japanese), type(chinese))
                if isinstance(chinese, dict):
                    self.assertEqual(list(japanese), list(chinese))
                if isinstance(chinese, list):
                    self.assertEqual(len(japanese), len(chinese))

    def test_both_versions_references(self):
        results = build_rules.validate_all(self.configs, self.japanese)
        self.assertEqual(results["2.7.1"], (44, 323, 320))
        self.assertEqual(results["2.7.4"], (44, 341, 338))

    def test_placeholders_and_markup(self):
        def values(value):
            if isinstance(value, dict):
                return value.values()
            if isinstance(value, list):
                return value
            return [value]

        formatter = string.Formatter()
        tag_pattern = re.compile(r"<(/?(?:a|b|br|i|p|span))(?=\s|>)")
        for key, chinese in self.chinese["messages"].items():
            japanese = self.japanese["messages"][key]
            for index, (before, after) in enumerate(zip(values(chinese), values(japanese))):
                with self.subTest(key=key, index=index):
                    original_fields = Counter(
                        field for _, field, _, _ in formatter.parse(before)
                        if field is not None
                    )
                    japanese_fields = Counter(
                        field for _, field, _, _ in formatter.parse(after)
                        if field is not None
                    )
                    self.assertEqual(japanese_fields, original_fields)
                    self.assertEqual(tag_pattern.findall(after), tag_pattern.findall(before))

    def test_template_rendering(self):
        messages = self.japanese["messages"]
        for config in self.configs:
            for entry in config["files"]:
                for rule in entry["rules"]:
                    with self.subTest(version=config["version"], key=rule["id"]):
                        text = json.dumps(messages[rule["id"]], ensure_ascii=False)
                        rendered = rule["template"].format(text=text)
                        self.assertTrue(rendered)

    def test_runtime_format_values(self):
        messages = self.japanese["messages"]
        self.assertIn("Yuki", messages["account.connected_user"].format(username="Yuki"))
        updated = messages["update.notice"].format(version="2.7.4", extra_text="")
        self.assertIn("2.7.4", updated)
        self.assertIn("JupyterLab", messages["welcome.assistant"])
        self.assertIn("Spyder", messages["env.open_with"].format(name="Spyder"))


if __name__ == "__main__":
    unittest.main()
