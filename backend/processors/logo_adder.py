# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

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


def _calculate_position(
    img_w: int, img_h: int, logo_w: int, logo_h: int,
    position: str, margin: int = 20
) -> tuple:
    """计算 Logo 粘贴坐标"""
    pos_x_ratio, pos_y_ratio = POSITION_MAP.get(position, (1, 1))

    if pos_x_ratio == 0:
        x = margin
    elif pos_x_ratio == 1:
        x = img_w - logo_w - margin
    else:
        x = (img_w - logo_w) // 2

    if pos_y_ratio == 0:
        y = margin
    elif pos_y_ratio == 1:
        y = img_h - logo_h - margin
    else:
        y = (img_h - logo_h) // 2

    return (x, y)


def _apply_opacity(logo: Image.Image, opacity: float) -> Image.Image:
    """调整 Logo 透明度"""
    if opacity >= 1.0:
        return logo
    logo = logo.copy()
    alpha = logo.split()[3]
    alpha = alpha.point(lambda p: int(p * opacity))
    logo.putalpha(alpha)
    return logo


def _create_text_watermark(text: str, color: str = "#000000", font_size: int = 36) -> Image.Image:
    """创建文字水印图片"""
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except (IOError, OSError):
        font = ImageFont.load_default()

    # 计算文字尺寸
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0] + 20
    text_h = bbox[3] - bbox[1] + 20

    text_img = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_img)
    draw.text((10, 10), text, font=font, fill=color)
    return text_img


def _crop_transparent(logo: Image.Image) -> Image.Image:
    """裁剪 Logo 自身的透明边框，使 margin 从可见内容算起"""
    bbox = logo.getbbox()
    if bbox:
        return logo.crop(bbox)
    return logo


def add_logo(
    image: Image.Image,
    logo: Image.Image,
    position: str = "right-bottom",
    logo_ratio: float = 0.15,
    opacity: float = 0.8,
    margin: int = 20,
    tile: bool = False,
) -> Image.Image:
    """在图片上添加 Logo 水印"""
    image = image.convert("RGBA")
    logo = logo.convert("RGBA")
    logo = _crop_transparent(logo)

    # 按比例缩放 Logo
    target_logo_width = int(image.width * logo_ratio)
    ratio = target_logo_width / logo.width
    target_logo_height = int(logo.height * ratio)
    logo_resized = logo.resize((target_logo_width, target_logo_height), Image.LANCZOS)

    # 设置透明度
    logo_resized = _apply_opacity(logo_resized, opacity)

    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))

    if tile:
        # 平铺模式：对角线重复排列
        step_x = target_logo_width + margin * 3
        step_y = target_logo_height + margin * 3
        for y in range(-target_logo_height, image.height + target_logo_height, step_y):
            for x in range(-target_logo_width, image.width + target_logo_width, step_x):
                layer.paste(logo_resized, (x, y))
    else:
        x, y = _calculate_position(image.width, image.height, target_logo_width, target_logo_height, position, margin)
        layer.paste(logo_resized, (x, y))

    result = Image.alpha_composite(image, layer)
    # 释放中间大对象（layer 与 image 同尺寸）
    del layer, logo_resized
    return result


def add_text_watermark(
    image: Image.Image,
    text: str,
    position: str = "right-bottom",
    text_ratio: float = 0.05,
    opacity: float = 0.5,
    color: str = "#000000",
    tile: bool = False,
) -> Image.Image:
    """在图片上添加文字水印"""
    image = image.convert("RGBA")
    font_size = max(12, int(image.width * text_ratio))
    text_img = _create_text_watermark(text, color, font_size)
    result = add_logo(image, text_img, position=position, logo_ratio=0.3, opacity=opacity, tile=tile)
    del text_img
    return result
