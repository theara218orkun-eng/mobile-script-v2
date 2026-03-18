#!/usr/bin/env python3
"""
独立运行回调消息接收服务器（wdj-ispw 项目）

不依赖主进程，直接调用 IM 服务发送消息。适用于：
- 单独部署回调接收服务
- 测试回调接口

用法:
  # 从项目根目录
  python scripts/run_callback_server.py

  # 或指定端口
  CALLBACK_SERVER_PORT=8892 python scripts/run_callback_server.py

环境变量:
  CALLBACK_SERVER_PORT: 端口，默认 8891
  CALLBACK_API_SECRET: 可选，Bearer Token 校验
  DEVICE_ID: LINE/WhatsApp/Messenger 需要的设备 ID
  TELEGRAM_API_ID, TELEGRAM_API_HASH, TG_SESSION_STRING: Telegram 需要
"""

import os
import sys

# 添加 module-core/src 到路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
module_core_path = os.path.join(project_root, "module-core", "src")
if module_core_path not in sys.path:
    sys.path.insert(0, module_core_path)

# 加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(project_root, ".env"))
except ImportError:
    pass

# 强制使用直接发送模式（不依赖 processor）
os.environ.setdefault("CALLBACK_USE_PROCESSOR", "0")

from server.callback_server import run_server

if __name__ == "__main__":
    port = int(os.getenv("CALLBACK_SERVER_PORT", "8891"))
    api_secret = os.getenv("CALLBACK_API_SECRET", "").strip() or None
    use_processor = False  # 独立运行始终直接调用服务

    print(f"[wdj-ispw-callback] Starting standalone server on 0.0.0.0:{port}")
    print(f"[wdj-ispw-callback] POST /webhook or /callback with JSON: platform, target, message")
    server = run_server(port=port, api_secret=api_secret, use_processor=use_processor)
    server.serve_forever()
