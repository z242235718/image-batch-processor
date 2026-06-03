# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

import io
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

POSITION_MAP = {
    "left-top": (0, 0),
    "center-top": (0.5, 0),
    "right-top": (1, 0),
    "left-center": (0, 0.5),
    "center": (0.5, 0.5),
    "right-center": (1, 0.5),
    "left-bottom": (0, 1),
    "center-bottom": (0.5, 1),
    "right-bottom": (1, 1),
}


def _calculate_position(img_w: int, img_h: int, text_w: int, text_h: int, position: str, margin: int = 20):
    pos_x_ratio, pos_y_ratio = POSITION_MAP.get(position, (1, 1))
    if pos_x_ratio == 0:
        x = margin
    elif pos_x_ratio == 1:
        x = img_w - text_w - margin
    else:
        x = (img_w - text_w) // 2
    if pos_y_ratio == 0:
        y = margin
    elif pos_y_ratio == 1:
        y = img_h - text_h - margin
    else:
        y = (img_h - text_h) // 2
    return (x, y)


def _render_text(text: str, color: str, font_size: int) -> Image.Image:
    """渲染水印文字，自动裁剪到实际内容边界，确保不被截断"""
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except (IOError, OSError):
        font = ImageFont.load_default()

    padding = 20
    # 先用 textbbox 获取 ink 边界
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)

    # 计算足够大的渲染尺寸
    text_w = max(1, bbox[2] - bbox[0] + padding * 2)
    text_h = max(1, bbox[3] - bbox[1] + padding * 2)

    text_img = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_img)
    # 偏移绘制，使 ink 从 padding 位置开始
    draw.text((padding - bbox[0], padding - bbox[1]), text, font=font, fill=color)

    # 二次裁剪到实际内容，去除多余空白
    actual_bbox = text_img.getbbox()
    if actual_bbox:
        text_img = text_img.crop(actual_bbox)

    return text_img


def _create_tile_layer(image_size: tuple, text_img: Image.Image, step_x: int, step_y: int) -> Image.Image:
    """
    使用 numpy 批量合成平铺图层，比 PIL paste 循环快 5-20 倍。
    内部使用预乘 alpha 做 over 合成，最后反预乘输出。
    """
    text_arr = np.array(text_img, dtype=np.float32) / 255.0
    th, tw = text_arr.shape[:2]
    h, w = image_size[1], image_size[0]

    # 预乘 alpha
    src_alpha = text_arr[:, :, 3:4]
    src_rgb = text_arr[:, :, :3] * src_alpha
    src_all = np.concatenate([src_rgb, src_alpha], axis=2)  # (th, tw, 4) premultiplied

    out = np.zeros((h, w, 4), dtype=np.float32)

    for y in range(-th, h + th, step_y):
        for x in range(-tw, w + tw, step_x):
            x1, y1 = max(0, x), max(0, y)
            x2 = min(w, x + tw)
            y2 = min(h, y + th)
            if x2 <= x1 or y2 <= y1:
                continue

            sx, sy = x1 - x, y1 - y
            ex, ey = sx + (x2 - x1), sy + (y2 - y1)

            region = out[y1:y2, x1:x2]
            src_region = src_all[sy:ey, sx:ex]
            src_a = src_region[:, :, 3:4]

            # alpha over: result = src + dst * (1 - src_alpha)
            region[:, :, :3] = src_region[:, :, :3] + region[:, :, :3] * (1 - src_a)
            region[:, :, 3:4] = src_a + region[:, :, 3:4] * (1 - src_a)

    # 反预乘 alpha → uint8
    mask = out[:, :, 3:4] > 0.001
    result_arr = np.zeros((h, w, 4), dtype=np.uint8)
    result_arr[:, :, :3] = np.where(mask, (out[:, :, :3] / out[:, :, 3:4] * 255), 0).astype(np.uint8)
    result_arr[:, :, 3] = np.clip(out[:, :, 3] * 255, 0, 255).astype(np.uint8)

    # 释放中间大数组（out 是 float32，占 ~16 字节/像素）
    del out, mask, text_arr, src_all, src_alpha, src_rgb

    return Image.fromarray(result_arr, "RGBA")


def add_text_watermark(
    image: Image.Image,
    text: str,
    position: str = "right-bottom",
    text_ratio: float = 0.05,
    opacity: float = 0.5,
    color: str = "#FFFFFF",
    tile: bool = False,
    tile_direction: str = "horizontal",
    dense: bool = False,
    dense_density: int = 5,
) -> Image.Image:
    """
    显式水印：指定位置 / 平铺 / 密集型。

    参数：
        tile_direction: "horizontal" 横排 / "diagonal" 斜角45° / "vertical" 竖排
        dense:          True = 密集型（极小字体 + 极密排列 + 强制低透明度）
        dense_density:  1-10，越高越密集越不可见
    """
    image = image.convert("RGBA")

    if dense:
        # 密集型：字体极小，排列极密，透明度极低
        font_size = max(4, int(26 - dense_density * 2))  # density 1→24px, 10→6px
        text_img = _render_text(text, color, font_size)
        # 透明度上限随密度递减
        opacity = min(opacity, max(0.04, dense_density * 0.02))
        tile = True
        tile_spacing = max(2, int(22 - dense_density * 2))  # density 1→20px, 10→2px
    else:
        font_size = max(10, int(image.width * text_ratio))
        text_img = _render_text(text, color, font_size)
        tile_spacing = 40

    # 平铺方向 → 旋转文字
    if tile and tile_direction != "horizontal":
        angle = 45 if tile_direction == "diagonal" else 90
        text_img = text_img.rotate(angle, expand=True, resample=Image.BICUBIC)

    # 透明度
    if opacity < 1.0:
        alpha = text_img.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity))
        text_img = text_img.copy()
        text_img.putalpha(alpha)

    if tile:
        step_x = text_img.width + tile_spacing
        step_y = text_img.height + tile_spacing
        layer = _create_tile_layer(image.size, text_img, step_x, step_y)
    else:
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        x, y = _calculate_position(image.width, image.height, text_img.width, text_img.height, position, margin=20)
        layer.paste(text_img, (x, y))

    result = Image.alpha_composite(image, layer)
    # 释放中间大对象
    del layer, text_img
    return result


# ─── 盲水印 (DCT 中频鲁棒水印 + ECC + 重复嵌入 + 同步模板) ───

"""
使用 DCT 中频系数差分调制的鲁棒盲水印，替代旧的 LSB 方案。
特性：
  - 8x8 分块 DCT 变换，中频系数对嵌入
  - Reed-Solomon 前向纠错 (ECC)
  - 重复嵌入 + 多数投票
  - m-sequence 同步模板（抗裁剪、缩放检测）
  - 多尺度盲搜（抗缩放攻击）
  - 感知哈希兜底降级
"""

from backend.processors.dct_watermark import embed_watermark, extract_watermark
from backend.utils.perceptual_hash import compute_phash_hex, hamming_distance


def add_blind_watermark(
    image: Image.Image,
    text: str,
    strength: int = 16,
    use_subject_mask: bool = True,
) -> Image.Image:
    """
    鲁棒盲水印嵌入（主体区域自适应方案）

    新方案针对白底商品图：
      - 主体掩膜检测 → 仅在产品区域内嵌入
      - 确定性块乱序 → 分散冗余 → 抗裁剪
      - 自适应弱强度 → 平滑区域接近不可见
      - ECC + 重复嵌入 + 多数投票

    Args:
        image: 输入图片
        text: 待嵌入文本（建议 ≤ 32 字节）
        strength: 嵌入强度 (4-40)，默认 12。白底商品图建议 8-16
        use_subject_mask: 是否启用主体掩膜（跳过白底背景）
    Returns:
        含水印的 PIL Image (RGBA)
    """
    from backend.processors.dct_watermark import DCTWatermark, DCTWatermarkConfig

    config = DCTWatermarkConfig(
        strength=strength,
        use_subject_mask=use_subject_mask,
    )
    watermaker = DCTWatermark(config)
    result = watermaker.embed(image, text, strength)
    # 释放水印器中的预计算数组和 ECC 实例
    del watermaker
    return result


def extract_blind_watermark(image: Image.Image) -> str:
    """
    提取鲁棒盲水印

    优先 DCT 提取，若失败则降级到感知哈希匹配作为兜底。

    Returns:
        提取的文本（成功）或感知哈希标识（兜底）或空字符串（完全失败）
    """
    # 1. 尝试 DCT 水印提取
    text = extract_watermark(image)
    if text:
        return text

    # 2. DCT 提取失败 → 感知哈希兜底
    try:
        phash_hex = compute_phash_hex(image)
        return f"[PHASH:{phash_hex}]"
    except Exception:
        return ""
