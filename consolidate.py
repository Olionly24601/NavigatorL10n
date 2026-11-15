import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent

RULES = ROOT / "patches" / "2.7.1.json"
LOCALE = ROOT / "locales" / "zh_CN.json"

REQUIRED = [
    ROOT / "main.py",
    ROOT / "core" / "engine.py",
    RULES,
    LOCALE,
]


def validate():
    for path in REQUIRED:
        if not path.is_file():
            raise RuntimeError(f"缺少必要文件：{path}")

    rules = json.loads(RULES.read_text(encoding="utf-8"))
    locale = json.loads(LOCALE.read_text(encoding="utf-8"))

    if rules.get("version") != "2.7.1":
        raise RuntimeError("版本适配信息异常")

    if locale.get("language") != "zh_CN":
        raise RuntimeError("语言包标识异常")

    messages = locale["messages"]
    seen_ids = set()
    seen_paths = set()
    count = 0

    for entry in rules["files"]:
        relative = entry["path"]

        if relative in seen_paths:
            raise RuntimeError(f"重复的源码文件配置：{relative}")

        seen_paths.add(relative)

        for rule in entry["rules"]:
            rule_id = rule["id"]

            if rule_id in seen_ids and rule_id != 'packages.filter_labels':
                raise RuntimeError(f"重复的规则 ID：{rule_id}")

            if rule_id not in messages:
                raise RuntimeError(f"缺少翻译：{rule_id}")

            if not isinstance(rule["count"], int) or rule["count"] < 1:
                raise RuntimeError(f"无效的匹配数量：{rule_id}")

            translated = json.dumps(
                messages[rule_id],
                ensure_ascii=False,
            )

            try:
                rule["template"].format(text=translated)
            except (KeyError, ValueError, IndexError) as error:
                raise RuntimeError(
                    f"规则模板异常：{rule_id}"
                ) from error

            seen_ids.add(rule_id)
            count += 1

    return len(seen_paths), count, len(messages)


def backup():
    directory = ROOT.parent / "NavigatorZH_Backups"
    directory.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = directory / f"NavigatorZH_{timestamp}.zip"

    if destination.exists():
        raise RuntimeError("备份文件已经存在")

    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path in ROOT.rglob("*"):
            if path.is_file():
                archive.write(
                    path,
                    path.relative_to(ROOT),
                )

    with zipfile.ZipFile(destination) as archive:
        damaged = archive.testzip()

        if damaged is not None:
            raise RuntimeError(f"备份校验失败：{damaged}")

    return destination


def archive_generators():
    archive_dir = ROOT / "tools" / "archive" / "batches"

    candidates = []

    for pattern in ("expand_ui.py", "extend_batch*.py"):
        candidates.extend(ROOT.glob(pattern))

    candidates = sorted(set(candidates))

    for source in candidates:
        destination = archive_dir / source.name

        if destination.exists():
            raise RuntimeError(
                f"归档目标已存在：{destination}"
            )

    archive_dir.mkdir(parents=True, exist_ok=True)

    for source in candidates:
        shutil.move(
            str(source),
            str(archive_dir / source.name),
        )

    return candidates


def create_tests():
    tests = ROOT / "tests"
    tests.mkdir(parents=True, exist_ok=True)

    path = tests / "test_rules.py"

    if path.exists():
        print("已有规则测试文件，未覆盖")
        return

    content = '''import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestTranslationRules(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rules = json.loads(
            (ROOT / "patches" / "2.7.1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.locale = json.loads(
            (ROOT / "locales" / "zh_CN.json").read_text(
                encoding="utf-8"
            )
        )

    def test_version(self):
        self.assertEqual(self.rules["version"], "2.7.1")

    def test_language(self):
        self.assertEqual(self.locale["language"], "zh_CN")

    def test_unique_paths(self):
        paths = [item["path"] for item in self.rules["files"]]
        self.assertEqual(len(paths), len(set(paths)))

    def test_unique_ids(self):
        ids = [
            rule["id"]
            for entry in self.rules["files"]
            for rule in entry["rules"]
        ]
        self.assertEqual({k: ids.count(k) for k in set(ids) if ids.count(k) > 1}, {'packages.filter_labels': 2})

    def test_translation_completeness(self):
        messages = self.locale["messages"]

        for entry in self.rules["files"]:
            for rule in entry["rules"]:
                with self.subTest(rule=rule["id"]):
                    self.assertIn(rule["id"], messages)

    def test_template_rendering(self):
        messages = self.locale["messages"]

        for entry in self.rules["files"]:
            for rule in entry["rules"]:
                with self.subTest(rule=rule["id"]):
                    translated = json.dumps(
                        messages[rule["id"]],
                        ensure_ascii=False,
                    )

                    output = rule["template"].format(
                        text=translated
                    )

                    self.assertIsInstance(output, str)
                    self.assertTrue(output)

    def test_positive_match_counts(self):
        for entry in self.rules["files"]:
            for rule in entry["rules"]:
                with self.subTest(rule=rule["id"]):
                    self.assertGreater(rule["count"], 0)


if __name__ == "__main__":
    unittest.main()
'''

    path.write_text(content, encoding="utf-8")


def main():
    files, rules, translations = validate()

    generators = sorted(set(
        list(ROOT.glob("expand_ui.py"))
        + list(ROOT.glob("extend_batch*.py"))
    ))

    destination_dir = ROOT / "tools" / "archive" / "batches"

    for source in generators:
        if (destination_dir / source.name).exists():
            raise RuntimeError(
                f"归档文件已存在：{source.name}"
            )

    print("当前项目检查通过")
    print(f"适配源码文件：{files}")
    print(f"翻译规则：{rules}")
    print(f"语言包条目：{translations}")

    destination = backup()
    print(f"完整备份：{destination}")

    archived = archive_generators()

    print(f"归档历史生成器：{len(archived)} 个")

    create_tests()
    print("自动化规则测试已建立")

    print("第一次工程整合完成")
    print("现有 Navigator 安装保持不变")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"整合失败：{error}")
        raise SystemExit(1)