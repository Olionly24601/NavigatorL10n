from pathlib import Path

from build_rules import load, originals


PROJECT = Path(__file__).resolve().parents[1]

WATCH = {
    "widgets/dialogs/login/account_dialogs.py": [
        "REPOSITORIES",
        "SIGN IN",
        "result.action",
    ],
    "widgets/manager/packages.py": [
        "combobox_filter",
        "COMBOBOX_VALUES_ORDERED",
        "filter_package",
    ],
    "widgets/manager/table.py": [
        "_filterbox",
        "COMBOBOX_VALUES.get",
        "filter_changed",
    ],
    "widgets/manager/model.py": [
        "'Name'",
        "'Version'",
        "'Description'",
        "'Status'",
        "headerData",
    ],
    "widgets/lists/content.py": [
        "'documentation': 'Read'",
        "valid_tags",
    ],
}


def main():
    config, _ = load()
    root, sources = originals(config)

    report = ["NavigatorZH 源码语义审查", ""]

    for relative, keywords in WATCH.items():
        lines = sources[relative].splitlines()
        selected = set()

        report.append(f"===== {relative} =====")

        for keyword in keywords:
            matches = [
                index
                for index, line in enumerate(lines)
                if keyword in line
            ]

            report.append(
                f"{keyword}: {len(matches)} 处"
            )

            for index in matches[:12]:
                start = max(0, index - 4)
                end = min(len(lines), index + 5)
                selected.update(range(start, end))

        previous = -2

        for index in sorted(selected):
            if index > previous + 1:
                report.append("...")

            report.append(
                f"{index + 1:4d} | {lines[index]}"
            )
            previous = index

        report.append("")

    report.append("===== Conda package 提示来源 =====")

    found = 0

    for path in root.rglob("*.py"):
        relative = path.relative_to(root).as_posix()

        if relative in sources:
            content = sources[relative]
        else:
            content = path.read_bytes().decode("utf-8-sig")

        for number, line in enumerate(
            content.splitlines(), 1
        ):
            if "Conda package" in line:
                found += 1
                report.append(
                    f"{relative}:{number}: {line.strip()}"
                )

    if found == 0:
        report.append(
            "Python 源码中未找到该字面量"
        )

    destination = PROJECT / "reports" / "semantic_audit.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)

    destination.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print(f"审查报告已生成：{destination}")
    print("没有修改 Anaconda Navigator 或现有语言补丁规则")


if __name__ == "__main__":
    main()