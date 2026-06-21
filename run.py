# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

import socket
import threading
import uvicorn
import webbrowser


def find_free_port(start: int = 8000, max_attempts: int = 100) -> int:
    """查找从 start 开始的第一个可用端口"""
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"无法在范围 [{start}, {start + max_attempts}) 内找到可用端口")


def _open_browser(url: str) -> None:
    """延迟自动打开浏览器"""
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    host = "127.0.0.1"
    port = find_free_port(8000)
    url = f"http://{host}:{port}"
    print(f"\n  Image Processor 调试模式")
    print(f"  {url}")
    print(f"  代码修改后自动重载\n")
    # 等待 1.5 秒后自动打开浏览器（确保 server 已就绪）
    threading.Timer(1.5, _open_browser, args=(url,)).start()
    uvicorn.run("backend.main:app", host=host, port=port, reload=True)
