# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

from pathlib import Path
from config import ALLOWED_EXTENSIONS, MAX_UPLOAD_SIZE_MB, FILE_SIGNATURES


def validate_extension(filename: str) -> bool:
    """检查文件扩展名是否在允许列表中"""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS


def validate_magic_bytes(data: bytes) -> bool:
    """通过文件签名验证文件类型"""
    for signature, _ in FILE_SIGNATURES.items():
        if data[: len(signature)] == signature:
            return True
    # WEBP 特殊检查: RIFF....WEBP
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def validate_file_size(size: int) -> bool:
    """检查文件大小是否在限制内"""
    return size <= MAX_UPLOAD_SIZE_MB * 1024 * 1024
