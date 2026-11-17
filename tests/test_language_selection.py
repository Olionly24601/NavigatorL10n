import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import build_rules


class TestLanguageSelection(unittest.TestCase):
    def test_default_language(self):
        config, locale = build_rules.load("2.7.1")
        self.assertEqual(config["version"], "2.7.1")
        self.assertEqual(locale["language"], "zh_CN")

    def test_explicit_chinese(self):
        _, locale = build_rules.load("2.7.4", "zh_CN")
        self.assertEqual(locale["language"], "zh_CN")

    def test_unknown_language(self):
        with self.assertRaisesRegex(ValueError, "不支持的语言"):
            build_rules.load("2.7.1", "../zh_CN")

    def test_japanese_file_selection(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "ja_JP.json").write_text(
                json.dumps({
                    "language": "ja_JP",
                    "messages": {},
                }),
                encoding="utf-8",
            )

            with patch.object(build_rules, "LOCALES", folder):
                config, locale = build_rules.load("2.7.1", "ja_JP")

            self.assertEqual(locale["language"], "ja_JP")
            with self.assertRaisesRegex(ValueError, "缺少翻译"):
                build_rules.validate(config, locale)

    def test_mismatched_language_identifier(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "ja_JP.json").write_text(
                json.dumps({
                    "language": "zh_CN",
                    "messages": {},
                }),
                encoding="utf-8",
            )

            with patch.object(build_rules, "LOCALES", folder):
                with self.assertRaisesRegex(ValueError, "语言包标识不一致"):
                    build_rules.load("2.7.1", "ja_JP")


if __name__ == "__main__":
    unittest.main()