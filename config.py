# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

import os
import sys
from pathlib import Path


def _is_frozen() -> bool:
    """检测是否在 PyInstaller 打包环境中运行"""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _get_base_dir() -> Path:
    """获取应用源文件的基础目录（只读，打包后为 sys._MEIPASS）"""
    if _is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _get_data_dir() -> Path:
    """获取可写数据目录，打包后重定向到 %LOCALAPPDATA%"""
    if _is_frozen():
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ImageProcessor"
    return _get_base_dir()


BASE_DIR = _get_base_dir()
DATA_DIR = _get_data_dir()
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
TEMP_DIR = DATA_DIR / "temp"
ASSETS_DIR = BASE_DIR / "assets"
FRONTEND_DIR = BASE_DIR / "frontend"

# 上传限制
MAX_UPLOAD_SIZE_MB = 50
MAX_TOTAL_UPLOADS = 200
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

# 处理控制
CONCURRENT_PROCESS_LIMIT = 4
# 背景移除(ONNX推理)并发数 — ONNX推理内存密集，设为1避免OOM
CONCURRENT_BG_LIMIT = 1

# 文件清理（结果文件保留 7 天）
CLEANUP_AGE_HOURS = 168

# Session 管理（同一台机器不同浏览器隔离 + 过期清理，8 小时无活动自动清除）
SESSION_TIMEOUT_HOURS = 8
SESSION_CLEANUP_INTERVAL = 3600  # 清理检查间隔（秒）

# remove.bg API Key (用于云端抠图)
REMBG_API_KEY = "test123"

# 默认 Logo 配置
DEFAULT_LOGO_POSITION = "left-top"
DEFAULT_LOGO_RATIO = 0.2
DEFAULT_LOGO_OPACITY = 0.8
DEFAULT_LOGO_MARGIN = 20

# 文件签名 (magic bytes) 用于验证上传文件类型
FILE_SIGNATURES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",  # 需进一步检查 WEBP 标识
    b"BM": "image/bmp",
    b"MM\x00\x2a": "image/tiff",
    b"II\x2a\x00": "image/tiff",
}

# 确保目录存在（parents=True 支持跨驱动器创建路径链）
for d in [INPUT_DIR, OUTPUT_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)
