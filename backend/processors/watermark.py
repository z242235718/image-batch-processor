import io
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
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except (IOError, OSError):
        font = ImageFont.load_default()
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0] + 20
    text_h = bbox[3] - bbox[1] + 20
    text_img = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_img)
    draw.text((10, 10), text, font=font, fill=color)
    return text_img


def add_text_watermark_sparse(
    image: Image.Image,
    text: str,
    position: str = "right-bottom",
    text_ratio: float = 0.04,
    opacity: float = 0.3,
    color: str = "#FFFFFF",
) -> Image.Image:
    """显式水印 - 疏散模式：文字小而淡，不遮挡主体"""
    image = image.convert("RGBA")
    font_size = max(10, int(image.width * text_ratio))
    text_img = _render_text(text, color, font_size)

    text_img_resized = text_img
    if opacity < 1.0:
        alpha = text_img_resized.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity))
        text_img_resized = text_img_resized.copy()
        text_img_resized.putalpha(alpha)

    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    x, y = _calculate_position(image.width, image.height, text_img_resized.width, text_img_resized.height, position, margin=30)
    layer.paste(text_img_resized, (x, y))
    return Image.alpha_composite(image, layer)


def add_text_watermark_dense(
    image: Image.Image,
    text: str,
    position: str = "right-bottom",
    text_ratio: float = 0.12,
    opacity: float = 0.6,
    color: str = "#FFFFFF",
) -> Image.Image:
    """显式水印 - 密集模式：文字大而醒目，压在角落"""
    image = image.convert("RGBA")
    font_size = max(20, int(image.width * text_ratio))
    text_img = _render_text(text, color, font_size)

    if opacity < 1.0:
        alpha = text_img.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity))
        text_img = text_img.copy()
        text_img.putalpha(alpha)

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