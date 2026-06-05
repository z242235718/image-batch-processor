# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

import socket
import uvicorn


def find_free_port(start: int = 8000, max_attempts: int = 100) -> int:
    """查找从 start 开始的第一个可用端口"""
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"无法在范围 [{start}, {start + max_attempts}) 内找到可用端口")


if __name__ == "__main__":
    host = "127.0.0.1"
    port = find_free_port(8000)
    print(f"\n  Image Processor 调试模式")
    print(f"  http://{host}:{port}")
    print(f"  代码修改后自动重载\n")
    uvicorn.run("backend.main:app", host=host, port=port, reload=True)
