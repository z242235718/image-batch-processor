# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

import io
from PIL import Image


def generate_thumbnail(image: Image.Image, size: int = 200) -> bytes:
    """生成缩略图，返回 PNG 字节"""
    img = image.copy()
    img.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_image_size(image: Image.Image) -> tuple:
    """返回 (width, height)"""
    return image.size


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小为人类可读字符串"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
