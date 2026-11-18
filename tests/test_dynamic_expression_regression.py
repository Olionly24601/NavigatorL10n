import ast
from collections import Counter
import html
import json
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT = Path(__file__).resolve().parents[1]
VERSIONS = ("2.7.1", "2.7.4")
LANGUAGES = ("zh_CN", "ja_JP")

FSTRING_KEYS = (
    "errors.ssl_certificate_missing",
    "errors.unavailable_environment",
    "errors.branding_overwrite",
    "cloud.signed_in_as",
    "status.verifying_toolbox",
    "status.launching_app",
    "errors.app_launch_message",
    "status.installing_app",
    "apps.version_available",
    "env.conflict_title",
    "env.download_success_message",
)
VERSION_KEYS = {
    "2.7.1": "status.installing_in_new_environment",
    "2.7.4": "status.installing_in_environment",
}

CONTEXT = {
    "html": html,
    "ssl_certificate": '<cert&".pem>',
    "default_env": '<missing&env>',
    "issue": SimpleNamespace(to_option='<new&value>', from_option='<old&value>'),
    "account": '<user&name>',
    "toolbox_install_worker": SimpleNamespace(prefix='C:/toolbox-test'),
    "package_name": 'jupyterlab',
    "application": SimpleNamespace(package='spyder'),
    "app": SimpleNamespace(display_name='<sample&app>'),
    "self": SimpleNamespace(versions=['1.0.0', '2.0.0']),
    "package": 'sample-package',
    "name": 'sample-env.yaml',
    "path": 'C:/sample-env.yaml',
    "worker": SimpleNamespace(pkgs=['sample-tool']),
    "env_prefix": 'C:/sample-environment',
    "state": SimpleNamespace(username='test-user'),
    "word": 'python',
}

DYNAMIC_VALUES = {
    "errors.ssl_certificate_missing": (html.escape(CONTEXT["ssl_certificate"]),),
    "errors.unavailable_environment": (html.escape(CONTEXT["default_env"]),),
    "errors.branding_overwrite": (
        html.escape(CONTEXT["issue"].to_option),
        html.escape(CONTEXT["issue"].from_option),
    ),
    "cloud.signed_in_as": (html.escape(CONTEXT["account"]),),
    "status.verifying_toolbox": (CONTEXT["toolbox_install_worker"].prefix,),
    "status.launching_app": (CONTEXT["package_name"],),
    "errors.app_launch_message": (CONTEXT["application"].package,),
    "status.installing_app": (html.escape(CONTEXT["app"].display_name),),
    "apps.version_available": (CONTEXT["self"].versions[-1],),
    "env.conflict_title": (CONTEXT["package"],),
    "env.download_success_message": (CONTEXT["name"], CONTEXT["path"]),
    "status.installing_in_new_environment": (
        CONTEXT["worker"].pkgs[0], CONTEXT["env_prefix"],
    ),
    "status.installing_in_environment": (
        CONTEXT["worker"].pkgs[0], CONTEXT["env_prefix"],
    ),
}


ALLOWED_ATTRIBUTES = {
    "html": {"escape"},
    "issue": {"to_option", "from_option"},
    "toolbox_install_worker": {"prefix"},
    "application": {"package"},
    "app": {"display_name"},
    "self": {"versions"},
    "worker": {"pkgs"},
    "state": {"username"},
}


def evaluate(node):
    """Execute the real Python expression after validating its limited AST."""
    allowed = (
        ast.JoinedStr, ast.FormattedValue, ast.Constant, ast.Name,
        ast.Attribute, ast.Call, ast.Subscript, ast.UnaryOp, ast.USub,
        ast.Load, ast.BinOp, ast.Add, ast.keyword,
    )
    for part in ast.walk(node):
        if not isinstance(part, allowed):
            raise ValueError(f"Unsupported expression node: {type(part).__name__}")
        if isinstance(part, ast.Name) and part.id not in CONTEXT:
            raise ValueError(f"Unknown expression name: {part.id}")
        if isinstance(part, ast.Attribute):
            if isinstance(part.value, ast.Name):
                if part.attr not in ALLOWED_ATTRIBUTES.get(part.value.id, set()):
                    raise ValueError("Unsupported attribute access")
            elif not (
                isinstance(part.value, ast.Constant)
                and isinstance(part.value.value, str)
                and part.attr == "format"
            ):
                raise ValueError("Unsupported attribute access")
        if isinstance(part, ast.Call):
            func = part.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "html"
                and func.attr == "escape"
                and len(part.args) == 1
                and not part.keywords
            ):
                continue
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Constant)
                and isinstance(func.value.value, str)
                and func.attr == "format"
                and not part.args
                and all(k.arg in ("name", "username") for k in part.keywords)
            ):
                continue
            raise ValueError("Unsupported function call")
        if isinstance(part, ast.Subscript):
            if not (
                isinstance(part.value, ast.Attribute)
                and isinstance(part.value.value, ast.Name)
                and (part.value.value.id, part.value.attr)
                in (("worker", "pkgs"), ("self", "versions"))
            ):
                raise ValueError("Unsupported subscript")
    expression = ast.fix_missing_locations(ast.Expression(body=node))
    return eval(compile(expression, "<regression-test>", "eval"),
                {"__builtins__": {}}, CONTEXT)


def fields(expression):
    tree = ast.parse(expression, mode="eval")
    if not isinstance(tree.body, ast.JoinedStr):
        raise ValueError("Expected an f-string")
    return [
        (ast.dump(node.value, include_attributes=False), node.conversion,
         ast.dump(node.format_spec, include_attributes=False) if node.format_spec else None)
        for node in tree.body.values
        if isinstance(node, ast.FormattedValue)
    ], tree.body


class TestDynamicExpressionRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = {}
        cls.messages = {}
        for version in VERSIONS:
            data = json.loads(
                (PROJECT / "patches" / f"{version}.json").read_text(encoding="utf-8")
            )
            cls.rules[version] = {
                rule["id"]: rule
                for item in data["files"]
                for rule in item["rules"]
            }
        for language in LANGUAGES:
            cls.messages[language] = json.loads(
                (PROJECT / "locales" / f"{language}.json").read_text(encoding="utf-8")
            )["messages"]

    def test_fstring_variables_and_runtime_output(self):
        for version in VERSIONS:
            for language in LANGUAGES:
                for key in (*FSTRING_KEYS, VERSION_KEYS[version]):
                    with self.subTest(version=version, language=language, key=key):
                        self.assertIn(key, self.rules[version])
                        self.assertIn(key, self.messages[language])
                        rule = self.rules[version][key]
                        translated = rule["template"].format(
                            text=json.dumps(self.messages[language][key], ensure_ascii=False)
                        )
                        before_fields, before = fields(rule["original"])
                        after_fields, after = fields(translated)
                        self.assertTrue(before_fields)
                        self.assertEqual(Counter(before_fields), Counter(after_fields))
                        original_output = evaluate(before)
                        translated_output = evaluate(after)
                        self.assertIsInstance(original_output, str)
                        self.assertIsInstance(translated_output, str)
                        for value in DYNAMIC_VALUES[key]:
                            self.assertIn(value, original_output)
                            self.assertIn(value, translated_output)

    def test_html_escaping_and_markup(self):
        for version in VERSIONS:
            for language in LANGUAGES:
                for key in (
                    "errors.ssl_certificate_missing",
                    "errors.unavailable_environment",
                    "errors.branding_overwrite",
                    "status.installing_app",
                    "cloud.signed_in_as",
                ):
                    with self.subTest(version=version, language=language, key=key):
                        rule = self.rules[version][key]
                        translated = rule["template"].format(
                            text=json.dumps(self.messages[language][key], ensure_ascii=False)
                        )
                        _, expression = fields(translated)
                        output = evaluate(expression)
                        self.assertNotIn("<cert&", output)
                        self.assertNotIn("<missing&", output)
                        self.assertNotIn("<new&", output)
                        self.assertNotIn("<old&", output)
                        self.assertNotIn("<sample&", output)
                        self.assertNotIn("<user&", output)
                        if key in ("errors.ssl_certificate_missing", "errors.unavailable_environment"):
                            self.assertIn("<br>- ", output)
                        if key in ("errors.branding_overwrite", "status.installing_app"):
                            self.assertIn("<b>", output)

    def test_format_conversion_keeps_dynamic_values(self):
        for version in VERSIONS:
            for language in LANGUAGES:
                for key in ("account.connected_user", "env.open_with"):
                    with self.subTest(version=version, language=language, key=key):
                        rule = self.rules[version][key]
                        translated = rule["template"].format(
                            text=json.dumps(self.messages[language][key], ensure_ascii=False)
                        )
                        source_ast = ast.parse(rule["original"]).body[0].value
                        translated_ast = ast.parse(translated).body[0].value
                        if key == "env.open_with":
                            source_ast = source_ast.args[0]
                            translated_ast = translated_ast.args[0]
                        original_output = evaluate(source_ast)
                        translated_output = evaluate(translated_ast)
                        token = CONTEXT["state"].username if key == "account.connected_user" else CONTEXT["word"]
                        self.assertIn(token, original_output)
                        self.assertIn(token, translated_output)

    def test_rejects_lost_dynamic_escape_expression(self):
        rule = self.rules["2.7.4"]["errors.ssl_certificate_missing"]
        translated = rule["template"].format(
            text=json.dumps(self.messages["ja_JP"]["errors.ssl_certificate_missing"],
                            ensure_ascii=False)
        )
        broken = translated.replace("html.escape(ssl_certificate)", "ssl_certificate")
        self.assertNotEqual(translated, broken)
        safe_fields, safe_expression = fields(translated)
        broken_fields, broken_expression = fields(broken)
        self.assertNotEqual(Counter(safe_fields), Counter(broken_fields))
        self.assertNotIn(CONTEXT["ssl_certificate"], evaluate(safe_expression))
        self.assertIn(CONTEXT["ssl_certificate"], evaluate(broken_expression))
