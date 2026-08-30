from __future__ import annotations

from typing import Any

_FIRST_PERSON_REPLACEMENTS = (
    ("原作者的主观预期是", "我预计"),
    ("原作者的主观预期", "我预计"),
    ("原作者预期", "我预计"),
    ("原作者认为", "我认为"),
    ("作者的主观预期是", "我预计"),
    ("作者的主观预期", "我预计"),
    ("作者主观预期", "我预计"),
    ("作者预期", "我预计"),
    ("作者认为", "我认为"),
    ("输入认为", "我认为"),
    ("原文认为", "我认为"),
)


def first_person_text(value: Any) -> Any:
    """Render input-derived analysis in AXIS's first-person editorial voice."""

    if not isinstance(value, str):
        return value
    output = value
    for source, replacement in _FIRST_PERSON_REPLACEMENTS:
        output = output.replace(source, replacement)
    return output
