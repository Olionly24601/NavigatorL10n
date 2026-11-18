import argparse
import sys

from core.engine import apply, check, restore, status


def main():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="backslashreplace")
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(
        description="Anaconda Navigator 多语言本地化工具"
    )
    parser.add_argument(
        "command",
        choices=["check", "status", "apply", "restore"],
    )
    parser.add_argument(
        "--lang",
        default="zh_CN",
        help="目标语言，默认 zh_CN",
    )
    args = parser.parse_args()

    try:
        if args.command == "check":
            check(args.lang)
        elif args.command == "status":
            status()
        elif args.command == "apply":
            apply(args.lang)
        elif args.command == "restore":
            restore()
    except Exception as error:
        print(f"操作失败：{error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()