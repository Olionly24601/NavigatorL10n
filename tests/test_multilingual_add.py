import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from tools import build_rules


class TestMultilingualAdd(unittest.TestCase):
    def setUp(self):
        self.config = {
            "version": "2.7.4",
            "files": [{
                "path": "sample.py",
                "rules": [{
                    "id": "label.hello",
                    "original": "'Hello'",
                    "template": "{text}",
                    "count": 1,
                }],
            }],
        }

        self.zh = {
            "language": "zh_CN",
            "messages": {"label.hello": "你好"},
        }

        self.ja = {
            "language": "ja_JP",
            "messages": {"label.hello": "こんにちは"},
        }

        self.sources = {
            "sample.py": "first = 'Hello'\nsecond = 'World'\n",
        }

        self.source_patch = patch.object(
            build_rules,
            "originals",
            return_value=(Path("/unused"), self.sources),
        )
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)

    def draft(self, japanese="世界"):
        item = {
            "id": "label.world",
            "path": "sample.py",
            "original": "'World'",
            "template": "{text}",
            "count": 1,
            "translation": "世界",
        }

        if japanese is not None:
            item["translations"] = {"ja_JP": japanese}

        return item

    def submit(self, rules, other_locales=None):
        if other_locales is None:
            other_locales = {"ja_JP": self.ja}

        with patch.object(
            build_rules.engine,
            "read_json",
            return_value={"rules": rules},
        ):
            return build_rules.add(
                Path("unused.json"),
                self.config,
                self.zh,
                other_locales,
            )

    def test_add_two_languages(self):
        added, skipped = self.submit([self.draft()])

        self.assertEqual((added, skipped), (1, 0))
        self.assertEqual(
            self.zh["messages"]["label.world"], "世界"
        )
        self.assertEqual(
            self.ja["messages"]["label.world"], "世界"
        )
        self.assertEqual(
            len(self.config["files"][0]["rules"]), 2
        )

    def test_missing_japanese_rejected(self):
        original = deepcopy(
            (self.config, self.zh, self.ja)
        )

        with self.assertRaisesRegex(
            ValueError, "新增规则缺少翻译"
        ):
            self.submit([self.draft(japanese=None)])

        self.assertEqual(
            (self.config, self.zh, self.ja), original
        )

    def test_conflicting_japanese_rejected(self):
        self.ja["messages"]["label.world"] = "既存の翻訳"

        original = deepcopy(
            (self.config, self.zh, self.ja)
        )

        with self.assertRaisesRegex(
            ValueError, "共享翻译 ID 内容冲突"
        ):
            self.submit([self.draft()])

        self.assertEqual(
            (self.config, self.zh, self.ja), original
        )

    def test_existing_legacy_draft_skipped(self):
        item = {
            "id": "label.hello",
            "path": "sample.py",
            "original": "'Hello'",
            "template": "{text}",
            "count": 1,
            "translation": "你好",
        }

        added, skipped = self.submit([item])

        self.assertEqual((added, skipped), (0, 1))

    def test_batch_failure_preserves_all_data(self):
        original = deepcopy(
            (self.config, self.zh, self.ja)
        )

        with self.assertRaisesRegex(
            ValueError, "新增规则缺少翻译"
        ):
            self.submit([
                self.draft(),
                {
                    "id": "label.missing",
                    "path": "sample.py",
                    "original": "'Missing'",
                    "template": "{text}",
                    "count": 1,
                    "translation": "缺失",
                },
            ])

        self.assertEqual(
            (self.config, self.zh, self.ja), original
        )

    def test_legacy_single_language_compatibility(self):
        added, skipped = self.submit(
            [self.draft(japanese=None)],
            other_locales={},
        )

        self.assertEqual((added, skipped), (1, 0))
        self.assertIn("label.world", self.zh["messages"])
        self.assertNotIn("label.world", self.ja["messages"])


if __name__ == "__main__":
    unittest.main()