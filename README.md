# 智能视频监控系统

## 1. 项目简介

这是一个基于 Python + Flask 的视频监控项目，目标是把摄像头播放、后端目标检测、违规规则判断、报警记录和截图留存串起来，形成一套可运行的现场监控系统。

项目当前采用“按摄像头类型分流播放、统一后端检测”的实现方式：

- NVR 摄像头前端播放：海康 Web SDK
- RTSP 摄像头前端播放：OpenCV 拉流 + Flask MJPEG
- AI 检测：统一由 Python 后端执行
- 报警记录：落库到 SQLite，并支持截图保存与 WebSocket 推送

## 2. 当前技术框架

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

- 双模型检测
  - `models/ultra.pt`：安全帽 / 反光衣 / 人体相关检测
  - `models/best.pt`：抽烟检测
- 规则引擎去抖与状态判断
- SQLite 报警记录
- 本地截图保存
- WebSocket 实时报警推送

## 3. 系统架构说明

### 3.1 后端服务分层

1. `CameraStream`
   负责单路 RTSP/NVR RTSP 拉流、缓存最新帧、维护重连状态。
2. `CameraManager`
   负责管理多路 `CameraStream` 实例。
3. `VideoProcessor`
   负责按固定间隔调度检测任务，只取“最新帧”做推理。
4. `DetectionPipeline`
   负责调用模型、合并结果、生成叠框画面。
5. `RuleEngine`
   负责把逐帧检测结果转成更稳定的违规状态与报警事件。
6. `AlarmManager`
   负责报警落库、截图补齐、WebSocket 推送。

### 3.2 前后端协作关系

- 前端播放只负责“看画面”
- 后端检测只负责“读流、推理、出结果”
- 主界面通过 `camera_id` 继续轮询检测结果，不依赖播放方式

也就是说，前端播放链路和后端检测链路是解耦的：

- 前端海康播放正常，不代表后端检测流一定稳定
- 前端播放失败，也不一定代表后端检测中断

## 4. 播放架构说明

### 4.1 NVR 摄像头

- 前端播放：海康 Web SDK
- 入口页面：
  - 主界面 `/`
  - 测试页 `/hik_test`
  - 融合测试页 `/hik_fusion_test`
- 公共播放器桥接：`app/static/js/hik_common_player.js`

当前要求是：

- `playURL` 不带账号密码
- 用户名密码通过 `auth` 单独传递
- 主界面与测试页复用同一套海康播放参数构造逻辑

### 4.2 RTSP 摄像头

- 后端读取：OpenCV `VideoCapture`
- 前端播放：Flask `video_feed` 输出 MJPEG，页面用 `<img>` 显示

### 4.3 检测流与播放流

当前系统已支持为摄像头单独配置检测专用流：

- `rtsp_url`：原始流/主流配置
- `detection_rtsp_url`：检测专用流

推荐做法：

- 播放继续使用高质量主流
- 检测优先使用更稳定、码率更低的子码流

对于 NVR，若检测侧仍出现 HEVC/H.265 解码问题，优先检查设备端子码流是否已经切为 H.264。

## 5. 检测与报警流程

1. `CameraStream` 持续读取摄像头最新帧
2. `VideoProcessor` 按 `detect_interval_seconds` 调度检测
3. `DetectionPipeline` 调用 YOLO 模型并输出 `DetectionResult`
4. `RuleEngine` 根据计数、去抖和冷却时间生成报警事件
5. `AlarmManager` 负责：
   - 报警入库
   - 截图保存
   - WebSocket 推送
6. 主界面轮询：
   - `/api/main/detections/overlay/<camera_id>`
   - `/api/cameras/status`
   用于刷新统计卡片、叠框和状态文案

## 6. 核心目录结构

```text
Test1/
├─ app/
│  ├─ models/                 数据模型定义
│  ├─ routes/                 Flask 路由
│  ├─ services/               拉流、检测、报警等服务
│  ├─ static/                 前端静态资源
│  ├─ templates/              页面模板
│  ├─ utils/                  标签、时间、统计等工具函数
│  ├─ __init__.py             Flask 应用工厂
│  └─ config_loader.py        配置加载与校验
├─ data/                      SQLite 数据库目录
├─ demo/                      海康 Web SDK 静态资源
├─ logs/                      日志目录
├─ models/                    YOLO 模型权重
├─ snapshots/                 报警截图目录
├─ app.py                     启动入口
├─ requirements.txt           Python 依赖
├─ settings.json              项目运行配置
└─ README.md                  项目说明文档
```

## 7. 核心文件说明

### 项目入口与配置

- `app.py`
  Flask 启动入口。
- `app/__init__.py`
  Flask 应用工厂，负责装配所有核心服务。
- `app/config_loader.py`
  负责读取、校验和标准化 `settings.json`。

### 摄像头与拉流

- `app/services/camera_stream.py`
  单路视频流拉取、最新帧缓存、重连状态维护。
- `app/services/camera_manager.py`
  多路摄像头实例管理。
- `app/services/stream_factory.py`
  创建 `CameraStream` 的简单工厂。
- `app/services/camera_settings_service.py`
  摄像头配置的读写服务。

### 检测与模型

- `app/services/video_processor.py`
  检测调度器。
- `app/services/detection_pipeline.py`
  模型推理结果整合、叠框生成。
- `app/services/model_manager.py`
  YOLO 模型加载与推理封装。
- `app/services/rule_engine.py`
  违规规则引擎。
- `app/utils/detection_summary_utils.py`
  主界面统计和违规过滤工具，包含抽烟近人体过滤逻辑。

### 报警与截图

- `app/services/alarm_manager.py`
  报警持久化和通知分发。
- `app/services/alarm_repository.py`
  SQLite 报警记录读写。
- `app/services/snapshot_service.py`
  报警截图保存。
- `app/services/websocket_manager.py`
  WebSocket 客户端管理与报警推送。

### 路由与页面

- `app/routes/main_routes.py`
  首页、报警页、MJPEG 输出、主界面检测接口、海康测试页。
- `app/routes/camera_routes.py`
  摄像头管理页面与增删改查提交流程。
- `app/routes/ws_routes.py`
  WebSocket 路由。
- `app/templates/index.html`
  主界面模板。
- `app/templates/hik_test.html`
  海康播放测试页。
- `app/templates/hik_fusion_test.html`
  海康播放 + 检测叠框融合测试页。

### 前端脚本

- `app/static/js/index.js`
  主界面前端逻辑，包含播放分流、摄像头切换、叠框轮询、声音开关。
- `app/static/js/hik_common_player.js`
  海康 Web SDK 公共桥接层。

## 8. 配置说明（settings.json）

### 8.1 server

- `host`：Flask 监听地址
- `port`：Flask 监听端口
- `debug`：调试模式开关

### 8.2 paths

- `snapshot_dir`：报警截图目录
- `db_path`：SQLite 数据库文件路径

### 8.3 logging

- `level`：日志级别
- `file`：日志文件路径

### 8.4 cameras

每路摄像头常用字段：

- `camera_id` / `id`：摄像头唯一标识
- `name`：显示名称
- `source_type`：摄像头类型
  - `rtsp_camera`
  - `nvr_rtsp`
- `rtsp_url`：原始流地址
- `detection_rtsp_url`：检测专用流地址，可选
- `enabled`：是否启用
- `fps_target`：目标 FPS 配置
- `retry_interval_seconds`：重连等待秒数
- `max_reconnect_attempts`：最大重连次数，`0` 表示不限
- `resolution.width` / `resolution.height`：目标分辨率
- `location`：安装位置
- `nvr_*` / `channel_no` / `username` / `password`：NVR 或设备补充信息

### 8.5 detection

- `confidence`：兼容旧配置的统一置信度
- `safety_confidence`：安全检测模型阈值
- `smoking_confidence`：抽烟检测模型阈值
- `detect_interval_seconds`：检测调度间隔
- `max_inference_workers`：推理线程数

### 8.6 alarm

- `confirm_counts`：违规确认阈值
- `clear_count`：清除阈值
- `session_end_grace_seconds`：会话结束宽限期
- `enable_reminder_events`：是否开启提醒型事件
- `reminder_interval_seconds`：提醒间隔

### 8.7 hik_playback

- `access_url`：海康 deviceGateway WebSocket 地址
- `username` / `password`：海康播放认证信息

## 9. 启动方式

### 9.1 安装依赖

```bash
pip install -r requirements.txt
```

### 9.2 启动服务

```bash
python app.py
```

启动后默认访问：

- [http://127.0.0.1:5000](http://127.0.0.1:5000)
- [http://localhost:5000](http://localhost:5000)

## 10. 已实现功能

- 多路摄像头配置加载与运行时热更新
- RTSP / NVR RTSP 分类型接入
- RTSP 摄像头主界面 MJPEG 播放
- NVR 摄像头海康 Web SDK 播放
- 双模型检测与违规叠框
- 主界面实时统计卡片与最近报警列表
- 报警记录落库
- 报警截图保存
- WebSocket 实时报警推送
- 海康测试页与融合测试页
- NVR 主界面声音开关

## 11. 当前已知问题 / 后续优化方向

- NVR 检测流稳定性仍依赖设备端子码流配置；若子码流仍为 H.265，OpenCV/FFmpeg 兼容性可能不足。
- `settings.json` 已支持 `detection_rtsp_url`，但摄像头管理表单尚未直接暴露该字段，现场调整时通常仍需手动修改配置文件。
- `app/static/js/index.js` 仍保留少量历史兼容函数，后续如继续维护主界面，可在不改行为的前提下做一次清理。
- 海康 Web SDK 无法直接提供可信的主界面实时播放 FPS，因此主界面状态文案目前采用“实时播放 / 检测中”而非数字帧率。
- 抽烟误检已增加“靠近人体”过滤，但阈值仍与现场机位、画面尺度有关，后续可根据数据继续调优。
