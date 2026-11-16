import json
import re
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
