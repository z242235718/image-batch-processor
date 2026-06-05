# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

import io
from PIL import Image

from config import (
    JPEG_TARGET_RATIO_MIN,
    JPEG_TARGET_RATIO_MAX,
    JPEG_TARGET_QUALITY_FLOOR,
)


# PNG 颜色数阶梯（quality → 调色板颜色数；0 表示不量化）
# 档位拉细让相邻 quality 档位输出大小有明显差异
_PNG_COLOR_TABLE = [
    (100, 0),    # ≥ 100：PNG-24/32 严格无损
    (95,  256),  # 95~99 ：256 色调色板（高保真）
    (85,  128),  # 85~94 ：128 色
    (70,  64),   # 70~84 ：64 色
    (50,  32),   # 50~69 ：32 色
    (30,  16),   # 30~49 ：16 色
    (1,   8),    # 1~29  ：8 色（极限压缩）
]

# max_file_size_kb 在 PNG 路径上的"颜色数兜底"序列
_PNG_FALLBACK_COLORS = (256, 128, 64, 32, 16, 8)


def _png_palette_size(quality: int) -> int:
    """quality → 调色板颜色数；0 表示不量化。"""
    for threshold, n in _PNG_COLOR_TABLE:
        if quality >= threshold:
            return n
    return 16


def compress_image(
    image: Image.Image,
    output_format: str = "JPEG",
    quality: int = 85,
    max_file_size_kb: int = 0,
    max_width: int = 0,
    original_file_size: int = 0,
    prefer_target_jpeg_size: bool = False,
) -> bytes:
    """压缩图片并返回字节数据。

    执行顺序：限宽缩放 → 格式转换 → 编码（含 max_file_size_kb 二分 / 目标体积搜索）。
    裁切/蒙版裁切由调用方在 compress_image 之前完成。
    """
    img = image
    owned_imgs = []

    try:
        # 1) 限宽等比缩放
        if max_width > 0 and img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.LANCZOS)
            owned_imgs.append(img)

        # 2) JPEG 不支持透明通道
        if output_format.upper() in ("JPEG", "JPG"):
            if img.mode == "RGBA":
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background
                owned_imgs.append(img)
            elif img.mode != "RGB":
                img = img.convert("RGB")
                owned_imgs.append(img)

        fmt_upper = output_format.upper()

        # 3) 目标文件大小约束
        if max_file_size_kb > 0:
            target_bytes = max_file_size_kb * 1024

            if fmt_upper == "PNG":
                # PNG 路径：先按 quality 二分，再按颜色数兜底
                low, high = 1, 100
                best_data = None
                while low <= high:
                    mid = (low + high) // 2
                    data = _encode(img, output_format, mid)
                    if len(data) <= target_bytes:
                        best_data = data
                        low = mid + 1
                    else:
                        high = mid - 1
                if best_data is not None:
                    return best_data
                # 仍超限 → 按颜色数兜底
                for n in _PNG_FALLBACK_COLORS:
                    data = _encode_png_fixed_colors(img, n)
                    if len(data) <= target_bytes:
                        return data
                return _encode_png_fixed_colors(img, _PNG_FALLBACK_COLORS[-1])
            else:
                # JPEG / WEBP 路径：原二分搜索
                low, high = 1, 95
                best_data = None
                while low <= high:
                    mid = (low + high) // 2
                    data = _encode(img, output_format, mid)
                    if len(data) <= target_bytes:
                        best_data = data
                        low = mid + 1
                    else:
                        high = mid - 1
                if best_data:
                    return best_data
                return _encode(img, output_format, 1)

        if (
            prefer_target_jpeg_size
            and fmt_upper in ("JPEG", "JPG")
            and original_file_size > 0
        ):
            return _encode_jpeg_to_target_ratio(img, output_format, quality, original_file_size)

        return _encode(img, output_format, quality)
    finally:
        # 释放函数内部创建的中间图像（可能为大图）
        for owned in reversed(owned_imgs):
            if owned is not image:
                try:
                    owned.close()
                except Exception:
                    pass


def _encode_jpeg_to_target_ratio(
    img: Image.Image,
    fmt: str,
    preferred_quality: int,
    original_file_size: int,
) -> bytes:
    """在画质优先前提下，将 JPG 输出控制在目标体积窗口附近。"""
    min_target = max(1, int(original_file_size * JPEG_TARGET_RATIO_MIN))
    max_target = max(min_target, int(original_file_size * JPEG_TARGET_RATIO_MAX))
    quality_floor = max(1, min(95, JPEG_TARGET_QUALITY_FLOOR))
    quality_ceiling = max(quality_floor, min(95, preferred_quality if preferred_quality > 0 else 95))

    candidates = []
    low, high = quality_floor, quality_ceiling
    while low <= high:
        mid = (low + high) // 2
        data = _encode(img, fmt, mid)
        size = len(data)
        candidates.append((mid, size, data))
        if min_target <= size <= max_target:
            low = mid + 1
        elif size < min_target:
            low = mid + 1
        else:
            high = mid - 1

    if not candidates:
        return _encode(img, fmt, quality_ceiling)

    in_range = [c for c in candidates if min_target <= c[1] <= max_target]
    if in_range:
        return max(in_range, key=lambda item: (item[0], item[1]))[2]

    under_limit = [c for c in candidates if c[1] <= max_target]
    if under_limit:
        return max(under_limit, key=lambda item: (item[0], item[1]))[2]

    overs = [c for c in candidates if c[1] > max_target]
    if overs:
        return min(overs, key=lambda item: (item[1] - max_target, -item[0]))[2]

    return max(candidates, key=lambda item: item[0])[2]


def _encode(img: Image.Image, fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    save_kwargs = {"optimize": True}

    if fmt.upper() in ("JPEG", "JPG"):
        save_kwargs["quality"] = quality
        img.save(buf, format="JPEG", **save_kwargs)
    elif fmt.upper() == "WEBP":
        save_kwargs["quality"] = quality
        img.save(buf, format="WEBP", **save_kwargs)
    elif fmt.upper() == "PNG":
        _save_png(buf, img, quality, **save_kwargs)

    return buf.getvalue()


def _save_png(buf: io.BytesIO, img: Image.Image, quality: int, **save_kwargs) -> None:
    """按 quality 走颜色量化阶梯（PNG 路径）。"""
    n_colors = _png_palette_size(quality)
    save_kwargs["compress_level"] = max(0, min(9, (100 - quality) // 11))

    if n_colors <= 0:
        # 无损路径
        img.save(buf, format="PNG", **save_kwargs)
        return

    # 量化路径：保留 alpha 通道
    src = img
    try:
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            # method=2 (libimagequant) + dither=NONE 自动保留 alpha
            src = img.quantize(colors=n_colors, method=2, dither=Image.Dither.NONE)
        else:
            src = img.convert("RGB").quantize(colors=n_colors, method=2, dither=Image.Dither.NONE)
    except Exception:
        # 回退到 ADAPTIVE 方法（兼容老 Pillow）
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            src = img.quantize(colors=n_colors, method=Image.Palette.ADAPTIVE, dither=Image.Dither.NONE)
        else:
            src = img.convert("RGB").quantize(colors=n_colors, method=Image.Palette.ADAPTIVE, dither=Image.Dither.NONE)

    src.save(buf, format="PNG", **save_kwargs)


def _encode_png_fixed_colors(img: Image.Image, n_colors: int) -> bytes:
    """固定颜色数编码（用于 max_file_size_kb 兜底路径）。"""
    buf = io.BytesIO()
    save_kwargs = {"optimize": True, "compress_level": 9}
    if n_colors <= 0:
        img.save(buf, format="PNG", **save_kwargs)
        return buf.getvalue()
    try:
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            src = img.quantize(colors=n_colors, method=2, dither=Image.Dither.NONE)
        else:
            src = img.convert("RGB").quantize(colors=n_colors, method=2, dither=Image.Dither.NONE)
    except Exception:
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            src = img.quantize(colors=n_colors, method=Image.Palette.ADAPTIVE, dither=Image.Dither.NONE)
        else:
            src = img.convert("RGB").quantize(colors=n_colors, method=Image.Palette.ADAPTIVE, dither=Image.Dither.NONE)
    src.save(buf, format="PNG", **save_kwargs)
    return buf.getvalue()
