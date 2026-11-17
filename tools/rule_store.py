
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import errno
import os
from contextlib import contextmanager

from core import engine


def _paths(root):
    folder = root / "state" / "rule_transactions"
    return folder, folder / "pending.json"


@contextmanager
def project_lock(root):
    root = Path(root).resolve()
    folder, _ = _paths(root)
    folder.mkdir(parents=True, exist_ok=True)

    lock_path = folder / "write.lock"

    with lock_path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)

        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()

        stream.seek(0)

        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(
                    stream.fileno(),
                    msvcrt.LK_NBLCK,
                    1,
                )
            else:
                import fcntl
                fcntl.flock(
                    stream.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                raise

            raise RuntimeError(
                "另一个规则维护操作正在进行"
            ) from error

        try:
            yield
        finally:
            stream.seek(0)

            if os.name == "nt":
                msvcrt.locking(
                    stream.fileno(),
                    msvcrt.LK_UNLCK,
                    1,
                )
            else:
                fcntl.flock(
                    stream.fileno(),
                    fcntl.LOCK_UN,
                )


def require_clean_rules(root):
    _, pending = _paths(Path(root).resolve())
    if pending.exists():
        raise RuntimeError(
            "存在未完成的规则事务，请先执行 "
            "python tools/build_rules.py recover"
        )


def _encode(value):
    return (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _verify_final_state(root, entries, state):
    for entry in entries:
        target = (root / entry["path"]).resolve()
        if not target.is_relative_to(root):
            raise ValueError("事务目标路径无效")
        if engine.digest(target.read_bytes()) != entry[state]:
            raise RuntimeError(f"事务最终校验失败：{target}")


def recover_pending(root):
    root = Path(root).resolve()
    folder, pending = _paths(root)

    if not pending.exists():
        return False

    record = engine.read_json(pending)
    operations = []

    for entry in record["files"]:
        target = (root / entry["path"]).resolve()
        backup = (root / entry["backup"]).resolve()

        if not target.is_relative_to(root):
            raise ValueError("事务目标路径无效")
        if not backup.is_relative_to(folder):
            raise ValueError("事务备份路径无效")

        original = backup.read_bytes()
        if engine.digest(original) != entry["before"]:
            raise ValueError(f"事务备份校验失败：{backup}")

        current = engine.digest(target.read_bytes())
        if current not in (entry["before"], entry["after"]):
            raise ValueError(f"事务目标已被修改：{target}")

        operations.append((target, original, current, entry))

    for target, original, current, entry in reversed(operations):
        if current != entry["before"]:
            engine.atomic_write(
                target,
                original,
                expected_hash=entry["after"],
            )

    _verify_final_state(root, record["files"], "before")
    pending.unlink()
    return True


def save_many(root, updates, expected_hashes=None):
    root = Path(root).resolve()
    folder, pending = _paths(root)

    if pending.exists():
        raise RuntimeError("存在未完成的规则事务，请先恢复")

    if not updates:
        return

    if expected_hashes is not None:
        normalized_expected = {
            Path(path).resolve(): digest
            for path, digest in expected_hashes.items()
        }
        update_paths = {Path(path).resolve() for path in updates}
        if set(normalized_expected) != update_paths:
            raise ValueError("预期快照与保存目标不一致")

    transaction_id = (
        datetime.now().strftime("%Y%m%d_%H%M%S")
        + "_"
        + uuid4().hex[:8]
    )
    archive = folder / "archive" / transaction_id

    entries = []
    prepared = []
    seen = set()

    for index, (path, content) in enumerate(updates.items()):
        target = Path(path).resolve()

        if not target.is_relative_to(root):
            raise ValueError(f"目标不属于项目目录：{target}")
        if target in seen:
            raise ValueError(f"重复写入目标：{target}")
        if not target.is_file():
            raise ValueError(f"目标文件不存在：{target}")
        if not isinstance(content, bytes):
            raise TypeError("待写入内容必须为 bytes")

        seen.add(target)
        original = target.read_bytes()
        before_hash = engine.digest(original)
        if expected_hashes is not None:
            if before_hash != normalized_expected[target]:
                raise RuntimeError(f"源文件在读取后已修改：{target}")
        backup = archive / f"{index:03d}.bak"

        engine.atomic_write(backup, original)

        entries.append({
            "path": target.relative_to(root).as_posix(),
            "backup": backup.relative_to(root).as_posix(),
            "before": before_hash,
            "after": engine.digest(content),
        })
        prepared.append((target, content, before_hash))

    for target, _, before_hash in prepared:
        if engine.digest(target.read_bytes()) != before_hash:
            raise RuntimeError(f"源文件在保存准备期间已修改：{target}")

    engine.atomic_write(
        pending,
        _encode({"id": transaction_id, "files": entries}),
    )

    try:
        for target, content, before_hash in prepared:
            engine.atomic_write(
                target,
                content,
                expected_hash=before_hash,
            )
    except Exception:
        try:
            recover_pending(root)
        except Exception as recovery_error:
            raise RuntimeError(
                "规则保存与自动恢复均未完成，请保留 state 目录"
            ) from recovery_error
        raise

    _verify_final_state(root, entries, "after")
    pending.unlink()
