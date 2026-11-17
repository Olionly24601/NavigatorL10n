import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import engine
from core.translation_validation import validate_messages
from tools import build_rules


class TestLocaleValidation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_dir = self.root / "navigator"
        self.source_dir.mkdir()
        (self.source_dir / "sample.py").write_text(
            "label = 'Hello'\nsecond = 'World'\n", encoding="utf-8",
        )
        self.config = {
            "version": "2.7.4",
            "files": [{"path": "sample.py", "rules": [{
                "id": "sample.hello", "original": "'Hello'",
                "template": "{text}", "count": 1,
            }]}],
        }
        self.zh = {"language": "zh_CN", "messages": {"sample.hello": "你好"}}
        self.ja = {"language": "ja_JP", "messages": {"sample.hello": "こんにちは"}}

    def test_simple_and_structured_values(self):
        validate_messages({
            "sample.hello": "こんにちは",
            "packages.action_table_headers": ["a", "b", "c", "d", "e"],
            "preferences.action_buttons": {
                "Apply": "適用", "Cancel": "キャンセル",
                "Reset to defaults": "元に戻す",
            },
        })

    def test_null_and_invalid_scalars_rejected(self):
        for invalid in (None, True, 123, [], {}, "", "  "):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    build_rules.validate(
                        self.config,
                        {"language": "ja_JP", "messages": {"sample.hello": invalid}},
                    )

    def test_plain_text_rejects_nonempty_list_or_dict(self):
        for invalid in (
            ["接続ユーザー：{username}"],
            {"label": "接続ユーザー：{username}"},
        ):
            with self.subTest(value=invalid):
                broken = {
                    "language": "ja_JP",
                    "messages": {"sample.hello": invalid},
                }
                with self.assertRaisesRegex(ValueError, "翻译值类型无效"):
                    validate_messages({"account.connected_user": invalid})
                with self.assertRaisesRegex(ValueError, "翻译值类型无效"):
                    build_rules.validate(self.config, broken)
                with self.assertRaisesRegex(ValueError, "翻译值类型无效"):
                    build_rules.verify(
                        self.config, broken,
                        {"sample.py": "label = 'Hello'\nsecond = 'World'\n"},
                    )
                with patch.object(build_rules.rule_store, "save_many") as store:
                    with self.assertRaisesRegex(ValueError, "翻译值类型无效"):
                        build_rules.save(
                            self.config, self.zh, {"ja_JP": broken},
                        )
                store.assert_not_called()

    def test_bad_list_item_and_wrong_number_of_headers(self):
        for value in (["a", "b"], ["a", "b", "c", "d", None]):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_messages({"packages.action_table_headers": value})

    def test_missing_or_extra_internal_button_keys_rejected(self):
        for value in (
            {"Apply": "適用", "Reset to defaults": "元に戻す"},
            {"Apply": "適用", "Cancel": "キャンセル", "Reset to defaults": "戻す", "Extra": "余分"},
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "翻译字典键不一致"):
                    build_rules.validate(self.config, {
                        "language": "ja_JP", "messages": {
                            "sample.hello": "こんにちは", "preferences.action_buttons": value,
                        },
                    })

    def test_nested_invalid_values_rejected(self):
        for value in (["a", None], {"key": None}, {"key": ["nested"]}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_messages({"extra.item": value})

    def test_filter_labels_must_be_reversible(self):
        labels = {
            "Installed": "済", "Not installed": "未", "Updatable": "更新",
            "Selected": "済", "All": "全部",
        }
        with self.assertRaisesRegex(ValueError, "软件包筛选译文重复"):
            validate_messages({"packages.filter_labels": labels})

    def test_verify_rejects_invalid_translation(self):
        broken = {"language": "ja_JP", "messages": {"sample.hello": None}}
        with self.assertRaises(ValueError):
            build_rules.verify(
                self.config, broken, {"sample.py": "label = 'Hello'\n"},
            )

    def test_save_rejects_bad_translation_before_write(self):
        self.ja["messages"]["sample.hello"] = None
        with patch.object(build_rules.rule_store, "save_many") as save_many:
            with self.assertRaises(ValueError):
                build_rules.save(self.config, self.zh, {"ja_JP": self.ja})
        save_many.assert_not_called()

    def test_add_rejects_null_draft_without_mutating_inputs(self):
        spec = self.root / "draft.json"
        spec.write_text(json.dumps({"rules": [{
            "id": "sample.world", "path": "sample.py",
            "original": "'World'", "template": "{text}", "count": 1,
            "translation": "世界", "translations": {"ja_JP": None},
        }]}), encoding="utf-8")
        before = copy.deepcopy((self.config, self.zh, self.ja))
        with patch.object(build_rules, "originals", return_value=(
            self.source_dir, {"sample.py": "label = 'Hello'\nsecond = 'World'\n"},
        )):
            with self.assertRaises(ValueError):
                build_rules.add(spec, self.config, self.zh, {"ja_JP": self.ja})
        self.assertEqual((self.config, self.zh, self.ja), before)

    def test_engine_prepare_rejects_invalid_translation(self):
        project = self.root / "project"
        (project / "patches").mkdir(parents=True)
        (project / "locales").mkdir()
        (project / "patches/2.7.4.json").write_text(
            json.dumps(self.config), encoding="utf-8",
        )
        original = (self.source_dir / "sample.py").read_bytes()
        locale_path = project / "locales/ja_JP.json"
        with (
            patch.object(engine, "PROJECT", project),
            patch.object(engine, "installation", return_value=(
                self.root, "2.7.4", self.source_dir.resolve(),
            )),
        ):
            for invalid in (
                None,
                ["接続ユーザー：{username}"],
                {"label": "接続ユーザー：{username}"},
            ):
                with self.subTest(value=invalid):
                    broken = {
                        "language": "ja_JP",
                        "messages": {"sample.hello": invalid},
                    }
                    locale_path.write_text(
                        json.dumps(broken, ensure_ascii=False), encoding="utf-8",
                    )
                    with self.assertRaises(ValueError):
                        engine.prepare("ja_JP")
                    self.assertEqual(
                        (self.source_dir / "sample.py").read_bytes(), original,
                    )


if __name__ == "__main__":
    unittest.main()
