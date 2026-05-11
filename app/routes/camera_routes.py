"""摄像头管理页路由。

负责 settings.json 中摄像头配置的增删改查，并把改动同步到运行中的服务实例。
"""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.config_loader import ConfigError
from app.services.camera_stream import CameraConfig
from app.services.camera_settings_service import CameraSettingsService


camera_bp = Blueprint("camera", __name__, url_prefix="/cameras")


@camera_bp.route("/", methods=["GET"])
def list_cameras():
    """摄像头管理列表页。"""
    service = CameraSettingsService()
    cameras = service.list_cameras()
    return render_template("cameras.html", cameras=cameras)


@camera_bp.route("/new", methods=["GET", "POST"])
def create_camera():
    form_values = _default_form_values()
    if request.method == "POST":
        try:
            form_values = _form_values_from_request(request.form)
            service = CameraSettingsService()
            updated_settings = service.add_camera(_extract_camera_form(request.form))
            camera = next(
                camera for camera in updated_settings["cameras"]
                if camera["camera_id"] == request.form.get("camera_id", "").strip()
            )
            _apply_camera_settings_update(updated_settings, camera["camera_id"], camera["camera_id"])
            flash("摄像头新增成功。", "success")
            return redirect(url_for("camera.list_cameras"))
        except ConfigError as exc:
            flash(str(exc), "danger")
        except Exception as exc:
            current_app.logger.exception("Failed to create camera: %s", exc)
            flash("摄像头新增失败，请检查配置后重试。", "danger")

    return render_template(
        "camera_form.html",
        page_title="新增摄像头",
        submit_label="保存新增",
        form_values=form_values,
        original_camera_id="",
    )


@camera_bp.route("/<camera_id>/edit", methods=["GET", "POST"])
def edit_camera(camera_id: str):
    service = CameraSettingsService()
    camera = service.get_camera(camera_id)
    if camera is None:
        flash("摄像头不存在。", "danger")
        return redirect(url_for("camera.list_cameras"))

    if request.method == "POST":
        try:
            updated_settings = service.update_camera(
                camera_id,
                _extract_camera_form(request.form),
            )
            updated_camera_id = request.form.get("camera_id", "").strip() or camera_id
            _apply_camera_settings_update(updated_settings, updated_camera_id, camera_id)
            flash("摄像头修改成功。", "success")
            return redirect(url_for("camera.list_cameras"))
        except ConfigError as exc:
            flash(str(exc), "danger")
            camera = _form_values_from_request(request.form)
        except Exception as exc:
            current_app.logger.exception("Failed to update camera %s: %s", camera_id, exc)
            flash("摄像头修改失败，请稍后重试。", "danger")
            camera = _form_values_from_request(request.form)

    return render_template(
        "camera_form.html",
        page_title="编辑摄像头",
        submit_label="保存修改",
        form_values=camera,
        original_camera_id=camera_id,
    )


@camera_bp.route("/<camera_id>/delete", methods=["POST"])
def delete_camera(camera_id: str):
    try:
        service = CameraSettingsService()
        updated_settings = service.delete_camera(camera_id)
        _apply_camera_delete(updated_settings, camera_id)
        flash("摄像头删除成功。", "success")
    except ConfigError as exc:
        flash(str(exc), "danger")
    except Exception as exc:
        current_app.logger.exception("Failed to delete camera %s: %s", camera_id, exc)
        flash("摄像头删除失败，请稍后重试。", "danger")

    return redirect(url_for("camera.list_cameras"))


@camera_bp.route("/<camera_id>/toggle", methods=["POST"])
def toggle_camera(camera_id: str):
    try:
        service = CameraSettingsService()
        updated_settings = service.toggle_camera(camera_id)
        camera = next(camera for camera in updated_settings["cameras"] if camera["id"] == camera_id)
        _apply_camera_settings_update(updated_settings, camera_id, camera_id)
        flash(
            "摄像头已启用。" if camera["enabled"] else "摄像头已禁用。",
            "success",
        )
    except ConfigError as exc:
        flash(str(exc), "danger")
    except Exception as exc:
        current_app.logger.exception("Failed to toggle camera %s: %s", camera_id, exc)
        flash("摄像头状态更新失败，请稍后重试。", "danger")

    return redirect(url_for("camera.list_cameras"))


def _extract_camera_form(form_data) -> dict[str, object]:
    return {
        "camera_id": form_data.get("camera_id", "").strip(),
        "name": form_data.get("name", "").strip(),
        "source_type": form_data.get("source_type", "rtsp_camera").strip(),
        "rtsp_url": form_data.get("rtsp_url", "").strip(),
        "enabled": form_data.get("enabled") == "on",
        "location": form_data.get("location", "").strip(),
        "resolution_width": form_data.get("resolution_width", "").strip(),
        "resolution_height": form_data.get("resolution_height", "").strip(),
        "fps_target": form_data.get("fps_target", "").strip(),
        "retry_interval_seconds": form_data.get("retry_interval_seconds", "").strip(),
        "max_reconnect_attempts": form_data.get("max_reconnect_attempts", "").strip(),
        "nvr_name": form_data.get("nvr_name", "").strip(),
        "nvr_host": form_data.get("nvr_host", "").strip(),
        "nvr_port": form_data.get("nvr_port", "").strip(),
        "channel_no": form_data.get("channel_no", "").strip(),
        "username": form_data.get("username", "").strip(),
        "password": form_data.get("password", "").strip(),
    }


def _default_form_values() -> dict[str, object]:
    return {
        "camera_id": "",
        "id": "",
        "name": "",
        "source_type": "rtsp_camera",
        "rtsp_url": "rtsp://",
        "enabled": True,
        "location": "",
        "resolution": {"width": 1280, "height": 720},
        "fps_target": 10,
        "retry_interval_seconds": 5,
        "max_reconnect_attempts": 0,
        "nvr_name": "",
        "nvr_host": "",
        "nvr_port": 554,
        "channel_no": "",
        "username": "",
        "password": "",
    }


def _form_values_from_request(form_data) -> dict[str, object]:
    camera_id = form_data.get("camera_id", "").strip()
    return {
        "camera_id": camera_id,
        "id": camera_id,
        "name": form_data.get("name", "").strip(),
        "source_type": form_data.get("source_type", "rtsp_camera").strip(),
        "rtsp_url": form_data.get("rtsp_url", "").strip(),
        "enabled": form_data.get("enabled") == "on",
        "location": form_data.get("location", "").strip(),
        "resolution": {
            "width": form_data.get("resolution_width", "").strip(),
            "height": form_data.get("resolution_height", "").strip(),
        },
        "fps_target": form_data.get("fps_target", "").strip(),
        "retry_interval_seconds": form_data.get("retry_interval_seconds", "").strip(),
        "max_reconnect_attempts": form_data.get("max_reconnect_attempts", "").strip(),
        "nvr_name": form_data.get("nvr_name", "").strip(),
        "nvr_host": form_data.get("nvr_host", "").strip(),
        "nvr_port": form_data.get("nvr_port", "").strip(),
        "channel_no": form_data.get("channel_no", "").strip(),
        "username": form_data.get("username", "").strip(),
        "password": form_data.get("password", "").strip(),
    }


def _apply_camera_settings_update(
    updated_settings: dict,
    camera_id: str,
    previous_camera_id: str,
) -> None:
    """把配置文件改动同步到 CameraManager 和 VideoProcessor。"""
    previous_settings = current_app.config.get("APP_SETTINGS")
    camera_manager = current_app.extensions["camera_manager"]
    video_processor = current_app.extensions["video_processor"]

    camera_data = next(
        camera for camera in updated_settings["cameras"] if camera["id"] == camera_id
    )
    camera_config = CameraConfig.from_dict(camera_data)

    try:
        camera_manager.update_camera(camera_config, previous_camera_id=previous_camera_id)
        video_processor.settings = updated_settings
        video_processor.update_camera(
            camera_id=camera_id,
            enabled=bool(camera_data["enabled"]),
            previous_camera_id=previous_camera_id,
        )
        current_app.config["APP_SETTINGS"] = updated_settings
    except Exception:
        if previous_settings is not None:
            current_app.config["APP_SETTINGS"] = previous_settings
            video_processor.settings = previous_settings
        raise


def _apply_camera_delete(updated_settings: dict, camera_id: str) -> None:
    """删除摄像头后，同时移除对应拉流与检测处理器。"""
    previous_settings = current_app.config.get("APP_SETTINGS")
    camera_manager = current_app.extensions["camera_manager"]
    video_processor = current_app.extensions["video_processor"]

    try:
        video_processor.settings = updated_settings
        video_processor.remove_camera(camera_id)
        camera_manager.remove_camera(camera_id)
        current_app.config["APP_SETTINGS"] = updated_settings
    except Exception:
        if previous_settings is not None:
            current_app.config["APP_SETTINGS"] = previous_settings
            video_processor.settings = previous_settings
        raise
