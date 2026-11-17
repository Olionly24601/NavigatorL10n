import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import engine
from tools import build_rules, rule_store


class TestMultilingualSave(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)

        self.paths = {
            "rules": self.root / "patches/2.7.4.json",
            "zh": self.root / "locales/zh_CN.json",
            "ja": self.root / "locales/ja_JP.json",
        }

        self.config = {
            "version": "2.7.4",
            "files": [{
                "path": "sample.py",
                "rules": [{
                    "id": "hello",
                    "original": "'Hello'",
                    "template": "{text}",
                    "count": 1,
                }],
            }],
        }

        self.zh = {
            "language": "zh_CN",
            "messages": {"hello": "你好"},
        }

        self.ja = {
            "language": "ja_JP",
            "messages": {"hello": "こんにちは"},
        }

        values = {
            "rules": self.config,
            "zh": self.zh,
            "ja": self.ja,
        }

        for name, path in self.paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(values[name], ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )

        self.originals = {
            path: path.read_bytes()
            for path in self.paths.values()
        }

        for attr, value in (
            ("PROJECT", self.root),
            ("PATCHES", self.root / "patches"),
            ("LOCALES", self.root / "locales"),
        ):
            patcher = patch.object(build_rules, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.config["files"][0]["rules"][0]["count"] = 2
        self.zh["messages"]["hello"] = "您好"
        self.ja["messages"]["hello"] = "やあ"

    def assert_originals(self):
        for path, original in self.originals.items():
            self.assertEqual(path.read_bytes(), original)

    def test_save_three_files(self):
        build_rules.save(
            self.config,
            self.zh,
            {"ja_JP": self.ja},
        )

        for name, expected in (
            ("rules", self.config),
            ("zh", self.zh),
            ("ja", self.ja),
        ):
            actual = json.loads(
                self.paths[name].read_text(encoding="utf-8")
            )
            self.assertEqual(actual, expected)

    def test_missing_language_rejected(self):
        with self.assertRaisesRegex(
            ValueError, "正式保存缺少语言包"
        ):
            build_rules.save(self.config, self.zh)

        self.assert_originals()

    def test_failure_restores_all_files(self):
        original_write = engine.atomic_write
        japanese_path = self.paths["ja"]

        def failing_write(path, data, **kwargs):
            if (
                Path(path) == japanese_path
                and data != self.originals[japanese_path]
            ):
                raise OSError("simulated failure")

            return original_write(path, data, **kwargs)

        with patch.object(
            rule_store.engine,
            "atomic_write",
            side_effect=failing_write,
        ):
            with self.assertRaises(OSError):
                build_rules.save(
                    self.config,
                    self.zh,
                    {"ja_JP": self.ja},
                )

        self.assert_originals()

        pending = (
            self.root
            / "state/rule_transactions/pending.json"
        )

        self.assertFalse(pending.exists())


    def test_external_edit_after_load_rejects_save(self):
        snapshot = {}
        config, zh = build_rules.load_snapshot(
            "2.7.4", "zh_CN", snapshot
        )
        _, ja = build_rules.load_snapshot(
            "2.7.4", "ja_JP", snapshot
        )

        config["files"][0]["rules"][0]["count"] = 2
        zh["messages"]["hello"] = "您好"
        ja["messages"]["hello"] = "やあ"

        edited = self.paths["ja"]
        edited.write_text(
            json.dumps({
                "language": "ja_JP",
                "messages": {"hello": "エディターで修正"},
            }, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RuntimeError, "源文件在读取后已修改"):
            build_rules.save(
                config,
                zh,
                {"ja_JP": ja},
                expected_hashes=snapshot,
            )

        self.assertEqual(self.paths["rules"].read_bytes(), self.originals[self.paths["rules"]])
        self.assertEqual(self.paths["zh"].read_bytes(), self.originals[self.paths["zh"]])
        self.assertIn("エディターで修正", edited.read_text(encoding="utf-8"))
        self.assertFalse((self.root / "state/rule_transactions/pending.json").exists())

    def test_rule_changed_between_language_loads_is_rejected(self):
        snapshot = {}
        build_rules.load_snapshot("2.7.4", "zh_CN", snapshot)
        self.paths["rules"].write_bytes(b"{}")

        with self.assertRaisesRegex(RuntimeError, "规则维护期间源文件发生变化"):
            build_rules.load_snapshot("2.7.4", "ja_JP", snapshot)

if __name__ == "__main__":
    unittest.main()
