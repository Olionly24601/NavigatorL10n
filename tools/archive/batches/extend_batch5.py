import ast
import json

from core.engine import PROJECT, MANIFEST, atomic_write, installation


EXPECTED_TAGS = {
    "documentation": "Read",
    "webinar": "Explore",
    "event": "Learn More",
    "video": "View",
    "training": "Explore",
    "forum": "Explore",
    "social": "Engage",
}

CHINESE_TAGS = {
    "documentation": "阅读",
    "webinar": "探索",
    "event": "了解更多",
    "video": "查看",
    "training": "探索",
    "forum": "探索",
    "social": "参与",
}


def find_home_rule(source):
    tree = ast.parse(source)
    matches = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if not isinstance(node.func, ast.Name):
            continue

        if node.func.id != "ApplicationFilterDetails":
            continue

        if len(node.args) != 2:
            continue

        first, second = node.args

        if not isinstance(first, ast.Constant):
            continue

        if first.value != "Updatable applications":
            continue

        if not isinstance(second, ast.Name):
            continue

        if second.id != "check_updatable":
            continue

        matches.append(node)

    if len(matches) != 1:
        raise RuntimeError(
            f"首页筛选定位异常：找到 {len(matches)} 处"
        )

    original = ast.get_source_segment(source, matches[0])

    if not original or source.count(original) != 1:
        raise RuntimeError("首页筛选源码无法唯一定位")

    literal = ast.get_source_segment(source, matches[0].args[0])

    if not literal or original.count(literal) != 1:
        raise RuntimeError("首页筛选文字无法唯一定位")

    template = original.replace(literal, "{text}", 1)

    return {
        "id": "home.filter_updatable",
        "original": original,
        "template": template,
        "count": 1,
    }


def find_content_rule(source):
    tree = ast.parse(source)
    matches = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue

        if not any(
            isinstance(target, ast.Name)
            and target.id == "valid_tags"
            for target in node.targets
        ):
            continue

        matches.append(node)

    if len(matches) != 1:
        raise RuntimeError(
            f"卡片按钮映射定位异常：找到 {len(matches)} 处"
        )

    node = matches[0]

    if ast.literal_eval(node.value) != EXPECTED_TAGS:
        raise RuntimeError("卡片按钮原始分类映射不符合预期")

    original = ast.get_source_segment(source, node.value)

    if not original or source.count(original) != 1:
        raise RuntimeError("卡片按钮映射无法唯一定位")

    return {
        "id": "content.card_actions",
        "original": original,
        "template": "{text}",
        "count": 1,
    }


def main():
    if MANIFEST.exists():
        raise RuntimeError("当前存在汉化安装记录，请先恢复英文")

    _, version, root = installation()

    if version != "2.7.1":
        raise RuntimeError(f"暂不支持 Navigator {version}")

    rules_path = PROJECT / "patches" / "2.7.1.json"
    locale_path = PROJECT / "locales" / "zh_CN.json"

    rules_original = rules_path.read_bytes()
    locale_original = locale_path.read_bytes()

    rules = json.loads(rules_original)
    locale = json.loads(locale_original)

    if rules["version"] != version:
        raise RuntimeError("版本规则不匹配")

    if locale["language"] != "zh_CN":
        raise RuntimeError("语言包不匹配")

    targets = [
        (
            "widgets/tabs/home.py",
            "home.filter_updatable",
            "可更新的应用",
            find_home_rule,
        ),
        (
            "widgets/lists/content.py",
            "content.card_actions",
            CHINESE_TAGS,
            find_content_rule,
        ),
    ]

    files = {
        entry["path"]: entry
        for entry in rules["files"]
    }

    existing_ids = {
        rule["id"]
        for entry in rules["files"]
        for rule in entry["rules"]
    }

    for relative, rule_id, translation, finder in targets:
        if rule_id in existing_ids or rule_id in locale["messages"]:
            raise RuntimeError(f"翻译 ID 已存在：{rule_id}")

        path = root / relative
        source = path.read_bytes().decode("utf-8-sig")
        rule = finder(source)

        entry = files.get(relative)

        if entry is None:
            entry = {"path": relative, "rules": []}
            rules["files"].append(entry)
            files[relative] = entry

        entry["rules"].append(rule)
        locale["messages"][rule_id] = translation
        existing_ids.add(rule_id)

    for entry in rules["files"]:
        path = root / entry["path"]
        content = path.read_bytes().decode("utf-8-sig")

        for rule in entry["rules"]:
            actual = content.count(rule["original"])

            if actual != rule["count"]:
                raise RuntimeError(
                    f"{entry['path']} / {rule['id']}："
                    f"预期 {rule['count']} 处，实际 {actual} 处"
                )

            translated = json.dumps(
                locale["messages"][rule["id"]],
                ensure_ascii=False,
            )

            content = content.replace(
                rule["original"],
                rule["template"].format(text=translated),
            )

        ast.parse(content, filename=str(path))

    snapshots = PROJECT / "state" / "rule_snapshots"

    old_rules = snapshots / "2.7.1.before_batch5.json"
    old_locale = snapshots / "zh_CN.before_batch5.json"

    if old_rules.exists() or old_locale.exists():
        raise RuntimeError("第五批规则快照已经存在")

    snapshots.mkdir(parents=True, exist_ok=True)

    atomic_write(old_rules, rules_original)
    atomic_write(old_locale, locale_original)

    try:
        atomic_write(
            rules_path,
            (
                json.dumps(rules, ensure_ascii=False, indent=2)
                + "\n"
            ).encode("utf-8"),
        )

        atomic_write(
            locale_path,
            (
                json.dumps(locale, ensure_ascii=False, indent=2)
                + "\n"
            ).encode("utf-8"),
        )

    except Exception:
        atomic_write(rules_path, rules_original)
        atomic_write(locale_path, locale_original)
        raise

    print("第五批规则生成成功")
    print("新增翻译规则：2 组")
    print(f"累计涉及源码文件：{len(rules['files'])}")
    print("全部规则及 Python 语法检查通过")
    print("Navigator 安装文件尚未修改")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"生成失败：{error}")
        raise SystemExit(1)