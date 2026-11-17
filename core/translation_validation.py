"""Validate the data shape used by Navigator translation rules."""

# These keys and list widths are determined by the existing Navigator rules.
# Changing their structure requires updating the rule that consumes them.
MAP_KEYS = {
    "nav.tabs": frozenset(("Home", "Environments", "Learning", "Community")),
    "content.card_actions": frozenset((
        "documentation", "webinar", "event", "video", "training", "forum", "social",
    )),
    "packages.filter_labels": frozenset((
        "Installed", "Not installed", "Updatable", "Selected", "All",
    )),
    "content.category_labels": frozenset((
        "documentation", "training", "forum", "social",
    )),
    "preferences.action_buttons": frozenset((
        "Apply", "Cancel", "Reset to defaults",
    )),
    "logger.headers": frozenset((
        "time", "level", "module", "method", "line", "path",
        "message", "exception", "traceback",
    )),
    "content.training_buttons": frozenset((
        "Get Certified", "Get Access", "Get Free Access",
    )),
}

LIST_LENGTHS = {
    "packages.action_table_headers": 5,
    "packages.action_table_headers_spaced": 5,
}


def _text(value, key):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"翻译内容不是非空字符串：{key}")


def validate_messages(messages):
    if not isinstance(messages, dict):
        raise ValueError("语言包 messages 必须为字典")

    for key, value in messages.items():
        _text(key, "翻译 ID")

        if key in MAP_KEYS:
            if not isinstance(value, dict):
                raise ValueError(f"翻译结构错误（需要字典）：{key}")
            actual = set(value)
            expected = MAP_KEYS[key]
            if actual != expected:
                raise ValueError(
                    f"翻译字典键不一致：{key}，"
                    f"缺失={sorted(expected - actual)}，"
                    f"多余={sorted(actual - expected)}"
                )
        elif key in LIST_LENGTHS:
            if not isinstance(value, list) or len(value) != LIST_LENGTHS[key]:
                raise ValueError(
                    f"翻译列表列数不一致：{key}，"
                    f"需要 {LIST_LENGTHS[key]} 项"
                )
        elif not isinstance(value, str):
            raise ValueError(f"翻译值类型无效：{key}")

        if isinstance(value, str):
            _text(value, key)
        elif isinstance(value, list):
            if not value:
                raise ValueError(f"翻译列表为空：{key}")
            for index, item in enumerate(value):
                _text(item, f"{key}[{index}]")
        elif isinstance(value, dict):
            if not value:
                raise ValueError(f"翻译字典为空：{key}")
            for name, item in value.items():
                _text(name, f"{key} 的内部键")
                _text(item, f"{key}.{name}")

    filters = messages.get("packages.filter_labels")
    if isinstance(filters, dict) and len(set(filters.values())) != len(filters):
        raise ValueError("软件包筛选译文重复：packages.filter_labels")
