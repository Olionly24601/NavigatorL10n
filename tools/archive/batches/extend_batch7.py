import ast
import json
from pathlib import Path

from core.engine import MANIFEST, PROJECT, atomic_write, installation


TAGS = {
    "documentation": "文档",
    "training": "培训",
    "forum": "论坛",
    "social": "社交",
}

SPECS = [
    ("widgets/dialogs/__init__.py", "ActionsDialog.__init__", "ButtonDanger", "Cancel", "取消"),
    ("widgets/dialogs/__init__.py", "ActionsDialog.__init__", "ButtonPrimary", "Ok", "确定"),
    ("widgets/dialogs/__init__.py", "ActionsDialog.__init__", "setWindowTitle", "Proceed with the following actions?", "确定执行以下操作？"),

    ("widgets/dialogs/__init__.py", "InputDialog.__init__", "ButtonPrimary", "Ok", "确定"),
    ("widgets/dialogs/__init__.py", "InputDialog.__init__", "ButtonNormal", "Cancel", "取消"),

    ("widgets/dialogs/__init__.py", "MessageBox.__init__", "ButtonPrimary", "Ok", "确定"),
    ("widgets/dialogs/__init__.py", "MessageBox.__init__", "ButtonPrimary", "Yes", "是"),
    ("widgets/dialogs/__init__.py", "MessageBox.__init__", "ButtonNormal", "No", "否"),
    ("widgets/dialogs/__init__.py", "MessageBox.__init__", "ButtonNormal", "Copy text", "复制文本"),
    ("widgets/dialogs/__init__.py", "MessageBox.__init__", "ButtonNormal", "Learn more", "了解更多"),
    ("widgets/dialogs/__init__.py", "MessageBox.__init__", "ButtonDanger", "Remove", "删除"),
    ("widgets/dialogs/__init__.py", "MessageBox.__init__", "ButtonNormal", "Cancel", "取消"),
    ("widgets/dialogs/__init__.py", "MessageBox.__init__", "ButtonNormal", "Report Issue", "报告问题"),

    ("widgets/dialogs/environment/create_dialogs.py", "CreateDialog.__init__", "setWindowTitle", "Create new environment", "创建新环境"),
    ("widgets/dialogs/environment/create_dialogs.py", "CreateDialog.__init__", "LabelBase", "Name:", "名称："),
    ("widgets/dialogs/environment/create_dialogs.py", "CreateDialog.__init__", "setPlaceholderText", "New environment name", "新环境名称"),
    ("widgets/dialogs/environment/create_dialogs.py", "CreateDialog.__init__", "LabelBase", "Location:", "位置："),
    ("widgets/dialogs/environment/create_dialogs.py", "CreateDialog.__init__", "LabelBase", "Packages:", "软件包："),
    ("widgets/dialogs/environment/create_dialogs.py", "CreateDialog.__init__", "ButtonPrimary", "Create", "创建"),
    ("widgets/dialogs/environment/create_dialogs.py", "CreateDialog.__init__", "ButtonNormal", "Cancel", "取消"),

    ("widgets/dialogs/environment/clone_dialogs.py", "CloneDialog.__init__", "LabelBase", "Name:", "名称："),
    ("widgets/dialogs/environment/clone_dialogs.py", "CloneDialog.__init__", "LabelBase", "Location:", "位置："),
    ("widgets/dialogs/environment/clone_dialogs.py", "CloneDialog.__init__", "ButtonPrimary", "Clone", "克隆"),
    ("widgets/dialogs/environment/clone_dialogs.py", "CloneDialog.__init__", "ButtonNormal", "Cancel", "取消"),
    ("widgets/dialogs/environment/clone_dialogs.py", "CloneDialog.__init__", "setWindowTitle", "Clone from environment: ", "克隆自环境："),
    ("widgets/dialogs/environment/clone_dialogs.py", "CloneDialog.__init__", "setPlaceholderText", "New environment name", "新环境名称"),

    ("widgets/dialogs/about.py", "AboutDialog.__init__", "ButtonLink", "Issue Tracker", "问题追踪"),
    ("widgets/dialogs/about.py", "AboutDialog.__init__", "ButtonLabel", "on GitHub.", "在 GitHub 上。"),
    ("widgets/dialogs/about.py", "AboutDialog.__init__", "ButtonNormal", "Ok", "确定"),
    ("widgets/dialogs/about.py", "AboutDialog.__init__", "setWindowTitle", "About Anaconda Navigator", "关于 Anaconda Navigator"),

    ("widgets/dialogs/packages.py", "PackagesDialog.__init__", "ButtonPrimary", "Apply", "应用"),
    ("widgets/dialogs/packages.py", "PackagesDialog.__init__", "ButtonNormal", "Cancel", "取消"),
    ("widgets/dialogs/packages.py", "PackagesDialog.__init__", "setWindowTitle", "Remove Packages", "删除软件包"),
    ("widgets/dialogs/packages.py", "PackagesDialog.__init__", "setWindowTitle", "Update Packages", "更新软件包"),
    ("widgets/dialogs/packages.py", "PackagesDialog.__init__", "setWindowTitle", "Install Packages", "安装软件包"),
]


def function_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def node_scope(node, parents):
    result = []

    while node in parents:
        node = parents[node]

        if isinstance(
            node,
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            result.append(node.name)

    return ".".join(reversed(result))


def make_rule(source, scope_name, method, english, rule_id):
    tree = ast.parse(source)

    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    matches = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if function_name(node.func) != method:
            continue

        if node_scope(node, parents) != scope_name:
            continue

        arguments = [
            *node.args,
            *(item.value for item in node.keywords),
        ]

        for argument in arguments:
            if (
                isinstance(argument, ast.Constant)
                and argument.value == english
            ):
                matches.append((node, argument))

    if len(matches) != 1:
        raise ValueError(
            f"AST 匹配数量为 {len(matches)}"
        )

    call, literal = matches[0]
    expression = ast.get_source_segment(source, call)
    old_literal = ast.get_source_segment(source, literal)

    if not expression or not old_literal:
        raise ValueError("无法提取源码表达式")

    if expression.count(old_literal) != 1:
        raise ValueError("表达式中存在重复字面量")

    if source.count(expression) == 1:
        original = expression
    else:
        lines = source.splitlines(keepends=True)
        start = call.lineno - 1
        end = call.end_lineno

        while True:
            original = "".join(lines[start:end])

            if (
                source.count(original) == 1
                and original.count(expression) == 1
                and original.count(old_literal) == 1
            ):
                break

            if start > 0:
                start -= 1
            elif end < len(lines):
                end += 1
            else:
                raise ValueError("无法构造唯一源码上下文")

    marker = "__NAVZH_TRANSLATION__"

    if marker in original:
        raise ValueError("翻译占位符冲突")

    template = original.replace(old_literal, marker, 1)
    template = template.replace("{", "{{").replace("}", "}}")
    template = template.replace(marker, "{text}")

    return {
        "id": rule_id,
        "original": original,
        "template": template,
        "count": 1,
    }


def make_tag_rule(source):
    original = "f'{tag.capitalize()} ({count})'.strip()"

    if source.count(original) != 1:
        raise ValueError(
            f"标签显示表达式匹配到 {source.count(original)} 处"
        )

    return {
        "id": "content.category_labels",
        "original": original,
        "template": (
            "f'{{ {text}.get(tag.lower(), tag.capitalize())}} "
            "({{count}})'.strip()"
        ),
        "count": 1,
    }


def validate(rules, locale, root):
    for entry in rules["files"]:
        path = root / entry["path"]
        content = path.read_bytes().decode("utf-8-sig")

        for rule in entry["rules"]:
            actual = content.count(rule["original"])

            if actual != rule["count"]:
                raise ValueError(
                    f"{entry['path']} / {rule['id']}："
                    f"匹配数量 {actual}"
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
        raise RuntimeError("请先恢复当前安装的汉化版本")

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

    def append_rule(relative, rule, translation):
        nonlocal added

        entry = files.get(relative)

        if entry is None:
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

            if not entry["rules"]:
                rules["files"].remove(entry)
                del files[relative]

            raise

        ids.add(rule["id"])
        added += 1

    relative = "widgets/tabs/community.py"

    try:
        source = (root / relative).read_bytes().decode("utf-8-sig")
        rule = make_tag_rule(source)

        if rule["id"] in ids:
            raise ValueError("翻译 ID 已存在")

        append_rule(relative, rule, TAGS)

    except (ValueError, OSError, SyntaxError) as error:
        skipped.append(
            f"content.category_labels：{error}"
        )

    for index, spec in enumerate(SPECS, 1):
        relative, scope_name, method, english, chinese = spec
        rule_id = f"batch7.dialog.{index:02d}"

        try:
            if rule_id in ids:
                raise ValueError("翻译 ID 已存在")

            source = (root / relative).read_bytes().decode(
                "utf-8-sig"
            )

            rule = make_rule(
                source,
                scope_name,
                method,
                english,
                rule_id,
            )

            append_rule(relative, rule, chinese)

        except (ValueError, OSError, SyntaxError) as error:
            skipped.append(f"{rule_id}：{error}")

    if added == 0:
        raise RuntimeError("没有生成任何新规则")

    validate(rules, locale, root)

    snapshots = PROJECT / "state" / "rule_snapshots"
    old_rules = snapshots / "2.7.1.before_batch7.json"
    old_locale = snapshots / "zh_CN.before_batch7.json"

    if old_rules.exists() or old_locale.exists():
        raise RuntimeError("第七批快照已存在")

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

    print(f"新增规则：{added}")
    print(f"未生成的候选：{len(skipped)}")
    print(f"累计涉及源码文件：{len(rules['files'])}")
    print("源码兼容性和 Python 语法检查通过")
    print("已保存原始规则快照")

    if skipped:
        print("\n未生成的候选：")
        for item in skipped:
            print(item)

    print("\nNavigator 安装文件尚未修改")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"生成失败：{error}")
        raise SystemExit(1)