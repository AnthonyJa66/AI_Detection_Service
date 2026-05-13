"""Lightweight Flask REST API routes for AI Detection Service."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from app.utils import (
    aggregate_live_alarm_events,
    format_display_time,
    summarize_violation_counts,
)


api_bp = Blueprint("api", __name__)


def _json_response(
    success: bool,
    message: str,
    data: dict | None = None,
    status_code: int = 200,
):
    payload = {
        "success": success,
        "message": message,
        "data": data or {},
    }
    return jsonify(payload), status_code


@api_bp.route("/health", methods=["GET"])
def health():
    """Return AI service health status."""

    try:
        settings = current_app.config.get("APP_SETTINGS", {})
        current_app.logger.info("REST health check requested.")
        return _json_response(
            True,
            "AI Detection Service is running.",
            {
                "service": "AI Detection Service",
                "camera_count": len(settings.get("cameras", [])),
            },
        )
    except Exception as exc:
        current_app.logger.exception("Health check failed: %s", exc)
        return _json_response(False, "Health check failed.", status_code=500)


@api_bp.route("/api/cameras/status", methods=["GET"])
def camera_status():
    """Return all camera runtime statuses."""

    try:
        camera_manager = current_app.extensions["camera_manager"]
        status_map = camera_manager.get_all_status()
        current_app.logger.info("REST camera status requested.")
        return _json_response(True, "Camera status fetched successfully.", status_map)
    except Exception as exc:
        current_app.logger.exception("Failed to get camera status: %s", exc)
        return _json_response(False, "Failed to get camera status.", status_code=500)


@api_bp.route("/api/cameras/<camera_id>/latest", methods=["GET"])
def latest_detection(camera_id: str):
    """Return latest AI detection result for one camera."""

    try:
        video_processor = current_app.extensions["video_processor"]
        camera_manager = current_app.extensions["camera_manager"]
        current_app.logger.info(
            "REST latest detection requested. camera_id=%s",
            camera_id,
        )

        if not video_processor.has_camera(camera_id):
            return _json_response(False, "Camera not found.", status_code=404)

        detection_result = video_processor.get_latest_detection(camera_id)
        if detection_result is None:
            status = camera_manager.get_status(camera_id) or {}
            return _json_response(
                True,
                "No detection result available.",
                {
                    "camera_id": camera_id,
                    "timestamp": "",
                    "frame_width": 0,
                    "frame_height": 0,
                    "detections": [],
                    "camera_status": status,
                },
            )

        return _json_response(
            True,
            "Latest detection result fetched successfully.",
            {
                **detection_result.to_dict(),
                **summarize_violation_counts(detection_result),
            },
        )
    except Exception as exc:
        current_app.logger.exception("Failed to get latest detection: %s", exc)
        return _json_response(
            False,
            "Failed to get latest detection result.",
            status_code=500,
        )


@api_bp.route("/api/alerts/recent", methods=["GET"])
def recent_alerts():
    """Return recent violation alerts."""

    try:
        limit = min(20, max(1, int(request.args.get("limit", 10))))
        alerts = _load_recent_alerts(limit=limit)
        current_app.logger.info("REST recent alerts requested. limit=%s", limit)
        return _json_response(
            True,
            "Recent alerts fetched successfully.",
            {"items": alerts},
        )
    except Exception as exc:
        current_app.logger.exception("Failed to get recent alerts: %s", exc)
        return _json_response(False, "Failed to get recent alerts.", status_code=500)


@api_bp.route("/api/alerts/summary", methods=["GET"])
def alerts_summary():
    """Return lightweight alert summary for dashboard display."""

    try:
        camera_manager = current_app.extensions["camera_manager"]
        status_map = camera_manager.get_all_status()
        alerts = _load_recent_alerts(limit=20)
        alert_types = _summarize_alert_types(alerts)

        camera_total = len(status_map)
        camera_online = sum(
            1
            for status in status_map.values()
            if status.get("status") == "running" and bool(status.get("thread_alive"))
        )

        summary = {
            "total_alerts": len(alerts),
            "today_alerts": _count_today_alerts(alerts),
            "camera_online": camera_online,
            "camera_total": camera_total,
            "alert_types": alert_types,
        }
        current_app.logger.info("REST alert summary requested.")
        return _json_response(True, "Alert summary fetched successfully.", summary)
    except Exception as exc:
        current_app.logger.exception("Failed to get alert summary: %s", exc)
        return _json_response(False, "Failed to get alert summary.", status_code=500)


def _load_recent_alerts(limit: int) -> list[dict]:
    alarm_manager = current_app.extensions["alarm_manager"]
    repository = alarm_manager.repository
    settings = current_app.config.get("APP_SETTINGS", {})
    camera_name_map = _build_camera_name_map(settings.get("cameras", []))

    events = repository.list_events(limit=max(limit * 5, limit))
    aggregated_events = aggregate_live_alarm_events(
        events,
        camera_name_map=camera_name_map,
    )
    return [
        _build_alert_view_model(item)
        for item in aggregated_events[:limit]
    ]


def _build_camera_name_map(cameras: list[dict]) -> dict[str, str]:
    return {
        camera["id"]: camera.get("name", camera["id"])
        for camera in cameras
    }


def _build_alert_view_model(item: dict[str, object]) -> dict[str, object]:
    timestamp = str(item["timestamp"])
    snapshot_path = item.get("snapshot_path")
    if not isinstance(snapshot_path, str):
        snapshot_path = None

    return {
        "event_id": item["event_id"],
        "aggregate_key": item["aggregate_key"],
        "camera_id": item["camera_id"],
        "camera_name": item["camera_name"],
        "violation_type": item["violation_type"],
        "violation_types": list(item.get("violation_types", [])),
        "violation_type_text": item["violation_type_text"],
        "timestamp": timestamp,
        "display_time": format_display_time(timestamp),
        "confidence": float(item["confidence"]),
        "snapshot_path": snapshot_path,
        "snapshot_url": None,
        "raw_event_ids": list(item.get("raw_event_ids", [])),
        "violation_counts": dict(item.get("violation_counts", {})),
    }


def _summarize_alert_types(alerts: list[dict]) -> dict[str, int]:
    alert_types = {
        "NO_HELMET": 0,
        "NO_VEST": 0,
        "SMOKING": 0,
    }
    type_map = {
        "no_helmet": "NO_HELMET",
        "nohelmet": "NO_HELMET",
        "no_vest": "NO_VEST",
        "novest": "NO_VEST",
        "smoking": "SMOKING",
        "smoke": "SMOKING",
    }

    for alert in alerts:
        violation_counts = alert.get("violation_counts")
        if isinstance(violation_counts, dict) and violation_counts:
            for raw_type, count in violation_counts.items():
                normalized_type = type_map.get(str(raw_type).strip().lower())
                if normalized_type is None:
                    continue
                alert_types[normalized_type] += int(count)
            continue

        raw_type = str(alert.get("violation_type") or "").strip().lower()
        normalized_type = type_map.get(raw_type)
        if normalized_type is not None:
            alert_types[normalized_type] += 1

    return alert_types


def _count_today_alerts(alerts: list[dict]) -> int:
    today_prefix = datetime.now().strftime("%Y-%m-%d")
    return sum(
        1
        for alert in alerts
        if str(alert.get("display_time") or alert.get("timestamp") or "").startswith(
            today_prefix
        )
    )
