import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestSemanticSafety(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(
            (ROOT / "patches" / "2.7.1.json").read_text(
                encoding="utf-8"
            )
        )

        cls.messages = json.loads(
            (ROOT / "locales" / "zh_CN.json").read_text(
                encoding="utf-8"
            )
        )["messages"]

    def test_account_link_targets_unchanged(self):
        path = "widgets/dialogs/login/account_dialogs.py"

        entry = next(
            item
            for item in self.config["files"]
            if item["path"] == path
        )

        for rule in entry["rules"]:
            original = rule["original"]

            if "navigator://" not in original:
                continue

            rendered = rule["template"].format(
                text=json.dumps(
                    self.messages[rule["id"]],
                    ensure_ascii=False,
                )
            )

            pattern = r"navigator://[^\"']+"

            before = re.findall(pattern, original)
            after = re.findall(pattern, rendered)

            with self.subTest(rule=rule["id"]):
                self.assertEqual(before, after)

    def test_package_filter_mapping(self):
        mapping = self.messages["packages.filter_labels"]

        self.assertEqual(
            len(mapping.values()),
            len(set(mapping.values())),
        )

        locations = [
            item["path"]
            for item in self.config["files"]
            for rule in item["rules"]
            if rule["id"] == "packages.filter_labels"
        ]

        self.assertEqual(
            set(locations),
            {
                "widgets/manager/packages.py",
                "widgets/manager/table.py",
            },
        )


if __name__ == "__main__":
    unittest.main()