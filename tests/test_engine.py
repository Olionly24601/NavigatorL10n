import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from core import engine


class TestEngine(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.project = Path(self.temp.name) / "NavigatorZH"
        self.prefix = Path(self.temp.name) / "Anaconda3"
        self.source = (
            self.prefix / "Lib" / "site-packages"
            / "anaconda_navigator"
        )

        self.source.mkdir(parents=True)
        (self.source / "__init__.py").write_text(
            "", encoding="utf-8"
        )

        self.originals = {
            "widgets/dialogs/quit.py": b"title = 'Hello'\n",
            "widgets/tabs/home.py": b"button = 'Hello'\n",
        }

        for relative, content in self.originals.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        rules = {
            "version": "2.7.1",
            "files": [
                {
                    "path": relative,
                    "rules": [
                        {
                            "id": "common.greeting",
                            "original": "'Hello'",
                            "template": "{text}",
                            "count": 1,
                        }
                    ],
                }
                for relative in self.originals
            ],
        }

        locale = {
            "language": "zh_CN",
            "messages": {
                "common.greeting": "你好"
            },
        }

        patches = self.project / "patches"
        locales = self.project / "locales"

        patches.mkdir(parents=True)
        locales.mkdir(parents=True)

        (patches / "2.7.1.json").write_text(
            json.dumps(rules, ensure_ascii=False),
            encoding="utf-8",
        )

        (locales / "zh_CN.json").write_text(
            json.dumps(locale, ensure_ascii=False),
            encoding="utf-8",
        )

        state = self.project / "state"

        replacements = {
            "PROJECT": self.project,
            "STATE": state,
            "BACKUPS": state / "backups",
            "MANIFEST": state / "manifest.json",
        }

        for key, value in replacements.items():
            helper = patch.object(engine, key, value)
            helper.start()
            self.addCleanup(helper.stop)

        helper = patch.object(
            engine,
            "installation",
            return_value=(
                self.prefix,
                "2.7.1",
                self.source.resolve(),
            ),
        )

        helper.start()
        self.addCleanup(helper.stop)

    def execute(self, operation):
        with redirect_stdout(io.StringIO()):
            operation()

    def test_check_does_not_modify_files(self):
        self.execute(engine.check)

        for relative, original in self.originals.items():
            self.assertEqual(
                (self.source / relative).read_bytes(),
                original,
            )

        self.assertFalse(engine.MANIFEST.exists())

    def test_apply_and_restore(self):
        self.execute(engine.apply)

        self.assertTrue(engine.MANIFEST.exists())

        for relative in self.originals:
            content = (self.source / relative).read_text(
                encoding="utf-8"
            )
            self.assertIn("你好", content)

        self.execute(engine.restore)

        self.assertFalse(engine.MANIFEST.exists())

        for relative, original in self.originals.items():
            self.assertEqual(
                (self.source / relative).read_bytes(),
                original,
            )

    def test_repeated_installation_is_rejected(self):
        self.execute(engine.apply)

        with self.assertRaises(RuntimeError):
            self.execute(engine.apply)

        self.execute(engine.restore)

    def test_restore_rejects_external_changes(self):
        self.execute(engine.apply)

        target = self.source / "widgets/dialogs/quit.py"
        changed = b"title = 'Externally changed'\n"

        target.write_bytes(changed)

        with self.assertRaises(RuntimeError):
            self.execute(engine.restore)

        self.assertEqual(target.read_bytes(), changed)
        self.assertTrue(engine.MANIFEST.exists())

    def test_status_recognizes_patched_files(self):
        self.execute(engine.apply)

        output = io.StringIO()

        with redirect_stdout(output):
            engine.status()

        self.assertIn("已汉化", output.getvalue())

        self.execute(engine.restore)


if __name__ == "__main__":
    unittest.main()