import ast
import json

from core.engine import MANIFEST, PROJECT, atomic_write, installation


SPECS = [
    ("widgets/dialogs/environment/import_dialogs.py",
     "ImportSelectorDialog.__init__", "Import Environment", "导入环境"),
    ("widgets/dialogs/environment/import_dialogs.py",
     "ImportSelectorDialog.__init_header__", "Import from:", "导入来源："),
    ("widgets/dialogs/environment/import_dialogs.py",
     "ImportSelectorDialog.__init_footer__", "New environment name:", "新环境名称："),
    ("widgets/dialogs/environment/import_dialogs.py",
     "ImportSelectorDialog.__init_actions__", "Import", "导入"),
    ("widgets/dialogs/environment/import_dialogs.py",
     "ImportSelectorDialog.__init_actions__", "Cancel", "取消"),

    ("widgets/dialogs/environment/backup_dialogs.py",
     "BackupSelectorDialog.__init__", "Backup Environment", "备份环境"),
    ("widgets/dialogs/environment/backup_dialogs.py",
     "BackupSelectorDialog.__init_header__",
     "Select location to backup environment:", "选择环境备份位置："),
    ("widgets/dialogs/environment/backup_dialogs.py",
     "BackupSelectorDialog.__init_footer__", "Backup as:", "备份名称："),
    ("widgets/dialogs/environment/backup_dialogs.py",
     "BackupSelectorDialog.__init_actions__", "Backup", "备份"),
    ("widgets/dialogs/environment/backup_dialogs.py",
     "BackupSelectorDialog.__init_actions__", "Cancel", "取消"),

    ("widgets/dialogs/environment/multiaccount_dialogs.py",
     "SelectorDialog.__init_form__", "Local drive", "本地磁盘"),
    ("widgets/dialogs/environment/multiaccount_dialogs.py",
     "PrepopulatedSelectorDialog.__init_footer__",
     "Overwrite existing environment", "覆盖现有环境"),

    ("widgets/dialogs/environment/clone_dialogs.py",
     "CloneDialog.__init__", "Clone from environment: ", "克隆自环境："),
]


def scope_of(node, parents):
    result = []

    while node in parents:
        node = parents[node]

        if isinstance(node, (
            ast.ClassDef,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        )):
            result.append(node.name)

    return ".".join(reversed(result))


def make_literal_rule(source, scope_name, english, rule_id):
    tree = ast.parse(source)

    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value == english
        and scope_of(node, parents) == scope_name
    ]

    if len(matches) != 1:
        raise ValueError(f"AST 匹配数量为 {len(matches)}")

    node = matches[0]
    literal = ast.get_source_segment(source, node)

    if not literal:
        raise ValueError("无法取得原始字符串")

    lines = source.splitlines(keepends=True)
    start = node.lineno - 1
    end = node.end_lineno

    while True:
        original = "".join(lines[start:end])

        if (
            source.count(original) == 1
            and original.count(literal) == 1
        ):
            break

        if start > 0:
            start -= 1
        elif end < len(lines):
            end += 1
        else:
            raise ValueError("无法构建唯一源码范围")

    marker = "__NAVZH_TEXT__"

    template = original.replace(literal, marker, 1)
    template = template.replace("{", "{{").replace("}", "}}")
    template = template.replace(marker, "{text}")

    return {
        "id": rule_id,
        "original": original,
        "template": template,
        "count": 1,
    }


def make_about_rule(source):
    english = (
        "For bug reports and feature requests, "
        "please visit our"
    )

    chinese = "如需报告问题或提出功能建议，请访问 GitHub 上的"

    tree = ast.parse(source)

    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        and any(
            isinstance(part, ast.Constant)
            and isinstance(part.value, str)
            and english in part.value
            for part in node.values
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            f"关于窗口正文匹配到 {len(matches)} 处"
        )

    original = ast.get_source_segment(source, matches[0])

    if not original or source.count(original) != 1:
        raise ValueError("无法唯一定位关于窗口正文")

    marker = "__NAVZH_ABOUT_TEXT__"

    template = original.replace(english, marker, 1)
    template = template.replace("{", "{{").replace("}", "}}")
    template = template.replace(marker, "{{{text}}}")

    return {
        "id": "batch8.about_description",
        "original": original,
        "template": template,
        "count": 1,
    }, chinese


def validate(rules, locale, root):
    for entry in rules["files"]:
        path = root / entry["path"]
        content = path.read_bytes().decode("utf-8-sig")

        for rule in entry["rules"]:
            count = content.count(rule["original"])

            if count != rule["count"]:
                raise ValueError(
                    f"{entry['path']} / {rule['id']}："
                    f"匹配数 {count}"
                )

            value = json.dumps(
                locale["messages"][rule["id"]],
                ensure_ascii=False,
            )

            content = content.replace(
                rule["original"],
                rule["template"].format(text=value),
            )

        ast.parse(content, filename=str(path))


def main():
    if MANIFEST.exists():
        raise RuntimeError("请先恢复当前汉化版本")

    _, version, root = installation()

    if version != "2.7.1":
        raise RuntimeError(f"暂不支持 Navigator {version}")

    rules_path = PROJECT / "patches" / "2.7.1.json"
    locale_path = PROJECT / "locales" / "zh_CN.json"

    original_rules = rules_path.read_bytes()
    original_locale = locale_path.read_bytes()

    rules = json.loads(original_rules)
    locale = json.loads(original_locale)

    if rules["version"] != version:
        raise RuntimeError("版本规则不匹配")

    files = {
        item["path"]: item
        for item in rules["files"]
    }

    ids = {
        rule["id"]
        for item in rules["files"]
        for rule in item["rules"]
    }

    skipped = []
    added = 0

    def add(relative, rule, translation):
        nonlocal added

        if rule["id"] in ids:
            raise ValueError("翻译 ID 已存在")

        entry = files.get(relative)
        created = entry is None

        if created:
            entry = {"path": relative, "rules": []}
            files[relative] = entry
            rules["files"].append(entry)

        entry["rules"].append(rule)
        locale["messages"][rule["id"]] = translation

        try:
            validate(rules, locale, root)
        except Exception:
            entry["rules"].pop()
            del locale["messages"][rule["id"]]

            if created:
                rules["files"].remove(entry)
                del files[relative]

            raise

        ids.add(rule["id"])
        added += 1

    for index, (relative, scope, english, chinese) in enumerate(SPECS, 1):
        rule_id = f"batch8.environment.{index:02d}"

        try:
            source = (root / relative).read_bytes().decode("utf-8-sig")
            rule = make_literal_rule(
                source, scope, english, rule_id
            )
            add(relative, rule, chinese)

        except (ValueError, OSError, SyntaxError) as error:
            skipped.append(f"{rule_id}: {error}")

    relative = "widgets/dialogs/about.py"

    try:
        source = (root / relative).read_bytes().decode("utf-8-sig")
        rule, translation = make_about_rule(source)
        add(relative, rule, translation)

    except (ValueError, OSError, SyntaxError) as error:
        skipped.append(f"batch8.about_description: {error}")

    about_rule = next(
        (
            rule
            for entry in rules["files"]
            if entry["path"] == relative
            for rule in entry["rules"]
            if "ButtonLabel('on GitHub.')" in rule["original"]
        ),
        None,
    )

    if about_rule is not None:
        locale["messages"][about_rule["id"]] = "。"

    validate(rules, locale, root)

    if added == 0:
        raise RuntimeError("本批没有生成可用规则")

    snapshots = PROJECT / "state" / "rule_snapshots"

    old_rules = snapshots / "2.7.1.before_batch8.json"
    old_locale = snapshots / "zh_CN.before_batch8.json"

    if old_rules.exists() or old_locale.exists():
        raise RuntimeError("第八批快照已存在")

    snapshots.mkdir(parents=True, exist_ok=True)

    atomic_write(old_rules, original_rules)
    atomic_write(old_locale, original_locale)

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
        atomic_write(rules_path, original_rules)
        atomic_write(locale_path, original_locale)
        raise

    print(f"新增规则：{added}")
    print(f"未生成候选：{len(skipped)}")
    print(f"累计源码文件：{len(rules['files'])}")
    print("全部规则与 Python 语法检查通过")

    for item in skipped:
        print(item)

    print("Navigator 安装文件尚未修改")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"生成失败：{error}")
        raise SystemExit(1)