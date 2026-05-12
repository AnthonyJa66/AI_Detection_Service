# 智能视频监控系统

## 1. 部署前必看

这一节是给“把项目迁移到另一台电脑运行”的维护人员准备的。  
如果你当前最关心的是“哪些文件要带、哪些配置要改、改完还要联动检查什么”，先看这一节就够了。

### 1.1 部署时必须保留哪些内容

最小可运行集建议保留：

```text
app/
hik/
models/
app.py
settings.json
requirements.txt
README.md
start.bat
```

说明：

- `app/`：主程序代码，必须保留
- `hik/`：海康 Web SDK 静态资源，NVR 播放必须保留
- `models/`：YOLO 权重文件，检测必须保留
- `settings.json`：运行配置，必须保留
- `requirements.txt`：依赖安装必须保留
- `start.bat`：仅 Windows 一键启动时需要

### 1.2 哪些目录可以不带

以下内容不是运行必需，可以不带：

- `.git/`
- `__pycache__/`
- `CLAUDE.md`

以下目录可以不带，程序会自动创建，但是否保留取决于你是否需要历史数据：

- `logs/`
- `snapshots/`
- `data/`

补充说明：

- 不保留 `logs/`：只会丢失旧日志，不影响运行
- 不保留 `snapshots/`：只会丢失旧报警截图，不影响运行
- 不保留 `data/`：只会丢失旧 SQLite 报警记录，程序会重新创建空库

如果你要保留历史报警记录和截图，请一并保留：

- `data/`
- `snapshots/`

### 1.3 新电脑必须修改的配置

所有运行配置都在：`settings.json`

最少要检查这 5 组内容。

#### 1. `server`

修改位置：

- `settings.json -> server.host`
- `settings.json -> server.port`

需要联动检查：

- 新电脑端口是否被占用
- 浏览器最终访问地址是否跟着变化
- 若你写了反向代理或防火墙规则，也要同步改端口

示例：

```json
"server": {
  "host": "0.0.0.0",
  "port": 5000,
  "debug": true
}
```

#### 2. `paths`

修改位置：

- `settings.json -> paths.snapshot_dir`
- `settings.json -> paths.db_path`

需要联动检查：

- 如果改成绝对路径，要确认目标目录有写权限
- 如果数据库路径换盘符，记得一起迁移旧数据库文件
- 如果截图目录变了，历史截图访问路径也会对应变化

默认相对路径通常可直接沿用：

```json
"paths": {
  "snapshot_dir": "snapshots",
  "db_path": "data/monitoring.db"
}
```

#### 3. `logging`

修改位置：

- `settings.json -> logging.file`
- `settings.json -> logging.level`

需要联动检查：

- 新日志路径所在目录是否可写
- 生产环境建议把 `level` 调成 `INFO` 或 `WARNING`

示例：

```json
"logging": {
  "level": "INFO",
  "file": "logs/app.log"
}
```

#### 4. `cameras`

修改位置：

- `settings.json -> cameras[*].rtsp_url`
- `settings.json -> cameras[*].detection_rtsp_url`
- `settings.json -> cameras[*].username`
- `settings.json -> cameras[*].password`
- `settings.json -> cameras[*].nvr_host`
- `settings.json -> cameras[*].nvr_port`
- `settings.json -> cameras[*].channel_no`
- `settings.json -> cameras[*].name`
- `settings.json -> cameras[*].location`

需要联动检查：

- 摄像头或 NVR IP 变了，必须同步改 `rtsp_url`
- 检测专用子码流变了，必须同步改 `detection_rtsp_url`
- 账号密码变了，必须同步改认证信息
- 如果检测端仍然不稳定，优先检查 `detection_rtsp_url` 对应的是不是 H.264 子码流
- 摄像头 `id/camera_id` 变了，会影响主界面选择、报警记录归属和前端轮询的 `camera_id`

重点建议：

- 播放主流和检测专用流尽量分开
- `rtsp_url` 用主码流
- `detection_rtsp_url` 用更稳定的子码流

#### 5. `hik_playback`

修改位置：

- `settings.json -> hik_playback.access_url`
- `settings.json -> hik_playback.username`
- `settings.json -> hik_playback.password`

需要联动检查：

- 新电脑必须能访问这个 `deviceGateway`
- 例如 `ws://192.168.1.100:8090`
- 如果这个地址不通，NVR 在网页里无法播放，即使 VLC/RTSP 正常也没用
- 如果用户名密码变了，要和 NVR 实际账号一致

示例：

```json
"hik_playback": {
  "access_url": "ws://192.168.1.100:8090",
  "username": "admin",
  "password": "cmc.1340"
}
```

### 1.4 新电脑需要具备的环境

#### 基础环境

- Python 3.12
- `pip`
- 能安装 `requirements.txt`

当前依赖：

- Flask
- Flask-Sock
- opencv-python
- ultralytics

#### 必须具备的文件

- `models/ultra.pt`
- `models/best.pt`

缺少任意一个，检测都不完整。

#### 网络条件

新电脑必须能访问：

- 摄像头 RTSP 地址
- NVR 地址
- 海康 `deviceGateway` 地址和端口

最少要确认：

- RTSP 可连通
- NVR 可连通
- `ws://<deviceGateway>:8090` 可连通

#### 浏览器建议

建议使用较新的：

- Edge
- Chrome

因为项目依赖：

- 海康 Web SDK
- Canvas overlay
- WebSocket
- 浏览器音频权限控制

#### 操作系统建议

推荐：

- Windows 10 / 11

原因：

- 当前字体路径优先查找 `C:/Windows/Fonts/*`
- 项目自带 `start.bat`
- 当前海康播放和现场调试链路更贴近 Windows 环境

### 1.5 部署后建议按这个顺序验证

1. 执行 `pip install -r requirements.txt`
2. 确认 `models/ultra.pt`、`models/best.pt` 存在
3. 修改 `settings.json`
4. 启动 `python app.py`
5. 打开首页确认 RTSP 摄像头能显示
6. 打开首页确认 NVR 摄像头能通过海康 Web SDK 播放
7. 确认 `/api/cameras/status` 返回正常
8. 确认报警截图、数据库、日志目录可写

## 2. 快速启动

### 2.1 安装依赖

```bash
pip install -r requirements.txt
```

### 2.2 启动服务

```bash
python app.py
```

默认访问地址：

- [http://127.0.0.1:5000](http://127.0.0.1:5000)
- [http://localhost:5000](http://localhost:5000)

## 3. 项目简介

本项目是一个基于 `Python + Flask + OpenCV + Ultralytics YOLO` 的视频监控系统，负责完成以下能力：

- 摄像头 / NVR 视频接入
- 实时画面播放
- 安全帽、反光衣、抽烟等违规检测
- 规则判断与报警生成
- 报警截图保存
- 报警记录入库
- WebSocket 实时推送

当前系统采用“播放分流、检测统一后端处理”的架构：

- `NVR 摄像头 -> 海康 Web SDK 播放`
- `RTSP 摄像头 -> OpenCV + Flask + MJPEG 播放`
- `AI 检测 -> 统一由 Python 后端执行`

## 4. 当前技术框架

### 后端

- Python 3.12
- Flask 3.1
- Flask-Sock
- OpenCV
- Ultralytics YOLO
- SQLite

### 前端

- HTML / CSS / JavaScript
- 海康 Web SDK / JSPlugin
- Canvas 叠框
- MJPEG `<img>` 播放

### 检测与报警

- 安全检测模型：`models/ultra.pt`
- 抽烟检测模型：`models/best.pt`
- 规则引擎：违规计数、去抖、状态切换
- 报警截图：本地落盘
- 报警通知：SQLite + WebSocket

### 当前检测类别 / 关键词

- 人体：`person`
- 安全帽：`helmet`
- 反光衣：`vest`
- 未戴安全帽：`no_helmet`
- 未穿反光衣：`no_vest`
- 抽烟：`smoking`

## 5. 系统架构说明

### 5.1 后端主链路

1. `CameraStream`
   负责单路 RTSP/NVR RTSP 拉流、缓存最新帧、维护重连状态。
2. `CameraManager`
   负责管理全部 `CameraStream` 实例。
3. `VideoProcessor`
   负责按固定间隔取最新帧做检测，避免旧帧堆积。
4. `DetectionPipeline`
   负责调用模型、整合检测结果、生成标注画面。
5. `RuleEngine`
   负责把逐帧检测结果转成稳定的违规状态和报警事件。
6. `AlarmManager`
   负责报警入库、截图保存、WebSocket 推送。

### 5.2 播放与检测关系

- 前端播放和后端检测是解耦的
- 画面播放成功，不代表后端检测流一定稳定
- 前端按 `camera_id` 单独拉取检测结果、统计和 overlay 数据

## 6. 播放架构说明

### 6.1 NVR 摄像头

- 播放方式：海康 Web SDK
- 主页面：`/`
- 测试页：`/hik_test`
- 融合测试页：`/hik_fusion_test`
- 公共桥接层：`app/static/js/hik_common_player.js`

要求：

- `playURL` 不带账号密码
- 用户名密码通过 `auth` 单独传递
- 主界面与测试页复用同一套播放请求构造逻辑

### 6.2 RTSP 摄像头

- 后端读取：OpenCV `VideoCapture`
- 前端播放：Flask `video_feed` 输出 MJPEG

### 6.3 检测流与播放流

每路摄像头当前支持两条流：

- `rtsp_url`：原始流 / 播放主流
- `detection_rtsp_url`：检测专用流

推荐：

- 播放：使用主码流
- 检测：使用更稳定、码率更低的子码流

对于 NVR，如后端检测仍出现 `HEVC/H.265` 解码异常，优先检查设备端子码流是否已切为 `H.264`。

## 7. 检测与报警流程

1. `CameraStream` 读取摄像头最新帧
2. `VideoProcessor` 按 `detect_interval_seconds` 调度检测
3. `DetectionPipeline` 调用 YOLO 模型输出 `DetectionResult`
4. `RuleEngine` 生成违规状态和报警事件
5. `AlarmManager` 负责：
   - 报警入库
   - 报警截图保存
   - WebSocket 推送
6. 主界面轮询：
   - `/api/main/detections/overlay/<camera_id>`
   - `/api/cameras/status`

## 8. 核心目录结构

```text
Test1/
├─ app/                      Flask 应用代码
├─ data/                     SQLite 数据库目录
├─ hik/                      海康 Web SDK 静态资源
├─ logs/                     日志目录
├─ models/                   YOLO 模型权重
├─ snapshots/                报警截图目录
├─ app.py                    启动入口
├─ settings.json             运行配置
├─ requirements.txt          Python 依赖
├─ start.bat                 Windows 启动脚本
└─ README.md                 项目说明
```

## 9. 核心文件说明

### 项目入口与配置

- `app.py`
  Flask 启动入口。
- `app/__init__.py`
  Flask 应用工厂，负责初始化全部服务。
- `app/config_loader.py`
  读取、校验并标准化 `settings.json`。

### 摄像头与拉流

- `app/services/camera_stream.py`
  单路视频流拉取、缓存与重连。
- `app/services/camera_manager.py`
  多路摄像头实例管理。
- `app/services/stream_factory.py`
  创建 `CameraStream` 的工厂。
- `app/services/camera_settings_service.py`
  摄像头配置读写服务。

### 检测与模型

- `app/services/video_processor.py`
  检测调度器。
- `app/services/detection_pipeline.py`
  推理结果整合、标注图生成。
- `app/services/model_manager.py`
  YOLO 模型加载与推理。
- `app/services/rule_engine.py`
  违规规则判断。
- `app/utils/detection_summary_utils.py`
  主界面统计与违规过滤工具。

### 报警与截图

- `app/services/alarm_manager.py`
  报警持久化与通知分发。
- `app/services/alarm_repository.py`
  SQLite 报警记录读写。
- `app/services/snapshot_service.py`
  报警截图保存。
- `app/services/websocket_manager.py`
  WebSocket 报警推送。

### 路由与页面

- `app/routes/main_routes.py`
  首页、报警页、主界面 API、视频流接口、海康测试页。
- `app/routes/camera_routes.py`
  摄像头管理页面与提交逻辑。
- `app/routes/ws_routes.py`
  WebSocket 路由。
- `app/templates/index.html`
  主界面模板。
- `app/templates/hik_test.html`
  海康播放测试页。
- `app/templates/hik_fusion_test.html`
  海康播放 + 检测融合测试页。

### 前端脚本

- `app/static/js/index.js`
  主界面播放分流、叠框轮询、报警列表、声音开关。
- `app/static/js/hik_common_player.js`
  海康播放器公共桥接层。

## 10. 配置说明（settings.json）

### 10.1 server

- `host`：Flask 监听地址
- `port`：Flask 监听端口
- `debug`：调试模式

### 10.2 paths

- `snapshot_dir`：报警截图目录
- `db_path`：SQLite 数据库文件路径

### 10.3 logging

- `level`：日志级别
- `file`：日志文件路径

### 10.4 cameras

每路摄像头常用字段：

- `camera_id` / `id`：摄像头唯一 ID
- `name`：摄像头名称
- `source_type`：`rtsp_camera` 或 `nvr_rtsp`
- `rtsp_url`：原始流地址
- `detection_rtsp_url`：检测专用流地址，可选
- `enabled`：是否启用
- `fps_target`：目标 FPS
- `retry_interval_seconds`：重连等待秒数
- `max_reconnect_attempts`：最大重连次数
- `resolution.width` / `resolution.height`：分辨率
- `location`：安装位置
- `nvr_*` / `channel_no` / `username` / `password`：设备补充信息

### 10.5 detection

- `confidence`
- `safety_confidence`
- `smoking_confidence`
- `detect_interval_seconds`
- `max_inference_workers`

### 10.6 alarm

- `confirm_counts`
- `clear_count`
- `session_end_grace_seconds`
- `enable_reminder_events`
- `reminder_interval_seconds`

### 10.7 hik_playback

- `access_url`：海康 `deviceGateway` WebSocket 地址
- `username` / `password`：海康播放认证信息

## 11. 已实现功能

- 多路摄像头配置与运行时热更新
- RTSP / NVR RTSP 分类接入
- RTSP 主界面 MJPEG 播放
- NVR 海康 Web SDK 播放
- 双模型检测与违规叠框
- 主界面统计卡片与最近报警列表
- 报警记录落库
- 报警截图保存
- WebSocket 实时报警推送
- 海康测试页与融合测试页
- NVR 主界面声音开关

## 12. 当前已知问题 / 后续优化方向

- NVR 检测流稳定性仍依赖设备端子码流配置；如果子码流仍为 H.265，OpenCV/FFmpeg 兼容性可能不足。
- `settings.json` 已支持 `detection_rtsp_url`，但摄像头管理表单尚未直接暴露该字段。
- `app/static/js/index.js` 仍保留少量历史兼容函数，后续可在不改行为的前提下做清理。
- 海康 Web SDK 无法直接提供可信的真实播放 FPS，因此主界面目前显示运行态文案而不是数字帧率。
- 抽烟误检已增加“靠近人体”过滤，但阈值仍可能需要结合现场机位继续调优。
