import ast
import hashlib
import importlib.metadata
import json
import os
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
STATE = PROJECT / "state"
BACKUPS = STATE / "backups"
MANIFEST = STATE / "manifest.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path, data):
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
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def installation():
    prefix = Path(sys.prefix).resolve()
    root = prefix / "Lib" / "site-packages" / "anaconda_navigator"

    if not (root / "__init__.py").is_file():
        raise RuntimeError(
            "当前 Python 环境未找到 Navigator，请使用 Anaconda Prompt"
        )

    try:
        version = importlib.metadata.version("anaconda-navigator")
    except importlib.metadata.PackageNotFoundError:
        versions = set()
        for path in (prefix / "conda-meta").glob(
            "anaconda-navigator-*.json"
        ):
            info = read_json(path)
            if info.get("name") == "anaconda-navigator":
                versions.add(info["version"])
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
            atomic_write(plan["target"], plan["patched"])
    except Exception as error:
        try:
            restore()
        except Exception as rollback_error:
            raise RuntimeError(
                "写入失败，自动恢复也未完成，请保留 state 目录"
            ) from rollback_error
        raise RuntimeError(
            "写入失败，已自动恢复原始文件"
        ) from error

    print(f"已安装 {language} 汉化，重启 Navigator 后生效")


def restore():
    if not MANIFEST.exists():
        print("没有需要恢复的汉化记录")
        return

    prefix, version, root = installation()
    record = read_json(MANIFEST)

    if record["prefix"] != str(prefix):
        raise RuntimeError("安装记录不属于当前 Conda 环境")

    operations = []

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

        if current_hash == entry["patched_sha256"]:
            operations.append((target, original))

    for target, original in operations:
        atomic_write(target, original)

    MANIFEST.unlink()
    print("已恢复原始英文版本")