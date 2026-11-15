from build_rules import load, originals, verify, save


RULE_ID = "account.sign_in"

TARGET_FILE = "widgets/dialogs/login/account_dialogs.py"

EXPECTED_ORIGINAL = "result.action = 'SIGN IN'"


def main():
    config, locale = load()

    matches = [
        (entry, rule)
        for entry in config["files"]
        for rule in entry["rules"]
        if rule["id"] == RULE_ID
    ]

    if len(matches) != 1:
        raise RuntimeError(
            f"预期找到一条目标规则，实际找到 {len(matches)} 条"
        )

    entry, rule = matches[0]

    if entry["path"] != TARGET_FILE:
        raise RuntimeError("目标文件不匹配")

    if rule["original"].strip() != EXPECTED_ORIGINAL:
        raise RuntimeError("目标源码不匹配")

    if locale["messages"].get(RULE_ID) != "登录":
        raise RuntimeError("当前翻译内容不匹配")

    _, source = originals(config)

    verify(config, locale, source)

    entry["rules"].remove(rule)
    del locale["messages"][RULE_ID]

    verify(config, locale, source)

    save(config, locale)

    print("已移除内部操作标识的错误翻译规则")
    print("原始 SIGN IN 标识将被保留")
    print("其他汉化规则保持不变")
    print("原有规则已自动备份")
    print("当前 Navigator 安装尚未修改")


if __name__ == "__main__":
    main()