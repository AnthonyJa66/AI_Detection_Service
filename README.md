# 智能视频监控系统

更新时间：2026-05-20

本项目是一个基于 `Python 3.12 + Flask + OpenCV + Ultralytics YOLO` 的智能视频监控服务。系统负责从 RTSP/NVR 拉取视频帧，在后端执行安全帽、反光衣、抽烟等检测，生成报警记录、截图和 WebSocket 推送，同时提供主页面、摄像头管理页面、海康 Web SDK 播放和 MJPEG 视频流接口。

## 1. 一句话架构

```text
settings.json / camera_gateway
        |
        v
CameraGatewayClient / 本地 cameras fallback
        |
        v
CameraManager -> CameraStream(OpenCV/FFmpeg 拉流) -> VideoProcessor
        |                                             |
        |                                             v
        |                                  DetectionPipeline -> RuleEngine
        |                                             |
        v                                             v
Flask 页面/API/MJPEG                         AlarmManager -> SQLite/截图/WebSocket
```

核心原则：

- 摄像头列表优先来自 `camera_gateway`，接口失败或生成结果为空时自动 fallback 到 `settings.json -> cameras`。
- 后台检测统一使用 `CameraStream` + `cv2.VideoCapture` 拉流。
- 前端播放分流：RTSP 摄像头走 `/video_feed/<camera_id>`，NVR/海康源优先走海康 Web SDK。
- RTSP 带账号密码时，真实拉流 URL 携带密码，日志必须脱敏。

## 2. 快速启动

### 2.1 安装依赖

```bash
pip install -r requirements.txt
```

### 2.2 启动服务

```bash
python app.py
```

默认访问：

- [http://127.0.0.1:5000](http://127.0.0.1:5000)
- [http://localhost:5000](http://localhost:5000)

Windows 可使用：

```bat
start.bat
```

## 3. 运行环境

推荐环境：

- Windows 10 / 11
- Python 3.12
- Edge 或 Chrome
- 可访问摄像头/NVR/海康网关的局域网环境

关键依赖：

- `Flask`
- `Flask-Sock`
- `Flask-Cors`
- `opencv-python`
- `ultralytics`
- `SQLite`

必须保留：

```text
app/
hik/
models/ultra.pt
models/best.pt
app.py
settings.json
requirements.txt
```

运行时目录：

- `logs/`：日志，程序会自动创建
- `data/`：SQLite 数据库，程序会自动创建
- `snapshots/`：报警截图，程序会自动创建

## 4. 核心目录

```text
AI_Detection_Service/
├─ app/
│  ├─ routes/                 Flask 页面/API/WebSocket 路由
│  ├─ services/               摄像头、检测、报警、网关客户端等服务
│  ├─ models/                 数据模型
│  ├─ utils/                  标签、时间、报警聚合、标注样式等工具
│  ├─ templates/              Jinja2 页面模板
│  └─ static/                 前端 JS/CSS
├─ hik/                       海康 Web SDK 静态资源
├─ models/                    YOLO 权重
├─ scripts/                   临时/诊断脚本
├─ settings.json              主配置
├─ app.py                     Flask 启动入口
└─ API.md                     接口文档
```

## 5. 关键模块

### 5.1 配置与启动

- `app.py`：读取 Flask app 并按 `settings.json -> server` 启动。
- `app/__init__.py`：Flask 应用工厂，注册 CORS、日志、摄像头、检测、报警、WebSocket、蓝图。
- `app/config_loader.py`：读取、校验、标准化配置；接入 `camera_gateway`；失败时 fallback 到本地 `cameras`。

### 5.2 摄像头与视频流

- `app/services/camera_gateway_client.py`：登录网关、缓存 token、拉设备列表、按通道生成 RTSP 摄像头。
- `app/services/camera_stream.py`：单路 OpenCV/FFmpeg 拉流、缓存最新帧、重连、状态维护。
- `app/services/camera_manager.py`：管理全部 `CameraStream`。
- `app/services/camera_settings_service.py`：本地 `settings.json -> cameras` 的增删改查。

### 5.3 AI 检测与报警

- `app/services/video_processor.py`：按固定间隔取最新帧并提交推理。
- `app/services/model_manager.py`：加载 `models/ultra.pt` 和 `models/best.pt`。
- `app/services/detection_pipeline.py`：合并模型结果，生成标注画面。
- `app/services/rule_engine.py`：违规确认、去抖、事件生成。
- `app/services/alarm_manager.py`：报警入库、截图、WebSocket 推送。
- `app/services/alarm_repository.py`：SQLite 报警记录读写。
- `app/services/snapshot_service.py`：报警截图保存。

### 5.4 页面与接口

- `app/routes/main_routes.py`：首页、报警页、海康测试页、视频流、主页面 API。
- `app/routes/api_routes.py`：轻量 REST API，供第三方/大屏联调。
- `app/routes/camera_routes.py`：本地摄像头管理页面。
- `app/routes/ws_routes.py`：`/ws/alerts`、`/ws/alarms`。

## 6. 摄像头来源

### 6.1 动态网关优先

当 `settings.json -> camera_gateway.enabled = true` 时，启动流程为：

1. POST `/sysUser/login` 登录。
2. 从返回 JSON 的 `data.token` 读取 token。
3. POST `/hik-gateway/device/list` 拉取设备列表。
4. 只处理 `devType == "encodingDev"` 且 `videoChannelNum > 0` 的设备。
5. 每个设备按 `channelNo = 1..videoChannelNum` 生成多路摄像头。
6. 如果生成结果为空，输出 `fallback to local camera config` 并使用本地 `cameras`。

`AccessControl` 等非视频设备不会生成摄像头；`devStatus` 暂不参与过滤，online/offline 都保留。

### 6.2 本地配置 fallback

以下情况使用本地 `settings.json -> cameras`：

- `camera_gateway.enabled = false`
- 登录失败
- 设备列表接口失败/超时
- 返回 JSON 结构异常
- 设备列表为空
- 转换后没有生成任何摄像头

本地摄像头配置逻辑仍然保留，摄像头管理页面修改的是本地配置。

## 7. camera_gateway 配置

示例：

```json
"camera_gateway": {
  "enabled": true,
  "base_url": "http://192.168.1.100:1144",
  "username": "admin",
  "password": "<login-password-or-md5>",
  "timeout": 5,
  "max_result": 100,
  "protocol_types": ["ehomeV5"],
  "device_status": ["online", "offline"],
  "rtsp_host": "192.168.1.100",
  "rtsp_port": 554,
  "rtsp_stream_type": "MAIN",
  "rtsp_transport": "TCP",
  "rtsp_streamform": "rtp",
  "rtsp_auth_enabled": true,
  "rtsp_username": "admin",
  "rtsp_password": "<rtsp-password>"
}
```

RTSP 生成规则：

```text
rtsp://{auth}{rtsp_host}:{rtsp_port}/dac/realplay/{devIndex}{channelNo}/{rtsp_stream_type}/{rtsp_transport}?streamform={rtsp_streamform}
```

当 `rtsp_auth_enabled = true` 且用户名/密码不为空时：

```text
rtsp://admin:***@192.168.1.100:554/dac/realplay/<devIndex><channelNo>/MAIN/TCP?streamform=rtp
```

说明：

- 真实传给 `cv2.VideoCapture` 的 URL 会包含密码。
- 日志通过 `mask_rtsp_url()` 脱敏，不能明文打印 RTSP 密码。
- 登录接口 token 不会打印。

## 8. 本地 cameras 配置

每路摄像头常用字段：

| 字段 | 说明 |
| --- | --- |
| `camera_id` / `id` | 摄像头唯一 ID |
| `name` | 显示名称 |
| `source_type` | `rtsp_camera` 或 `nvr_rtsp` |
| `rtsp_url` | 主 RTSP 地址 |
| `detection_rtsp_url` | 检测专用流，可为空；为空时回退到 `rtsp_url` |
| `enabled` | 是否启用 |
| `fps_target` | 目标 FPS |
| `retry_interval_seconds` | 重连等待秒数 |
| `max_reconnect_attempts` | 最大重连次数，0 表示不限 |
| `resolution.width/height` | 目标分辨率 |
| `location` | 位置 |
| `nvr_host/nvr_port/channel_no` | NVR 补充信息 |

注意：

- `camera_id` 改变会影响前端选择、报警归属和 API 路径。
- 如果使用带密码 RTSP，日志会脱敏，但页面配置表格可能显示原始配置值；生产环境注意权限。

## 9. 播放与检测

### 9.1 后台检测

后台检测链路固定走：

```text
CameraStream.resolve_stream_url()
  -> detection_rtsp_url 或 rtsp_url
  -> cv2.VideoCapture(url, cv2.CAP_FFMPEG)
```

关键日志：

- `camera gateway rtsp auth enabled: true`
- `generated camera url: rtsp://admin:***@...`
- `detection worker using url: rtsp://admin:***@...`
- `first frame received...`
- `inference success...`

### 9.2 前端播放

- RTSP/MJPEG：`/video_feed/<camera_id>`
- 海康/NVR：主界面通过 `/api/main/playback-config/<camera_id>` 获取播放配置，前端调用 `hik_common_player.js`
- overlay：前端轮询 `/api/main/detections/overlay/<camera_id>` 并在 Canvas 绘制检测框

## 10. REST 与 WebSocket

常用接口：

- `GET /health`
- `GET /api/cameras/status`
- `GET /api/cameras/<camera_id>/latest`
- `GET /api/alerts/recent`
- `GET /api/alerts/summary`
- `GET /api/main/playback-config/<camera_id>`
- `GET /api/main/detections/overlay/<camera_id>`
- `GET /video_feed/<camera_id>`
- `WS /ws/alerts`
- `WS /ws/alarms`

完整说明见 [API.md](API.md)。

## 11. 页面

| 路径 | 说明 |
| --- | --- |
| `/` | 主监控页面 |
| `/alarms` | 报警记录页面 |
| `/cameras/` | 本地摄像头管理 |
| `/hik_test` | 海康播放测试页 |
| `/hik_fusion_test` | 海康播放 + 检测 overlay 测试页 |

## 12. 常见排障

### 12.1 RTSP 401 Unauthorized

现象：

```text
[rtsp] method DESCRIBE failed: 401 Unauthorized
Failed to open stream.
```

检查：

1. VLC 是否能播放带账号密码的 RTSP。
2. `camera_gateway.rtsp_auth_enabled` 是否为 `true`。
3. `rtsp_username` / `rtsp_password` 是否正确。
4. 启动日志里的 `detection worker using url` 是否是 `rtsp://admin:***@...`，而不是裸地址。
5. 不要在日志里查找明文密码，系统会脱敏。

可用诊断脚本：

```bash
python scripts/test_rtsp_auth.py
```

### 12.2 网关设备没有生成摄像头

检查：

- 登录是否成功：`camera gateway login success`
- 设备列表是否成功：`camera gateway fetch device list success`
- 设备数量：`camera gateway device count: N`
- 生成数量：`camera gateway generated camera count: N`
- 设备是否为 `devType == "encodingDev"`
- `videoChannelNum` 是否大于 0

### 12.3 页面能播放但没有检测

播放和检测是两条链路。检查：

- `/api/cameras/status` 中摄像头状态是否为 `running`
- 是否出现 `first frame received`
- 是否出现 `inference success`
- 模型文件 `models/ultra.pt`、`models/best.pt` 是否存在
- `detection.detect_interval_seconds` 和 `max_inference_workers` 是否合理

### 12.4 H.265/HEVC 解码问题

OpenCV/FFmpeg 对部分设备的 H.265/HEVC 流兼容性不稳定。建议将检测流配置为 H.264 子码流。

## 13. 维护注意

- 不要删除本地 `cameras`，它是网关失败时的 fallback。
- 不要在日志中打印 token 或 RTSP 明文密码。
- 不要把页面播放成功等同于后台检测成功。
- 修改 `camera_id` 会影响历史报警关联和前端 API 路径。
- `app/main.py`、`app/api/*` 中保留了部分 FastAPI 结构，当前常规启动入口仍是 Flask `app.py`。
