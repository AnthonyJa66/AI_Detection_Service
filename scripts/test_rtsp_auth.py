"""Quick RTSP auth check for OpenCV/FFmpeg.

Run from the project root:
    python scripts/test_rtsp_auth.py
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import cv2


os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|stimeout;5000000|max_delay;500000"
)


def mask_rtsp_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        if not parts.username:
            return url
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{parts.username}:***@{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "<invalid-rtsp-url>"


def test_rtsp(name: str, url: str) -> bool:
    print("=" * 80)
    print(f"Testing: {name}")
    print(f"URL: {mask_rtsp_url(url)}")

    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)

    opened = cap.isOpened()
    print(f"open result: {opened}")
    if not opened:
        print("open failed")
        cap.release()
        return False

    ok, frame = cap.read()
    print(f"read result: {ok}")
    if not ok or frame is None:
        print("read frame failed")
        cap.release()
        return False

    print(f"frame shape: {frame.shape}")
    cap.release()
    return True


if __name__ == "__main__":
    raw_url = (
        "rtsp://192.168.1.100:554/dac/realplay/"
        "68F108CF-522A-4774-A0A7-AC41687839601/MAIN/TCP?streamform=rtp"
    )
    auth_url = (
        "rtsp://admin:cmc.1340@192.168.1.100:554/dac/realplay/"
        "68F108CF-522A-4774-A0A7-AC41687839601/MAIN/TCP?streamform=rtp"
    )

    raw_ok = test_rtsp("raw rtsp", raw_url)
    auth_ok = test_rtsp("auth rtsp", auth_url)

    print("=" * 80)
    print(f"raw rtsp ok: {raw_ok}")
    print(f"auth rtsp ok: {auth_ok}")
