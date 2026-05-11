from __future__ import annotations

DISPLAY_LABEL_MAP = {
    "person": "人员",
    "helmet": "安全帽",
    "vest": "反光背心",
    "smoking": "抽烟行为",
    "no_vest": "无反光背心",
    "no_helmet": "无安全帽",
}

VIOLATION_DISPLAY_CLASSES = {
    "smoking",
    "no_vest",
    "no_helmet",
}

LABEL_ALIAS_MAP = {
    "person": "person",
    "people": "person",
    "helmet": "helmet",
    "hardhat": "helmet",
    "hard_hat": "helmet",
    "safety_helmet": "helmet",
    "vest": "vest",
    "safety_vest": "vest",
    "reflective_vest": "vest",
    "smoke": "smoking",
    "smoking": "smoking",
    "cigarette": "smoking",
    "no_vest": "no_vest",
    "novest": "no_vest",
    "no_helmet": "no_helmet",
    "nohelmet": "no_helmet",
}


def normalize_label_name(value: str) -> str:
    normalized = (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    return LABEL_ALIAS_MAP.get(normalized, normalized)


def get_display_label(value: str) -> str:
    normalized = normalize_label_name(value)
    return DISPLAY_LABEL_MAP.get(normalized, normalized)


def should_display_violation_overlay(value: str) -> bool:
    normalized = normalize_label_name(value)
    return normalized in VIOLATION_DISPLAY_CLASSES
