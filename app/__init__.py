"""Flask 应用工厂。

这里集中完成配置加载、核心服务装配、蓝图注册，以及摄像头拉流/检测线程的启动。
"""

import atexit
import os

from flask import Flask

from app.config_loader import load_settings
from app.logger import setup_logging
from app.routes.camera_routes import camera_bp
from app.routes.main_routes import main_bp
from app.routes.ws_routes import init_websocket_routes
from app.services.alarm_manager import AlarmManager
from app.services.alarm_repository import SQLiteAlarmRepository
from app.services.camera_manager import CameraManager
from app.services.rule_engine import RuleEngine
from app.services.snapshot_service import AlarmSnapshotService
from app.services.video_processor import VideoProcessor
from app.services.websocket_manager import (
    WebSocketAlarmNotifier,
    WebSocketConnectionManager,
)


def create_app() -> Flask:
    """创建并装配整个应用并返回 Flask 实例。"""
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "smart-video-monitor-secret")

    settings = load_settings()
    app.config["APP_SETTINGS"] = settings

    logger = setup_logging(settings)
    app.logger.handlers = logger.handlers
    app.logger.setLevel(logger.level)

    camera_manager = CameraManager()
    camera_manager.load_from_settings(settings)
    app.extensions["camera_manager"] = camera_manager

    websocket_manager = WebSocketConnectionManager()
    app.extensions["websocket_manager"] = websocket_manager

    alarm_repository = SQLiteAlarmRepository(settings["paths"]["db_path"])
    alarm_manager = AlarmManager(
        repository=alarm_repository,
        notifier=WebSocketAlarmNotifier(websocket_manager),
        async_mode=True,
    )
    app.extensions["alarm_manager"] = alarm_manager

    alarm_settings = settings.get("alarm", {})
    rule_engine = RuleEngine(
        confirm_counts=dict(alarm_settings.get("confirm_counts", {})),
        clear_count=alarm_settings.get("clear_count"),
        session_end_grace_seconds=alarm_settings.get("session_end_grace_seconds"),
        enable_reminder_events=alarm_settings.get("enable_reminder_events"),
        reminder_interval_seconds=alarm_settings.get("reminder_interval_seconds"),
    )
    app.extensions["rule_engine"] = rule_engine

    video_processor = VideoProcessor(
        camera_manager=camera_manager,
        settings=settings,
        rule_engine=rule_engine,
        alarm_manager=alarm_manager,
    )
    video_processor.load_from_settings()
    app.extensions["video_processor"] = video_processor

    snapshot_service = AlarmSnapshotService(
        video_processor=video_processor,
        snapshot_dir=settings["paths"]["snapshot_dir"],
    )
    alarm_manager.snapshot_provider = snapshot_service
    app.extensions["snapshot_service"] = snapshot_service

    sock = init_websocket_routes(app, websocket_manager)
    app.extensions["sock"] = sock

    # Debug 模式下会有 Werkzeug 父子进程，只有真正承载请求的子进程才启动后台线程。
    if _should_start_camera_streams(settings):
        alarm_manager.start()
        camera_manager.start_all()
        video_processor.start_all()
        app.logger.info("Camera streams started.")
        atexit.register(alarm_manager.stop)
        atexit.register(camera_manager.stop_all)
        atexit.register(video_processor.stop_all)
    else:
        app.logger.info(
            "Camera streams startup skipped for debug reloader parent process."
        )

    app.register_blueprint(main_bp)
    app.register_blueprint(camera_bp)

    app.logger.info("Flask application initialized successfully.")
    return app


def _should_start_camera_streams(settings: dict) -> bool:
    """判断当前进程是否应启动拉流、检测和报警后台线程。"""
    debug_enabled = bool(settings["server"]["debug"])
    if not debug_enabled:
        return True

    return os.environ.get("WERKZEUG_RUN_MAIN") == "true"
