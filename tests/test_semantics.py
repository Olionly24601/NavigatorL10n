import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestSemanticSafety(unittest.TestCase):

    def test_internal_action_is_not_translated(self):
        path = ROOT / "patches" / "2.7.1.json"

        config = json.loads(
            path.read_text(encoding="utf-8")
        )

        unsafe = [
            f"{entry['path']} / {rule['id']}"
            for entry in config["files"]
            for rule in entry["rules"]
            if "result.action =" in rule["original"]
        ]

        self.assertEqual(
            unsafe,
            [],
            f"发现内部操作标识翻译：{unsafe}",
        )


if __name__ == "__main__":
    unittest.main()