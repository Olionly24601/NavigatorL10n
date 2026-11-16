import io
import json
import os
import subprocess
import sys
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

    def test_operation_lock_excludes_other_processes(self):
        code = (
            "from core import engine\n"
            "with engine.environment_lock():\n"
            "    print('Unexpected lock acquisition')\n"
        )
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        with engine.environment_lock():
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=Path(engine.__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("已有另一个 NavigatorZH 操作", result.stderr)
        with engine.environment_lock():
            pass

    def test_restore_cannot_interrupt_install_after_manifest_write(self):
        original_write = engine.atomic_write
        results = []
        code = (
            "import sys\n"
            "from pathlib import Path\n"
            "from core import engine\n"
            "engine.MANIFEST = Path(sys.argv[1])\n"
            "engine.BACKUPS = Path(sys.argv[2])\n"
            "engine.restore()\n"
        )

        def try_restore_when_manifest_written(path, data):
            result = original_write(path, data)
            if Path(path) == engine.MANIFEST:
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                results.append(subprocess.run(
                    [sys.executable, "-c", code,
                     str(engine.MANIFEST), str(engine.BACKUPS)],
                    cwd=Path(engine.__file__).resolve().parents[1],
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=10,
                ))
            return result

        with patch.object(
            engine, "atomic_write", side_effect=try_restore_when_manifest_written
        ):
            self.execute(engine.apply)

        self.assertEqual(len(results), 1)
        self.assertNotEqual(results[0].returncode, 0)
        self.assertIn("已有另一个 NavigatorZH 操作", results[0].stderr)
        self.assertTrue(engine.MANIFEST.exists())
        for relative, original in self.originals.items():
            self.assertNotEqual((self.source / relative).read_bytes(), original)
        self.execute(engine.restore)

    def test_apply_rejects_change_after_planning(self):
        target = self.source / "widgets/dialogs/quit.py"
        changed = b"title = 'Changed after planning'\n"
        original_write = engine.atomic_write

        def change_when_manifest_written(path, data):
            if Path(path) == engine.MANIFEST:
                target.write_bytes(changed)
            return original_write(path, data)

        with patch.object(
            engine, "atomic_write", side_effect=change_when_manifest_written
        ):
            with self.assertRaisesRegex(RuntimeError, "自动恢复也未完成"):
                self.execute(engine.apply)

        self.assertEqual(target.read_bytes(), changed)
        self.assertTrue(engine.MANIFEST.exists())
        self.assertEqual(
            (self.source / "widgets/tabs/home.py").read_bytes(),
            self.originals["widgets/tabs/home.py"],
        )
        target.write_bytes(self.originals["widgets/dialogs/quit.py"])
        self.execute(engine.restore)
        self.assertFalse(engine.MANIFEST.exists())

    def test_restore_rejects_change_after_preflight(self):
        self.execute(engine.apply)
        first_target = self.source / "widgets/dialogs/quit.py"
        second_target = self.source / "widgets/tabs/home.py"
        patched_second = second_target.read_bytes()
        changed = b"button = 'External edit'\n"
        original_write = engine.atomic_write

        def change_after_first_restoration(path, data):
            result = original_write(path, data)
            if (
                Path(path) == first_target
                and data == self.originals["widgets/dialogs/quit.py"]
            ):
                second_target.write_bytes(changed)
            return result

        with patch.object(
            engine, "atomic_write", side_effect=change_after_first_restoration
        ):
            with self.assertRaisesRegex(RuntimeError, "拒绝覆盖"):
                self.execute(engine.restore)

        self.assertEqual(
            first_target.read_bytes(), self.originals["widgets/dialogs/quit.py"]
        )
        self.assertEqual(second_target.read_bytes(), changed)
        self.assertTrue(engine.MANIFEST.exists())

        second_target.write_bytes(patched_second)
        self.execute(engine.restore)
        self.assertFalse(engine.MANIFEST.exists())

    def test_restore_keeps_manifest_if_restored_file_changes(self):
        self.execute(engine.apply)
        first_target = self.source / "widgets/dialogs/quit.py"
        changed = b"title = 'Changed after restoration'\n"
        original_write = engine.atomic_write

        def change_after_restoring_other_file(path, data):
            result = original_write(path, data)
            if Path(path) == self.source / "widgets/tabs/home.py":
                first_target.write_bytes(changed)
            return result

        with patch.object(
            engine, "atomic_write", side_effect=change_after_restoring_other_file
        ):
            with self.assertRaisesRegex(RuntimeError, "拒绝覆盖"):
                self.execute(engine.restore)

        self.assertTrue(engine.MANIFEST.exists())
        self.assertEqual(first_target.read_bytes(), changed)
        first_target.write_bytes(self.originals["widgets/dialogs/quit.py"])
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


class TestVersionIdentification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prefix = Path(self.temp.name) / "Anaconda3"
        self.source = (
            self.prefix / "Lib" / "site-packages" / "anaconda_navigator"
        )
        self.source.mkdir(parents=True)
        (self.source / "__init__.py").write_text("", encoding="utf-8")

    def add_conda_record(self, version):
        meta = self.prefix / "conda-meta"
        meta.mkdir(exist_ok=True)
        (meta / f"anaconda-navigator-{version}-0.json").write_text(
            json.dumps({"name": "anaconda-navigator", "version": version}),
            encoding="utf-8",
        )

    def add_dist_info(self, version):
        info = (
            self.prefix / "Lib" / "site-packages"
            / f"anaconda_navigator-{version}.dist-info"
        )
        info.mkdir()
        (info / "METADATA").write_text(
            f"Name: anaconda-navigator\nVersion: {version}\n",
            encoding="utf-8",
        )

    def test_uses_metadata_from_target_prefix(self):
        self.add_conda_record("2.7.1")
        with (
            patch.object(engine.sys, "prefix", str(self.prefix)),
            patch.object(engine.importlib.metadata, "version", return_value="2.7.4"),
        ):
            prefix, version, root = engine.installation()
        self.assertEqual(version, "2.7.1")
        self.assertEqual(root, self.source.resolve())

    def test_rejects_conflicting_local_metadata(self):
        self.add_conda_record("2.7.1")
        self.add_dist_info("2.7.4")
        with patch.object(engine.sys, "prefix", str(self.prefix)):
            with self.assertRaisesRegex(RuntimeError, "版本不一致"):
                engine.installation()

    def test_accepts_matching_local_metadata(self):
        self.add_conda_record("2.7.4")
        self.add_dist_info("2.7.4")
        with patch.object(engine.sys, "prefix", str(self.prefix)):
            self.assertEqual(engine.installation()[1], "2.7.4")


class TestCliOutput(unittest.TestCase):
    def test_success_output_with_cp1252(self):
        import main as cli

        output = io.BytesIO()
        writer = io.TextIOWrapper(output, encoding="cp1252", errors="strict")
        with (
            patch.object(sys, "argv", ["main.py", "apply"]),
            patch.object(sys, "stdout", writer),
            patch.object(cli, "apply", side_effect=lambda _: print("已安装汉化")),
        ):
            cli.main()
            writer.flush()
        self.assertIn(b"\\u5df2", output.getvalue())

    def test_error_output_with_cp1252(self):
        import main as cli

        output = io.BytesIO()
        writer = io.TextIOWrapper(output, encoding="cp1252", errors="strict")
        with (
            patch.object(sys, "argv", ["main.py", "apply"]),
            patch.object(sys, "stdout", writer),
            patch.object(cli, "apply", side_effect=RuntimeError("文件发生变化")),
        ):
            with self.assertRaises(SystemExit) as result:
                cli.main()
            writer.flush()
        self.assertEqual(result.exception.code, 1)
        self.assertIn(b"\\u64cd", output.getvalue())


if __name__ == "__main__":
    unittest.main()