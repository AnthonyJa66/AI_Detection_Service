"""违规标注样式工具。

前端主画面 overlay 和后端报警截图都从这里读取同一套颜色与文字样式，
避免两边各自维护一套映射导致视觉不一致。
"""

from __future__ import annotations

from typing import Any

from app.utils.label_utils import normalize_label_name


ANNOTATION_TEXT_COLOR = "#ffffff"
ANNOTATION_LINE_WIDTH = 2
ANNOTATION_FONT_SIZE = 14
ANNOTATION_TEXT_BOX_HEIGHT = 22
ANNOTATION_TEXT_PADDING_X = 7
DEFAULT_ANNOTATION_COLOR = "#38bdf8"

VIOLATION_ANNOTATION_COLOR_MAP = {
    "smoking": "#ef4444",
    "no_vest": "#f59e0b",
    "no_helmet": "#22c55e",
}


def normalize_annotation_type(value: str | None) -> str:
    return normalize_label_name(value or "")


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    normalized = str(color or DEFAULT_ANNOTATION_COLOR).strip().lstrip("#")
    if len(normalized) != 6:
        normalized = DEFAULT_ANNOTATION_COLOR.lstrip("#")
    return tuple(int(normalized[index:index + 2], 16) for index in (0, 2, 4))


def get_annotation_color_hex(violation_type: str | None) -> str:
    normalized = normalize_annotation_type(violation_type)
    return VIOLATION_ANNOTATION_COLOR_MAP.get(normalized, DEFAULT_ANNOTATION_COLOR)


def get_annotation_color_rgb(violation_type: str | None) -> tuple[int, int, int]:
    return _hex_to_rgb(get_annotation_color_hex(violation_type))


def get_annotation_color_bgr(violation_type: str | None) -> tuple[int, int, int]:
    red, green, blue = get_annotation_color_rgb(violation_type)
    return (blue, green, red)


def build_annotation_styles_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "default": {
            "color": DEFAULT_ANNOTATION_COLOR,
            "textColor": ANNOTATION_TEXT_COLOR,
            "lineWidth": ANNOTATION_LINE_WIDTH,
            "fontSize": ANNOTATION_FONT_SIZE,
            "textBoxHeight": ANNOTATION_TEXT_BOX_HEIGHT,
            "textPaddingX": ANNOTATION_TEXT_PADDING_X,
        }
    }

    for violation_type, color in VIOLATION_ANNOTATION_COLOR_MAP.items():
        payload[violation_type] = {
            "color": color,
            "textColor": ANNOTATION_TEXT_COLOR,
            "lineWidth": ANNOTATION_LINE_WIDTH,
            "fontSize": ANNOTATION_FONT_SIZE,
            "textBoxHeight": ANNOTATION_TEXT_BOX_HEIGHT,
            "textPaddingX": ANNOTATION_TEXT_PADDING_X,
        }

    return payload
