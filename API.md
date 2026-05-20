# 智能视频监控系统 API 文档

更新时间：2026-05-20

本文档描述当前 Flask 入口 `app.py` 注册的页面、REST、MJPEG 和 WebSocket 接口。服务默认端口来自 `settings.json -> server.port`，当前默认是 `5000`。

示例基础地址：

```text
http://127.0.0.1:5000
```

统一 JSON 响应结构：

```json
{
  "success": true,
  "message": "说明文本",
  "data": {}
}
```

## 1. 接口总览

### 1.1 REST / HTTP

| 分类 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 健康检查 | GET | `/health` | 服务健康检查 |
| 摄像头 | GET | `/api/cameras/status` | 摄像头运行状态 |
| 检测 | GET | `/api/cameras/<camera_id>/latest` | 最新检测结果 |
| 检测 | GET | `/api/detections/latest/<camera_id>` | 最新检测结果别名 |
| 报警 | GET | `/api/alerts/recent` | 最近报警 |
| 报警 | GET | `/api/alarms/latest` | 最近报警别名 |
| 报警 | GET | `/api/alerts/summary` | 大屏轻量统计 |
| 播放 | GET | `/api/main/playback-config/<camera_id>` | 主界面播放配置 |
| 播放 | GET | `/api/camera/play_config/<camera_id>` | 兼容播放配置 |
| 检测 overlay | GET | `/api/main/detections/overlay/<camera_id>` | 主界面 Canvas overlay 数据 |
| 视频流 | GET | `/video_feed/<camera_id>` | MJPEG 视频流 |
| 截图 | GET | `/snapshots/<path:filename>` | 报警截图访问 |
| 性能 | GET | `/api/fusion/performance` | 融合测试页性能信息 |

### 1.2 页面

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 主监控页面 |
| GET | `/alarms` | 报警记录页面 |
| GET | `/cameras/` | 本地摄像头管理列表 |
| GET/POST | `/cameras/new` | 新增本地摄像头 |
| GET/POST | `/cameras/<camera_id>/edit` | 编辑本地摄像头 |
| POST | `/cameras/<camera_id>/delete` | 删除本地摄像头 |
| POST | `/cameras/<camera_id>/toggle` | 启用/禁用本地摄像头 |
| GET | `/hik_test` | 海康播放测试页 |
| GET | `/hik_fusion_test` | 海康播放 + 检测 overlay 测试页 |
| GET | `/hik/<path:filename>` | 海康 SDK 静态资源 |

### 1.3 WebSocket

| 路径 | 说明 |
| --- | --- |
| `/ws/alerts` | 实时报警推送 |
| `/ws/alarms` | 实时报警推送别名 |

## 2. 健康检查

### GET `/health`

返回服务状态和当前摄像头数量。

示例：

```bash
curl http://127.0.0.1:5000/health
```

响应：

```json
{
  "success": true,
  "message": "AI Detection Service is running.",
  "data": {
    "service": "AI Detection Service",
    "camera_count": 5
  }
}
```

状态码：

| 状态码 | 说明 |
| --- | --- |
| 200 | 正常 |
| 500 | 服务异常 |

## 3. 摄像头状态

### GET `/api/cameras/status`

返回所有摄像头拉流状态。摄像头来源可能是 `camera_gateway` 动态生成，也可能是本地 `settings.json -> cameras` fallback。

示例：

```bash
curl http://127.0.0.1:5000/api/cameras/status
```

响应：

```json
{
  "success": true,
  "message": "Camera status fetched successfully.",
  "data": {
    "68F108CF-522A-4774-A0A7-AC4168783960_1": {
      "camera_id": "68F108CF-522A-4774-A0A7-AC4168783960_1",
      "camera_name": "硬盘录像机-通道1",
      "enabled": true,
      "source_type": "nvr_rtsp",
      "stream_url_role": "rtsp_url",
      "status": "running",
      "fps": 24.8,
      "last_error": "",
      "reconnect_attempts": 0,
      "last_frame_at": "2026-05-20 14:30:00",
      "thread_alive": true
    }
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `camera_id` | string | 摄像头 ID |
| `camera_name` | string | 摄像头名称 |
| `enabled` | boolean | 是否启用 |
| `source_type` | string | `rtsp_camera` / `nvr_rtsp` |
| `stream_url_role` | string | 当前检测使用 `rtsp_url` 或 `detection_rtsp_url` |
| `status` | string | `stopped` / `connecting` / `running` / `reconnecting` / `error` |
| `fps` | number | 后台读取帧率 |
| `last_error` | string | 最近错误 |
| `reconnect_attempts` | integer | 重连次数 |
| `last_frame_at` | string/null | 最近帧时间 |
| `thread_alive` | boolean | 拉流线程是否存活 |

## 4. 最新检测结果

### GET `/api/cameras/<camera_id>/latest`

别名：

```text
GET /api/detections/latest/<camera_id>
```

返回指定摄像头最近一次 AI 检测结果。

示例：

```bash
curl http://127.0.0.1:5000/api/cameras/68F108CF-522A-4774-A0A7-AC4168783960_1/latest
```

响应：

```json
{
  "success": true,
  "message": "Latest detection result fetched successfully.",
  "data": {
    "camera_id": "68F108CF-522A-4774-A0A7-AC4168783960_1",
    "timestamp": "2026-05-20T06:30:00+00:00",
    "frame_width": 1280,
    "frame_height": 720,
    "detections": [
      {
        "class_name": "no_helmet",
        "confidence": 0.91,
        "bbox": [100, 120, 220, 360],
        "source_model": "ultra"
      }
    ],
    "no_helmet_count": 1,
    "no_vest_count": 0,
    "smoking_count": 0
  }
}
```

状态码：

| 状态码 | 说明 |
| --- | --- |
| 200 | 成功，或摄像头存在但暂无检测 |
| 404 | 摄像头不存在 |
| 500 | 服务异常 |

## 5. 主界面 Overlay 数据

### GET `/api/main/detections/overlay/<camera_id>`

返回前端 Canvas 叠框所需的检测框、统计和摄像头状态。这个接口和播放方式解耦：海康 Web SDK 播放和 MJPEG 播放都可以使用它。

示例：

```bash
curl http://127.0.0.1:5000/api/main/detections/overlay/68F108CF-522A-4774-A0A7-AC4168783960_1
```

响应：

```json
{
  "success": true,
  "message": "主界面叠框检测结果获取成功。",
  "data": {
    "camera_id": "68F108CF-522A-4774-A0A7-AC4168783960_1",
    "frame_time": "2026-05-20T06:30:00+00:00",
    "frame_width": 1280,
    "frame_height": 720,
    "violations": [
      {
        "type": "no_helmet",
        "type_label": "未戴安全帽",
        "confidence": 0.91,
        "bbox": {
          "x1": 100,
          "y1": 120,
          "x2": 220,
          "y2": 360
        }
      }
    ],
    "stats": {
      "no_helmet": 1,
      "no_vest": 0,
      "smoking": 0
    },
    "camera_status": {
      "status": "running"
    }
  }
}
```

说明：

- 摄像头未 running 时，接口会主动返回空违规列表，避免前端展示旧框。
- `bbox` 坐标基于后端检测帧尺寸，前端按当前播放器尺寸缩放。

## 6. 播放配置

### GET `/api/main/playback-config/<camera_id>`

主界面使用的播放配置。前端根据 `playback_mode` 决定用海康 Web SDK 还是 MJPEG。

示例：

```bash
curl http://127.0.0.1:5000/api/main/playback-config/68F108CF-522A-4774-A0A7-AC4168783960_1
```

响应：

```json
{
  "success": true,
  "message": "主界面海康播放配置获取成功。",
  "data": {
    "camera_id": "68F108CF-522A-4774-A0A7-AC4168783960_1",
    "camera_name": "硬盘录像机-通道1",
    "source_type": "nvr_rtsp",
    "playback_mode": "hik",
    "play_type": "hik_sdk",
    "access_url": "ws://192.168.1.100:8090",
    "ws_url": "ws://192.168.1.100:8090",
    "username": "admin",
    "password": "<hik-password>",
    "play_url": "rtsp://192.168.1.100:554/dac/realplay/xxx/MAIN/TCP?streamform=rtp",
    "rtsp_url": "rtsp://192.168.1.100:554/dac/realplay/xxx/MAIN/TCP?streamform=rtp",
    "raw_play_url": "rtsp://admin:***@192.168.1.100:554/dac/realplay/xxx/MAIN/TCP?streamform=rtp",
    "auth_in_url": true,
    "mjpeg_url": "/video_feed/68F108CF-522A-4774-A0A7-AC4168783960_1",
    "demo_base_path": "/hik/dist",
    "polyfill_url": "/hik/dist/polyfill2.js",
    "plugin_url": "/hik/dist/jsPlugin-1.2.0.min.js"
  }
}
```

注意：

- 对海康 Web SDK，后端会尽量把 `play_url` 中的账号密码剥离，账号密码单独通过字段传给前端播放逻辑。
- 后台检测是否带 RTSP 密码不由这个接口决定，而由 `CameraStream.resolve_stream_url()` 使用的 `rtsp_url` / `detection_rtsp_url` 决定。
- 上方示例中的 `raw_play_url` 做了文档脱敏；实际接口按当前配置返回字段，生产环境请通过网络隔离、账号权限和页面访问控制保护播放凭据。

### GET `/api/camera/play_config/<camera_id>`

兼容旧前端的播放配置接口，返回字段较少：

```json
{
  "camera_id": "camera_id",
  "play_type": "hik_sdk",
  "ws_url": "ws://192.168.1.100:8090",
  "rtsp_url": "rtsp://...",
  "mjpeg_url": "/video_feed/camera_id"
}
```

## 7. MJPEG 视频流

### GET `/video_feed/<camera_id>`

返回 `multipart/x-mixed-replace` MJPEG 流，主要供 RTSP 摄像头和回退播放使用。

Query 参数：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `overlay` | boolean | `false` | 为 true 时后端叠加检测框后输出 |

示例：

```text
http://127.0.0.1:5000/video_feed/101
http://127.0.0.1:5000/video_feed/101?overlay=1
```

返回：

```text
Content-Type: multipart/x-mixed-replace; boundary=frame
```

说明：

- 摄像头不存在时返回 JSON 404。
- 摄像头暂无画面时会输出占位帧。

## 8. 最近报警

### GET `/api/alerts/recent`

别名：

```text
GET /api/alarms/latest
```

Query 参数：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `limit` | integer | 10 | 返回数量，范围 1-20 |

示例：

```bash
curl "http://127.0.0.1:5000/api/alerts/recent?limit=10"
```

响应：

```json
{
  "success": true,
  "message": "Recent alerts fetched successfully.",
  "data": {
    "items": [
      {
        "event_id": "evt_001",
        "aggregate_key": "camera:no_helmet",
        "camera_id": "camera",
        "camera_name": "硬盘录像机-通道1",
        "violation_type": "no_helmet",
        "violation_types": ["no_helmet"],
        "violation_type_text": "未戴安全帽",
        "timestamp": "2026-05-20T06:30:00+00:00",
        "display_time": "2026-05-20 14:30:00",
        "confidence": 0.92,
        "snapshot_path": "snapshots/camera/xxx.jpg",
        "snapshot_url": null,
        "raw_event_ids": ["evt_001"],
        "violation_counts": {
          "no_helmet": 1
        }
      }
    ]
  }
}
```

## 9. 报警统计

### GET `/api/alerts/summary`

返回轻量统计，供大屏或外部系统快速展示。

示例：

```bash
curl http://127.0.0.1:5000/api/alerts/summary
```

响应：

```json
{
  "success": true,
  "message": "Alert summary fetched successfully.",
  "data": {
    "total_alerts": 20,
    "today_alerts": 6,
    "camera_online": 4,
    "camera_total": 5,
    "alert_types": {
      "NO_HELMET": 12,
      "NO_VEST": 5,
      "SMOKING": 3
    }
  }
}
```

说明：

- 当前统计基于最近报警聚合结果，适合轻量展示，不等同于全库复杂报表。

## 10. 报警记录页面

### GET `/alarms`

返回 HTML 页面，支持查询参数：

| 参数 | 说明 |
| --- | --- |
| `camera_id` | 按摄像头过滤 |
| `violation_type` | 按违规类型过滤 |
| `start_time` | 开始时间 |
| `end_time` | 结束时间 |
| `page` | 页码 |
| `page_size` | 每页数量 |

示例：

```text
http://127.0.0.1:5000/alarms?camera_id=101&page=1&page_size=10
```

## 11. 截图访问

### GET `/snapshots/<path:filename>`

访问报警截图文件。`filename` 是相对于 `settings.json -> paths.snapshot_dir` 的路径。

示例：

```text
http://127.0.0.1:5000/snapshots/101/20260520/example.jpg
```

## 12. WebSocket 报警推送

### WS `/ws/alerts`

别名：

```text
WS /ws/alarms
```

服务端在报警事件入库后推送事件 JSON。

示例消息：

```json
{
  "event_id": "evt_001",
  "camera_id": "101",
  "camera_name": "办公室1",
  "violation_type": "no_helmet",
  "timestamp": "2026-05-20T06:30:00+00:00",
  "confidence": 0.92,
  "snapshot_path": "snapshots/101/example.jpg"
}
```

调试：

```bash
wscat -c ws://127.0.0.1:5000/ws/alerts
```

## 13. 融合测试性能接口

### GET `/api/fusion/performance`

返回 CPU/GPU 可用性、检测调度参数和播放模式，供 `/hik_fusion_test` 页面展示。

响应字段包括：

- `timestamp`
- `cpu.available`
- `cpu.usage_percent`
- `gpu.available`
- `gpu.gpu_util_percent`
- `gpu.memory_used_mb`
- `detection.detect_interval_seconds`
- `detection.max_inference_workers`
- `playback.mode`

## 14. 动态摄像头网关说明

网关接口不是对外 REST API，而是后端启动时主动调用的上游接口：

| 用途 | 方法 | 上游路径 |
| --- | --- | --- |
| 登录取 token | POST | `{camera_gateway.base_url}/sysUser/login` |
| 获取设备列表 | POST | `{camera_gateway.base_url}/hik-gateway/device/list` |

登录成功判断：

```text
code == 1000 且 data.token 存在
```

设备列表成功判断：

```text
code == 200
```

生成摄像头规则：

- 只处理 `Device.devType == "encodingDev"`
- 跳过 `videoChannelNum <= 0`
- 每个通道生成一条摄像头
- `id = "{devIndex}_{channelNo}"`
- `name = "{devName}-通道{channelNo}"`
- `url = CameraGatewayClient.build_rtsp_url(devIndex, channelNo)`
- 原始 `Device` 保留到 `raw`

RTSP 鉴权：

- `rtsp_auth_enabled = true` 时，真实拉流 URL 包含用户名密码。
- 日志通过脱敏函数输出 `rtsp://admin:***@...`。
- token 和 RTSP 明文密码都不应出现在日志中。

## 15. 常见状态码

| 状态码 | 说明 |
| --- | --- |
| 200 | 请求成功 |
| 404 | 摄像头或截图不存在 |
| 500 | 服务内部异常 |

## 16. 对接建议

- 第三方系统优先使用 `/api/cameras/status`、`/api/cameras/<camera_id>/latest`、`/api/alerts/recent`、`/api/alerts/summary`。
- 主界面播放相关接口可能随前端播放方案调整，外部系统慎用 `/api/main/*`。
- 视频流 `/video_feed/<camera_id>` 是 MJPEG 长连接，不适合当普通 JSON API 轮询。
- 摄像头 ID 可能来自动态网关，格式通常为 `{devIndex}_{channelNo}`。
