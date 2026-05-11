import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def setup_logging(settings: dict[str, Any]) -> logging.Logger:
    logger = logging.getLogger("video_monitor")
    level_name = str(settings["logging"]["level"]).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    if logger.handlers:
        logger.setLevel(log_level)
        return logger

    log_file = Path(settings["logging"]["file"])
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(formatter)

    logger.setLevel(log_level)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False

    logging.getLogger().handlers = logger.handlers
    logging.getLogger().setLevel(log_level)

    logger.info("Logger initialized successfully.")
    return logger
