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
    result = np.zeros((h, w, 4), dtype=np.uint8)
    result[:, :, :3] = np.where(mask, (out[:, :, :3] / out[:, :, 3:4] * 255), 0).astype(np.uint8)
    result[:, :, 3] = np.clip(out[:, :, 3] * 255, 0, 255).astype(np.uint8)

    return Image.fromarray(result, "RGBA")


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

    return Image.alpha_composite(image, layer)


# ─── 盲水印 (LSB) ───

_SECRET = [7, 2, 4, 1, 5, 3, 0, 6]


def _scramble_bit(bit: int, idx: int) -> int:
    return bit ^ (_SECRET[idx % len(_SECRET)] & 1)


def _bits_to_text(bits: list) -> str:
    chars = []
    for i in range(0, len(bits), 8):
        byte_bits = bits[i : i + 8]
        if len(byte_bits) < 8:
            break
        byte = sum(bits[j] << j for j in range(8))
        try:
            chars.append(chr(byte))
        except (ValueError, OverflowError):
            break
    return "".join(chars)


def add_blind_watermark(image: Image.Image, text: str) -> Image.Image:
    """将 text 的 UTF-8 二进制嵌入图片 RGB 最低位 (LSB)"""
    image = image.convert("RGBA")
    arr = np.array(image, dtype=np.uint8)

    data_bits = []
    for c in text.encode("utf-8"):
        for i in range(8):
            data_bits.append((c >> i) & 1)

    h, w = arr.shape[:2]
    total_bits = h * w * 3
    required = len(data_bits)

    if required > total_bits:
        raise ValueError(f"图片太小，无法嵌入 {required} bits（最多 {total_bits}）")

    bit_idx = 0
    flat = arr.flatten()
    for i in range(len(flat)):
        if bit_idx >= required:
            break
        channel = i % 3
        if channel == 3:
            continue
        orig = flat[i]
        bit = data_bits[bit_idx]
        bit = _scramble_bit(bit, bit_idx)
        new_val = (orig & 0xFE) | bit
        flat[i] = new_val
        bit_idx += 1

    arr = flat.reshape(h, w, 4)
    return Image.fromarray(arr, "RGBA")


def extract_blind_watermark(image: Image.Image) -> str:
    """从 LSB 中提取盲水印文本"""
    arr = np.array(image.convert("RGBA"), dtype=np.uint8)
    flat = arr.flatten()

    all_bits = []
    for i in range(len(flat)):
        channel = i % 3
        if channel == 3:
            continue
        all_bits.append(flat[i] & 1)

    descrambled = [_scramble_bit(b, i) for i, b in enumerate(all_bits)]

    null_pos = None
    for i in range(0, len(descrambled), 8):
        if i + 8 > len(descrambled):
            break
        byte = sum(descrambled[i + j] << j for j in range(8))
        if byte == 0:
            null_pos = i
            break

    if null_pos:
        descrambled = descrambled[:null_pos]

    return _bits_to_text(descrambled)
