# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

import os
import uuid
import asyncio
import shutil
from pathlib import Path
from typing import Optional
from PIL import Image, ImageOps

from config import INPUT_DIR, OUTPUT_DIR, TEMP_DIR, CLEANUP_AGE_HOURS
from backend.utils.image_utils import generate_thumbnail
from backend.utils.validators import validate_extension, validate_magic_bytes, validate_file_size


# ─── Session 目录辅助 ───


def get_session_input_dir(session_id: str) -> Path:
    """返回当前 session 的 input 子目录，自动创建"""
    d = INPUT_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_session_output_dir(session_id: str) -> Path:
    """返回当前 session 的 output 子目录，自动创建"""
    d = OUTPUT_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_session_temp_dir(session_id: str) -> Path:
    """返回当前 session 的 temp 子目录，自动创建"""
    d = TEMP_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─── 结果/中间文件路径辅助 ───


def get_cutout_path(image_id: str, session_id: str = "") -> Path:
    """兼容旧版 cutout PNG 路径（供编辑器预览 / legacy 流程使用）"""
    temp_dir = get_session_temp_dir(session_id) if session_id else TEMP_DIR
    return temp_dir / f"{image_id}_cutout.png"


def get_alpha_path(image_id: str, run_id: str = "", session_id: str = "") -> Path:
    """alpha-only canonical 资产路径"""
    temp_dir = get_session_temp_dir(session_id) if session_id else TEMP_DIR
    if run_id:
        return temp_dir / f"{image_id}_{run_id}_alpha.png"
    return temp_dir / f"{image_id}_alpha.png"


def get_probe_alpha_path(image_id: str, run_id: str = "", session_id: str = "") -> Path:
    """alpha-only probe 小图资产路径（按需再放大为 canonical alpha）。"""
    temp_dir = get_session_temp_dir(session_id) if session_id else TEMP_DIR
    if run_id:
        return temp_dir / f"{image_id}_{run_id}_alpha_probe.png"
    return temp_dir / f"{image_id}_alpha_probe.png"


def get_result_meta_path(image_id: str, run_id: str = "", session_id: str = "") -> Path:
    """结果元数据路径"""
    temp_dir = get_session_temp_dir(session_id) if session_id else TEMP_DIR
    if run_id:
        return temp_dir / f"{image_id}_{run_id}_meta.json"
    return temp_dir / f"{image_id}_meta.json"


def get_result_thumb_path(image_id: str, run_id: str = "", session_id: str = "") -> Path:
    """结果缩略图路径"""
    temp_dir = get_session_temp_dir(session_id) if session_id else TEMP_DIR
    if run_id:
        return temp_dir / f"{image_id}_{run_id}_result_thumb.png"
    return temp_dir / f"{image_id}_result_thumb.png"


# ─── 文件操作 ───


def save_uploaded_file(content: bytes, original_filename: str, session_id: str = "") -> dict:
    """保存上传文件，返回元数据（session_id 非空时写入 session 子目录）"""
    if not validate_extension(original_filename):
        raise ValueError(f"不支持的文件格式: {original_filename}")
    if not validate_file_size(len(content)):
        raise ValueError(f"文件过大，最大允许 {50}MB")
    if not validate_magic_bytes(content):
        raise ValueError("文件内容不是有效的图片格式")

    ext = Path(original_filename).suffix.lower()
    image_id = str(uuid.uuid4())[:8]

    if session_id:
        save_dir = get_session_input_dir(session_id)
    else:
        save_dir = INPUT_DIR
    save_path = save_dir / f"{image_id}{ext}"
    with open(save_path, "wb") as f:
        f.write(content)

    # 获取图片尺寸和生成缩略图（自动修正 EXIF 方向）
    img = Image.open(save_path)
    img = ImageOps.exif_transpose(img) or img
    width, height = img.size
    thumb_data = generate_thumbnail(img)
    if session_id:
        thumb_dir = get_session_temp_dir(session_id)
    else:
        thumb_dir = TEMP_DIR
    thumb_path = thumb_dir / f"{image_id}_thumb.png"
    with open(thumb_path, "wb") as f:
        f.write(thumb_data)

    return {
        "id": image_id,
        "filename": original_filename,
        "path": str(save_path),
        "width": width,
        "height": height,
        "file_size": len(content),
        "thumbnail_url": f"/api/thumbnail/{image_id}",
    }


def delete_image_files(image_id: str, session_id: str = ""):
    """删除原始上传文件（保留已处理的结果文件）"""
    if session_id:
        input_dir = get_session_input_dir(session_id)
        temp_dir = get_session_temp_dir(session_id)
    else:
        input_dir = INPUT_DIR
        temp_dir = TEMP_DIR

    # 删除原始输入文件
    for f in input_dir.iterdir():
        if f.name.startswith(image_id):
            try:
                os.remove(f)
            except OSError:
                pass
    # 清理原始缩略图和中间文件，但保留结果缩略图
    for f in temp_dir.iterdir():
        if f.name.startswith(image_id) and not f.name.endswith("_result_thumb.png"):
            try:
                os.remove(f)
            except OSError:
                pass


def delete_result_files(image_id: str, run_id: str = "", session_id: str = ""):
    """删除图片关联的处理结果文件（保留原始上传文件）"""
    dirs = []
    if session_id:
        dirs = [get_session_output_dir(session_id), get_session_temp_dir(session_id)]
    else:
        dirs = [OUTPUT_DIR, TEMP_DIR]

    for dir_path in dirs:
        for f in dir_path.iterdir():
            if run_id:
                if f.name.startswith(f"{image_id}_{run_id}"):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
            else:
                if f.name.startswith(image_id):
                    try:
                        os.remove(f)
                    except OSError:
                        pass


def get_output_path(image_id: str, ext: str, run_id: str = "", session_id: str = "") -> Path:
    """构造输出文件路径（session_id 非空时写入 session 子目录）"""
    if session_id:
        out_dir = get_session_output_dir(session_id)
    else:
        out_dir = OUTPUT_DIR

    if run_id:
        return out_dir / f"{image_id}_{run_id}_processed{ext}"
    return out_dir / f"{image_id}_processed{ext}"


def cleanup_old_files():
    """清理过期文件（保留 session 目录结构，只清理文件）"""
    import time

    now = time.time()
    max_age = CLEANUP_AGE_HOURS * 3600
    for dir_path in [INPUT_DIR, OUTPUT_DIR, TEMP_DIR]:
        if not dir_path.exists():
            continue
        for f in dir_path.iterdir():
            if f.is_file() and (now - f.stat().st_mtime) > max_age:
                try:
                    os.remove(f)
                except OSError:
                    pass


async def periodic_cleanup():
    """后台定时清理任务"""
    while True:
        await asyncio.sleep(3600)  # 每小时
        cleanup_old_files()
