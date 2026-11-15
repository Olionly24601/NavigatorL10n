import ast
import json

from core.engine import MANIFEST, PROJECT, atomic_write, installation


TARGETS = [
    (
        "widgets/dialogs/environment/multiaccount_dialogs.py",
        "PrepopulatedSelectorDialog.__refresh_cloud_form__",
        "Sign in</a> to save your environment",
        "登录</a>后可将环境保存到云端",
        "contains",
    ),
    (
        "widgets/dialogs/environment/multiaccount_dialogs.py",
        "PrepopulatedSelectorDialog.__refresh_cloud_form__",
        "You are in offline mode, cloud options are disabled",
        "当前处于离线模式，云端选项不可用",
        "contains",
    ),

    (
        "widgets/dialogs/environment/import_dialogs.py",
        "EnvSelectorDialog.__init__",
        "Select environment from Cloud:",
        "从云端选择环境：",
        "contains",
    ),
    (
        "widgets/dialogs/environment/import_dialogs.py",
        "EnvSelectorDialog.__init__",
        "Cancel",
        "取消",
        "exact",
    ),
    (
        "widgets/dialogs/environment/import_dialogs.py",
        "EnvSelectorDialog.__init__",
        "Select",
        "选择",
        "exact",
    ),
    (
        "widgets/dialogs/environment/import_dialogs.py",
        "EnvSelectorDialog.__init__",
        "Import New Environment",
        "导入新环境",
        "exact",
    ),
    (
        "widgets/dialogs/environment/import_dialogs.py",
        "EnvSelectorItem._get_env_item_layout",
        "Download environment file",
        "下载环境文件",
        "exact",
    ),

    (
        "widgets/manager/table.py",
        "TableCondaPackages.filter_changed",
        "0 packages available ",
        "0 个软件包可用 ",
        "exact",
    ),
    (
        "widgets/manager/table.py",
        "TableCondaPackages.filter_changed",
        "1 package available ",
        "1 个软件包可用 ",
        "exact",
    ),
    (
        "widgets/manager/table.py",
        "TableCondaPackages.filter_changed",
        " packages available ",
        " 个软件包可用 ",
        "exact",
    ),
    (
        "widgets/manager/table.py",
        "TableCondaPackages.filter_changed",
        "matching \"{0}\"",
        "匹配“{0}”",
        "exact",
    ),

    (
        "widgets/manager/table.py",
        "TableCondaPackages.context_menu_requested",
        "Unmark",
        "取消标记",
        "exact",
    ),
    (
        "widgets/manager/table.py",
        "TableCondaPackages.context_menu_requested",
        "Mark for installation",
        "标记为待安装",
        "exact",
    ),
    (
        "widgets/manager/table.py",
        "TableCondaPackages.context_menu_requested",
        "Mark for update",
        "标记为待更新",
        "exact",
    ),
    (
        "widgets/manager/table.py",
        "TableCondaPackages.context_menu_requested",
        "Mark for removal",
        "标记为待删除",
        "exact",
    ),
    (
        "widgets/manager/table.py",
        "TableCondaPackages.context_menu_requested",
        "Mark for specific version installation",
        "安装指定版本",
        "exact",
    ),
    (
        "widgets/manager/table.py",
        "TableCondaPackages.context_menu_requested",
        "Python Package Index",
        "Python 软件包索引",
        "exact",
    ),
    (
        "widgets/manager/table.py",
        "TableCondaPackages.context_menu_requested",
        "Homepage",
        "主页",
        "exact",
    ),
    (
        "widgets/manager/table.py",
        "TableCondaPackages.context_menu_requested",
        "Documentation",
        "文档",
        "exact",
    ),
    (
        "widgets/manager/table.py",
        "TableCondaPackages.context_menu_requested",
        "Development",
        "开发页面",
        "exact",
    ),

    (
        "widgets/dialogs/environment/import_dialogs.py",
        "ImportSelectorDialog._process_open_local",
        "Conda environment files (*.yaml *.yml)",
        "Conda 环境文件 (*.yaml *.yml)",
        "exact",
    ),
    (
        "widgets/dialogs/environment/import_dialogs.py",
        "ImportSelectorDialog._process_open_local",
        "Conda explicit specification files (*.txt)",
        "Conda 显式规格文件 (*.txt)",
        "exact",
    ),
    (
        "widgets/dialogs/environment/import_dialogs.py",
        "ImportSelectorDialog._process_open_local",
        "Pip requirement files (*.txt)",
        "pip 依赖文件 (*.txt)",
        "exact",
    ),
    (
        "widgets/dialogs/environment/backup_dialogs.py",
        "BackupSelectorDialog.__process_accept_local",
        "Conda environment files (*.yaml *.yml)",
        "Conda 环境文件 (*.yaml *.yml)",
        "exact",
    ),
    (
        "widgets/dialogs/environment/backup_dialogs.py",
        "BackupSelectorDialog.__process_accept_local",
        "All files (*)",
        "所有文件 (*)",
        "exact",
    ),
]


def get_scope(node, parents):
    names = []

    while node in parents:
        node = parents[node]

        if isinstance(
            node,
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            names.append(node.name)

    return ".".join(reversed(names))


def make_rule(source, scope, english, chinese, mode, rule_id):
    tree = ast.parse(source)

    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    matches = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue

        if not isinstance(node.value, str):
            continue

        if get_scope(node, parents) != scope:
            continue

        if mode == "exact":
            matched = node.value == english
        else:
            matched = english in node.value

        if matched:
            matches.append(node)

    if len(matches) != 1:
        raise ValueError(
            f"AST 定位结果为 {len(matches)} 处"
        )

    node = matches[0]

    if mode == "exact":
        translated = chinese
    else:
        if node.value.count(english) != 1:
            raise ValueError("目标字符串重复")

        translated = node.value.replace(
            english, chinese, 1
        )

    literal = ast.get_source_segment(source, node)

    if not literal:
        raise ValueError("无法读取原始字符串")

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
            raise ValueError("无法确定唯一替换位置")

    marker = "__NAVZH_BATCH9_TEXT__"

    if marker in original:
        raise ValueError("翻译占位符发生冲突")

    template = original.replace(
        literal, marker, 1
    )

    template = (
        template
        .replace("{", "{{")
        .replace("}", "}}")
        .replace(marker, "{text}")
    )

    return {
        "id": rule_id,
        "original": original,
        "template": template,
        "count": 1,
    }, translated


def validate(rules, locale, root):
    for entry in rules["files"]:
        path = root / entry["path"]

        content = path.read_bytes().decode("utf-8-sig")

        for rule in entry["rules"]:
            count = content.count(rule["original"])

            if count != rule["count"]:
                raise ValueError(
                    f"{entry['path']} / {rule['id']}："
                    f"预期 {rule['count']}，实际 {count}"
                )

            translation = json.dumps(
                locale["messages"][rule["id"]],
                ensure_ascii=False,
            )

            replacement = rule["template"].format(
                text=translation
            )

            content = content.replace(
                rule["original"],
                replacement,
            )

        ast.parse(
            content,
            filename=str(path),
        )


def main():
    if MANIFEST.exists():
        raise RuntimeError("当前仍有汉化安装记录，请先恢复原版")

    _, version, root = installation()

    if version != "2.7.1":
        raise RuntimeError(
            f"当前不支持 Navigator {version}"
        )

    rules_path = PROJECT / "patches" / "2.7.1.json"
    locale_path = PROJECT / "locales" / "zh_CN.json"

    rules_original = rules_path.read_bytes()
    locale_original = locale_path.read_bytes()

    rules = json.loads(rules_original)
    locale = json.loads(locale_original)

    if rules.get("version") != version:
        raise RuntimeError("版本规则不匹配")

    if locale.get("language") != "zh_CN":
        raise RuntimeError("语言包不匹配")

    files = {
        entry["path"]: entry
        for entry in rules["files"]
    }

    ids = {
        rule["id"]
        for entry in rules["files"]
        for rule in entry["rules"]
    }

    added = 0
    skipped = []

    for index, target in enumerate(TARGETS, 1):
        relative, scope, english, chinese, mode = target
        rule_id = f"batch9.{index:02d}"

        try:
            if rule_id in ids or rule_id in locale["messages"]:
                raise ValueError("翻译 ID 已存在")

            path = root / relative

            if not path.is_file():
                raise ValueError("源码文件不存在")

            source = path.read_bytes().decode("utf-8-sig")

            rule, translation = make_rule(
                source,
                scope,
                english,
                chinese,
                mode,
                rule_id,
            )

            entry = files.get(relative)
            created = entry is None

            if created:
                entry = {
                    "path": relative,
                    "rules": [],
                }

                files[relative] = entry
                rules["files"].append(entry)

            entry["rules"].append(rule)
            locale["messages"][rule_id] = translation

            try:
                validate(rules, locale, root)
            except Exception:
                entry["rules"].pop()
                del locale["messages"][rule_id]

                if created:
                    rules["files"].remove(entry)
                    del files[relative]

                raise

            ids.add(rule_id)
            added += 1

        except (ValueError, OSError, SyntaxError) as error:
            skipped.append(f"{rule_id}: {error}")

    if added == 0:
        raise RuntimeError("没有成功生成新规则")

    validate(rules, locale, root)

    snapshots = PROJECT / "state" / "rule_snapshots"

    old_rules = snapshots / "2.7.1.before_batch9.json"
    old_locale = snapshots / "zh_CN.before_batch9.json"

    if old_rules.exists() or old_locale.exists():
        raise RuntimeError("第九批规则快照已存在")

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

    print("第九批规则生成完成")
    print(f"新增规则：{added}")
    print(f"未生成候选：{len(skipped)}")
    print(f"累计涉及源码文件：{len(rules['files'])}")
    print("规则匹配及 Python 语法检查通过")
    print("Navigator 安装文件尚未修改")

    if skipped:
        print("\n未生成的候选：")

        for item in skipped:
            print(item)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"生成失败：{error}")
        raise SystemExit(1)