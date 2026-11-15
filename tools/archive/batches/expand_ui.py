import ast
import json

from core.engine import MANIFEST, PROJECT, atomic_write, installation


ITEMS = [
    ("widgets/tabs/home.py", "home.channels", "ButtonHomeChannels", "Channels", "软件源"),
    ("widgets/tabs/home.py", "home.on", "LabelHome", "on", "位于"),

    ("widgets/tabs/environments.py", "env.create", "ButtonToolNormal", "Create", "创建"),
    ("widgets/tabs/environments.py", "env.clone", "ButtonToolNormal", "Clone", "克隆"),
    ("widgets/tabs/environments.py", "env.import", "ButtonToolNormal", "Import", "导入"),
    ("widgets/tabs/environments.py", "env.backup", "ButtonToolNormal", "Backup", "备份"),
    ("widgets/tabs/environments.py", "env.remove", "ButtonToolNormal", "Remove", "删除"),
    ("widgets/tabs/environments.py", "env.search", "setPlaceholderText", "Search Environments", "搜索环境"),
    ("widgets/tabs/environments.py", "env.terminal", "addAction", "Open Terminal", "打开终端"),

    ("widgets/lists/apps.py", "apps.install", "ButtonApplicationInstall", "Install", "安装"),
    ("widgets/lists/apps.py", "apps.launch", "ButtonApplicationLaunch", "Launch", "启动"),
    ("widgets/lists/apps.py", "apps.options", "QMenu", "Application options", "应用选项"),
    ("widgets/lists/apps.py", "apps.version", "QMenu", "Install specific version", "安装指定版本"),

    ("widgets/dialogs/login/reminder/login_welcome.py", "welcome.assistant", "QLabel", "Access Anaconda Assistant in Jupyter Notebooks and JupyterLab.", "在 Jupyter Notebook 和 JupyterLab 中使用 Anaconda Assistant。"),
    ("widgets/dialogs/login/reminder/login_welcome.py", "welcome.remember", "CheckBoxBase", "Do not show again", "不再显示"),
    ("widgets/dialogs/login/reminder/login_welcome.py", "welcome.sign_in", "ButtonPrimary", "Sign In", "登录"),
    ("widgets/dialogs/login/reminder/login_welcome.py", "welcome.repository", "ButtonSecondaryTextual", "Connect to a Repository", "连接到软件仓库"),
    ("widgets/dialogs/login/reminder/login_welcome.py", "welcome.no_account", "QLabel", "Don’t have an account? ", "还没有账号？ "),
    ("widgets/dialogs/login/reminder/login_welcome.py", "welcome.sign_up", "ButtonLink", "Sign Up", "注册"),

    ("widgets/dialogs/login/account_dialogs.py", "account.title", None, "Connect to Anaconda", "连接 Anaconda"),
    ("widgets/dialogs/login/account_dialogs.py", "account.repositories", None, "REPOSITORIES", "软件仓库"),
    ("widgets/dialogs/login/account_dialogs.py", "account.sign_in", None, "SIGN IN", "登录"),

    ("widgets/tabs/community.py", "community.search", "setPlaceholderText", "Search", "搜索"),

    ("widgets/dialogs/channels.py", "channels.intro", "LabelBase", "Manage channels you want Navigator to include.", "管理 Navigator 使用的软件源。"),
    ("widgets/dialogs/channels.py", "channels.collecting", "LabelBase", "Collecting sources...", "正在获取软件源…"),
    ("widgets/dialogs/channels.py", "channels.add", "ButtonNormal", "Add...", "添加…"),
    ("widgets/dialogs/channels.py", "channels.cancel", "ButtonNormal", "Cancel", "取消"),
    ("widgets/dialogs/channels.py", "channels.update", "ButtonPrimary", "Update channels", "更新软件源"),
]


def name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def unique_context(source, node):
    lines = source.splitlines(keepends=True)

    start = node.lineno - 1
    end = node.end_lineno

    if start < 0 or end > len(lines):
        raise ValueError("源码行号超出范围")

    while True:
        segment = "".join(lines[start:end])

        if source.count(segment) == 1:
            return segment

        if start > 0:
            start -= 1
        elif end < len(lines):
            end += 1
        else:
            raise ValueError("无法生成唯一的源码上下文")


def make_rule(source, method, english, rule_id):
    tree = ast.parse(source)
    found = []

    if method is None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == english:
                found.append((node, node))
    else:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            if name(node.func) != method:
                continue

            args = list(node.args)
            args.extend(item.value for item in node.keywords)

            for item in args:
                if isinstance(item, ast.Constant) and item.value == english:
                    found.append((node, item))

    if len(found) != 1:
        raise ValueError(
            f"{rule_id}: 找到 {len(found)} 个 AST 目标，无法唯一定位"
        )

    call, literal = found[0]

    original = ast.get_source_segment(source, call)
    old_literal = ast.get_source_segment(source, literal)

    if not original or not old_literal:
        raise ValueError(f"{rule_id}: 无法提取源码")

    if source.count(original) != 1 or original.count(old_literal) != 1:
        original = unique_context(source, literal)

    if source.count(original) != 1:
        raise ValueError(f"{rule_id}: 替换范围仍然重复")

    if original.count(old_literal) != 1:
        raise ValueError(f"{rule_id}: 目标字面量无法唯一定位")

    marker = "__NAVIGATOR_ZH_TEXT__"

    if marker in original:
        raise ValueError(f"{rule_id}: 占位符冲突")

    template = original.replace(old_literal, marker, 1)
    template = template.replace("{", "{{").replace("}", "}}")
    template = template.replace(marker, "{text}")

    return {
        "id": rule_id,
        "original": original,
        "template": template,
        "count": 1
    }


def main():
    if MANIFEST.exists():
        raise RuntimeError("当前已有汉化记录，请先恢复原版")

    _, version, root = installation()

    if version != "2.7.1":
        raise RuntimeError(f"暂不支持 Navigator {version}")

    rules_path = PROJECT / "patches" / "2.7.1.json"
    locale_path = PROJECT / "locales" / "zh_CN.json"

    rules_raw = rules_path.read_bytes()
    locale_raw = locale_path.read_bytes()

    rules = json.loads(rules_raw)
    locale = json.loads(locale_raw)

    if rules.get("version") != version:
        raise RuntimeError("版本适配规则不一致")

    if locale.get("language") != "zh_CN":
        raise RuntimeError("语言包标识不一致")

    files_by_path = {
        item["path"]: item for item in rules["files"]
    }

    ids = {
        rule["id"]
        for item in rules["files"]
        for rule in item["rules"]
    }

    added = 0

    for relative, rule_id, method, english, chinese in ITEMS:
        if rule_id in ids or rule_id in locale["messages"]:
            raise RuntimeError(f"翻译 ID 已存在：{rule_id}")

        path = root / relative

        if not path.is_file():
            raise RuntimeError(f"源码文件不存在：{path}")

        source = path.read_bytes().decode("utf-8-sig")
        rule = make_rule(source, method, english, rule_id)

        entry = files_by_path.get(relative)

        if entry is None:
            entry = {
                "path": relative,
                "rules": []
            }
            files_by_path[relative] = entry
            rules["files"].append(entry)

        entry["rules"].append(rule)
        locale["messages"][rule_id] = chinese

        ids.add(rule_id)
        added += 1

    for entry in rules["files"]:
        path = root / entry["path"]
        content = path.read_bytes().decode("utf-8-sig")

        for rule in entry["rules"]:
            count = content.count(rule["original"])

            if count != rule["count"]:
                raise RuntimeError(
                    f"{entry['path']} / {rule['id']}: "
                    f"匹配数 {count}，预期 {rule['count']}"
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
    snapshots.mkdir(parents=True, exist_ok=True)

    previous_rules = snapshots / "2.7.1.before_ui_batch.json"
    previous_locale = snapshots / "zh_CN.before_ui_batch.json"

    if previous_rules.exists() or previous_locale.exists():
        raise RuntimeError("规则快照已存在，请先检查")

    atomic_write(previous_rules, rules_raw)
    atomic_write(previous_locale, locale_raw)

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
        atomic_write(rules_path, rules_raw)
        atomic_write(locale_path, locale_raw)
        raise

    print(f"新增翻译规则：{added}")
    print(f"涉及源码文件：{len({item[0] for item in ITEMS})}")
    print("规则检查及 Python 语法检查通过")
    print("Navigator 安装文件尚未修改")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"生成失败：{error}")
        raise SystemExit(1)