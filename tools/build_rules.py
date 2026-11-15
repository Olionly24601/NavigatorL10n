import argparse
import ast
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]

if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from core import engine

RULES = PROJECT / "patches" / "2.7.1.json"
LOCALE = PROJECT / "locales" / "zh_CN.json"


def load():
    return engine.read_json(RULES), engine.read_json(LOCALE)


def validate(config, locale):
    if (
        config.get("version") != "2.7.1"
        or locale.get("language") != "zh_CN"
    ):
        raise ValueError("规则版本或语言不匹配")

    if (
        not isinstance(config.get("files"), list)
        or not isinstance(locale.get("messages"), dict)
    ):
        raise ValueError("规则或语言包结构异常")

    paths = set()
    used = set()
    total = 0

    for item in config["files"]:
        relative = item["path"]
        path = Path(relative)

        if (
            path.is_absolute()
            or "\\" in relative
            or ".." in path.parts
            or path.suffix != ".py"
        ):
            raise ValueError(f"非法路径：{relative}")

        if relative in paths:
            raise ValueError(f"重复的文件配置：{relative}")

        paths.add(relative)

        if not item["rules"]:
            raise ValueError(f"空规则文件：{relative}")

        for rule in item["rules"]:
            key = rule["id"]

            if key not in locale["messages"]:
                raise ValueError(f"缺少翻译：{key}")

            if (
                not rule["original"]
                or not isinstance(rule["count"], int)
                or isinstance(rule["count"], bool)
                or rule["count"] < 1
            ):
                raise ValueError(f"规则内容或匹配次数无效：{key}")

            try:
                value = json.dumps(
                    locale["messages"][key],
                    ensure_ascii=False,
                )

                rendered = rule["template"].format(text=value)

                if not rendered:
                    raise ValueError("空替换结果")

            except (KeyError, IndexError, ValueError) as error:
                raise ValueError(
                    f"模板错误：{key}：{error}"
                ) from error

            used.add(key)
            total += 1

    unused = set(locale["messages"]) - used

    if unused:
        raise ValueError(
            f"语言包存在未引用的条目：{sorted(unused)}"
        )

    return len(paths), total, len(used)


def originals(config):
    prefix, version, root = engine.installation()

    if version != config["version"]:
        raise ValueError(
            f"当前安装的 Navigator {version} 与规则版本不一致"
        )

    records = {}

    if engine.MANIFEST.exists():
        manifest = engine.read_json(engine.MANIFEST)

        if (
            manifest["prefix"] != str(prefix)
            or manifest["version"] != version
        ):
            raise ValueError("当前安装记录与解释器环境不一致")

        records = {
            item["relative"]: item
            for item in manifest["files"]
        }

    result = {}

    for item in config["files"]:
        relative = item["path"]
        target = engine.target_path(root, relative)

        if relative in records:
            record = records[relative]

            data = (
                engine.BACKUPS / record["backup"]
            ).read_bytes()

            if engine.digest(data) != record["original_sha256"]:
                raise ValueError(
                    f"原始备份校验失败：{relative}"
                )

            current_hash = engine.digest(target.read_bytes())

            if current_hash not in (
                record["original_sha256"],
                record["patched_sha256"],
            ):
                raise ValueError(
                    f"已安装文件发生其他变化：{relative}"
                )
        else:
            data = target.read_bytes()

        result[relative] = data.decode("utf-8")

    return root, result


def verify(config, locale, source):
    validate(config, locale)

    for item in config["files"]:
        relative = item["path"]

        if relative not in source:
            raise ValueError(
                f"缺少原始源码：{relative}"
            )

        content = source[relative]

        for rule in item["rules"]:
            actual = content.count(rule["original"])

            if actual != rule["count"]:
                raise ValueError(
                    f"{relative} / {rule['id']}："
                    f"预期 {rule['count']} 处，实际 {actual} 处"
                )

            value = json.dumps(
                locale["messages"][rule["id"]],
                ensure_ascii=False,
            )

            replacement = rule["template"].format(
                text=value
            )

            content = content.replace(
                rule["original"],
                replacement,
            )

        ast.parse(content, filename=relative)


def make_rule(source, item):
    if "original" in item:
        return {
            "id": item["id"],
            "original": item["original"],
            "template": item["template"],
            "count": item.get("count", 1),
        }, item["translation"]

    tree = ast.parse(source)

    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    def scope_of(node):
        names = []

        while node in parents:
            node = parents[node]

            if isinstance(
                node,
                (
                    ast.ClassDef,
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                names.append(node.name)

        return ".".join(reversed(names))

    english = item["find"]
    mode = item.get("mode", "exact")

    if mode not in ("exact", "contains"):
        raise ValueError(
            f"无效匹配模式：{mode}"
        )

    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and scope_of(node) == item["scope"]
        and (
            node.value == english
            if mode == "exact"
            else english in node.value
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            f"{item['path']} / {item['id']}："
            f"AST 找到 {len(matches)} 处"
        )

    node = matches[0]

    if node.lineno != node.end_lineno:
        raise ValueError(
            "多行拼接字符串请使用 original/template 明确指定"
        )

    literal = ast.get_source_segment(source, node)

    if not literal:
        raise ValueError("无法提取源码字符串")

    if mode == "exact":
        translated = item["translation"]
    else:
        if node.value.count(english) != 1:
            raise ValueError(
                "字符串内存在多个同名片段"
            )

        translated = node.value.replace(
            english,
            item["translation"],
        )

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
            raise ValueError(
                "无法取得唯一源码定位"
            )

    marker = "__NAVIGATORZH_REPLACEMENT__"

    if marker in original:
        raise ValueError("占位符冲突")

    template = original.replace(
        literal,
        marker,
        1,
    )

    template = (
        template
        .replace("{", "{{")
        .replace("}", "}}")
        .replace(marker, "{text}")
    )

    return {
        "id": item["id"],
        "original": original,
        "template": template,
        "count": 1,
    }, translated


def add(spec_path, config, locale):
    source_root, sources = originals(config)

    verify(config, locale, sources)

    spec = engine.read_json(spec_path)
    changes = spec["rules"]

    if not changes:
        raise ValueError("没有新增规则候选")

    file_map = {
        entry["path"]: entry
        for entry in config["files"]
    }

    added = 0
    skipped = 0

    for item in changes:
        relative = item["path"]

        if relative not in sources:
            target = engine.target_path(
                source_root,
                relative,
            )

            sources[relative] = (
                target.read_bytes().decode("utf-8")
            )

        rule, translation = make_rule(
            sources[relative],
            item,
        )

        rule_id = rule["id"]
        entry = file_map.get(relative)

        existing = None

        if entry is not None:
            existing = next(
                (
                    candidate
                    for candidate in entry["rules"]
                    if candidate["id"] == rule_id
                ),
                None,
            )

        if existing is not None:
            if existing != rule:
                raise ValueError(
                    f"规则 ID 冲突："
                    f"{relative} / {rule_id}"
                )

            if locale["messages"].get(rule_id) != translation:
                raise ValueError(
                    f"现有翻译内容不一致：{rule_id}"
                )

            skipped += 1
            continue

        if (
            rule_id in locale["messages"]
            and locale["messages"][rule_id] != translation
        ):
            raise ValueError(
                f"共享翻译 ID 内容冲突：{rule_id}"
            )

        if entry is not None:
            if any(
                candidate["original"] == rule["original"]
                for candidate in entry["rules"]
            ):
                raise ValueError(
                    f"源码位置已有不同补丁："
                    f"{relative} / {rule_id}"
                )
        else:
            entry = {
                "path": relative,
                "rules": [],
            }

            config["files"].append(entry)
            file_map[relative] = entry

        entry["rules"].append(rule)
        locale["messages"][rule_id] = translation

        added += 1

    verify(config, locale, sources)

    return added, skipped


def save(config, locale):
    old_rules = RULES.read_bytes()
    old_locale = LOCALE.read_bytes()

    folder = (
        PROJECT / "state" / "rule_snapshots"
    )

    name = (
        datetime.now().strftime("%Y%m%d_%H%M%S")
        + "_"
        + uuid4().hex[:8]
    )

    engine.atomic_write(
        folder / f"{name}.rules.json",
        old_rules,
    )

    engine.atomic_write(
        folder / f"{name}.locale.json",
        old_locale,
    )

    rules_new = (
        json.dumps(
            config,
            ensure_ascii=False,
            indent=2,
        ) + "\n"
    ).encode("utf-8")

    locale_new = (
        json.dumps(
            locale,
            ensure_ascii=False,
            indent=2,
        ) + "\n"
    ).encode("utf-8")

    try:
        engine.atomic_write(RULES, rules_new)
        engine.atomic_write(LOCALE, locale_new)

    except Exception:
        engine.atomic_write(RULES, old_rules)
        engine.atomic_write(LOCALE, old_locale)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="NavigatorZH 规则构建工具"
    )

    parser.add_argument(
        "command",
        choices=("validate", "verify", "add"),
    )

    parser.add_argument(
        "spec",
        nargs="?",
        type=Path,
    )

    args = parser.parse_args()

    config, locale = load()

    if args.command == "validate":
        files, rules, keys = validate(
            config,
            locale,
        )

        print(
            f"结构检查通过：{files} 个文件、"
            f"{rules} 条规则、{keys} 个翻译条目"
        )

    elif args.command == "verify":
        _, sources = originals(config)

        verify(config, locale, sources)

        print(
            "源码匹配和 Python 语法检查通过，"
            "未修改 Navigator"
        )

    else:
        if args.spec is None:
            parser.error(
                "add 需要指定规则草稿 JSON 路径"
            )

        added, skipped = add(
            args.spec,
            config,
            locale,
        )

        if added:
            save(config, locale)

        print(f"新增规则：{added}")
        print(f"已存在并跳过：{skipped}")

        if added:
            print(
                "所有规则检查通过，"
                "已更新规则文件"
            )
        else:
            print(
                "规则内容没有变化，"
                "未重新写入规则文件"
            )

        print("Navigator 安装文件未修改")


if __name__ == "__main__":
    try:
        main()
    except (
        OSError,
        ValueError,
        KeyError,
        SyntaxError,
    ) as error:
        print(f"失败：{error}")
        raise SystemExit(1)