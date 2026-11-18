
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import engine
from tools import rule_store


class TestRuleStore(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

        paths = [
            "patches/2.7.4.json",
            "locales/zh_CN.json",
            "locales/ja_JP.json",
        ]

        self.targets = []
        for index, relative in enumerate(paths):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f"old-{index}".encode())
            self.targets.append(target)

        self.updates = {
            target: f"new-{index}".encode()
            for index, target in enumerate(self.targets)
        }

    def assert_originals(self):
        for index, target in enumerate(self.targets):
            self.assertEqual(
                target.read_bytes(),
                f"old-{index}".encode(),
            )

    def test_project_lock_blocks_concurrent_reader(self):
        import os
        import subprocess
        import sys

        code = (
            "import sys\n"
            "from pathlib import Path\n"
            "from tools import rule_store\n"
            "try:\n"
            "    with rule_store.project_lock(Path(sys.argv[1])):\n"
            "        print('LOCK_ACQUIRED')\n"
            "except RuntimeError as error:\n"
            "    if '另一个规则维护操作正在进行' not in str(error):\n"
            "        raise\n"
            "    print('LOCK_REJECTED')\n"
        )
        with rule_store.project_lock(self.root):
            result = subprocess.run(
                [sys.executable, "-c", code, str(self.root)],
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
        self.assertEqual(
            result.returncode, 0,
            f"stdout={result.stdout!r}; stderr={result.stderr!r}",
        )
        self.assertIn("LOCK_REJECTED", result.stdout or "")
        self.assertNotIn("LOCK_ACQUIRED", result.stdout or "")

    def test_successful_three_file_save(self):
        rule_store.save_many(self.root, self.updates)

        for target, content in self.updates.items():
            self.assertEqual(target.read_bytes(), content)

        self.assertFalse(
            (self.root / "state/rule_transactions/pending.json").exists()
        )

    def test_write_failure_rolls_back_all_files(self):
        original_write = engine.atomic_write
        failing_target = self.targets[2]

        def failing_write(path, content, **kwargs):
            if Path(path) == failing_target and content == b"new-2":
                raise OSError("simulated write failure")
            return original_write(path, content, **kwargs)

        with patch.object(
            rule_store.engine, "atomic_write",
            side_effect=failing_write,
        ):
            with self.assertRaises(OSError):
                rule_store.save_many(self.root, self.updates)

        self.assert_originals()

    def test_interrupted_save_can_be_recovered(self):
        original_write = engine.atomic_write
        interrupted_target = self.targets[1]

        def interrupted_write(path, content, **kwargs):
            if Path(path) == interrupted_target and content == b"new-1":
                raise KeyboardInterrupt()
            return original_write(path, content, **kwargs)

        with patch.object(
            rule_store.engine, "atomic_write",
            side_effect=interrupted_write,
        ):
            with self.assertRaises(KeyboardInterrupt):
                rule_store.save_many(self.root, self.updates)

        pending = self.root / "state/rule_transactions/pending.json"
        self.assertTrue(pending.exists())

        self.assertTrue(rule_store.recover_pending(self.root))
        self.assert_originals()
        self.assertFalse(pending.exists())

    def test_recovery_rejects_external_modifications(self):
        original_write = engine.atomic_write

        def interrupted_write(path, content, **kwargs):
            if Path(path) == self.targets[1] and content == b"new-1":
                raise KeyboardInterrupt()
            return original_write(path, content, **kwargs)

        with patch.object(
            rule_store.engine, "atomic_write",
            side_effect=interrupted_write,
        ):
            with self.assertRaises(KeyboardInterrupt):
                rule_store.save_many(self.root, self.updates)

        self.targets[0].write_bytes(b"external-change")

        with self.assertRaisesRegex(ValueError, "事务目标已被修改"):
            rule_store.recover_pending(self.root)

        pending = self.root / "state/rule_transactions/pending.json"
        self.assertTrue(pending.exists())

    def test_save_detects_late_external_modification(self):
        original_write = engine.atomic_write
        last_target = self.targets[2]

        def modified_after_write(path, content, **kwargs):
            result = original_write(path, content, **kwargs)
            if Path(path) == last_target and content == b"new-2":
                self.targets[0].write_bytes(b"external-change")
            return result

        with patch.object(
            rule_store.engine, "atomic_write",
            side_effect=modified_after_write,
        ):
            with self.assertRaisesRegex(RuntimeError, "事务最终校验失败"):
                rule_store.save_many(self.root, self.updates)

        pending = self.root / "state/rule_transactions/pending.json"
        self.assertTrue(pending.exists())
        self.assertEqual(self.targets[0].read_bytes(), b"external-change")

    def test_recovery_detects_change_to_previously_skipped_file(self):
        original_write = engine.atomic_write

        def interrupt_second_write(path, content, **kwargs):
            if Path(path) == self.targets[1] and content == b"new-1":
                raise KeyboardInterrupt()
            return original_write(path, content, **kwargs)

        with patch.object(
            rule_store.engine, "atomic_write",
            side_effect=interrupt_second_write,
        ):
            with self.assertRaises(KeyboardInterrupt):
                rule_store.save_many(self.root, self.updates)

        def edit_skipped_file_during_recovery(path, content, **kwargs):
            result = original_write(path, content, **kwargs)
            if Path(path) == self.targets[0] and content == b"old-0":
                self.targets[1].write_bytes(b"external-change")
            return result

        with patch.object(
            rule_store.engine, "atomic_write",
            side_effect=edit_skipped_file_during_recovery,
        ):
            with self.assertRaisesRegex(RuntimeError, "事务最终校验失败"):
                rule_store.recover_pending(self.root)

        pending = self.root / "state/rule_transactions/pending.json"
        self.assertTrue(pending.exists())
        self.assertEqual(self.targets[1].read_bytes(), b"external-change")

    def test_expected_snapshot_prevents_overwriting_editor_change(self):
        snapshot = {
            target: engine.digest(target.read_bytes())
            for target in self.targets
        }
        self.targets[1].write_bytes(b"editor-change")

        with self.assertRaisesRegex(RuntimeError, "源文件在读取后已修改"):
            rule_store.save_many(
                self.root, self.updates, expected_hashes=snapshot
            )

        self.assertEqual(self.targets[0].read_bytes(), b"old-0")
        self.assertEqual(self.targets[1].read_bytes(), b"editor-change")
        self.assertEqual(self.targets[2].read_bytes(), b"old-2")
        self.assertFalse(
            (self.root / "state/rule_transactions/pending.json").exists()
        )

    def test_missing_snapshot_target_is_rejected(self):
        snapshot = {
            self.targets[0]: engine.digest(self.targets[0].read_bytes())
        }
        with self.assertRaisesRegex(ValueError, "预期快照与保存目标不一致"):
            rule_store.save_many(
                self.root, self.updates, expected_hashes=snapshot
            )
        self.assert_originals()

    def test_pending_transaction_blocks_new_save(self):
        pending = self.root / "state/rule_transactions/pending.json"
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text("{}", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "未完成的规则事务"):
            rule_store.save_many(self.root, self.updates)

        self.assert_originals()


if __name__ == "__main__":
    unittest.main()
