import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ("2.7.1", "2.7.4")


class TestSemanticSafety(unittest.TestCase):

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
        cls.messages = json.loads(
            (ROOT / "locales" / "zh_CN.json").read_text(
                encoding="utf-8"
            )
        )["messages"]

    def test_account_link_targets_unchanged(self):
        path = "widgets/dialogs/login/account_dialogs.py"
        pattern = r"navigator://[^\"']+"

        for version, config in self.configs.items():
            entry = next(
                item for item in config["files"] if item["path"] == path
            )
            for rule in entry["rules"]:
                original = rule["original"]
                if "navigator://" not in original:
                    continue

                rendered = rule["template"].format(
                    text=json.dumps(
                        self.messages[rule["id"]], ensure_ascii=False
                    )
                )
                with self.subTest(version=version, rule=rule["id"]):
                    self.assertEqual(
                        re.findall(pattern, original),
                        re.findall(pattern, rendered),
                    )

    def test_package_filter_mapping(self):
        mapping = self.messages["packages.filter_labels"]
        self.assertEqual(len(mapping), len(set(mapping.values())))

        for version, config in self.configs.items():
            locations = {
                item["path"]
                for item in config["files"]
                for rule in item["rules"]
                if rule["id"] == "packages.filter_labels"
            }
            with self.subTest(version=version):
                self.assertEqual(
                    locations,
                    {
                        "widgets/manager/packages.py",
                        "widgets/manager/table.py",
                    },
                )


    def test_about_description_language_neutral(self):
        translated = self.messages["batch8.about_description"]

        for version, config in self.configs.items():
            rule = next(
                rule
                for entry in config["files"]
                if entry["path"] == "widgets/dialogs/about.py"
                for rule in entry["rules"]
                if rule["id"] == "batch8.about_description"
            )

            with self.subTest(version=version):
                self.assertNotRegex(
                    rule["template"],
                    r"[\u3400-\u9fff]",
                )

                rendered = rule["template"].format(
                    text=json.dumps(translated, ensure_ascii=False)
                )

                description = eval(
                    rendered,
                    {
                        "__about__": SimpleNamespace(
                            __version__=version
                        )
                    },
                )

                self.assertIn(
                    f"Anaconda Navigator {version}",
                    description,
                )

                self.assertIn(translated, description)

                self.assertEqual(
                    description.count("由 Anaconda 创建"),
                    1,
                )


if __name__ == "__main__":
    unittest.main()
