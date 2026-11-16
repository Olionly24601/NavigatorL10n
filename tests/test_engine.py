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

    def test_separate_conda_environments(self):
        self.execute(engine.apply)

        first_manifest = engine.MANIFEST
        second_prefix = Path(self.temp.name) / "navigatorzh-274"
        second_source = (
            second_prefix / "Lib" / "site-packages"
            / "anaconda_navigator"
        )
        second_source.mkdir(parents=True)
        (second_source / "__init__.py").write_text(
            "", encoding="utf-8"
        )

        for relative, original in self.originals.items():
            target = second_source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original)

        config = json.loads(
            (self.project / "patches" / "2.7.1.json").read_text(
                encoding="utf-8"
            )
        )
        config["version"] = "2.7.4"

        (self.project / "patches" / "2.7.4.json").write_text(
            json.dumps(config, ensure_ascii=False),
            encoding="utf-8"
        )

        with patch.object(engine.sys, "prefix", str(second_prefix)):
            second_manifest, second_backups = engine.select_state()

        self.assertNotEqual(first_manifest, second_manifest)

        with (
            patch.object(engine, "MANIFEST", second_manifest),
            patch.object(engine, "BACKUPS", second_backups),
            patch.object(
                engine,
                "installation",
                return_value=(
                    second_prefix,
                    "2.7.4",
                    second_source.resolve(),
                ),
            ),
        ):
            self.execute(engine.apply)

            self.assertTrue(first_manifest.exists())
            self.assertTrue(second_manifest.exists())

            for relative, original in self.originals.items():
                self.assertNotEqual(
                    (second_source / relative).read_bytes(),
                    original,
                )
                self.assertNotEqual(
                    (self.source / relative).read_bytes(),
                    original,
                )

            self.execute(engine.restore)

            self.assertFalse(second_manifest.exists())
            self.assertTrue(first_manifest.exists())

            for relative, original in self.originals.items():
                self.assertEqual(
                    (second_source / relative).read_bytes(),
                    original,
                )
                self.assertNotEqual(
                    (self.source / relative).read_bytes(),
                    original,
                )

        self.execute(engine.restore)
        self.assertFalse(first_manifest.exists())

    def test_install_failure_rolls_back(self):
        failed_target = self.source / "widgets/tabs/home.py"
        original_write = engine.atomic_write
        failed = False

        def interrupted_write(path, data):
            nonlocal failed

            if Path(path) == failed_target and not failed:
                failed = True
                raise OSError("Simulated installation failure")

            return original_write(path, data)

        with patch.object(
            engine, "atomic_write", side_effect=interrupted_write
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "写入失败，已自动恢复原始文件",
            ):
                self.execute(engine.apply)

        self.assertTrue(failed)
        self.assertFalse(engine.MANIFEST.exists())

        for relative, original in self.originals.items():
            self.assertEqual(
                (self.source / relative).read_bytes(),
                original,
            )

    def test_failed_restore_can_be_retried(self):
        self.execute(engine.apply)

        first_target = self.source / "widgets/dialogs/quit.py"
        second_target = self.source / "widgets/tabs/home.py"

        original_write = engine.atomic_write
        failed = False

        def interrupted_restore(path, data):
            nonlocal failed

            if (
                Path(path) == second_target
                and data == self.originals["widgets/tabs/home.py"]
                and not failed
            ):
                failed = True
                raise OSError("Simulated restoration failure")

            return original_write(path, data)

        with patch.object(
            engine, "atomic_write", side_effect=interrupted_restore
        ):
            with self.assertRaises(OSError):
                self.execute(engine.restore)

        self.assertTrue(failed)
        self.assertTrue(engine.MANIFEST.exists())

        self.assertEqual(
            first_target.read_bytes(),
            self.originals["widgets/dialogs/quit.py"],
        )
        self.assertNotEqual(
            second_target.read_bytes(),
            self.originals["widgets/tabs/home.py"],
        )

        record = json.loads(
            engine.MANIFEST.read_text(encoding="utf-8")
        )

        for entry in record["files"]:
            self.assertTrue(
                (engine.BACKUPS / entry["backup"]).is_file()
            )

        self.execute(engine.restore)

        self.assertFalse(engine.MANIFEST.exists())

        for relative, original in self.originals.items():
            self.assertEqual(
                (self.source / relative).read_bytes(),
                original,
            )

    def test_failed_rollback_preserves_recovery_data(self):
        first_target = self.source / "widgets/dialogs/quit.py"
        second_target = self.source / "widgets/tabs/home.py"

        original_write = engine.atomic_write
        install_failed = False
        rollback_failed = False

        def interrupted_write(path, data):
            nonlocal install_failed, rollback_failed

            path = Path(path)

            if path == second_target and not install_failed:
                install_failed = True
                raise OSError("Simulated installation failure")

            if (
                path == first_target
                and install_failed
                and not rollback_failed
                and data == self.originals["widgets/dialogs/quit.py"]
            ):
                rollback_failed = True
                raise OSError("Simulated rollback failure")

            return original_write(path, data)

        with patch.object(
            engine, "atomic_write", side_effect=interrupted_write
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "写入失败，自动恢复也未完成",
            ):
                self.execute(engine.apply)

        self.assertTrue(install_failed)
        self.assertTrue(rollback_failed)
        self.assertTrue(engine.MANIFEST.exists())

        record = json.loads(
            engine.MANIFEST.read_text(encoding="utf-8")
        )

        for entry in record["files"]:
            backup = engine.BACKUPS / entry["backup"]
            self.assertTrue(backup.is_file())
            self.assertEqual(
                backup.read_bytes(),
                self.originals[entry["relative"]],
            )

        self.assertNotEqual(
            first_target.read_bytes(),
            self.originals["widgets/dialogs/quit.py"],
        )
        self.assertEqual(
            second_target.read_bytes(),
            self.originals["widgets/tabs/home.py"],
        )

        self.execute(engine.restore)

        self.assertFalse(engine.MANIFEST.exists())

        for relative, original in self.originals.items():
            self.assertEqual(
                (self.source / relative).read_bytes(),
                original,
            )


if __name__ == "__main__":
    unittest.main()