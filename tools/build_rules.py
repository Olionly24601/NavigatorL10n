import argparse
import ast
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from copy import deepcopy

PROJECT = Path(__file__).resolve().parents[1]

if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from core import engine
from core.translation_validation import validate_messages
from tools import rule_store

PATCHES = PROJECT / "patches"
LOCALES = PROJECT / "locales"
LOCALE = LOCALES / "zh_CN.json"
SUPPORTED_LANGUAGES = ("zh_CN", "ja_JP")


def available_versions():
    return sorted(path.stem for path in PATCHES.glob("*.json"))


def load(version=None, language="zh_CN"):
    rule_store.require_clean_rules(PROJECT)
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"不支持的语言：{language}")

    if version is None:
        _, version, _ = engine.installation()

    rules = PATCHES / f"{version}.json"
    if not rules.is_file():
        raise ValueError(f"暂不支持 Navigator {version}")

    config = engine.read_json(rules)
    if config.get("version") != version:
        raise ValueError(f"规则文件版本不一致：{rules.name}")

    locale_path = LOCALES / f"{language}.json"
    if not locale_path.is_file():
        raise ValueError(f"找不到语言包：{language}")

    locale = engine.read_json(locale_path)
    if locale.get("language") != language:
        raise ValueError(f"语言包标识不一致：{language}")

    return config, locale


def load_snapshot(version, language, snapshot):
    rule_store.require_clean_rules(PROJECT)
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"不支持的语言：{language}")
    if version is None:
        _, version, _ = engine.installation()

    def read(path):
        if not path.is_file():
            raise ValueError(f"找不到规则或语言文件：{path}")
        raw = path.read_bytes()
        checksum = engine.digest(raw)
        canonical = path.resolve()
        if canonical in snapshot and snapshot[canonical] != checksum:
            raise RuntimeError(f"规则维护期间源文件发生变化：{path}")
        snapshot[canonical] = checksum
        return json.loads(raw.decode("utf-8-sig"))

    rules = PATCHES / f"{version}.json"
    config = read(rules)
    if config.get("version") != version:
        raise ValueError(f"规则文件版本不一致：{rules.name}")

    locale_path = LOCALES / f"{language}.json"
    locale = read(locale_path)
    if locale.get("language") != language:
        raise ValueError(f"语言包标识不一致：{language}")
    return config, locale


def validate(config, locale):
    if (
        not isinstance(config.get("version"), str)
        or locale.get("language") not in SUPPORTED_LANGUAGES
    ):
        raise ValueError("规则版本或语言不匹配")

    if (
        not isinstance(config.get("files"), list)
        or not isinstance(locale.get("messages"), dict)
    ):
        raise ValueError("规则或语言包结构异常")

    validate_messages(locale["messages"])

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

    return len(paths), total, used


def validate_all(configs, locale):
    used = set()
    results = {}

    for config in configs:
        files, rules, keys = validate(config, locale)
        results[config["version"]] = (files, rules, len(keys))
        used.update(keys)

    unused = set(locale["messages"]) - used
    if unused:
        raise ValueError(
            f"语言包存在未引用的条目：{sorted(unused)}"
        )

    return results


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


def add(spec_path, config, locale, other_locales=None):
    locales = {"zh_CN": locale}

    if other_locales:
        for language, data in other_locales.items():
            if language == "zh_CN":
                raise ValueError("重复的中文语言包")
            if language not in SUPPORTED_LANGUAGES:
                raise ValueError(f"不支持的语言：{language}")
            locales[language] = data

    source_root, sources = originals(config)

    for language, data in locales.items():
        if data.get("language") != language:
            raise ValueError(f"语言包标识不一致：{language}")
        verify(config, data, sources)

    spec = engine.read_json(spec_path)
    changes = spec["rules"]

    if not changes:
        raise ValueError("没有新增规则候选")

    working_config = deepcopy(config)
    working_locales = {
        language: deepcopy(data)
        for language, data in locales.items()
    }

    file_map = {
        entry["path"]: entry
        for entry in working_config["files"]
    }

    missing = object()
    added = 0
    skipped = 0

    for item in changes:
        relative = item["path"]

        if relative not in sources:
            target = engine.target_path(source_root, relative)
            sources[relative] = target.read_bytes().decode("utf-8")

        translations = item.get("translations", {})

        if not isinstance(translations, dict):
            raise ValueError(f"翻译字段格式错误：{item['id']}")

        unknown = set(translations) - set(SUPPORTED_LANGUAGES)

        if unknown:
            raise ValueError(
                f"未知翻译语言：{item['id']} / {sorted(unknown)}"
            )

        if "translation" in item and "zh_CN" in translations:
            if item["translation"] != translations["zh_CN"]:
                raise ValueError(
                    f"中文翻译字段冲突：{item['id']}"
                )

        provided = {}

        for language in locales:
            if language == "zh_CN" and "translation" in item:
                value = item["translation"]
            else:
                value = translations.get(language, missing)

            if value is not missing:
                provided[language] = value

        if not provided:
            raise ValueError(f"没有提供翻译：{item['id']}")

        rule = None
        translated_values = {}

        for language, value in provided.items():
            candidate, translated = make_rule(
                sources[relative],
                {**item, "translation": value},
            )

            if rule is None:
                rule = candidate
            elif rule != candidate:
                raise ValueError(
                    f"不同语言生成了不同的规则：{item['id']}"
                )

            translated_values[language] = translated

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
                    f"规则 ID 冲突：{relative} / {rule_id}"
                )

            for language, translated in translated_values.items():
                actual = working_locales[language]["messages"].get(
                    rule_id, missing
                )

                if actual is missing or actual != translated:
                    raise ValueError(
                        f"现有翻译内容不一致："
                        f"{language} / {rule_id}"
                    )

            skipped += 1
            continue

        for language in locales:
            if language not in translated_values:
                raise ValueError(
                    f"新增规则缺少翻译：{language} / {rule_id}"
                )

            messages = working_locales[language]["messages"]
            actual = messages.get(rule_id, missing)

            if actual is not missing and actual != translated_values[language]:
                raise ValueError(
                    f"共享翻译 ID 内容冲突："
                    f"{language} / {rule_id}"
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
            entry = {"path": relative, "rules": []}
            working_config["files"].append(entry)
            file_map[relative] = entry

        entry["rules"].append(rule)

        for language, translated in translated_values.items():
            working_locales[language]["messages"][rule_id] = translated

        added += 1

    for language, data in working_locales.items():
        verify(working_config, data, sources)

    config.clear()
    config.update(working_config)

    for language, data in locales.items():
        data.clear()
        data.update(working_locales[language])

    return added, skipped


def save(config, locale, other_locales=None, expected_hashes=None):
    locales = {"zh_CN": locale}

    if other_locales:
        locales.update(other_locales)

    if set(locales) != set(SUPPORTED_LANGUAGES):
        missing = set(SUPPORTED_LANGUAGES) - set(locales)
        raise ValueError(
            f"正式保存缺少语言包：{sorted(missing)}"
        )

    updates = {}

    rules_path = PATCHES / f"{config['version']}.json"

    updates[rules_path] = (
        json.dumps(
            config,
            ensure_ascii=False,
            indent=2,
        ) + "\n"
    ).encode("utf-8")

    for language, data in locales.items():
        if data.get("language") != language:
            raise ValueError(
                f"语言包标识不一致：{language}"
            )

        validate(config, data)

        path = LOCALES / f"{language}.json"

        updates[path] = (
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ) + "\n"
        ).encode("utf-8")

    rule_store.save_many(PROJECT, updates, expected_hashes=expected_hashes)


def main():
    parser = argparse.ArgumentParser(
        description="NavigatorZH 规则构建工具"
    )

    parser.add_argument(
        "command",
        choices=("validate", "verify", "add", "recover"),
    )

    parser.add_argument(
        "spec",
        nargs="?",
        type=Path,
    )

    parser.add_argument(
        "--version",
        help="Navigator 版本；validate 默认检查全部版本",
    )

    parser.add_argument(
        "--lang",
        choices=SUPPORTED_LANGUAGES,
        default="zh_CN",
        help="目标语言，默认 zh_CN",
    )

    args = parser.parse_args()

    if args.spec is not None and args.command != "add":
        parser.error("只有 add 命令接受规则草稿 JSON 路径")

    if args.command == "recover":
        with rule_store.project_lock(PROJECT):
            recovered = rule_store.recover_pending(PROJECT)

        if recovered:
            print("未完成的规则事务已恢复")
        else:
            print("没有需要恢复的规则事务")
        return

    if args.command in ("validate", "verify"):
        with rule_store.project_lock(PROJECT):
            rule_store.require_clean_rules(PROJECT)
            if args.command == "validate":
                versions = (
                    [args.version]
                    if args.version
                    else available_versions()
                )
                if not versions:
                    raise ValueError("没有找到版本规则文件")

                configs = []
                for version in versions:
                    config, locale = load(version, args.lang)
                    configs.append(config)

                if args.version:
                    files, rules, keys = validate(configs[0], locale)
                    print(
                        f"Navigator {args.version}："
                        f"{files} 个文件、{rules} 条规则、"
                        f"{len(keys)} 个翻译条目，检查通过"
                    )
                else:
                    results = validate_all(configs, locale)
                    for version, (files, rules, keys) in results.items():
                        print(
                            f"Navigator {version}："
                            f"{files} 个文件、{rules} 条规则、"
                            f"{keys} 个翻译条目，检查通过"
                        )
                    print("共享语言包无未引用条目")
            else:
                config, locale = load(args.version, args.lang)
                _, sources = originals(config)
                verify(config, locale, sources)
                print(
                    f"Navigator {config['version']}："
                    "源码匹配和 Python 语法检查通过，"
                    "未修改 Navigator"
                )
        return

    if args.spec is None:
        parser.error("add 需要指定规则草稿 JSON 路径")

    if args.lang != "zh_CN":
        parser.error(
            "add 同时维护全部语言，请省略 --lang"
        )

    with rule_store.project_lock(PROJECT):
        rule_store.require_clean_rules(PROJECT)

        snapshot = {}
        config, locale = load_snapshot(args.version, "zh_CN", snapshot)

        other_locales = {}

        for language in SUPPORTED_LANGUAGES:
            if language == "zh_CN":
                continue

            _, data = load_snapshot(config["version"], language, snapshot)
            other_locales[language] = data

        added, skipped = add(
            args.spec,
            config,
            locale,
            other_locales,
        )

        if added:
            save(config, locale, other_locales, expected_hashes=snapshot)

    print(f"新增规则：{added}")
    print(f"已存在并跳过：{skipped}")

    if added:
        print("所有规则检查通过，已更新规则与语言包")
    else:
        print("规则内容没有变化，未重新写入文件")

    print("Navigator 安装文件未修改")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, SyntaxError, RuntimeError) as error:
        print(f"失败：{error}")
        raise SystemExit(1)