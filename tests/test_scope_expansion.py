import ast
import json
import re
import string
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT = Path(__file__).resolve().parents[1]
VERSIONS = ("2.7.1", "2.7.4")
LANGUAGES = ("zh_CN", "ja_JP")


class TestScopeExpansion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = {
            version: json.loads((PROJECT / "patches" / f"{version}.json").read_text(encoding="utf-8"))
            for version in VERSIONS
        }
        cls.locales = {
            lang: json.loads((PROJECT / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
            for lang in LANGUAGES
        }
        cls.by_id = {
            version: {
                rule["id"]: rule
                for group in cls.rules[version]["files"]
                for rule in group["rules"]
            }
            for version in VERSIONS
        }

    def test_core_status_and_dialog_rules_present(self):
        shared = {
            "status.initializing", "status.loading_packages", "status.launching_app",
            "env.remove_confirm", "env.remove_title", "login.form_username",
            "login.form_password", "login.form_submit", "offline.title",
            "errors.app_launch_title", "errors.ssl_certificate_missing",
            "errors.broken_config", "channels.duplicate", "status.refreshing_apps",
            "whats_new.title",
        }
        for version in VERSIONS:
            with self.subTest(version=version):
                self.assertFalse(shared - set(self.by_id[version]))

    def test_loading_status_preserves_prefix(self):
        sample = SimpleNamespace(current_prefix=r"D:\Apps\Anaconda3")
        for version in VERSIONS:
            rule = self.by_id[version]["status.loading_packages"]
            for lang in LANGUAGES:
                text = self.locales[lang]["messages"]["status.loading_packages"]
                expression = rule["template"].format(text=json.dumps(text, ensure_ascii=False))
                rendered = eval(expression, {"self": sample})
                with self.subTest(version=version, lang=lang):
                    self.assertIn(sample.current_prefix, rendered)
                    self.assertNotIn("Loading packages", rendered)
                    self.assertIn("<b>", rendered)

    def test_new_dynamic_messages_keep_expression_fields(self):
        keys = (
            "status.loading_packages", "status.launching_app", "status.installing_app",
            "errors.app_launch_message", "errors.unavailable_environment",
            "errors.ssl_certificate_missing", "cloud.signed_in_as",
        )
        formatter = string.Formatter()
        for key in keys:
            a = self.locales["zh_CN"]["messages"][key]
            b = self.locales["ja_JP"]["messages"][key]
            ca = sorted(field for _, field, _, _ in formatter.parse(a) if field is not None)
            cb = sorted(field for _, field, _, _ in formatter.parse(b) if field is not None)
            with self.subTest(key=key):
                self.assertEqual(ca, cb)
                self.assertEqual(re.findall(r"</?b>", a), re.findall(r"</?b>", b))

    def test_fstring_templates_compile_for_both_languages(self):
        for version in VERSIONS:
            for rule in self.by_id[version].values():
                if rule["template"] != "f{text}":
                    continue
                for lang in LANGUAGES:
                    value = self.locales[lang]["messages"][rule["id"]]
                    code = rule["template"].format(text=json.dumps(value, ensure_ascii=False))
                    with self.subTest(version=version, lang=lang, rule=rule["id"]):
                        ast.parse(code, mode="eval")

    def test_tos_is_supported_in_both_versions(self):
        expected = {
            version: next(item["rules"] for item in self.rules[version]["files"]
                          if item["path"] == "widgets/dialogs/conda_tos.py")
            for version in VERSIONS
        }
        self.assertEqual(expected["2.7.1"], expected["2.7.4"])
        self.assertGreaterEqual(len(expected["2.7.1"]), 10)


if __name__ == "__main__":
    unittest.main()
