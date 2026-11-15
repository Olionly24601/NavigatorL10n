import ast
import json

from core.engine import MANIFEST, PROJECT, atomic_write, installation


MARKER = "___NAVZH_TEXT_PLACEHOLDER___"

TARGETS = [
    ("widgets/dialogs/update.py", "update.notice", "notice", "",
     "There's a new version of Anaconda Navigator available.",
     "Anaconda Navigator 有新版本可用，建议更新。<br><br>"
     "点击「是」后，Navigator 将关闭并启动更新程序。<br><br><br>"
     "现在更新到 <b>Anaconda Navigator {version}</b> 吗？"
     "<br>{extra_text}<br>"),

    ("widgets/dialogs/update.py", "update.title", "call",
     "setWindowTitle", "Update Application", "更新应用程序"),

    ("widgets/dialogs/update.py", "update.yes", "call",
     "ButtonPrimary", "Yes", "是"),

    ("widgets/dialogs/update.py", "update.remind", "call",
     "ButtonNormal", "No, remind me later", "否，稍后提醒"),

    ("widgets/dialogs/update.py", "update.suppress", "call",
     "ButtonNormal", "No, don't show again", "否，不再提示"),

    ("widgets/dialogs/update.py", "update.no", "call",
     "setText", "No", "否"),

    ("widgets/manager/packages.py", "packages.channels", "call",
     "_", "Channels", "软件源"),

    ("widgets/manager/packages.py", "packages.update_index", "call",
     "_", "Update index...", "更新索引…"),

    ("widgets/manager/packages.py", "packages.search", "call",
     "setPlaceholderText", "Search Packages", "搜索软件包"),

    ("widgets/tabs/home.py", "home.filter_all", "call",
     "ApplicationFilterDetails", "All applications", "所有应用"),

    ("widgets/tabs/home.py", "home.filter_installed", "call",
     "ApplicationFilterDetails", "Installed applications", "已安装的应用"),

    ("widgets/tabs/home.py", "home.filter_uninstalled", "call",
     "ApplicationFilterDetails", "Not installed applications", "未安装的应用"),

    ("widgets/dialogs/login/reminder/login_welcome.py",
     "welcome.title", "literal", "LoginReminderDialog.__init__",
     "Sign in for AI Coding Help", "登录以使用 AI 编程助手"),

    ("widgets/dialogs/login/account_dialogs.py",
     "account.sign_in_link", "html", "AccountEntry.prepare",
     "SIGN IN", "登录"),

    ("widgets/manager/model.py", "packages.column_name", "literal",
     "CondaPackagesModel.headerData", "Name", "名称"),

    ("widgets/manager/model.py", "packages.column_version", "literal",
     "CondaPackagesModel.headerData", "Version", "版本"),

    ("widgets/manager/model.py", "packages.column_description", "literal",
     "CondaPackagesModel.headerData", "Description", "描述"),

    ("widgets/manager/model.py", "packages.column_status", "literal",
     "CondaPackagesModel.headerData", "Status", "状态"),
]


def name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def scope(node, parents):
    names = []
    current = node

    while current in parents:
        current = parents[current]

        if isinstance(
            current,
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            names.append(current.name)

    return ".".join(reversed(names))


def make_rule(source, key, mode, needle, english):
    tree = ast.parse(source)

    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    candidates = []

    for node in ast.walk(tree):
        if mode == "call" and isinstance(node, ast.Call):
            if name(node.func) != needle:
                continue

            arguments = [
                *node.args,
                *(kw.value for kw in node.keywords)
            ]

            for literal in arguments:
                if not isinstance(literal, ast.Constant):
                    continue

                if literal.value != english:
                    continue

                expression = ast.get_source_segment(source, node)
                old = ast.get_source_segment(source, literal)

                if expression and old and expression.count(old) == 1:
                    candidates.append((
                        node,
                        expression.replace(old, MARKER, 1)
                    ))

        elif mode == "literal" and isinstance(node, ast.Constant):
            if node.value == english and scope(node, parents) == needle:
                candidates.append((node, MARKER))

        elif mode == "notice" and isinstance(node, ast.Call):
            if name(node.func) != "QLabel":
                continue

            if any(
                isinstance(item, ast.Constant)
                and isinstance(item.value, str)
                and english in item.value
                for item in ast.walk(node)
            ):
                candidates.append((node, f"QLabel(f{MARKER})"))

        elif mode == "html" and isinstance(node, ast.JoinedStr):
            if scope(node, parents) != needle:
                continue

            if not any(
                isinstance(item, ast.Constant)
                and isinstance(item.value, str)
                and english in item.value
                for item in node.values
            ):
                continue

            expression = ast.get_source_segment(source, node)

            if expression and expression.count(english) == 1:
                replacement = expression.replace(
                    english, "{" + MARKER + "}", 1
                )
                candidates.append((node, replacement))

    if len(candidates) != 1:
        raise ValueError(
            f"{key}：找到 {len(candidates)} 个 AST 候选，无法唯一定位"
        )

    node, replacement = candidates[0]
    expression = ast.get_source_segment(source, node)

    if not expression:
        raise ValueError(f"{key}：无法提取源码表达式")

    if source.count(expression) == 1:
        original = expression
        changed = replacement

    else:
        lines = source.splitlines(keepends=True)
        start = node.lineno - 1
        end = node.end_lineno

        while True:
            original = "".join(lines[start:end])

            if (
                source.count(original) == 1
                and original.count(expression) == 1
            ):
                changed = original.replace(
                    expression, replacement, 1
                )
                break

            if start > 0:
                start -= 1
            elif end < len(lines):
                end += 1
            else:
                raise ValueError(
                    f"{key}：无法构建唯一替换范围"
                )

    template = (
        changed
        .replace("{", "{{")
        .replace("}", "}}")
        .replace(MARKER, "{text}")
    )

    return {
        "id": key,
        "original": original,
        "template": template,
        "count": 1
    }


def main():
    if MANIFEST.exists():
        raise RuntimeError(
            "当前已安装汉化，请先恢复原始英文版本"
        )

    prefix, version, root = installation()

    if version != "2.7.1":
        raise RuntimeError(
            f"当前版本 {version} 不在本批规则适配范围内"
        )

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
        entry["path"]: entry
        for entry in rules["files"]
    }

    existing_ids = {
        rule["id"]
        for entry in rules["files"]
        for rule in entry["rules"]
    }

    source_cache = {}

    for relative, key, mode, needle, english, chinese in TARGETS:
        if key in existing_ids or key in locale["messages"]:
            raise RuntimeError(f"翻译 ID 已存在：{key}")

        path = root / relative

        if not path.is_file():
            raise RuntimeError(f"源码文件不存在：{relative}")

        if relative not in source_cache:
            source_cache[relative] = path.read_bytes().decode("utf-8-sig")

        rule = make_rule(
            source_cache[relative],
            key,
            mode,
            needle,
            english
        )

        if relative not in files:
            entry = {
                "path": relative,
                "rules": []
            }
            files[relative] = entry
            rules["files"].append(entry)

        files[relative]["rules"].append(rule)
        locale["messages"][key] = chinese
        existing_ids.add(key)

    for entry in rules["files"]:
        path = root / entry["path"]
        content = path.read_bytes().decode("utf-8-sig")

        for rule in entry["rules"]:
            if content.count(rule["original"]) != rule["count"]:
                raise RuntimeError(
                    f"{entry['path']} / {rule['id']}："
                    "匹配数量不正确"
                )

            translated = json.dumps(
                locale["messages"][rule["id"]],
                ensure_ascii=False
            )

            content = content.replace(
                rule["original"],
                rule["template"].format(text=translated)
            )

        ast.parse(content, filename=str(path))

    snapshots = PROJECT / "state" / "rule_snapshots"

    old_rules = snapshots / "2.7.1.before_batch4.json"
    old_locale = snapshots / "zh_CN.before_batch4.json"

    if old_rules.exists() or old_locale.exists():
        raise RuntimeError("第四批规则快照已存在")

    snapshots.mkdir(parents=True, exist_ok=True)

    atomic_write(old_rules, rules_original)
    atomic_write(old_locale, locale_original)

    try:
        atomic_write(
            rules_path,
            (
                json.dumps(rules, ensure_ascii=False, indent=2)
                + "\n"
            ).encode("utf-8")
        )

        atomic_write(
            locale_path,
            (
                json.dumps(locale, ensure_ascii=False, indent=2)
                + "\n"
            ).encode("utf-8")
        )

    except Exception:
        atomic_write(rules_path, rules_original)
        atomic_write(locale_path, locale_original)
        raise

    print(f"Navigator：{version}")
    print(f"新增规则：{len(TARGETS)}")
    print(f"本批涉及源码文件：{len(source_cache)}")
    print(f"全部规则涉及源码文件：{len(rules['files'])}")
    print("规则匹配和 Python 语法检查通过")
    print("已保存第四批修改前的规则快照")
    print("Navigator 安装文件尚未修改")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"生成失败：{error}")
        raise SystemExit(1)