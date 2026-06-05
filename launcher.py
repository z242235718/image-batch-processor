# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

"""图片批量处理工具 - Windows 桌面版启动器

在 http://127.0.0.1:<port> 启动 uvicorn 服务器，自动打开浏览器，
保持控制台窗口打开以显示日志，方便调试定位问题。
使用 PyInstaller 打包为独立 exe 时作为入口点。
"""

import socket
import subprocess
import sys
import threading
import time

# --- 优先创建数据目录（在 uvicorn 启动前确保路径就绪）---
# config.py 中的目录创建会在 import 时触发
import config  # noqa: F401


def find_free_port(start: int = 8000, max_attempts: int = 100) -> int:
    """查找从 start 开始的第一个可用端口"""
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"无法在范围 [{start}, {start + max_attempts}) 内找到可用端口")


def open_browser(host: str, port: int, delay: float = 1.5):
    """延迟打开默认浏览器"""
    time.sleep(delay)
    url = f"http://{host}:{port}"
    try:
        # Windows 下最可靠的浏览器启动方式
        subprocess.Popen(["cmd", "/c", "start", url], shell=True)
    except Exception:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass  # 静默失败，用户可从控制台手动复制 URL


def main():
    host = "127.0.0.1"
    port = find_free_port(8000)

    print()
    print("=" * 60)
    print("         图片批量处理工具 (Image Processor)")
    print("=" * 60)
    print(f"  版本: v0.0.5")
    print(f"  服务器地址:  http://{host}:{port}")
    print(f"  API 文档:    http://{host}:{port}/docs")
    print()
    print(f"  数据目录:    {config.DATA_DIR}")
    print()
    print("  1) 浏览器已自动打开，如未自动打开请手动访问以上地址。")
    print("  2) 首次运行浏览器显示\"找不到到网站\"，是正常现象 请耐心等待程序初始化;")
    print("     初始化完毕后控制台会有输出运行信息，浏览器会自动刷新界面。")
    print("  3) 首次使用背景移除(抠像)功能会自动下载模型文件，导致处理时间较长，请耐心等待。")
    print("  4) 使用过程中遇到任何错误或Bug,请截图反馈给 z242235718@163.com")
    print("  按 Ctrl+C 关闭程序")
    print("=" * 60)
    print()

    # 后台线程打开浏览器（daemon 确保不阻塞关闭）
    t = threading.Thread(target=open_browser, args=(host, port), daemon=True)
    t.start()

    # 启动 uvicorn 服务器
    import uvicorn

    server_config = uvicorn.Config(
        "backend.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
    )
    server = uvicorn.Server(server_config)

    try:
        server.run()
    except KeyboardInterrupt:
        print("\n收到关闭信号，正在停止程序...")
        server.should_exit = True
        # 强制事件循环退出
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            loop.stop()
        except Exception:
            pass

    print("程序已关闭。可以关闭此窗口。")


if __name__ == "__main__":
    main()
