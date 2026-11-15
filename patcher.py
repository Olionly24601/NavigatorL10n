import argparse
import ast
import hashlib
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TARGET = Path(
    r"D:\Apps\Anaconda3\Lib\site-packages"
    r"\anaconda_navigator\widgets\dialogs\quit.py"
)
BACKUP_DIR = ROOT / "backups"
MANIFEST = ROOT / "manifest.json"

RULES = [
    (
        "QLabel('Quit Anaconda Navigator?')",
        "QLabel('确定退出 Anaconda Navigator 吗？')",
        1,
    ),
    (
        "ButtonPrimary('Yes')",
        "ButtonPrimary('确定')",
        1,
    ),
    (
        "ButtonNormal('No')",
        "ButtonNormal('取消')",
        1,
    ),
    (
        'CheckBoxBase("Don\'t show again")',
        'CheckBoxBase("不再提示")',
        1,
    ),
    (
        "setWindowTitle('Quit application')",
        "setWindowTitle('退出应用程序')",
        2,
    ),
    (
        "self.label_about.setText('Anaconda Navigator is still busy.<br><br>Do you want to quit?')",
        "self.label_about.setText('Anaconda Navigator 仍有任务正在运行。<br><br>确定要退出吗？')",
        1,
    ),
]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_atomic(path, data):
    fd, temporary = tempfile.mkstemp(
        prefix=".navigatorzh-",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply():
    if not TARGET.is_file():
        raise RuntimeError("找不到 Navigator 源码文件")

    if MANIFEST.exists():
        raise RuntimeError("已有汉化记录，请先检查状态")

    original = TARGET.read_bytes()
    content = original.decode("utf-8")

    for old, new, expected in RULES:
        count = content.count(old)
        if count != expected:
            raise RuntimeError(
                f"源码不符合预期：{old!r}，预期 {expected} 处，实际 {count} 处"
            )
        content = content.replace(old, new)

    ast.parse(content, filename=str(TARGET))
    patched = content.encode("utf-8")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"quit-{sha256(original)[:16]}.bak"

    if backup.exists():
        if backup.read_bytes() != original:
            raise RuntimeError("备份文件校验失败")
    else:
        backup.write_bytes(original)

    record = {
        "target": str(TARGET),
        "backup": str(backup),
        "original_sha256": sha256(original),
        "patched_sha256": sha256(patched),
    }

    MANIFEST.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    write_atomic(TARGET, patched)
    print("汉化安装成功，重新启动 Navigator 后生效。")


def restore():
    if not MANIFEST.exists():
        print("没有找到汉化安装记录")
        return

    record = json.loads(MANIFEST.read_text(encoding="utf-8"))

    if record["target"] != str(TARGET):
        raise RuntimeError("记录的目标路径不一致")

    backup = Path(record["backup"])
    original = backup.read_bytes()

    if sha256(original) != record["original_sha256"]:
        raise RuntimeError("备份文件校验失败，已停止恢复")

    current = TARGET.read_bytes()
    current_hash = sha256(current)

    if current_hash == record["patched_sha256"]:
        write_atomic(TARGET, original)
    elif current_hash != record["original_sha256"]:
        raise RuntimeError("源码已被其他操作修改，拒绝覆盖")

    MANIFEST.unlink()
    print("已恢复原始英文版本")


def status():
    if not TARGET.exists():
        print("未找到 Navigator")
        return

    if not MANIFEST.exists():
        print("未发现本工具的汉化记录")
        return

    record = json.loads(MANIFEST.read_text(encoding="utf-8"))
    current_hash = sha256(TARGET.read_bytes())

    if current_hash == record["patched_sha256"]:
        print("状态：已汉化")
    elif current_hash == record["original_sha256"]:
        print("状态：原始英文版本")
    else:
        print("状态：源码发生变化，需要人工检查")


def main():
    parser = argparse.ArgumentParser(description="NavigatorZH 汉化工具")
    parser.add_argument(
        "command",
        choices=["status", "apply", "restore"],
    )
    args = parser.parse_args()

    try:
        if args.command == "status":
            status()
        elif args.command == "apply":
            apply()
        else:
            restore()
    except Exception as error:
        print(f"操作失败：{error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()