import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools import build_rules


class TestRuleBuilder(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.relative = "widgets/sample.py"

        self.source = (
            "label = 'Hello'\n"
            "second = 'World'\n"
        )

        self.config = {
            "version": "2.7.1",
            "files": [
                {
                    "path": self.relative,
                    "rules": [
                        {
                            "id": "sample.hello",
                            "original": "label = 'Hello'",
                            "template": "label = {text}",
                            "count": 1,
                        }
                    ],
                }
            ],
        }

        self.locale = {
            "language": "zh_CN",
            "messages": {
                "sample.hello": "你好",
            },
        }

        helper = patch.object(
            build_rules,
            "originals",
            return_value=(
                self.root,
                {self.relative: self.source},
            ),
        )

        helper.start()
        self.addCleanup(helper.stop)

    def write_spec(self, rules):
        path = self.root / "rules.json"

        path.write_text(
            json.dumps(
                {"rules": rules},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return path

    def existing_rule(self):
        return {
            "path": self.relative,
            "id": "sample.hello",
            "original": "label = 'Hello'",
            "template": "label = {text}",
            "count": 1,
            "translation": "你好",
        }

    def new_rule(self):
        return {
            "path": self.relative,
            "id": "sample.second",
            "original": "second = 'World'",
            "template": "second = {text}",
            "count": 1,
            "translation": "世界",
        }

    def test_existing_rule_is_skipped(self):
        spec = self.write_spec([
            self.existing_rule(),
        ])

        before_config = copy.deepcopy(self.config)
        before_locale = copy.deepcopy(self.locale)

        result = build_rules.add(
            spec,
            self.config,
            self.locale,
        )

        self.assertEqual(result, (0, 1))
        self.assertEqual(self.config, before_config)
        self.assertEqual(self.locale, before_locale)

    def test_mixed_batch_adds_only_missing(self):
        spec = self.write_spec([
            self.existing_rule(),
            self.new_rule(),
        ])

        result = build_rules.add(
            spec,
            self.config,
            self.locale,
        )

        self.assertEqual(result, (1, 1))
        self.assertEqual(
            len(self.config["files"][0]["rules"]),
            2,
        )

        self.assertEqual(
            self.locale["messages"]["sample.second"],
            "世界",
        )

        repeated = build_rules.add(
            spec,
            self.config,
            self.locale,
        )

        self.assertEqual(repeated, (0, 2))

    def test_conflicting_translation_is_rejected(self):
        rule = self.existing_rule()
        rule["translation"] = "您好"

        spec = self.write_spec([rule])

        with self.assertRaisesRegex(
            ValueError,
            "翻译内容不一致",
        ):
            build_rules.add(
                spec,
                self.config,
                self.locale,
            )

    def test_conflicting_rule_id_is_rejected(self):
        rule = self.existing_rule()
        rule["template"] = "label = str({text})"

        spec = self.write_spec([rule])

        with self.assertRaisesRegex(
            ValueError,
            "规则 ID 冲突",
        ):
            build_rules.add(
                spec,
                self.config,
                self.locale,
            )

    def test_shared_id_across_files(self):
        relative = "widgets/other.py"
        path = self.root / relative

        path.parent.mkdir(parents=True)
        path.write_text(
            "name = 'Hello'\n",
            encoding="utf-8",
        )

        spec = self.write_spec([
            {
                "path": relative,
                "id": "sample.hello",
                "original": "name = 'Hello'",
                "template": "name = {text}",
                "count": 1,
                "translation": "你好",
            }
        ])

        result = build_rules.add(
            spec,
            self.config,
            self.locale,
        )

        self.assertEqual(result, (1, 0))
        self.assertEqual(len(self.config["files"]), 2)
        self.assertEqual(len(self.locale["messages"]), 1)

    def test_shared_locale_allows_version_specific_keys(self):
        newer = copy.deepcopy(self.config)
        newer["version"] = "2.7.4"
        newer["files"][0]["rules"].append({
            "id": "sample.only_274",
            "original": "second = 'World'",
            "template": "second = {text}",
            "count": 1,
        })

        locale = copy.deepcopy(self.locale)
        locale["messages"]["sample.only_274"] = "世界"

        build_rules.validate(self.config, locale)
        results = build_rules.validate_all([self.config, newer], locale)
        self.assertEqual(results["2.7.1"], (1, 1, 1))
        self.assertEqual(results["2.7.4"], (1, 2, 2))

    def test_shared_locale_rejects_orphaned_keys(self):
        locale = copy.deepcopy(self.locale)
        locale["messages"]["sample.unused"] = "未使用"
        with self.assertRaisesRegex(ValueError, "未引用的条目"):
            build_rules.validate_all([self.config], locale)

    def test_load_selects_installed_version(self):
        with patch.object(
            build_rules.engine,
            "installation",
            return_value=(self.root, "2.7.4", self.root),
        ):
            config, _ = build_rules.load()
        self.assertEqual(config["version"], "2.7.4")

    def test_save_only_updates_selected_version(self):
        patch_dir = self.root / "patches"
        patch_dir.mkdir()
        locale_path = self.root / "zh_CN.json"
        files = {}
        for version in ("2.7.1", "2.7.4"):
            target = patch_dir / f"{version}.json"
            original = dict(self.config, version=version)
            target.write_text(json.dumps(original), encoding="utf-8")
            files[version] = target
        locale_path.write_text(json.dumps(self.locale), encoding="utf-8")

        older_bytes = files["2.7.1"].read_bytes()
        newer = copy.deepcopy(self.config)
        newer["version"] = "2.7.4"
        newer["files"][0]["rules"].append({
            "id": "sample.second",
            "original": "second = 'World'",
            "template": "second = {text}",
            "count": 1,
        })

        with (
            patch.object(build_rules, "PATCHES", patch_dir),
            patch.object(build_rules, "LOCALE", locale_path),
            patch.object(build_rules, "PROJECT", self.root),
        ):
            build_rules.save(newer, self.locale)

        self.assertEqual(files["2.7.1"].read_bytes(), older_bytes)
        self.assertEqual(
            json.loads(files["2.7.4"].read_text(encoding="utf-8")),
            newer,
        )

    def test_validate_command_does_not_require_navigator(self):
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["build_rules.py", "validate"]),
            patch.object(
                build_rules.engine,
                "installation",
                side_effect=AssertionError("不应检查本地 Navigator"),
            ),
            redirect_stdout(output),
        ):
            build_rules.main()

        self.assertIn("Navigator 2.7.1", output.getvalue())
        self.assertIn("Navigator 2.7.4", output.getvalue())
        self.assertIn("共享语言包无未引用条目", output.getvalue())

    def test_explicit_version_validate_does_not_require_navigator(self):
        output = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                ["build_rules.py", "validate", "--version", "2.7.4"],
            ),
            patch.object(
                build_rules.engine,
                "installation",
                side_effect=AssertionError("不应检查本地 Navigator"),
            ),
            redirect_stdout(output),
        ):
            build_rules.main()

        self.assertNotIn("Navigator 2.7.1", output.getvalue())
        self.assertIn("Navigator 2.7.4", output.getvalue())

    def test_duplicate_command_does_not_save(self):
        with (
            patch.object(
                build_rules,
                "load",
                return_value=(self.config, self.locale),
            ),
            patch.object(
                build_rules,
                "add",
                return_value=(0, 1),
            ),
            patch.object(build_rules, "save") as mock_save,
            patch.object(
                sys,
                "argv",
                ["build_rules.py", "add", "existing.json"],
            ),
            redirect_stdout(io.StringIO()),
        ):
            build_rules.main()

        mock_save.assert_not_called()


if __name__ == "__main__":
    unittest.main()