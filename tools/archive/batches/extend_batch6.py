import ast
import json

from core.engine import MANIFEST, PROJECT, atomic_write, installation


TRANSLATIONS = {
    "Installed": "已安装",
    "Not installed": "未安装",
    "Updatable": "可更新",
    "Selected": "已选择",
    "All": "全部",
}

RULES = [
    {
        "path": "widgets/manager/packages.py",
        "original": "self.combobox_filter.addItems(C.COMBOBOX_VALUES_ORDERED[:])",
        "template": (
            "self.combobox_filter.addItems("
            "[{text}.get(label, label) "
            "for label in C.COMBOBOX_VALUES_ORDERED])"
        ),
    },
    {
        "path": "widgets/manager/table.py",
        "original": "self._filterbox = C.COMBOBOX_VALUES.get(text)",
        "template": (
            "self._filterbox = C.COMBOBOX_VALUES.get("
            "{{value: key for key, value in {text}.items()}}"
            ".get(text, text))"
        ),
    },
]


def main():
    if MANIFEST.exists():
        raise RuntimeError("当前仍有汉化记录，请先恢复原版")

    _, version, root = installation()

    if version != "2.7.1":
        raise RuntimeError(f"暂不支持 Navigator {version}")

    rules_path = PROJECT / "patches" / "2.7.1.json"
    locale_path = PROJECT / "locales" / "zh_CN.json"

    rules_original = rules_path.read_bytes()
    locale_original = locale_path.read_bytes()

    rules = json.loads(rules_original)
    locale = json.loads(locale_original)

    if rules.get("version") != version:
        raise RuntimeError("版本适配规则不匹配")

    if locale.get("language") != "zh_CN":
        raise RuntimeError("语言包标识不匹配")

    rule_id = "packages.filter_labels"

    existing_ids = {
        rule["id"]
        for entry in rules["files"]
        for rule in entry["rules"]
    }

    if rule_id in existing_ids or rule_id in locale["messages"]:
        raise RuntimeError("第六批翻译规则已经存在")

    if len(set(TRANSLATIONS.values())) != len(TRANSLATIONS):
        raise RuntimeError("中文筛选名称存在重复")

    files = {
        entry["path"]: entry
        for entry in rules["files"]
    }

    for item in RULES:
        relative = item["path"]
        path = root / relative

        if not path.is_file():
            raise RuntimeError(f"源码文件不存在：{relative}")

        source = path.read_bytes().decode("utf-8-sig")

        count = source.count(item["original"])

        if count != 1:
            raise RuntimeError(
                f"{relative}：预期匹配 1 处，实际 {count} 处"
            )

        entry = files.get(relative)

        if entry is None:
            entry = {
                "path": relative,
                "rules": [],
            }
            rules["files"].append(entry)
            files[relative] = entry

        entry["rules"].append({
            "id": rule_id,
            "original": item["original"],
            "template": item["template"],
            "count": 1,
        })

    locale["messages"][rule_id] = TRANSLATIONS

    for entry in rules["files"]:
        path = root / entry["path"]
        content = path.read_bytes().decode("utf-8-sig")

        for rule in entry["rules"]:
            expected = rule["count"]
            actual = content.count(rule["original"])

            if actual != expected:
                raise RuntimeError(
                    f"{entry['path']} / {rule['id']}："
                    f"预期 {expected} 处，实际 {actual} 处"
                )

            translated = json.dumps(
                locale["messages"][rule["id"]],
                ensure_ascii=False,
            )

            replacement = rule["template"].format(
                text=translated
            )

            content = content.replace(
                rule["original"],
                replacement,
            )

        ast.parse(content, filename=str(path))

    snapshots = PROJECT / "state" / "rule_snapshots"

    old_rules = snapshots / "2.7.1.before_batch6.json"
    old_locale = snapshots / "zh_CN.before_batch6.json"

    if old_rules.exists() or old_locale.exists():
        raise RuntimeError("第六批规则快照已经存在")

    snapshots.mkdir(parents=True, exist_ok=True)

    atomic_write(old_rules, rules_original)
    atomic_write(old_locale, locale_original)

    try:
        atomic_write(
            rules_path,
            (
                json.dumps(
                    rules,
                    ensure_ascii=False,
                    indent=2,
                ) + "\n"
            ).encode("utf-8"),
        )

        atomic_write(
            locale_path,
            (
                json.dumps(
                    locale,
                    ensure_ascii=False,
                    indent=2,
                ) + "\n"
            ).encode("utf-8"),
        )

    except Exception:
        atomic_write(rules_path, rules_original)
        atomic_write(locale_path, locale_original)
        raise

    print("第六批规则生成成功")
    print("新增补丁规则：2 条")
    print("新增翻译词条：5 条")
    print(f"累计涉及源码文件：{len(rules['files'])}")
    print("规则匹配和 Python 语法检查通过")
    print("已保存第六批修改前的规则快照")
    print("Navigator 安装文件尚未修改")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"生成失败：{error}")
        raise SystemExit(1)