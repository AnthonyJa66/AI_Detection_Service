import unittest

import numpy as np

from app.services.camera_manager import CameraManager


class FakeCameraStream:
    def __init__(self, config) -> None:
        self.config = config
        self.started = False
        self.stopped = False
        self.frame = np.ones((8, 8, 3), dtype=np.uint8)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def get_frame(self, copy: bool = True):
        return self.frame.copy() if copy else self.frame

    def get_status(self) -> dict:
        return {
            "camera_id": self.config.id,
            "camera_name": self.config.name,
            "enabled": self.config.enabled,
            "source_type": self.config.source_type,
            "status": "running" if self.started else "stopped",
            "fps": 0.0,
            "last_error": "",
            "reconnect_attempts": 0,
            "last_frame_at": None,
            "thread_alive": self.started and not self.stopped,
        }


class FakeStreamFactory:
    def create(self, camera_config):
        return FakeCameraStream(camera_config)


def make_settings() -> dict:
    return {
        "cameras": [
            {
                "camera_id": "cam_1",
                "id": "cam_1",
                "name": "Camera 1",
                "source_type": "rtsp_camera",
                "rtsp_url": "rtsp://example/1",
                "enabled": True,
                "fps_target": 10,
                "retry_interval_seconds": 5,
                "max_reconnect_attempts": 0,
                "resolution": {"width": 1280, "height": 720},
            },
            {
                "camera_id": "cam_2",
                "id": "cam_2",
                "name": "Camera 2",
                "source_type": "nvr_rtsp",
                "rtsp_url": "rtsp://example/2",
                "enabled": False,
                "fps_target": 10,
                "retry_interval_seconds": 5,
                "max_reconnect_attempts": 0,
                "resolution": {"width": 1280, "height": 720},
            },
        ]
    }


class CameraManagerTestCase(unittest.TestCase):
    def test_load_start_and_get_frame(self) -> None:
        manager = CameraManager(stream_factory=FakeStreamFactory())
        manager.load_from_settings(make_settings())
        manager.start_all()

        self.assertEqual(set(manager.get_camera_ids()), {"cam_1", "cam_2"})
        frame = manager.get_frame("cam_1")
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.shape, (8, 8, 3))

        statuses = manager.get_all_status()
        self.assertEqual(statuses["cam_1"]["status"], "running")
        self.assertEqual(statuses["cam_1"]["source_type"], "rtsp_camera")
        self.assertEqual(statuses["cam_2"]["status"], "stopped")
        self.assertEqual(statuses["cam_2"]["source_type"], "nvr_rtsp")

    def test_remove_camera_stops_target_only(self) -> None:
        manager = CameraManager(stream_factory=FakeStreamFactory())
        manager.load_from_settings(make_settings())

        stream_1 = manager._streams["cam_1"]
        stream_2 = manager._streams["cam_2"]

        removed = manager.remove_camera("cam_1")

        self.assertTrue(removed)
        self.assertTrue(stream_1.stopped)
        self.assertFalse(stream_2.stopped)
        self.assertFalse(manager.has_camera("cam_1"))
        self.assertTrue(manager.has_camera("cam_2"))


if __name__ == "__main__":
    unittest.main()
