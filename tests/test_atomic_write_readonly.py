import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import engine


class TestAtomicWriteCleanup(unittest.TestCase):
    def test_replace_failure_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.py"
            target.write_bytes(b"original")

            with patch.object(
                engine.os, "replace", side_effect=PermissionError("replace blocked")
            ):
                with self.assertRaisesRegex(PermissionError, "replace blocked"):
                    engine.atomic_write(target, b"updated")

            self.assertEqual(target.read_bytes(), b"original")
            self.assertEqual(list(root.glob(".navigatorzh-*")), [])

    def test_cleanup_failure_preserves_replace_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.py"
            target.write_bytes(b"original")

            with (
                patch.object(
                    engine.os, "replace", side_effect=PermissionError("replace blocked")
                ),
                patch.object(
                    engine.os, "unlink", side_effect=PermissionError("cleanup blocked")
                ),
            ):
                with self.assertRaisesRegex(PermissionError, "replace blocked"):
                    engine.atomic_write(target, b"updated")

            self.assertEqual(target.read_bytes(), b"original")

    @unittest.skipUnless(os.name == "nt", "Windows read-only attribute test")
    def test_readonly_target_rejects_replace_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.py"
            original = b"original"
            target.write_bytes(original)
            target.chmod(stat.S_IREAD)
            try:
                with self.assertRaises(PermissionError):
                    engine.atomic_write(
                        target, b"updated", expected_hash=engine.digest(original)
                    )
                self.assertEqual(target.read_bytes(), original)
                self.assertEqual(list(root.glob(".navigatorzh-*")), [])
            finally:
                target.chmod(stat.S_IREAD | stat.S_IWRITE)


if __name__ == "__main__":
    unittest.main()
