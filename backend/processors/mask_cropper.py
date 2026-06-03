# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

"""
蒙版裁切：用户手绘灰度蒙版，白色像素的最小包围矩形作为裁切框。
- 白色 (R/G/B > 128) = 保留
- 黑色 = 丢弃
- 全白 / 全黑 / bbox 覆盖全图 → return image（无变化）
"""
import io

import numpy as np
from PIL import Image


def apply_mask_crop(image: Image.Image, mask_bytes: bytes) -> Image.Image:
    """按蒙版白色像素的最小包围矩形裁切图片。

    Args:
        image:     输入图片（不会被修改；当 mask_bytes 为空或全白/全黑时直接返回）
        mask_bytes: 用户上传的 PNG 蒙版字节

    Returns:
        裁切后的新 Image；全白/全黑/无变化场景下返回原图。
    """
    if not mask_bytes:
        return image

    mask_img = Image.open(io.BytesIO(mask_bytes))
    # 任意模式都转成 L 单通道再做 bbox 分析
    if mask_img.mode != "L":
        mask_img = mask_img.convert("L")
    # 蒙版尺寸对齐到图像尺寸（NEAREST 保留硬边）
    if mask_img.size != image.size:
        mask_img = mask_img.resize(image.size, Image.NEAREST)

    arr = np.asarray(mask_img, dtype=np.uint8)
    ys, xs = np.where(arr > 128)
    if ys.size == 0 or xs.size == 0:
        # 没有任何白色像素 → no-op
        return image

    left = int(xs.min())
    top = int(ys.min())
    right = int(xs.max()) + 1
    bottom = int(ys.max()) + 1
    W, H = image.size
    # bbox 覆盖全图 → no-op（保留与「不裁切」等价的字节输出）
    if left <= 0 and top <= 0 and right >= W and bottom >= H:
        return image
    return image.crop((left, top, right, bottom))
