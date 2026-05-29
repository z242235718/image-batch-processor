import os
import uuid
import asyncio
from pathlib import Path
from PIL import Image

from config import INPUT_DIR, OUTPUT_DIR, TEMP_DIR, CLEANUP_AGE_HOURS
from backend.utils.image_utils import generate_thumbnail
from backend.utils.validators import validate_extension, validate_magic_bytes, validate_file_size


def save_uploaded_file(content: bytes, original_filename: str) -> dict:
    """保存上传文件，返回元数据"""
    if not validate_extension(original_filename):
        raise ValueError(f"不支持的文件格式: {original_filename}")
    if not validate_file_size(len(content)):
        raise ValueError(f"文件过大，最大允许 {50}MB")
    if not validate_magic_bytes(content):
        raise ValueError("文件内容不是有效的图片格式")

    ext = Path(original_filename).suffix.lower()
    image_id = str(uuid.uuid4())[:8]
    save_path = INPUT_DIR / f"{image_id}{ext}"
    with open(save_path, "wb") as f:
        f.write(content)

    # 获取图片尺寸和生成缩略图
    img = Image.open(save_path)
    width, height = img.size
    thumb_data = generate_thumbnail(img)
    thumb_path = TEMP_DIR / f"{image_id}_thumb.png"
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


def delete_image_files(image_id: str):
    """删除图片关联的所有文件"""
    for dir_path in [INPUT_DIR, OUTPUT_DIR, TEMP_DIR]:
        for f in dir_path.iterdir():
            if f.name.startswith(image_id):
                try:
                    os.remove(f)
                except OSError:
                    pass


def delete_result_files(image_id: str):
    """删除图片关联的处理结果文件（保留原始上传文件）"""
    for dir_path in [OUTPUT_DIR, TEMP_DIR]:
        for f in dir_path.iterdir():
            if f.name.startswith(image_id):
                try:
                    os.remove(f)
                except OSError:
                    pass


def get_output_path(image_id: str, ext: str) -> Path:
    return OUTPUT_DIR / f"{image_id}_processed{ext}"


def cleanup_old_files():
    """清理过期文件"""
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
