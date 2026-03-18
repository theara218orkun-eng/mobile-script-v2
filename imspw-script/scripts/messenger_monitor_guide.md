# Messenger Monitor 监听与发送复现指南

本文档说明 Messenger 的**监听（Listen）**和**发送（Send）**功能，已整合到本项目的 module-core 架构。

---

## 一、架构概览

```
【监听 Listen】ADB 轮询
messenger_database_monitor.py  →  incoming_queue  →  message_processor  →  Processor

【发送 Send】Deep Link + uiautomator2
Processor 返回 message  →  add_task(REPLY_MESSENGER)  →  messenger_service  →  Deep Link + u2 输入/发送
```

---

## 二、前置条件

| 项目 | 说明 |
|------|------|
| **Root** | 必须 root，用于读取 Messenger 应用数据目录 |
| **SELinux** | 建议 Permissive（`setenforce 0`） |
| **ADB** | 已连接并可用 `adb devices` |
| **Messenger** | `com.facebook.orca`，需已登录目标账号 |

---

## 三、关键文件

| 文件 | 职责 |
|------|------|
| `module-core/src/utils/messenger_database_monitor.py` | 监听：ADB 拉 DB、轮询、输出到 incoming_queue |
| `module-core/src/services/messenger_service.py` | 发送：Deep Link + uiautomator2 |
| `module-core/src/hooks/modules/messenger_message_sender.js` | Frida 可选：Deep Link 打开会话 |

---

## 四、使用方式

```bash
# .env
TARGET_PACKAGES=jp.naver.line.android,com.whatsapp,messenger

# 或
TARGET_PACKAGES=com.facebook.orca
```

```bash
uv run python src/main.py
```

- Messenger 仅使用 ADB 监听，不启动 Frida Supervisor
- 其他应用（LINE、WhatsApp）使用 Frida 监听

---

## 五、配置

| 环境变量 | 默认值 | 用途 |
|----------|--------|------|
| `MESSENGER_MONITOR_INTERVAL` | 2.0 | 轮询间隔（秒） |

---

## 六、数据格式

```json
{
  "type": "INCOMING",
  "user_info": {"uuid": "thread_id", "username": "", "phone": ""},
  "chat": {"uuid": "thread_id", "name": "", "type": "chat"},
  "content": "Base64_encoded_message",
  "time": "..."
}
```

`user_info.uuid` = `thread_id`，用于 Deep Link：`fb-messenger://user-thread/{uuid}`
