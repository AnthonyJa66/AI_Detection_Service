# AI Detection Service API Documentation

## 服务信息

| 项目 | 内容 |
| --- | --- |
| 服务地址 | `http://192.168.1.67:5000` |
| 端口 | `5000` |
| Flask版本 | `3.1.0` |
| 文档更新时间 | `2026-05-12` |

## 当前接口总数

| 类型 | 数量 |
| --- | ---: |
| HTTP REST API | 5 |
| WebSocket | 1 |
| 合计 | 6 |

## 最终保留接口

| 分类 | 请求方式 | 接口路径 | 说明 |
| --- | --- | --- | --- |
| 系统接口 | GET | `/health` | 服务健康检查 |
| 摄像头接口 | GET | `/api/cameras/status` | 摄像头运行状态 |
| 摄像头接口 | GET | `/api/cameras/<camera_id>/latest` | 最新 AI 检测结果 |
| 告警接口 | GET | `/api/alerts/recent` | 最近违规事件 |
| 告警接口 | GET | `/api/alerts/summary` | 大屏总告警统计 |
| 告警接口 | WebSocket | `/ws/alerts` | 实时告警推送 |

## app.url_map 推导结果

| 类型 | 请求方式 | 接口路径 | Endpoint |
| --- | --- | --- | --- |
| HTTP | GET | `/health` | `api.health` |
| HTTP | GET | `/api/cameras/status` | `api.camera_status` |
| HTTP | GET | `/api/cameras/<camera_id>/latest` | `api.latest_detection` |
| HTTP | GET | `/api/alerts/recent` | `api.recent_alerts` |
| HTTP | GET | `/api/alerts/summary` | `api.alerts_summary` |
| WebSocket | WS | `/ws/alerts` | `alarm_socket` |

## 自动检查结果

| 检查项 | 结果 |
| --- | --- |
| 重复接口 | 未发现 |
| 非 RESTful HTTP 接口 | 未发现明显问题 |
| 返回非 JSON 的 HTTP 接口 | 未发现 |
| 测试接口 | 未注册 |
| 页面接口 | 未注册 |
| 视频流接口 | 未注册 |

说明：`/health` 未使用 `/api/` 前缀，但它是企业联调约定的健康检查接口，保留。

---

## 系统接口

## 服务健康检查

### 请求方式

GET

### 接口地址

`/health`

### 完整URL

`http://192.168.1.67:5000/health`

### 接口作用

检测 AI Detection Service 是否在线。

### 请求参数

无

### 返回示例

```json
{
  "success": true,
  "message": "AI Detection Service is running.",
  "data": {
    "service": "AI Detection Service",
    "camera_count": 8
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| success | boolean | 请求是否成功 |
| message | string | 返回说明 |
| data.service | string | 服务名称 |
| data.camera_count | integer | 当前配置摄像头数量 |

### HTTP状态码

| 状态码 | 说明 |
| --- | --- |
| 200 | 请求成功 |
| 500 | 服务异常 |

### CURL调用示例

```bash
curl http://192.168.1.67:5000/health
```

---

## 摄像头接口

## 获取摄像头状态

### 请求方式

GET

### 接口地址

`/api/cameras/status`

### 完整URL

`http://192.168.1.67:5000/api/cameras/status`

### 接口作用

返回所有摄像头运行状态。

### 请求参数

无

### 返回示例

```json
{
  "success": true,
  "message": "Camera status fetched successfully.",
  "data": {
    "cam_001": {
      "camera_id": "cam_001",
      "camera_name": "1号摄像头",
      "enabled": true,
      "source_type": "rtsp_camera",
      "stream_url_role": "rtsp_url",
      "status": "running",
      "fps": 25.0,
      "last_error": "",
      "reconnect_attempts": 0,
      "last_frame_at": "2026-05-12 17:40:00",
      "thread_alive": true
    }
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| success | boolean | 请求是否成功 |
| message | string | 返回说明 |
| data | object | 摄像头状态字典，key 为摄像头 ID |
| camera_id | string | 摄像头 ID |
| camera_name | string | 摄像头名称 |
| enabled | boolean | 是否启用 |
| source_type | string | 视频源类型 |
| stream_url_role | string | 当前使用的流地址类型 |
| status | string | 运行状态 |
| fps | number | 当前读取帧率 |
| last_error | string | 最近错误 |
| reconnect_attempts | integer | 重连次数 |
| last_frame_at | string/null | 最近读取帧时间 |
| thread_alive | boolean | 拉流线程是否存活 |

### HTTP状态码

| 状态码 | 说明 |
| --- | --- |
| 200 | 请求成功 |
| 500 | 服务异常 |

### CURL调用示例

```bash
curl http://192.168.1.67:5000/api/cameras/status
```

---

## 获取最新检测结果

### 请求方式

GET

### 接口地址

`/api/cameras/<camera_id>/latest`

### 完整URL

`http://192.168.1.67:5000/api/cameras/cam_001/latest`

### 接口作用

返回指定摄像头最新 AI 检测结果。

### 请求参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| camera_id | path | string | 是 | 摄像头 ID |

### 返回示例

```json
{
  "success": true,
  "message": "Latest detection result fetched successfully.",
  "data": {
    "camera_id": "cam_001",
    "timestamp": "2026-05-12T09:40:00+00:00",
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

### 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| success | boolean | 请求是否成功 |
| message | string | 返回说明 |
| data.camera_id | string | 摄像头 ID |
| data.timestamp | string | 检测时间 |
| data.frame_width | integer | 帧宽 |
| data.frame_height | integer | 帧高 |
| data.detections | array | 检测结果 |
| data.detections[].class_name | string | 类别名称 |
| data.detections[].confidence | number | 置信度 |
| data.detections[].bbox | array | 检测框 `[x1, y1, x2, y2]` |
| data.detections[].source_model | string | 来源模型 |
| data.no_helmet_count | integer | 未戴安全帽数量 |
| data.no_vest_count | integer | 未穿反光衣数量 |
| data.smoking_count | integer | 抽烟数量 |

### HTTP状态码

| 状态码 | 说明 |
| --- | --- |
| 200 | 请求成功，或暂无检测结果 |
| 404 | 摄像头不存在 |
| 500 | 服务异常 |

### CURL调用示例

```bash
curl http://192.168.1.67:5000/api/cameras/cam_001/latest
```

---

## 告警接口

## 获取最近告警

### 请求方式

GET

### 接口地址

`/api/alerts/recent`

### 完整URL

`http://192.168.1.67:5000/api/alerts/recent`

### 接口作用

返回最近 AI 检测违规事件。

### 请求参数

| 参数 | 位置 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- | --- |
| limit | query | integer | 否 | 10 | 返回数量，服务端限制为 1-20 |

### 返回示例

```json
{
  "success": true,
  "message": "Recent alerts fetched successfully.",
  "data": {
    "items": [
      {
        "event_id": "evt_001",
        "aggregate_key": "cam_001:no_helmet",
        "camera_id": "cam_001",
        "camera_name": "1号摄像头",
        "violation_type": "no_helmet",
        "violation_types": ["no_helmet"],
        "violation_type_text": "未戴安全帽",
        "timestamp": "2026-05-12T09:40:00+00:00",
        "display_time": "2026-05-12 17:40:00",
        "confidence": 0.92,
        "snapshot_path": "snapshots/cam_001/evt_001.jpg",
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

### 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| success | boolean | 请求是否成功 |
| message | string | 返回说明 |
| data.items | array | 告警列表 |
| event_id | string | 告警事件 ID |
| aggregate_key | string | 聚合键 |
| camera_id | string | 摄像头 ID |
| camera_name | string | 摄像头名称 |
| violation_type | string | 主违规类型 |
| violation_types | array | 违规类型列表 |
| violation_type_text | string | 违规类型中文说明 |
| timestamp | string | 告警时间 |
| display_time | string | 展示时间 |
| confidence | number | 置信度 |
| snapshot_path | string/null | 快照路径 |
| snapshot_url | string/null | 快照 URL |
| raw_event_ids | array | 原始事件 ID |
| violation_counts | object | 违规计数 |

### HTTP状态码

| 状态码 | 说明 |
| --- | --- |
| 200 | 请求成功 |
| 500 | 服务异常 |

### CURL调用示例

```bash
curl "http://192.168.1.67:5000/api/alerts/recent?limit=10"
```

---

## 获取告警统计

### 请求方式

GET

### 接口地址

`/api/alerts/summary`

### 完整URL

`http://192.168.1.67:5000/api/alerts/summary`

### 接口作用

返回大屏总告警统计信息，包括告警数量、今日告警、摄像头在线数、摄像头总数和告警类型分布。

### 请求参数

无

### 返回示例

```json
{
  "success": true,
  "message": "Alert summary fetched successfully.",
  "data": {
    "total_alerts": 20,
    "today_alerts": 6,
    "camera_online": 6,
    "camera_total": 8,
    "alert_types": {
      "NO_HELMET": 15,
      "NO_VEST": 3,
      "SMOKING": 2
    }
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| success | boolean | 请求是否成功 |
| message | string | 返回说明 |
| data.total_alerts | integer | 当前轻量统计窗口内告警总数 |
| data.today_alerts | integer | 当前轻量统计窗口内今日告警数 |
| data.camera_online | integer | 当前在线摄像头数量 |
| data.camera_total | integer | 当前摄像头总数 |
| data.alert_types | object | 告警类型分布 |
| data.alert_types.NO_HELMET | integer | 未戴安全帽数量 |
| data.alert_types.NO_VEST | integer | 未穿反光衣数量 |
| data.alert_types.SMOKING | integer | 抽烟数量 |

### HTTP状态码

| 状态码 | 说明 |
| --- | --- |
| 200 | 请求成功 |
| 500 | 服务异常 |

### CURL调用示例

```bash
curl http://192.168.1.67:5000/api/alerts/summary
```

---

## WebSocket 实时告警

### 请求方式

WebSocket

### 接口地址

`/ws/alerts`

### 完整URL

`ws://192.168.1.67:5000/ws/alerts`

### 接口作用

实时推送 AI 违规告警消息。

### 推送示例

```json
{
  "camera_id": "cam_001",
  "violation_type": "no_helmet",
  "timestamp": "2026-05-12T09:40:00+00:00"
}
```

### 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| camera_id | string | 摄像头 ID |
| violation_type | string | 违规类型 |
| timestamp | string | 告警时间 |

### 调用示例

```bash
wscat -c ws://192.168.1.67:5000/ws/alerts
```

---

## 视频流接口

当前 Flask AI Detection Service 不注册 HTTP 视频流接口。视频播放由企业监控平台海康 WebSDK 负责。
