# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

"""
感知哈希（pHash）模块
基于 DCT 的感知哈希，用于图像相似度匹配。
作为盲水印提取失败时的兜底方案。
"""

import numpy as np
from PIL import Image

# 预计算 32x32 DCT 矩阵
def _make_dct_matrix_32():
    N = 32
    T = np.zeros((N, N), dtype=np.float64)
    for i in range(N):
        c = np.sqrt(1.0 / N) if i == 0 else np.sqrt(2.0 / N)
        for j in range(N):
            T[i, j] = c * np.cos((2 * j + 1) * i * np.pi / (2 * N))
    return T

_DCT_32 = _make_dct_matrix_32()
_DCT_32_T = _DCT_32.T


def compute_phash(image: Image.Image, hash_size: int = 8, highfreq_factor: int = 4) -> int:
    """
    计算图像的 DCT 感知哈希（64-bit）
    Args:
        image: PIL Image
        hash_size: 输出哈希的位数（8 → 64-bit）
        highfreq_factor: DCT 前缩放因子（越大精度越高）
    Returns:
        64-bit 整数哈希值
    """
    img_size = hash_size * highfreq_factor  # 32
    # 1. 转为灰度 + 缩放到 32x32
    img = image.convert("L").resize((img_size, img_size), Image.Resampling.LANCZOS)
    pixels = np.array(img, dtype=np.float64)

    # 2. 应用 DCT
    dct = _DCT_32 @ pixels @ _DCT_32_T

    # 3. 取左上角 hash_size x hash_size 低频分量
    dct_low = dct[:hash_size, :hash_size]

    # 4. 计算中值，生成二进制哈希
    median = np.median(dct_low)
    bits = (dct_low > median).flatten()

    # 5. 打包成 64-bit 整数
    result = 0
    for b in bits:
        result = (result << 1) | int(b)
    return result


def hamming_distance(h1: int, h2: int) -> int:
    """计算两个感知哈希之间的汉明距离"""
    xor = h1 ^ h2
    # 计算 popcount
    dist = 0
    while xor:
        dist += xor & 1
        xor >>= 1
    return dist


def match(h1: int, h2: int, threshold: int = 10) -> bool:
    """
    判断两个感知哈希是否匹配
    Args:
        h1, h2: 64-bit 哈希值
        threshold: 最大允许汉明距离（越小越严格）
                   一般 0-5 高度相似，6-10 可能相似，>10 不同
    Returns:
        True 匹配 / False 不匹配
    """
    return hamming_distance(h1, h2) <= threshold


def compute_phash_hex(image: Image.Image) -> str:
    """返回 16 进制字符串形式的感知哈希"""
    return f"{compute_phash(image):016x}"


class PerceptualHasher:
    """感知哈希管理器，可缓存已注册的哈希用于兜底匹配"""

    def __init__(self):
        self._registry: dict[str, dict] = {}  # hex_hash -> metadata

    def register(self, image_id: str, image: Image.Image, metadata: dict | None = None) -> int:
        """注册一张图片的感知哈希"""
        ph = compute_phash(image)
        self._registry[f"{ph:016x}"] = {
            "image_id": image_id,
            "hash": ph,
            "metadata": metadata or {},
        }
        return ph

    def lookup(self, image: Image.Image, threshold: int = 10) -> dict | None:
        """查找最匹配的注册图片"""
        ph = compute_phash(image)
        best = None
        best_dist = threshold + 1
        for entry in self._registry.values():
            dist = hamming_distance(ph, entry["hash"])
            if dist < best_dist:
                best_dist = dist
                best = entry
        if best is not None:
            return {
                "matched_id": best["image_id"],
                "distance": best_dist,
                "metadata": best["metadata"],
            }
        return None
