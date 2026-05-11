from __future__ import annotations

import hashlib
from typing import Iterable

from app.models.violation_event import ViolationEvent
from app.utils.label_utils import get_display_label, normalize_label_name


def build_live_alarm_group_key(event: ViolationEvent) -> str:
    session_started_at = str(event.meta.get("session_started_at") or event.timestamp)
    event_kind = str(event.meta.get("event_kind") or "start")
    snapshot_path = str(event.snapshot_path or "")
    raw_key = "|".join(
        [
            event.camera_id,
            session_started_at,
            event.timestamp,
            event_kind,
            snapshot_path,
        ]
    )
    digest = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:12]
    return f"live_{digest}"


def aggregate_live_alarm_events(
    events: Iterable[ViolationEvent],
    camera_name_map: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    camera_name_map = camera_name_map or {}
    grouped: dict[str, dict[str, object]] = {}
    ordered_keys: list[str] = []

    for event in events:
        group_key = build_live_alarm_group_key(event)
        normalized_type = normalize_label_name(event.violation_type)
        violation_types = [normalized_type]
        violation_type_text = get_display_label(normalized_type)
        snapshot_url = _build_snapshot_url(event.snapshot_path)

        if group_key not in grouped:
            grouped[group_key] = {
                "event_id": group_key,
                "aggregate_key": group_key,
                "camera_id": event.camera_id,
                "camera_name": camera_name_map.get(event.camera_id, event.camera_id),
                "timestamp": event.timestamp,
                "confidence": float(event.confidence),
                "snapshot_path": event.snapshot_path,
                "snapshot_url": snapshot_url,
                "violation_type": normalized_type,
                "violation_types": violation_types,
                "violation_type_text": violation_type_text,
                "violation_type_texts": [violation_type_text],
                "raw_event_ids": [event.event_id],
                "violation_counts": {
                    normalized_type: int(event.meta.get("violation_count") or 0),
                },
                "meta": {
                    "event_kind": event.meta.get("event_kind"),
                    "session_started_at": event.meta.get("session_started_at"),
                },
            }
            ordered_keys.append(group_key)
            continue

        aggregate_item = grouped[group_key]
        if normalized_type not in aggregate_item["violation_types"]:
            aggregate_item["violation_types"].append(normalized_type)
            aggregate_item["violation_type_texts"].append(violation_type_text)
            aggregate_item["violation_type_text"] = " / ".join(aggregate_item["violation_type_texts"])
        aggregate_item["violation_counts"][normalized_type] = int(
            event.meta.get("violation_count") or aggregate_item["violation_counts"].get(normalized_type, 0)
        )
        aggregate_item["raw_event_ids"].append(event.event_id)
        aggregate_item["confidence"] = max(
            float(aggregate_item["confidence"]),
            float(event.confidence),
        )
        if event.snapshot_path and not aggregate_item["snapshot_path"]:
            aggregate_item["snapshot_path"] = event.snapshot_path
            aggregate_item["snapshot_url"] = snapshot_url

    return [grouped[group_key] for group_key in ordered_keys]


def _build_snapshot_url(snapshot_path: str | None) -> str | None:
    if not snapshot_path:
        return None

    normalized = snapshot_path.replace("\\", "/").lstrip("/")
    if normalized.startswith("snapshots/"):
        normalized = normalized[len("snapshots/"):]
    if not normalized:
        return None
    return "/snapshots/" + normalized
