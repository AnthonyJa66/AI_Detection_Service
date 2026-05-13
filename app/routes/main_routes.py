import time
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit, urlunsplit

import cv2
import numpy as np
from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
    stream_with_context,
    url_for,
)

from app.utils import (
    aggregate_live_alarm_events,
    build_annotation_styles_payload,
    filtered_violation_detections,
    format_display_time,
    get_display_label,
    summarize_violation_counts,
)

# 主界面相关页面、播放接口和检测展示接口都集中在这个蓝图中。
main_bp = Blueprint("main", __name__)
MJPEG_BOUNDARY = "frame"

VIOLATION_OPTIONS = ("smoking", "no_helmet", "no_vest")
STATUS_TEXT_MAP = {
    "running": "\u5728\u7ebf",
    "connecting": "\u8fde\u63a5\u4e2d",
    "reconnecting": "\u91cd\u8fde\u4e2d",
    "stopped": "\u79bb\u7ebf",
    "error": "\u5f02\u5e38",
}

SOURCE_TYPE_TEXT_MAP = {
    "rtsp_camera": "RTSP \u6444\u50cf\u5934",
    "nvr_rtsp": "NVR RTSP \u901a\u9053",
}


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


@main_bp.route("/", methods=["GET"])
def index():
    """主界面：首页播放器、统计卡片和实时报警入口。"""
    try:
        settings = current_app.config.get("APP_SETTINGS", {})
        cameras = settings.get("cameras", [])
        selected_camera = _get_default_camera(cameras)
        recent_alarms = _load_recent_alarms(limit=10)
        return render_template(
            "index.html",
            cameras=cameras,
            selected_camera=selected_camera,
            recent_alarms=recent_alarms,
            annotation_styles=build_annotation_styles_payload(),
            source_type_text_map=SOURCE_TYPE_TEXT_MAP,
        )
    except Exception as exc:
        current_app.logger.exception("Failed to render index page: %s", exc)
        return _json_response(False, "\u9996\u9875\u52a0\u8f7d\u5931\u8d25\u3002", status_code=500)


@main_bp.route("/hik_test", methods=["GET"])
def hik_test():
    hik_config = _build_hik_test_config()
    return render_template("hik_test.html", hik_config=hik_config)


@main_bp.route("/hik/<path:filename>", methods=["GET"])
def hik_asset(filename: str):
    hik_root = Path(current_app.root_path).parent / "hik"
    return send_from_directory(hik_root, filename)


@main_bp.route("/hik_fusion_test", methods=["GET"])
def hik_fusion_test():
    settings = current_app.config.get("APP_SETTINGS", {})
    cameras = settings.get("cameras", [])
    selected_camera = _get_default_camera(cameras)
    hik_config = _build_hik_test_config()
    hik_config["cameraId"] = selected_camera["id"] if selected_camera else ""
    hik_config["latestDetectionApiBaseUrl"] = url_for(
        "main.latest_detection",
        camera_id="__camera_id__",
    )
    hik_config["performanceApiUrl"] = url_for("main.fusion_performance_status")
    return render_template(
        "hik_fusion_test.html",
        hik_config=hik_config,
        cameras=cameras,
        selected_camera=selected_camera,
    )


@main_bp.route("/api/fusion/performance", methods=["GET"])
def fusion_performance_status():
    settings = current_app.config.get("APP_SETTINGS", {})
    return _json_response(
        True,
        "融合验证状态获取成功。",
        {
            "timestamp": datetime.now().astimezone().isoformat(),
            "cpu": _get_cpu_usage_snapshot(),
            "gpu": _get_gpu_usage_snapshot(),
            "detection": {
                "detect_interval_seconds": settings.get("detection", {}).get("detect_interval_seconds"),
                "max_inference_workers": settings.get("detection", {}).get("max_inference_workers"),
                "mode": "python_backend_detection",
            },
            "playback": {
                "mode": "hikvision_js_player_with_canvas_overlay",
            },
        },
    )


@main_bp.route("/alarms", methods=["GET"])
def alarms():
    try:
        alarm_manager = current_app.extensions["alarm_manager"]
        repository = alarm_manager.repository
        settings = current_app.config.get("APP_SETTINGS", {})

        camera_id = (request.args.get("camera_id") or "").strip()
        violation_type = (request.args.get("violation_type") or "").strip()
        start_time_input = (request.args.get("start_time") or "").strip()
        end_time_input = (request.args.get("end_time") or "").strip()
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(100, max(1, int(request.args.get("page_size", 10))))

        start_time = _normalize_filter_datetime(start_time_input, is_end=False)
        end_time = _normalize_filter_datetime(end_time_input, is_end=True)
        offset = (page - 1) * page_size
        camera_name_map = _build_camera_name_map(settings.get("cameras", []))

        events = repository.list_events(
            camera_id=camera_id or None,
            violation_type=violation_type or None,
            start_time=start_time,
            end_time=end_time,
            limit=page_size,
            offset=offset,
        )
        total_count = repository.count_events(
            camera_id=camera_id or None,
            violation_type=violation_type or None,
            start_time=start_time,
            end_time=end_time,
        )
        statistics = repository.get_statistics(
            camera_id=camera_id or None,
            violation_type=violation_type or None,
            start_time=start_time,
            end_time=end_time,
        )

        display_events = [
            _build_alarm_view_model(event, camera_name_map)
            for event in events
        ]

        display_statistics = {
            "total_events": statistics["total_events"],
            "by_violation_type": [
                {
                    "violation_type": item["violation_type"],
                    "violation_type_text": _format_violation_type(item["violation_type"]),
                    "count": item["count"],
                }
                for item in statistics["by_violation_type"]
            ],
            "by_camera": [
                {
                    "camera_id": item["camera_id"],
                    "camera_name": camera_name_map.get(item["camera_id"], item["camera_id"]),
                    "count": item["count"],
                }
                for item in statistics["by_camera"]
            ],
        }

        total_pages = max(1, ceil(total_count / page_size)) if total_count else 1
        page = min(page, total_pages)

        return render_template(
            "alarms.html",
            events=display_events,
            statistics=display_statistics,
            filters={
                "camera_id": camera_id,
                "violation_type": violation_type,
                "start_time": start_time_input,
                "end_time": end_time_input,
                "page_size": page_size,
            },
            camera_options=settings.get("cameras", []),
            violation_options=list(VIOLATION_OPTIONS),
            violation_type_text_map={
                item: get_display_label(item) for item in VIOLATION_OPTIONS
            },
            pagination={
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_prev": page > 1,
                "has_next": page < total_pages,
            },
        )
    except Exception as exc:
        current_app.logger.exception("Failed to render alarms page: %s", exc)
        return _json_response(False, "\u62a5\u8b66\u8bb0\u5f55\u9875\u9762\u52a0\u8f7d\u5931\u8d25\u3002", status_code=500)


@main_bp.route("/health", methods=["GET"])
def health():
    try:
        settings = current_app.config.get("APP_SETTINGS", {})
        current_app.logger.info("REST health check requested.")
        return _json_response(
            True,
            "\u670d\u52a1\u8fd0\u884c\u6b63\u5e38\u3002",
            {
                "app_name": "\u667a\u80fd\u89c6\u9891\u76d1\u63a7\u7cfb\u7edf",
                "camera_count": len(settings.get("cameras", [])),
            },
        )
    except Exception as exc:
        current_app.logger.exception("Health check failed: %s", exc)
        return _json_response(False, "\u5065\u5eb7\u68c0\u67e5\u5931\u8d25\u3002", status_code=500)


@main_bp.route("/api/cameras/status", methods=["GET"])
def camera_status():
    try:
        camera_manager = current_app.extensions["camera_manager"]
        status_map = camera_manager.get_all_status()
        current_app.logger.info("REST camera status requested.")
        return _json_response(True, "\u6444\u50cf\u5934\u72b6\u6001\u83b7\u53d6\u6210\u529f\u3002", status_map)
    except Exception as exc:
        current_app.logger.exception("Failed to get camera status: %s", exc)
        return _json_response(False, "\u6444\u50cf\u5934\u72b6\u6001\u83b7\u53d6\u5931\u8d25\u3002", status_code=500)


@main_bp.route("/api/alerts/recent", methods=["GET"])
@main_bp.route("/api/alarms/latest", methods=["GET"])
def latest_alarms():
    try:
        limit = min(20, max(1, int(request.args.get("limit", 10))))
        alarms = _load_recent_alarms(limit=limit)
        current_app.logger.info("REST recent alerts requested. limit=%s", limit)
        return _json_response(True, "\u6700\u8fd1\u62a5\u8b66\u83b7\u53d6\u6210\u529f\u3002", {"items": alarms})
    except Exception as exc:
        current_app.logger.exception("Failed to get latest alarms: %s", exc)
        return _json_response(False, "\u6700\u8fd1\u62a5\u8b66\u83b7\u53d6\u5931\u8d25\u3002", status_code=500)


@main_bp.route("/api/camera/play_config/<camera_id>", methods=["GET"])
def camera_play_config(camera_id: str):
    settings = current_app.config.get("APP_SETTINGS", {})
    cameras = settings.get("cameras", [])
    camera = next((item for item in cameras if str(item.get("id")) == camera_id), None)
    if camera is None:
        return jsonify(
            {
                "camera_id": camera_id,
                "play_type": "mjpeg",
                "ws_url": "",
                "rtsp_url": "",
                "mjpeg_url": url_for("main.video_feed", camera_id=camera_id),
            }
        ), 404

    camera_type = str(camera.get("type") or "").strip().lower()
    play_type = "hik_sdk" if camera_type == "nvr" else "mjpeg"
    hik_settings = settings.get("hik_playback", {}) or {}
    ws_url = str(camera.get("ws_url") or hik_settings.get("access_url") or "").strip()
    rtsp_url = str(camera.get("rtsp_url") or "").strip()

    return jsonify(
        {
            "camera_id": camera_id,
            "play_type": play_type,
            "ws_url": ws_url,
            "rtsp_url": rtsp_url,
            "mjpeg_url": url_for("main.video_feed", camera_id=camera_id),
        }
    )


@main_bp.route("/api/cameras/<camera_id>/latest", methods=["GET"])
@main_bp.route("/api/detections/latest/<camera_id>", methods=["GET"])
def latest_detection(camera_id: str):
    try:
        video_processor = current_app.extensions["video_processor"]
        camera_manager = current_app.extensions["camera_manager"]
        current_app.logger.info("REST latest detection requested. camera_id=%s", camera_id)

        if not video_processor.has_camera(camera_id):
            return _json_response(False, "\u6444\u50cf\u5934\u4e0d\u5b58\u5728\u3002", status_code=404)

        detection_result = video_processor.get_latest_detection(camera_id)
        if detection_result is None:
            status = camera_manager.get_status(camera_id) or {}
            return _json_response(
                True,
                "\u6682\u65e0\u68c0\u6d4b\u7ed3\u679c\u3002",
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
            "\u6700\u65b0\u68c0\u6d4b\u7ed3\u679c\u83b7\u53d6\u6210\u529f\u3002",
            {
                **detection_result.to_dict(),
                **summarize_violation_counts(detection_result),
            },
        )
    except Exception as exc:
        current_app.logger.exception("Failed to get latest detection: %s", exc)
        return _json_response(False, "\u6700\u65b0\u68c0\u6d4b\u7ed3\u679c\u83b7\u53d6\u5931\u8d25\u3002", status_code=500)


@main_bp.route("/api/main/playback-config/<camera_id>", methods=["GET"])
def main_playback_config(camera_id: str):
    """返回主界面播放配置。

    前端会根据 camera.type 分流：
    - NVR：海康 Web SDK
    - RTSP：Flask MJPEG
    """
    settings = current_app.config.get("APP_SETTINGS", {})
    cameras = settings.get("cameras", [])
    camera = next((item for item in cameras if str(item.get("id")) == camera_id), None)
    if camera is None:
        return _json_response(False, "摄像头不存在。", status_code=404)

    payload = _build_hik_playback_payload(camera, settings)
    payload.update(
        {
            "mjpeg_url": url_for("main.video_feed", camera_id=camera_id),
            "demo_base_path": url_for("main.hik_asset", filename="dist"),
            "polyfill_url": url_for("main.hik_asset", filename="dist/polyfill2.js"),
            "plugin_url": url_for("main.hik_asset", filename="dist/jsPlugin-1.2.0.min.js"),
        }
    )

    return _json_response(
        True,
        "主界面海康播放配置获取成功。",
        payload,
    )


@main_bp.route("/api/main/detections/overlay/<camera_id>", methods=["GET"])
def main_detection_overlay(camera_id: str):
    """返回主界面检测统计与叠框数据。

    这里和播放方式解耦：只要 camera_id 相同，前端就能继续读检测结果。
    """
    try:
        video_processor = current_app.extensions["video_processor"]
        camera_manager = current_app.extensions["camera_manager"]

        if not video_processor.has_camera(camera_id):
            return _json_response(False, "摄像头不存在。", status_code=404)

        camera_status = camera_manager.get_status(camera_id) or {}
        detection_result = video_processor.get_latest_detection(camera_id)
        if detection_result is None:
            return _json_response(
                True,
                "暂无检测结果。",
                {
                    "camera_id": camera_id,
                    "frame_time": "",
                    "frame_width": 0,
                    "frame_height": 0,
                    "violations": [],
                    "stats": {
                        "no_helmet": 0,
                        "no_vest": 0,
                        "smoking": 0,
                    },
                    "camera_status": camera_status,
                },
            )

        # 后端检测线程未稳定运行时，主动返回空结果，避免前端继续展示旧叠框。
        if camera_status.get("status") != "running":
            return _json_response(
                True,
                "检测线程未稳定运行。",
                {
                    "camera_id": detection_result.camera_id,
                    "frame_time": detection_result.timestamp,
                    "frame_width": detection_result.frame_width,
                    "frame_height": detection_result.frame_height,
                    "violations": [],
                    "stats": {
                        "no_helmet": 0,
                        "no_vest": 0,
                        "smoking": 0,
                    },
                    "camera_status": camera_status,
                },
            )

        violation_items = []
        for detection in filtered_violation_detections(detection_result):
            normalized_type = str(detection.class_name).strip().lower()
            if normalized_type not in {"no_helmet", "no_vest", "smoking", "nohelmet", "novest", "smoke"}:
                continue
            bbox = detection.bbox if isinstance(detection.bbox, list) else [0, 0, 0, 0]
            if len(bbox) != 4:
                continue
            violation_items.append(
                {
                    "type": normalized_type,
                    "type_label": get_display_label(normalized_type),
                    "confidence": float(detection.confidence),
                    "bbox": {
                        "x1": int(bbox[0]),
                        "y1": int(bbox[1]),
                        "x2": int(bbox[2]),
                        "y2": int(bbox[3]),
                    },
                }
            )

        violation_summary = summarize_violation_counts(detection_result)
        return _json_response(
            True,
            "主界面叠框检测结果获取成功。",
            {
                "camera_id": detection_result.camera_id,
                "frame_time": detection_result.timestamp,
                "frame_width": detection_result.frame_width,
                "frame_height": detection_result.frame_height,
                "violations": violation_items,
                "stats": {
                    "no_helmet": int(violation_summary.get("no_helmet_count", 0)),
                    "no_vest": int(violation_summary.get("no_vest_count", 0)),
                    "smoking": int(violation_summary.get("smoking_count", 0)),
                },
                "camera_status": camera_status,
            },
        )
    except Exception as exc:
        current_app.logger.exception("Failed to get main overlay detection: %s", exc)
        return _json_response(False, "主界面叠框检测结果获取失败。", status_code=500)


@main_bp.route("/video_feed/<camera_id>", methods=["GET"])
def video_feed(camera_id: str):
    try:
        video_processor = current_app.extensions["video_processor"]
        if not video_processor.has_camera(camera_id):
            return _json_response(False, "\u6444\u50cf\u5934\u4e0d\u5b58\u5728\u3002", status_code=404)

        overlay_enabled = _parse_bool_arg(request.args.get("overlay"))

        return Response(
            stream_with_context(_mjpeg_stream(camera_id, overlay_enabled=overlay_enabled)),
            mimetype=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )
    except Exception as exc:
        current_app.logger.exception(
            "Failed to open video feed for %s: %s",
            camera_id,
            exc,
        )
        return _json_response(False, "\u89c6\u9891\u6d41\u6253\u5f00\u5931\u8d25\u3002", status_code=500)


@main_bp.route("/snapshots/<path:filename>", methods=["GET"])
def snapshot_file(filename: str):
    try:
        settings = current_app.config.get("APP_SETTINGS", {})
        snapshot_dir = Path(settings["paths"]["snapshot_dir"]).resolve()
        return send_from_directory(snapshot_dir, filename)
    except Exception as exc:
        current_app.logger.exception("Failed to serve snapshot %s: %s", filename, exc)
        return _json_response(False, "\u5feb\u7167\u6587\u4ef6\u8bfb\u53d6\u5931\u8d25\u3002", status_code=404)


def _mjpeg_stream(camera_id: str, overlay_enabled: bool):
    """MJPEG 输出生成器。

    RTSP 摄像头主界面播放走这里；NVR 仍由海康 Web SDK 负责播放。
    """
    camera_manager = current_app.extensions["camera_manager"]
    video_processor = current_app.extensions["video_processor"]
    logger = current_app.logger
    last_frame_id = -1

    while True:
        try:
            if not video_processor.has_camera(camera_id):
                placeholder_bytes = _encode_frame(
                    _build_placeholder_frame(
                        title="\u6444\u50cf\u5934\u4e0d\u5b58\u5728",
                        subtitle=f"ID: {camera_id}",
                    )
                )
                if placeholder_bytes is not None:
                    yield _build_mjpeg_chunk(placeholder_bytes)
                break

            frame_packet = camera_manager.get_frame_packet(camera_id)
            if frame_packet is None:
                status = camera_manager.get_status(camera_id) or {}
                encoded = _encode_frame(
                    _build_placeholder_frame(
                        title="\u6682\u65e0\u89c6\u9891\u753b\u9762",
                        subtitle=f"\u72b6\u6001\uff1a{_translate_status(status.get('status', 'unknown'))}",
                    )
                )
                if encoded is None:
                    logger.warning(
                        "Failed to encode placeholder frame for camera %s.",
                        camera_id,
                    )
                    time.sleep(0.05)
                    continue
                yield _build_mjpeg_chunk(encoded)
                time.sleep(0.05)
                continue

            frame_id = int(frame_packet["frame_id"])
            if frame_id == last_frame_id:
                time.sleep(0.005)
                continue

            last_frame_id = frame_id
            frame = frame_packet["frame"]
            if overlay_enabled:
                frame = video_processor.render_display_frame(
                    camera_id,
                    frame,
                    display_detection_overlay=True,
                )
            encoded = _encode_frame(frame)

            if encoded is None:
                logger.warning("Failed to encode frame for camera %s.", camera_id)
                time.sleep(0.02)
                continue

            yield _build_mjpeg_chunk(encoded)
        except GeneratorExit:
            logger.info("MJPEG stream closed for camera %s.", camera_id)
            break
        except Exception as exc:
            logger.exception("MJPEG stream error for camera %s: %s", camera_id, exc)
            fallback = _encode_frame(
                _build_placeholder_frame(
                    title="\u89c6\u9891\u6d41\u5f02\u5e38",
                    subtitle="\u8bf7\u7a0d\u540e\u91cd\u8bd5",
                )
            )
            if fallback is not None:
                yield _build_mjpeg_chunk(fallback)
            time.sleep(0.2)


def _build_placeholder_frame(title: str, subtitle: str):
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    frame[:] = (34, 40, 49)

    cv2.putText(
        frame,
        title,
        (60, 160),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        subtitle,
        (60, 220),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (166, 180, 200),
        2,
        cv2.LINE_AA,
    )
    return frame


def _encode_frame(frame: np.ndarray) -> bytes | None:
    try:
        success, encoded = cv2.imencode(".jpg", frame)
        if not success:
            return None
        return encoded.tobytes()
    except Exception:
        return None


def _build_mjpeg_chunk(encoded_frame: bytes) -> bytes:
    return (
        f"--{MJPEG_BOUNDARY}\r\n"
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode("utf-8") + encoded_frame + b"\r\n"


def _normalize_filter_datetime(value: str, is_end: bool) -> str | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if is_end and len(value) == 16:
            parsed = parsed.replace(second=59)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _get_default_camera(cameras: list[dict]) -> dict | None:
    if not cameras:
        return None

    for camera in cameras:
        if camera.get("enabled"):
            return camera
    return cameras[0]


def _load_recent_alarms(limit: int) -> list[dict]:
    alarm_manager = current_app.extensions["alarm_manager"]
    repository = alarm_manager.repository
    settings = current_app.config.get("APP_SETTINGS", {})
    camera_name_map = _build_camera_name_map(settings.get("cameras", []))

    events = repository.list_events(limit=max(limit * 5, limit))
    aggregated_events = aggregate_live_alarm_events(events, camera_name_map=camera_name_map)
    return [
        _build_live_alarm_view_model(item)
        for item in aggregated_events[:limit]
    ]


def _build_camera_name_map(cameras: list[dict]) -> dict[str, str]:
    return {
        camera["id"]: camera.get("name", camera["id"])
        for camera in cameras
    }


def _build_alarm_view_model(event, camera_name_map: dict[str, str]) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "camera_id": event.camera_id,
        "camera_name": camera_name_map.get(event.camera_id, event.camera_id),
        "violation_type": event.violation_type,
        "violation_type_text": _format_violation_type(event.violation_type),
        "timestamp": event.timestamp,
        "display_time": format_display_time(event.timestamp),
        "confidence": event.confidence,
        "snapshot_path": event.snapshot_path,
        "snapshot_url": _build_snapshot_url(event.snapshot_path),
    }


def _build_live_alarm_view_model(item: dict[str, object]) -> dict[str, object]:
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
        "snapshot_url": _build_snapshot_url(snapshot_path),
        "raw_event_ids": list(item.get("raw_event_ids", [])),
        "violation_counts": dict(item.get("violation_counts", {})),
    }


def _format_violation_type(violation_type: str) -> str:
    return get_display_label(violation_type)


def _translate_status(status: str) -> str:
    return STATUS_TEXT_MAP.get(status, status)


def _build_snapshot_url(snapshot_path: str | None) -> str | None:
    if not snapshot_path:
        return None

    normalized = snapshot_path.replace("\\", "/").lstrip("/")
    if normalized.startswith("snapshots/"):
        normalized = normalized[len("snapshots/"):]

    return url_for("main.snapshot_file", filename=normalized)


def _parse_bool_arg(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_hik_playback_source(source_type: str) -> bool:
    normalized = str(source_type or "").strip().lower()
    return normalized in {"nvr_rtsp", "hik_nvr", "hikvision_nvr"}


def _build_hik_playback_payload(camera: dict, settings: dict) -> dict[str, object]:
    hik_settings = settings.get("hik_playback", {}) or {}
    camera_id = str(camera.get("id") or camera.get("camera_id") or "").strip()
    source_type = str(camera.get("source_type") or "").strip()
    playback_mode = "hik" if _is_hik_playback_source(source_type) else "mjpeg"
    access_url = str(
        camera.get("hik_access_url")
        or camera.get("ws_url")
        or hik_settings.get("access_url")
        or ""
    ).strip()
    username = str(
        camera.get("hik_username")
        or camera.get("username")
        or hik_settings.get("username")
        or ""
    ).strip()
    password = str(
        camera.get("hik_password")
        or camera.get("password")
        or hik_settings.get("password")
        or ""
    ).strip()
    raw_play_url = str(
        camera.get("hik_play_url")
        or camera.get("rtsp_url")
        or ""
    ).strip()
    play_url = _strip_url_credentials(raw_play_url) if playback_mode == "hik" else raw_play_url
    camera_index_code = str(
        camera.get("camera_index_code")
        or camera.get("cameraIndexCode")
        or camera.get("camera_index")
        or ""
    ).strip()

    return {
        "camera_id": camera_id,
        "camera_name": camera.get("name", camera_id),
        "source_type": source_type,
        "playback_mode": playback_mode,
        "play_type": "hik_sdk" if playback_mode == "hik" else "mjpeg",
        "access_url": access_url,
        "ws_url": access_url,
        "username": username,
        "password": password,
        "play_url": play_url,
        "rtsp_url": play_url,
        "raw_play_url": raw_play_url,
        "auth_in_url": _url_contains_credentials(raw_play_url),
        "stream_mode": camera.get("stream_mode"),
        "trans_mode": camera.get("trans_mode"),
        "gpu_mode": camera.get("gpu_mode"),
        "camera_index_code": camera_index_code,
    }


def _url_contains_credentials(value: str) -> bool:
    try:
        return bool(urlsplit(str(value or "")).username)
    except Exception:
        return False


def _strip_url_credentials(value: str) -> str:
    try:
        parts = urlsplit(str(value or ""))
        hostname = parts.hostname or ""
        if not hostname:
            return str(value or "")
        port_suffix = f":{parts.port}" if parts.port else ""
        netloc = f"{hostname}{port_suffix}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return str(value or "")


def _build_hik_test_config() -> dict[str, object]:
    settings = current_app.config.get("APP_SETTINGS", {})
    cameras = settings.get("cameras", [])
    hik_camera = next(
        (item for item in cameras if _is_hik_playback_source(item.get("source_type"))),
        None,
    )

    if hik_camera is not None:
        payload = _build_hik_playback_payload(hik_camera, settings)
        return {
            "accessUrl": str(payload.get("access_url") or ""),
            "wsURL": str(payload.get("ws_url") or ""),
            "previewUrl": str(payload.get("play_url") or ""),
            "username": str(payload.get("username") or ""),
            "password": str(payload.get("password") or ""),
            "maskedPassword": "********",
            "streamMode": payload.get("stream_mode"),
            "transMode": payload.get("trans_mode"),
            "gpuMode": payload.get("gpu_mode"),
            "cameraIndexCode": str(payload.get("camera_index_code") or ""),
            "cameraId": str(payload.get("camera_id") or ""),
            "demoBasePath": url_for("main.hik_asset", filename="dist"),
            "polyfillUrl": url_for("main.hik_asset", filename="dist/polyfill2.js"),
            "pluginUrl": url_for("main.hik_asset", filename="dist/jsPlugin-1.2.0.min.js"),
        }

    return {
        "accessUrl": "ws://192.168.1.100:8090",
        "wsURL": "ws://192.168.1.100:8090",
        "previewUrl": (
            "rtsp://192.168.1.100:554/dac/realplay/"
            "68F108CF-522A-4774-A0A7-AC41687839601/MAIN/TCP?streamform=rtp"
        ),
        "username": "admin",
        "password": "cmc.1340",
        "maskedPassword": "********",
        "streamMode": None,
        "transMode": None,
        "gpuMode": None,
        "cameraIndexCode": "",
        "cameraId": "",
        "demoBasePath": url_for("main.hik_asset", filename="dist"),
        "polyfillUrl": url_for("main.hik_asset", filename="dist/polyfill2.js"),
        "pluginUrl": url_for("main.hik_asset", filename="dist/jsPlugin-1.2.0.min.js"),
    }


def _get_cpu_usage_snapshot() -> dict[str, object]:
    typeperf_path = shutil.which("typeperf")
    if not typeperf_path:
        return {
            "available": False,
            "usage_percent": None,
            "message": "typeperf 不可用，无法读取 CPU 使用率。",
        }

    try:
        completed = subprocess.run(
            [typeperf_path, r"\Processor(_Total)\% Processor Time", "-sc", "1"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        output = (completed.stdout or "").splitlines()
        for line in output:
            if "," not in line:
                continue
            parts = [part.strip().strip('"') for part in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                usage_value = float(parts[-1])
                return {
                    "available": True,
                    "usage_percent": round(usage_value, 2),
                    "message": "系统 CPU 总使用率。",
                }
            except ValueError:
                continue
    except Exception as exc:
        return {
            "available": False,
            "usage_percent": None,
            "message": f"读取 CPU 使用率失败：{exc}",
        }

    return {
        "available": False,
        "usage_percent": None,
        "message": "未能解析 CPU 使用率输出。",
    }


def _get_gpu_usage_snapshot() -> dict[str, object]:
    nvidia_smi_path = shutil.which("nvidia-smi")
    if not nvidia_smi_path:
        return {
            "available": False,
            "gpu_util_percent": None,
            "memory_used_mb": None,
            "memory_total_mb": None,
            "message": "未找到 nvidia-smi，无法自动读取 GPU 使用率。",
        }

    try:
        completed = subprocess.run(
            [
                nvidia_smi_path,
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        first_line = next(
            (line.strip() for line in (completed.stdout or "").splitlines() if line.strip()),
            "",
        )
        if first_line:
            parts = [part.strip() for part in first_line.split(",")]
            if len(parts) >= 3:
                return {
                    "available": True,
                    "gpu_util_percent": float(parts[0]),
                    "memory_used_mb": float(parts[1]),
                    "memory_total_mb": float(parts[2]),
                    "message": "读取首块 NVIDIA GPU 状态。",
                }
    except Exception as exc:
        return {
            "available": False,
            "gpu_util_percent": None,
            "memory_used_mb": None,
            "memory_total_mb": None,
            "message": f"读取 GPU 使用率失败：{exc}",
        }

    return {
        "available": False,
        "gpu_util_percent": None,
        "memory_used_mb": None,
        "memory_total_mb": None,
        "message": "未能解析 GPU 使用率输出。",
    }

