from __future__ import annotations

import re
from typing import Any

_ATTRIBUTION_PREFIXES = (
    "原作者的主观预期是",
    "作者的主观预期是",
    "原作者的主观预期",
    "作者的主观预期",
    "原作者预期",
    "作者主观预期",
    "作者预期",
    "原作者认为",
    "作者认为",
    "输入认为",
    "原文认为",
    "Mentor 认为",
    "Mentor认为",
    "大哥认为",
    "我们认为",
    "我认为",
    "我觉得",
    "我预计",
)
_IMAGE_REFERENCES = (
    "如图所示",
    "图中",
    "上图",
    "下图",
    "图里的",
    "框内",
    "圈出的区域",
    "红线",
    "蓝线",
    "箭头",
)


def public_analysis_text(value: Any) -> Any:
    """Remove attribution and image-dependent wording from member-facing analysis."""

    if not isinstance(value, str):
        return value
    output = value.strip()
    for phrase in _ATTRIBUTION_PREFIXES:
        output = output.replace(phrase, "")
    output = output.replace("我关注", "当前关注").replace("我们关注", "当前关注")
    for phrase in _IMAGE_REFERENCES:
        output = output.replace(phrase, "")
    output = re.sub(r"[ \t]{2,}", " ", output)
    output = re.sub(r"^[，,:：、\s]+", "", output)
    output = re.sub(r"\n[ \t]+", "\n", output)
    return output.strip()


def first_person_text(value: Any) -> Any:
    """Compatibility alias for the former Analysis voice helper."""

    return public_analysis_text(value)
