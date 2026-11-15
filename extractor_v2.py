import ast
import csv
import hashlib
import importlib.metadata
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


PROJECT = Path(__file__).resolve().parent
SOURCE = Path(sys.prefix) / "Lib" / "site-packages" / "anaconda_navigator"
OUT = PROJECT / "reports" / "v2"

UI_METHODS = {
    "setText", "setWindowTitle", "setToolTip", "setStatusTip",
    "setWhatsThis", "setPlaceholderText", "setAccessibleName",
    "setTitle", "setLabelText", "setInformativeText",
    "setDetailedText", "setTabText", "setItemText",
    "setHeaderData", "setHorizontalHeaderLabels",
    "setVerticalHeaderLabels", "addItem", "addTab",
    "addAction", "addMenu", "insertItem", "insertTab",
}

UI_CLASSES = {
    "QLabel", "QPushButton", "QCheckBox", "QRadioButton",
    "QAction", "QGroupBox", "QMenu", "QMessageBox",
}

TRANSLATORS = {"_", "gettext", "ngettext", "tr", "translate"}


def callable_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def parents_of(node, parent_map):
    while node in parent_map:
        node = parent_map[node]
        yield node


def is_ui(name):
    return (
        name in UI_METHODS
        or name in UI_CLASSES
        or name.startswith(
            ("Button", "Label", "CheckBox", "RadioButton")
        )
    )


def looks_visible(value):
    value = re.sub(r"<[^>]*>", " ", value).strip()

    if len(value) < 3:
        return False

    if re.match(r"^(https?://|[./\\]|--)", value):
        return False

    return bool(
        re.search(r"[A-Za-z]{2,}\s+[A-Za-z]{2,}", value)
        or re.fullmatch(r"&?[A-Z][a-zA-Z]{2,}[!?]?", value)
        or re.search(r"[A-Za-z]{3,}[!?：:]$", value)
    )


def fstring_preview(node):
    parts = []

    for part in node.values:
        if isinstance(part, ast.Constant):
            parts.append(str(part.value))
        elif isinstance(part, ast.FormattedValue):
            parts.append("{" + ast.unparse(part.value) + "}")

    return "".join(parts)


def scan(path):
    content = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(content, filename=str(path))

    parent_map = {
        child: node
        for node in ast.walk(tree)
        for child in ast.iter_child_nodes(node)
    }

    docs = set()

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
                expr = node.body[0].value

                if isinstance(expr, ast.Constant):
                    if isinstance(expr.value, str):
                        docs.add(expr)

    relative = path.relative_to(SOURCE).as_posix()
    entries = []

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            if any(
                isinstance(p, ast.JoinedStr)
                for p in parents_of(node, parent_map)
            ):
                continue

            value = fstring_preview(node)
            dynamic = True

        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, str):
                continue

            if node in docs:
                continue

            if any(
                isinstance(p, ast.JoinedStr)
                for p in parents_of(node, parent_map)
            ):
                continue

            value = node.value
            dynamic = False

        else:
            continue

        if not value.strip():
            continue

        if not re.search(r"[A-Za-z]", value):
            continue

        ancestors = list(parents_of(node, parent_map))

        calls = [
            ancestor
            for ancestor in ancestors
            if isinstance(ancestor, ast.Call)
        ]

        names = [
            callable_name(call.func)
            for call in calls
        ]

        scope = ".".join(
            reversed([
                ancestor.name
                for ancestor in ancestors
                if isinstance(
                    ancestor,
                    (
                        ast.ClassDef,
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                    ),
                )
            ])
        ) or "<module>"

        if any(name in TRANSLATORS for name in names):
            category = "gettext"
        elif any(is_ui(name) for name in names):
            category = "ui"
        elif dynamic:
            category = "dynamic"
        else:
            category = "review"

        if category in {"gettext", "ui"}:
            priority = "high"
        elif relative.startswith("widgets/") and looks_visible(value):
            priority = "medium"
        else:
            priority = "low"

        call = calls[0] if calls else None
        snippet = (
            ast.get_source_segment(content, call)
            if call else ""
        )

        entries.append({
            "file": relative,
            "line": node.lineno,
            "scope": scope,
            "call": names[0] if names else "",
            "category": category,
            "priority": priority,
            "dynamic": dynamic,
            "text": value,
            "context": (snippet or "")[:350],
        })

    return entries


def main():
    if not SOURCE.is_dir():
        raise RuntimeError("请在 Anaconda Prompt 中运行")

    version = importlib.metadata.version("anaconda-navigator")

    all_rows = []
    errors = []
    files = sorted(SOURCE.rglob("*.py"))

    for path in files:
        try:
            all_rows.extend(scan(path))
        except (OSError, UnicodeError, SyntaxError) as error:
            errors.append({
                "file": str(path),
                "error": str(error),
            })

    all_rows.sort(
        key=lambda row: (
            row["file"],
            row["line"],
            row["scope"],
            row["text"],
        )
    )

    counts = defaultdict(int)

    for row in all_rows:
        key = (
            row["file"],
            row["scope"],
            row["call"],
            row["text"],
        )

        counts[key] += 1

        key_text = "\0".join(
            map(str, (*key, counts[key]))
        )

        row["id"] = hashlib.sha256(
            key_text.encode("utf-8")
        ).hexdigest()[:16]

    OUT.mkdir(parents=True, exist_ok=True)

    (OUT / "all.json").write_text(
        json.dumps(
            all_rows, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )

    candidates = [
        row
        for row in all_rows
        if row["priority"] != "low"
    ]

    columns = [
        "id", "priority", "category", "file",
        "line", "scope", "call", "dynamic",
        "text", "context",
    ]

    with (OUT / "candidates.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=columns
        )
        writer.writeheader()
        writer.writerows(candidates)

    summary = {
        "navigator_version": version,
        "files": len(files),
        "records": len(all_rows),
        "candidates": len(candidates),
        "category": dict(
            Counter(row["category"] for row in all_rows)
        ),
        "priority": dict(
            Counter(row["priority"] for row in all_rows)
        ),
        "errors": errors,
    }

    (OUT / "summary.json").write_text(
        json.dumps(
            summary, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )

    print(json.dumps(
        summary, ensure_ascii=False, indent=2
    ))

    print("候选清单：", OUT / "candidates.csv")


if __name__ == "__main__":
    main()