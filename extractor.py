import ast
import csv
import hashlib
import importlib.metadata
import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = Path(sys.prefix) / "Lib" / "site-packages" / "anaconda_navigator"
REPORTS = ROOT / "reports"

UI_METHODS = {
    "setText",
    "setWindowTitle",
    "setToolTip",
    "setStatusTip",
    "setWhatsThis",
    "setPlaceholderText",
    "setAccessibleName",
    "setAccessibleDescription",
    "setTitle",
    "setLabelText",
    "setInformativeText",
    "setDetailedText",
    "setTabText",
    "setItemText",
    "setHeaderData",
    "setHorizontalHeaderLabels",
    "setVerticalHeaderLabels",
    "addItem",
    "addTab",
    "addAction",
    "addMenu",
    "insertItem",
    "insertTab",
}

UI_CLASSES = {
    "QLabel",
    "QPushButton",
    "QCheckBox",
    "QRadioButton",
    "QAction",
    "QGroupBox",
    "QMenu",
    "QMessageBox",
    "ButtonPrimary",
    "ButtonNormal",
    "ButtonBase",
    "ButtonHeader",
    "CheckBoxBase",
    "LabelBase",
}

TRANSLATORS = {"_", "gettext", "ngettext"}


def function_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def get_category(node, parents):
    current = node

    while current in parents:
        current = parents[current]

        if isinstance(current, ast.JoinedStr):
            return "dynamic"

        if isinstance(current, ast.Call):
            name = function_name(current.func)

            if name in TRANSLATORS:
                return "gettext"

            if name in UI_METHODS or name in UI_CLASSES:
                return "ui"

            if isinstance(current.func, ast.Attribute):
                full = ast.unparse(current.func)

                if "QMessageBox." in full:
                    return "ui"

            return "review"

    return "review"


def scan_file(path):
    relative = path.relative_to(SOURCE).as_posix()
    content = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(content, filename=str(path))

    parents = {
        child: node
        for node in ast.walk(tree)
        for child in ast.iter_child_nodes(node)
    }

    docstrings = set()

    for node in ast.walk(tree):
        if isinstance(
            node,
            (
                ast.Module,
                ast.ClassDef,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value

                if isinstance(value, ast.Constant):
                    if isinstance(value.value, str):
                        docstrings.add(id(value))

    records = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue

        if not isinstance(node.value, str):
            continue

        if id(node) in docstrings:
            continue

        value = node.value

        if not value.strip():
            continue

        if not re.search(r"[A-Za-z]", value):
            continue

        category = get_category(node, parents)

        identifier = hashlib.sha256(
            f"{relative}:{node.lineno}:{node.col_offset}:{value}".encode()
        ).hexdigest()[:16]

        records.append({
            "id": identifier,
            "file": relative,
            "line": node.lineno,
            "column": node.col_offset,
            "category": category,
            "text": value,
        })

    return records


def main():
    if not SOURCE.is_dir():
        raise RuntimeError(
            "找不到 Navigator 源码，请使用 Anaconda Prompt"
        )

    version = importlib.metadata.version("anaconda-navigator")
    files = sorted(SOURCE.rglob("*.py"))

    records = []
    errors = []

    for path in files:
        try:
            records.extend(scan_file(path))
        except (SyntaxError, UnicodeError, OSError) as error:
            errors.append({
                "file": str(path.relative_to(SOURCE)),
                "error": str(error),
            })

    REPORTS.mkdir(parents=True, exist_ok=True)

    json_path = REPORTS / "strings.json"
    csv_path = REPORTS / "strings.csv"
    summary_path = REPORTS / "summary.json"

    json_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with csv_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "id",
                "file",
                "line",
                "column",
                "category",
                "text",
            ],
        )
        writer.writeheader()
        writer.writerows(records)

    counts = Counter(
        record["category"] for record in records
    )

    summary = {
        "navigator_version": version,
        "source_files": len(files),
        "extracted_strings": len(records),
        "unique_strings": len(
            {record["text"] for record in records}
        ),
        "categories": dict(counts),
        "scan_errors": errors,
    }

    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Navigator 版本：{version}")
    print(f"扫描源码文件：{len(files)}")
    print(f"提取字符串：{len(records)}")
    print(f"不同字符串：{summary['unique_strings']}")

    for category in ("ui", "gettext", "dynamic", "review"):
        print(f"{category}：{counts[category]}")

    print(f"扫描异常：{len(errors)}")
    print(f"报告目录：{REPORTS}")


if __name__ == "__main__":
    main()