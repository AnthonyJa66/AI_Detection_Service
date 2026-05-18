"""HTTP client for the camera gateway device API."""

from __future__ import annotations

import json
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.logger import get_logger


class CameraGatewayClient:
    """Login, cache the gateway token, and fetch camera devices."""

    def __init__(self, config: dict):
        self.config = config or {}
        self.base_url = str(self.config.get("base_url", "")).strip().rstrip("/")
        self.username = str(self.config.get("username", "")).strip()
        self.password = str(self.config.get("password", "")).strip()
        self.timeout = float(self.config.get("timeout", 5) or 5)
        self.max_result = int(self.config.get("max_result", 100) or 100)
        self.protocol_types = _as_list(self.config.get("protocol_types")) or ["ehomeV5"]
        self.device_status = _as_list(self.config.get("device_status")) or [
            "online",
            "offline",
        ]
        self.rtsp_host = str(
            self.config.get("rtsp_host") or urlsplit(self.base_url).hostname or ""
        ).strip()
        self.rtsp_port = int(self.config.get("rtsp_port", 554) or 554)
        self.rtsp_stream_type = str(
            self.config.get("rtsp_stream_type", "MAIN") or "MAIN"
        ).strip()
        self.rtsp_transport = str(
            self.config.get("rtsp_transport", "TCP") or "TCP"
        ).strip()
        self.rtsp_streamform = str(
            self.config.get("rtsp_streamform", "rtp") or "rtp"
        ).strip()
        self.rtsp_auth_enabled = _as_bool(
            self.config.get("rtsp_auth_enabled", False)
        )
        self.rtsp_username = str(self.config.get("rtsp_username", "") or "").strip()
        self.rtsp_password = str(self.config.get("rtsp_password", "") or "").strip()
        self.logger = get_logger("video_monitor.camera_gateway")
        self.logger.info(
            "camera gateway rtsp auth enabled: %s",
            str(self.rtsp_auth_enabled).lower(),
        )
        self._token: str | None = None
        self._lock = threading.RLock()

    def login(self) -> str | None:
        """Login to the gateway and return a token, or None on failure."""
        if not self.base_url:
            self.logger.error("Camera gateway base_url is empty.")
            return None

        payload = {
            "username": self.username,
            "password": self.password,
        }
        status_code, response_json = self._post_json(
            f"{self.base_url}/sysUser/login",
            payload,
        )
        if status_code is None or not isinstance(response_json, dict):
            return None

        data = response_json.get("data")
        token = data.get("token") if isinstance(data, dict) else None
        if response_json.get("code") == 1000 and token:
            with self._lock:
                self._token = str(token)
            self.logger.info("camera gateway login success")
            return str(token)

        self.logger.warning(
            "Camera gateway login failed. status_code=%s code=%s",
            status_code,
            response_json.get("code"),
        )
        return None

    def get_token(self, force_refresh: bool = False) -> str | None:
        """Return a cached token unless force_refresh is requested."""
        with self._lock:
            if self._token and not force_refresh:
                return self._token
            if force_refresh:
                self._token = None

        return self.login()

    def fetch_device_list(self) -> list[dict]:
        """Fetch gateway devices from /hik-gateway/device/list."""
        token = self.get_token()
        if not token:
            return []

        payload = {
            "SearchDescription": {
                "position": 0,
                "maxResult": self.max_result,
                "Filter": {
                    "key": "",
                    "devType": "",
                    "protocolType": self.protocol_types,
                    "devStatus": self.device_status,
                },
            }
        }

        for attempt in range(2):
            status_code, response_json = self._post_json(
                f"{self.base_url}/hik-gateway/device/list",
                payload,
                headers={"Authorization": token},
            )

            if self._is_auth_failure(status_code, response_json):
                if attempt == 0:
                    self.logger.warning(
                        "Camera gateway token rejected, refreshing token once."
                    )
                    token = self.get_token(force_refresh=True)
                    if not token:
                        return []
                    continue
                return []

            if status_code is None or not isinstance(response_json, dict):
                return []

            if response_json.get("code") != 200:
                self.logger.warning(
                    "Camera gateway device list failed. status_code=%s code=%s",
                    status_code,
                    response_json.get("code"),
                )
                return []

            devices = self._extract_devices(response_json)
            self.logger.info("camera gateway device count: %s", len(devices))
            self.logger.info(
                "camera gateway fetch device list success. total=%s",
                len(devices),
            )
            return devices

        return []

    def build_rtsp_url(self, dev_index: str, channel_no: int) -> str:
        """Build the gateway RTSP URL for one device channel."""
        dev_index = str(dev_index or "").strip()
        channel_no = int(channel_no)
        auth = ""
        if self.rtsp_auth_enabled and self.rtsp_username and self.rtsp_password:
            username = quote(self.rtsp_username, safe="")
            password = quote(self.rtsp_password, safe="")
            auth = f"{username}:{password}@"

        return (
            f"rtsp://{auth}{self.rtsp_host}:{self.rtsp_port}/dac/realplay/"
            f"{dev_index}{channel_no}/{self.rtsp_stream_type}/"
            f"{self.rtsp_transport}?streamform={self.rtsp_streamform}"
        )

    def normalize_camera_list(self, raw_devices: list[dict]) -> list[dict]:
        """Expand encoding devices into per-channel camera entries."""
        devices = raw_devices if isinstance(raw_devices, list) else []
        self.logger.info("camera gateway device count: %s", len(devices))

        cameras: list[dict] = []
        for index, device in enumerate(devices):
            if not isinstance(device, dict):
                self.logger.warning(
                    "Camera gateway device is invalid. index=%s",
                    index,
                )
                continue

            dev_type = str(device.get("devType") or "").strip()
            if dev_type != "encodingDev":
                continue

            dev_index = str(device.get("devIndex") or "").strip()
            if not dev_index:
                self.logger.warning(
                    "Camera gateway encoding device missing devIndex. index=%s",
                    index,
                )
                continue

            try:
                video_channel_num = int(device.get("videoChannelNum") or 0)
            except (TypeError, ValueError):
                self.logger.warning(
                    "Camera gateway videoChannelNum is invalid. devIndex=%s",
                    dev_index,
                )
                continue

            if video_channel_num <= 0:
                continue

            dev_name = str(device.get("devName") or dev_index).strip()
            dev_status = str(device.get("devStatus") or "").strip()
            protocol_type = str(device.get("protocolType") or "").strip()

            for channel_no in range(1, video_channel_num + 1):
                camera = {
                    "id": f"{dev_index}_{channel_no}",
                    "name": f"{dev_name}-通道{channel_no}",
                    "url": self.build_rtsp_url(dev_index, channel_no),
                    "status": dev_status,
                    "source": "gateway",
                    "device_id": dev_index,
                    "channel_no": channel_no,
                    "protocol_type": protocol_type,
                    "dev_type": dev_type,
                    "raw": device,
                }
                cameras.append(camera)
                self.logger.info(
                    "generated camera: %s %s -> %s",
                    camera["id"],
                    camera["name"],
                    mask_rtsp_url(camera["url"]),
                )
                self.logger.info(
                    "generated camera url: %s",
                    mask_rtsp_url(camera["url"]),
                )

        self.logger.info("camera gateway generated camera count: %s", len(cameras))
        return cameras

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> tuple[int | None, dict[str, Any] | None]:
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)

        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_body = response.read()
                status_code = int(response.getcode())
        except HTTPError as exc:
            status_code = int(exc.code)
            try:
                response_body = exc.read()
            except Exception:
                response_body = b""
            self.logger.warning(
                "Camera gateway request failed. url=%s status_code=%s",
                url,
                status_code,
            )
        except (TimeoutError, URLError) as exc:
            self.logger.exception("Camera gateway request error. url=%s error=%s", url, exc)
            return None, None
        except Exception as exc:
            self.logger.exception(
                "Unexpected camera gateway request error. url=%s error=%s",
                url,
                exc,
            )
            return None, None

        try:
            decoded = response_body.decode("utf-8")
            return status_code, json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.logger.exception(
                "Camera gateway response JSON parse failed. url=%s status_code=%s error=%s",
                url,
                status_code,
                exc,
            )
            return status_code, None

    def _extract_devices(self, response_json: dict[str, Any]) -> list[dict]:
        data = response_json.get("data")
        if not isinstance(data, dict):
            self.logger.warning("Camera gateway device list missing data object.")
            return []

        search_result = data.get("SearchResult")
        if not isinstance(search_result, dict):
            self.logger.warning("Camera gateway device list missing SearchResult.")
            return []

        match_list = search_result.get("MatchList")
        if match_list is None:
            self.logger.warning("Camera gateway device list missing MatchList.")
            return []
        if isinstance(match_list, dict):
            match_list = [match_list]
        if not isinstance(match_list, list):
            self.logger.warning("Camera gateway MatchList is not a list.")
            return []

        devices: list[dict] = []
        for index, item in enumerate(match_list):
            if not isinstance(item, dict):
                self.logger.warning(
                    "Camera gateway MatchList item is invalid. index=%s",
                    index,
                )
                continue

            device = item.get("Device")
            if not isinstance(device, dict):
                self.logger.warning(
                    "Camera gateway MatchList item missing Device. index=%s",
                    index,
                )
                continue
            devices.append(device)

        return devices

    def _is_auth_failure(
        self,
        status_code: int | None,
        response_json: dict[str, Any] | None,
    ) -> bool:
        if status_code == 401:
            return True
        if not isinstance(response_json, dict):
            return False
        code = response_json.get("code")
        if code in {401, 1001, 1002, 1003}:
            return True
        message = str(
            response_json.get("message")
            or response_json.get("msg")
            or response_json.get("errorMsg")
            or ""
        ).lower()
        return "token" in message and (
            "invalid" in message
            or "expired" in message
            or "unauthorized" in message
            or "失效" in message
            or "过期" in message
        )


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def mask_rtsp_url(url: str) -> str:
    try:
        parts = urlsplit(str(url or ""))
        if not parts.username:
            return str(url or "")

        hostname = parts.hostname or ""
        port_suffix = f":{parts.port}" if parts.port else ""
        netloc = f"{parts.username}:***@{hostname}{port_suffix}"
        return urlunsplit(
            (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
        )
    except Exception:
        return "<invalid-rtsp-url>"
