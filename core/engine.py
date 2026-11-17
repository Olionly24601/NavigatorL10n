import ast
import errno
import hashlib
import importlib.metadata
import json
import os
import re
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from core.translation_validation import validate_messages

PROJECT = Path(__file__).resolve().parents[1]
STATE = PROJECT / "state"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def select_state():
    prefix = Path(sys.prefix).resolve()
    legacy_manifest = STATE / "manifest.json"

    if legacy_manifest.is_file():
        record = read_json(legacy_manifest)
        if record.get("prefix") == str(prefix):
            return legacy_manifest, STATE / "backups"

    key = digest(str(prefix).encode("utf-8"))[:16]
    folder = STATE / "environments" / key
    return folder / "manifest.json", folder / "backups"


MANIFEST, BACKUPS = select_state()

@contextmanager
def environment_lock():
    """Serialize modifications to a Conda prefix across NavigatorZH processes."""
    prefix = os.path.normcase(str(Path(sys.prefix).resolve()))
    lock_dir = Path(tempfile.gettempdir()) / "navigatorzh-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / (digest(prefix.encode("utf-8")) + ".lock")

    with lock_path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            raise RuntimeError(
                "当前 Conda 环境已有另一个 NavigatorZH 操作正在进行"
            ) from error

        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def verify_unchanged(target, expected_hash):
    """Refuse to overwrite a target changed since its last validation."""
    try:
        current_hash = digest(target.read_bytes())
    except OSError as error:
        raise RuntimeError(f"目标文件无法读取，拒绝覆盖：{target}") from error
    if current_hash != expected_hash:
        raise RuntimeError(f"目标文件已发生其他变化，拒绝覆盖：{target}")


def atomic_write(path, data, *, expected_hash=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".navigatorzh-", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode)
        if expected_hash is not None:
            verify_unchanged(path, expected_hash)
        os.replace(temporary, path)
    finally:
        primary_error = sys.exc_info()[0] is not None
        if os.path.exists(temporary):
            try:
                if os.name == "nt":
                    os.chmod(temporary, stat.S_IREAD | stat.S_IWRITE)
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except OSError:
                if not primary_error:
                    raise


def installation():
    prefix = Path(sys.prefix).resolve()
    root = prefix / "Lib" / "site-packages" / "anaconda_navigator"

    if not (root / "__init__.py").is_file():
        raise RuntimeError(
            "当前 Python 环境未找到 Navigator，请使用 Anaconda Prompt"
        )

    versions_from_metadata = set()
    site_packages = prefix / "Lib" / "site-packages"
    for distribution in importlib.metadata.distributions(
        path=[str(site_packages)]
    ):
        name = distribution.metadata.get("Name", "")
        if re.sub(r"[-_.]+", "-", name).lower() == "anaconda-navigator":
            versions_from_metadata.add(distribution.version)

    versions_from_conda = set()
    for path in (prefix / "conda-meta").glob("anaconda-navigator-*.json"):
        info = read_json(path)
        if info.get("name") == "anaconda-navigator":
            versions_from_conda.add(info["version"])

    if len(versions_from_metadata) > 1 or len(versions_from_conda) > 1:
        raise RuntimeError("当前 Conda 环境中的 Navigator 版本记录存在冲突")
    if (
        versions_from_metadata
        and versions_from_conda
        and versions_from_metadata != versions_from_conda
    ):
        raise RuntimeError("Navigator 安装元数据与 Conda 记录的版本不一致")

    versions = versions_from_conda or versions_from_metadata
    if len(versions) != 1:
        raise RuntimeError("无法可靠识别 Navigator 版本")
    version = versions.pop()

    return prefix, version, root.resolve()


def target_path(root, relative):
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise RuntimeError("检测到非法目标路径")
    return target


def prepare(language):
    from tools import rule_store

    with rule_store.project_lock(PROJECT):
        rule_store.require_clean_rules(PROJECT)
        return _prepare_unlocked(language)


def _prepare_unlocked(language):
    prefix, version, root = installation()
    config_path = PROJECT / "patches" / f"{version}.json"
    locale_path = PROJECT / "locales" / f"{language}.json"

    if not config_path.is_file():
        raise RuntimeError(f"暂不支持 Navigator {version}")
    if not locale_path.is_file():
        raise RuntimeError(f"找不到语言包：{language}")

    config = read_json(config_path)
    locale = read_json(locale_path)
    if config["version"] != version:
        raise RuntimeError("版本适配规则不一致")
    if locale["language"] != language:
        raise RuntimeError("语言包标识不一致")

    translations = locale["messages"]
    validate_messages(translations)
    plans = []

    for item in config["files"]:
        target = target_path(root, item["path"])
        original = target.read_bytes()
        content = original.decode("utf-8")

        for rule in item["rules"]:
            key = rule["id"]
            if key not in translations:
                raise RuntimeError(f"缺少翻译：{key}")

            before = rule["original"]
            actual = content.count(before)
            if actual != rule["count"]:
                raise RuntimeError(
                    f"{item['path']} 中 {key} 的匹配数量异常："
                    f"预期 {rule['count']}，实际 {actual}"
                )

            value = json.dumps(
                translations[key], ensure_ascii=False
            )
            after = rule["template"].format(text=value)
            content = content.replace(before, after)

        ast.parse(content, filename=str(target))
        patched = content.encode("utf-8")

        if patched == original:
            raise RuntimeError(f"没有产生有效修改：{target}")

        plans.append({
            "relative": item["path"],
            "target": target,
            "original": original,
            "patched": patched,
        })

    if not plans:
        raise RuntimeError("版本规则中没有可应用的文件")

    return prefix, version, plans


def check(language="zh_CN"):
    if MANIFEST.exists():
        raise RuntimeError("已有安装记录，请先恢复原版")

    prefix, version, plans = prepare(language)
    print(f"Anaconda：{prefix}")
    print(f"Navigator：{version}")
    print(f"目标语言：{language}")
    print(f"待修改文件数：{len(plans)}")
    print("兼容性与 Python 语法检查通过，尚未修改文件")


def status():
    prefix, version, root = installation()
    print(f"Navigator：{version}")
    print(f"安装目录：{prefix}")

    if not MANIFEST.exists():
        print("状态：没有本引擎的汉化安装记录")
        return

    record = read_json(MANIFEST)

    if record["prefix"] != str(prefix):
        raise RuntimeError("安装记录不属于当前 Conda 环境")

    language = record.get("language", "未知（旧记录）")
    print(f"已安装语言：{language}")

    for entry in record["files"]:
        target = target_path(root, entry["relative"])

        if not target.is_file():
            state = "文件缺失"
        else:
            current = digest(target.read_bytes())

            if current == entry["patched_sha256"]:
                state = "已汉化"
            elif current == entry["original_sha256"]:
                state = "原始版本"
            else:
                state = "文件发生其他变化"

        print(f"{entry['relative']}：{state}")


def apply(language="zh_CN"):
    with environment_lock():
        return _apply(language)


def _apply(language):
    if MANIFEST.exists():
        raise RuntimeError("已有汉化安装记录，请先恢复原版")

    prefix, version, plans = prepare(language)
    records = []

    for plan in plans:
        original = plan["original"]
        original_hash = digest(original)
        name = (
            digest(plan["relative"].encode("utf-8"))[:12]
            + "-"
            + original_hash[:16]
            + ".bak"
        )
        backup = BACKUPS / name

        if backup.exists():
            if backup.read_bytes() != original:
                raise RuntimeError(f"备份文件不一致：{backup}")
        else:
            atomic_write(backup, original)

        records.append({
            "relative": plan["relative"],
            "backup": name,
            "original_sha256": original_hash,
            "patched_sha256": digest(plan["patched"]),
        })

    record = {
        "prefix": str(prefix),
        "version": version,
        "language": language,
        "files": records,
    }

    atomic_write(
        MANIFEST,
        json.dumps(
            record, ensure_ascii=False, indent=2
        ).encode("utf-8"),
    )

    try:
        for plan in plans:
            original_hash = digest(plan["original"])
            verify_unchanged(plan["target"], original_hash)
            atomic_write(
                plan["target"], plan["patched"],
                expected_hash=original_hash,
            )
    except Exception as error:
        try:
            _restore()
        except Exception as rollback_error:
            raise RuntimeError(
                "写入失败，自动恢复也未完成，请保留 state 目录"
            ) from rollback_error
        raise RuntimeError(
            "写入失败，已自动恢复原始文件"
        ) from error

    print(f"已安装 {language} 汉化，重启 Navigator 后生效")


def restore():
    with environment_lock():
        return _restore()


def _restore():
    if not MANIFEST.exists():
        print("没有需要恢复的汉化记录")
        return

    prefix, version, root = installation()
    record = read_json(MANIFEST)

    if record["prefix"] != str(prefix):
        raise RuntimeError("安装记录不属于当前 Conda 环境")

    operations = []
    expected = []

    for entry in record["files"]:
        target = target_path(root, entry["relative"])
        backup = BACKUPS / entry["backup"]
        original = backup.read_bytes()

        if digest(original) != entry["original_sha256"]:
            raise RuntimeError(f"备份校验失败：{backup}")

        current_hash = digest(target.read_bytes())

        if current_hash not in (
            entry["original_sha256"],
            entry["patched_sha256"],
        ):
            raise RuntimeError(
                f"文件已发生其他变化，拒绝覆盖：{target}"
            )

        expected.append((target, entry["original_sha256"]))
        if current_hash == entry["patched_sha256"]:
            operations.append((target, original, entry["patched_sha256"]))

    for target, original, patched_hash in operations:
        verify_unchanged(target, patched_hash)
        atomic_write(target, original, expected_hash=patched_hash)

    for target, original_hash in expected:
        verify_unchanged(target, original_hash)

    MANIFEST.unlink()
    print("已恢复原始英文版本")