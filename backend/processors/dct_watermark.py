# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

"""
Subject-Region Adaptive Blind Watermark
=======================================
针对白底商品图的鲁棒盲水印，从"全图固定强度块 DCT"升级为：
  1. 主体内候选区域掩膜 — 检测非白底区域，仅在主体内嵌入
  2. 短 ID 编码 — 优化短标识符（≤32 字节），更多重复 → 更强鲁棒
  3. 自适应弱嵌入 — 强度基于局部纹理动态缩放，平滑区域接近不可见
  4. 分散冗余 — 确定性块乱序，抗裁剪（空间连续区域丢失 → 比特分散）
  5. Reed-Solomon ECC — 前向纠错
  6. 感知哈希兜底 — DCT 提取失败时降级到 pHash 检索

核心原理：
  - 8x8 分块 DCT，在中频系数对中通过差分调制嵌入信息
  - 主体掩膜（亮度和色度阈值 + 形态学清理）跳过白底背景
  - 能量门控：在主体块中进一步精选高纹理块
  - 确定性块乱序（固定种子）实现空间分散冗余
  - 多路径提取：掩膜路径 + 无掩膜回退，兼容新旧格式

旧方案的根本问题：
  即使有能量门控，全图嵌入仍会在主体边缘的平滑白底过渡区产生可见伪影。
  新方案从几何上排除了白底区域，从根本上解决了可见性问题。
"""

import math
from typing import Optional
import numpy as np
from PIL import Image

from backend.utils.ecc import ECC

# ─── scipy 可选依赖（形态学清理用） ─────────────────────────────
try:
    from scipy.ndimage import binary_dilation, binary_erosion, label as _scipy_label
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


# ═══════════════════════════════════════════════════════════════════
# 预计算 8x8 DCT 矩阵
# ═══════════════════════════════════════════════════════════════════

def _make_dct_8x8():
    T = np.zeros((8, 8), dtype=np.float64)
    for i in range(8):
        c = np.sqrt(1.0 / 8) if i == 0 else np.sqrt(2.0 / 8)
        for j in range(8):
            T[i, j] = c * np.cos((2 * j + 1) * i * np.pi / 16)
    return T

_DCT_8 = _make_dct_8x8()
_IDCT_8 = _DCT_8.T  # 正交矩阵，转置即逆

# Broadcast-ready 4D views for vectorized block operations
_DCT_8_4D = _DCT_8[None, None, :, :]    # (1, 1, 8, 8)
_DCT_8T_4D = _DCT_8.T[None, None, :, :]  # (1, 1, 8, 8)
_IDCT_8_4D = _IDCT_8[None, None, :, :]
_IDCT_8T_4D = _IDCT_8.T[None, None, :, :]


# ═══════════════════════════════════════════════════════════════════
# 中频系数对（差分嵌入用，JPEG 量化感知）
# ═══════════════════════════════════════════════════════════════════
#
# 选对原则：
#   1. 同一对中的两个系数在 JPEG 标准亮度量化表的值必须接近（或相同），
#      这样 JPEG 压缩时两者被近似等同缩放，相对大小关系不易翻转。
#   2. 必须避免低频系数（row+col < 4），否则在平滑区域产生可见伪影。
#   3. 对数不宜太多，以减少每块的修改量 → 降低可见性。
#   4. 系数复用检查：所有 10 个坐标必须互不相同。
#   5. 能量门控作为额外保护：即使 row+col >= 4，在无纹理的平滑块中
#      也会完全跳过。
#
# 标准 JPEG 亮度量化表 (ITU-T T.81 K.1)：
#   16 11 10 16 24 40 51 61
#   12 12 14 19 26 58 60 55
#   14 13 16 24 40 57 69 56
#   14 17 22 29 51 87 80 62
#   18 22 37 56 68 109 103 77
#   24 35 55 64 81 104 113 92
#   49 64 78 87 103 121 120 101
#   72 92 95 98 112 100 103 99
#
# 嵌入策略: bit=1 → coef[p1] >= coef[p2] + delta
#           bit=0 → coef[p2] >= coef[p1] + delta

_MID_FREQ_PAIRS: list[tuple[tuple[int, int], tuple[int, int]]] = [
    ((5, 2), (5, 3)),   # q=55,64 — diff=9,  row+col=7,7  (高频，冗余)
    ((5, 1), (4, 2)),   # q=35,37 — diff=2,  row+col=6
    ((4, 1), (3, 2)),   # q=22,22 — diff=0,  row+col=5
    ((0, 4), (2, 3)),   # q=24,24 — diff=0,  row+col=4,5
    ((3, 1), (2, 2)),   # q=17,16 — diff=1,  row+col=4
]

# 同步模板使用的系数（默认关闭；若启用则使用此中高频系数，不与数据对冲突）
_SYNC_COEFF = (3, 3)  # Q=24 in JPEG luminance table


# ═══════════════════════════════════════════════════════════════════
# m-sequence 生成器（同步模板）
# ═══════════════════════════════════════════════════════════════════

def _generate_m_sequence(length: int = 63, seed: int = 42) -> np.ndarray:
    """
    用 LFSR 生成最大长度序列 (m-sequence)，输出双极性值 {-1, +1}
    63-bit 使用多项式 x^6 + x + 1
    127-bit 使用多项式 x^7 + x + 1
    """
    if length == 63:
        taps, reg_len = [0, 5], 6
    elif length == 127:
        taps, reg_len = [0, 6], 7
    else:
        taps, reg_len = [0, length.bit_length() - 2], length.bit_length()

    reg = seed & ((1 << reg_len) - 1)
    if reg == 0:
        reg = 1

    seq = []
    for _ in range(length):
        out = reg & 1
        fb = 0
        for t in taps:
            fb ^= (reg >> t) & 1
        reg = ((reg << 1) | fb) & ((1 << reg_len) - 1)
        seq.append(1.0 if out else -1.0)

    return np.array(seq, dtype=np.float64)


# ═══════════════════════════════════════════════════════════════════
# 向量化块操作
# ═══════════════════════════════════════════════════════════════════

def _channel_to_blocks(channel: np.ndarray, bh: int, bw: int) -> np.ndarray:
    """
    将 2D 通道切分为 8x8 块，返回 4D 数组 (bh, bw, 8, 8)
    向量化版本，无 Python 循环。
    """
    return channel[:bh*8, :bw*8].reshape(bh, 8, bw, 8).transpose(0, 2, 1, 3)


def _blocks_to_channel(blocks_4d: np.ndarray, h: int, w: int) -> np.ndarray:
    """
    将 4D 块数组 (bh, bw, 8, 8) 重组回 2D 通道
    向量化版本，无 Python 循环。
    """
    bh, bw = blocks_4d.shape[:2]
    return blocks_4d.transpose(0, 2, 1, 3).reshape(bh * 8, bw * 8)


def _batch_dct(blocks_4d: np.ndarray) -> np.ndarray:
    """
    对 4D 块数组批量做 DCT 正变换
    DCT: D @ block @ D.T   for each (bh, bw)
    """
    temp = _DCT_8_4D @ blocks_4d       # (1,1,8,8) @ (bh,bw,8,8) → (bh,bw,8,8)
    return temp @ _DCT_8T_4D           # (bh,bw,8,8) @ (1,1,8,8) → (bh,bw,8,8)


def _batch_idct(blocks_4d: np.ndarray) -> np.ndarray:
    """
    对 4D 块数组批量做 DCT 逆变换
    IDCT: D.T @ block @ D   for each (bh, bw)
    """
    temp = _IDCT_8_4D @ blocks_4d
    return temp @ _IDCT_8T_4D


# ═══════════════════════════════════════════════════════════════════
# 能量门控（DCT 域纹理度量）
# ═══════════════════════════════════════════════════════════════════

def _compute_ac_energy(dct_flat: np.ndarray) -> np.ndarray:
    """
    计算每个 8×8 DCT 块的 AC 能量（所有非 DC 系数的平方和）。
    dct_flat shape: (K, 8, 8)
    Returns: (K,) 每块的 AC 能量
    """
    ac = dct_flat.copy()
    ac[:, 0, 0] = 0.0  # 置零 DC
    return np.sum(ac ** 2, axis=(1, 2))


def _select_textured_blocks(
    ac_energy: np.ndarray,
    keep_pct: float,
    min_blocks: int,
    abs_floor: float = 5.0,
) -> np.ndarray:
    """
    选择纹理块用于嵌入 / 提取。

    使用混合阈值：
      - 绝对下限 (abs_floor)：块 AC 能量必须 >= 此值，确保平滑块被跳过
      - 百分位阈值：在通过绝对下限的块中，取最高 keep_pct%

    如果选出的块数不够 min_blocks，逐步降低约束至 5%。
    最坏情况下返回所有块的索引。

    Args:
        ac_energy: (K,) 每块的 AC 能量
        keep_pct: 保留百分比（如 40 = 保留能量最高的 40%）
        min_blocks: 最少需要的块数
        abs_floor: 绝对能量下限

    Returns:
        选中块的索引数组 (按原始块序排列)
    """
    pct = keep_pct
    floor = abs_floor

    while pct > 5:
        pct_threshold = np.percentile(ac_energy, 100.0 - pct)
        threshold = max(floor, pct_threshold)

        idx = np.where(ac_energy >= threshold)[0]
        if len(idx) >= min_blocks:
            return idx

        pct -= 5
        floor = max(0.0, floor * 0.5)

    idx = np.where(ac_energy >= 0.0)[0]
    if len(idx) >= min_blocks:
        return idx
    return np.arange(len(ac_energy))


# ═══════════════════════════════════════════════════════════════════
# 主体掩膜（白底商品图 → 检测非背景区域）
# ═══════════════════════════════════════════════════════════════════

def _compute_subject_mask(
    y: np.ndarray,
    cb: np.ndarray,
    cr: np.ndarray,
    luma_threshold: float = 230.0,
    chroma_tolerance: float = 15.0,
) -> np.ndarray:
    """
    检测主体（非白色背景）区域。

    对于白底商品图：
      - 白色 / 近白色像素：Y > luma_threshold 且色度接近 128
      - 主体像素：不满足白色条件的像素

    Args:
        y:  Y 通道 (H, W) float64，范围 [0, 255]
        cb: Cb 通道 (H, W) float64
        cr: Cr 通道 (H, W) float64
        luma_threshold: 亮度阈值，高于此值视为"白底候选"
        chroma_tolerance: 色度容差，|Cb/Cr - 128| 小于此值视为"无色度"

    Returns:
        (H, W) bool 数组，True = 主体像素
    """
    is_bright = y > luma_threshold
    is_low_saturation = (
        (np.abs(cb - 128.0) < chroma_tolerance) &
        (np.abs(cr - 128.0) < chroma_tolerance)
    )
    background = is_bright & is_low_saturation
    return ~background


def _morphological_cleanup(
    mask: np.ndarray,
    min_size: int = 100,
    edge_margin: int = 1,
) -> np.ndarray:
    """
    形态学清理主体掩膜：闭运算填补小孔、移除孤立噪点、边缘安全扩展。

    Args:
        mask: (H, W) bool 数组，True = 主体
        min_size: 保留的最小连通分量大小（像素），更小的被视为噪点移除
        edge_margin: 膨胀迭代次数，用于在主体边缘外扩安全边界

    Returns:
        (H, W) bool 数组，清理后的掩膜
    """
    if not _HAS_SCIPY:
        raise ImportError(
            "主体掩膜需要 scipy.ndimage 进行形态学操作。"
            "请运行: pip install scipy>=1.9.0"
        )

    struct_3x3 = np.ones((3, 3), dtype=bool)

    # 1. 闭运算：先膨胀后腐蚀，填补主体内部的细小孔洞
    cleaned = binary_dilation(mask, structure=struct_3x3, iterations=2)
    cleaned = binary_erosion(cleaned, structure=struct_3x3, iterations=2)

    # 2. 移除小连通分量（孤立噪点）
    labeled, n_features = _scipy_label(cleaned)
    if n_features > 0:
        component_sizes = np.bincount(labeled.ravel())
        # component_sizes[0] 是背景，跳过
        too_small = component_sizes < min_size
        too_small[0] = False  # 不移除背景
        cleaned[too_small[labeled]] = False

    # 3. 轻度膨胀 → 在主体边缘外扩安全边界，防止边缘块因掩膜不精确被误排除
    if edge_margin > 0:
        cleaned = binary_dilation(cleaned, structure=struct_3x3, iterations=edge_margin)

    return cleaned


def _compute_block_mask_overlap(
    mask: np.ndarray,
    bh: int,
    bw: int,
) -> np.ndarray:
    """
    计算每个 8×8 块与主体掩膜的重叠比例。

    Args:
        mask: (H, W) bool 主体掩膜
        bh: 垂直方向的 8×8 块数
        bw: 水平方向的 8×8 块数

    Returns:
        (bh * bw,) float64，每块中主体像素的占比 [0, 1]
    """
    h_blocks = bh * 8
    w_blocks = bw * 8
    mask_cropped = mask[:h_blocks, :w_blocks]

    # 重塑为 (bh, 8, bw, 8) → (bh, bw, 8, 8) → (bh*bw, 64)
    blocks = mask_cropped.reshape(bh, 8, bw, 8).transpose(0, 2, 1, 3)
    blocks_flat = blocks.reshape(bh * bw, 64)

    # 每块中 True（主体像素）的占比
    return blocks_flat.mean(axis=1).astype(np.float64)


def _select_subject_blocks(
    ac_energy: np.ndarray,
    mask_overlap: np.ndarray,
    keep_pct: float,
    min_blocks: int,
    abs_floor: float,
    mask_threshold: float = 0.3,
) -> np.ndarray:
    """
    选择同时满足主体掩膜覆盖和纹理条件的块。

    两阶段筛选：
      1. 掩膜门控：block 的主体覆盖率 >= mask_threshold
      2. 能量门控：在通过掩膜门控的块中，取 AC 能量最高的 keep_pct%

    若选出的块数不足 min_blocks，按序放宽约束：
      先降低 mask_threshold（0.3 → 0.2 → 0.1 → 0.0）
      再降低 keep_pct 和 abs_floor
    最终回退到仅能量门控（等价于全图模式）。

    Args:
        ac_energy: (K,) 每块的 AC 能量
        mask_overlap: (K,) 每块的主体覆盖率
        keep_pct: 能量门控保留百分比
        min_blocks: 最少需要的块数
        abs_floor: AC 能量绝对下限
        mask_threshold: 主体覆盖率下限

    Returns:
        选中块的索引数组 (按原始块序排列)
    """
    m_thresh = mask_threshold
    pct = keep_pct
    floor = abs_floor

    # 外层：逐渐放宽掩膜阈值
    while m_thresh >= 0.0:
        # 内层：在当前掩膜阈值下，逐渐放宽能量约束
        inner_pct = pct
        inner_floor = floor
        while inner_pct > 5:
            pct_threshold = np.percentile(ac_energy, 100.0 - inner_pct)
            energy_threshold = max(inner_floor, pct_threshold)

            idx = np.where(
                (ac_energy >= energy_threshold) &
                (mask_overlap >= m_thresh)
            )[0]

            if len(idx) >= min_blocks:
                return idx

            inner_pct -= 5
            inner_floor = max(0.0, inner_floor * 0.5)

        m_thresh -= 0.1

    # 最终回退：忽略掩膜门控，仅用能量门控
    return _select_textured_blocks(ac_energy, keep_pct, min_blocks, abs_floor)


# ═══════════════════════════════════════════════════════════════════
# 确定性块乱序（分散冗余）
# ═══════════════════════════════════════════════════════════════════

def _get_embed_order(all_blocks: int, selected_idx: np.ndarray, seed: int = 42) -> np.ndarray:
    """
    确定性嵌入顺序：先生成全图块排列，再筛选选中块。

    即使提取时选中块数与嵌入时不同（例如 JPEG 导致掩膜漂移），
    共同块的相对顺序也完全一致（只取决于全图排列和块的全局索引）。

    Args:
        all_blocks: 全图 8×8 块总数 (bh * bw)
        selected_idx: 选中的块全局索引数组 (N,)
        seed: 乱序种子

    Returns:
        (N,) int64，按嵌入顺序排列的选中块全局索引
    """
    rng = np.random.RandomState(seed)
    full_perm = rng.permutation(all_blocks)  # 全图块排列
    selected_set = set(selected_idx.tolist())
    # 按全图排列顺序筛出选中块
    embed_order = np.array([i for i in full_perm if i in selected_set], dtype=np.int64)
    return embed_order


# ═══════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════

class DCTWatermarkConfig:
    """DCT 水印超参数"""

    def __init__(
        self,
        # ── 嵌入强度 ──
        strength: int = 16,
        # ── ECC ──
        ecc_symbols: int = 10,
        # ── 重复嵌入 ──
        repeat_min: int = 3,
        # ── 同步模板（默认关闭） ──
        sync_length: int = 0,
        # ── 多尺度盲搜 ──
        scale_search: Optional[list[float]] = None,
        # ── 能量门控 ──
        energy_keep_pct: float = 40.0,
        # ── 主体掩膜 ──
        use_subject_mask: bool = True,
        mask_overlap_threshold: float = 0.3,
        subject_luma_threshold: float = 230.0,
        subject_chroma_tolerance: float = 15.0,
        mask_min_size: int = 100,
        mask_edge_margin: int = 1,
    ):
        # 嵌入强度：白底商品图建议 8-16（默认 12），旧版全图模式建议 20-35
        self.strength = strength
        self.ecc_symbols = ecc_symbols
        self.repeat_min = repeat_min
        self.sync_length = sync_length
        self.scale_search = scale_search or [1.0, 0.9, 1.1, 0.8, 1.2]
        self.energy_keep_pct = energy_keep_pct

        # 主体掩膜参数
        self.use_subject_mask = use_subject_mask
        self.mask_overlap_threshold = mask_overlap_threshold
        self.subject_luma_threshold = subject_luma_threshold
        self.subject_chroma_tolerance = subject_chroma_tolerance
        self.mask_min_size = mask_min_size
        self.mask_edge_margin = mask_edge_margin


# ═══════════════════════════════════════════════════════════════════
# 主类
# ═══════════════════════════════════════════════════════════════════

class DCTWatermark:
    """Subject-Region Adaptive DCT 盲水印嵌入器 / 提取器"""

    def __init__(self, config: Optional[DCTWatermarkConfig] = None):
        self.config = config or DCTWatermarkConfig()
        self._ecc = ECC(self.config.ecc_symbols)
        self._sync_template = _generate_m_sequence(self.config.sync_length) if self.config.sync_length > 0 else np.array([])
        self._pairs = _MID_FREQ_PAIRS

        # 预提取 pair 坐标用于向量化索引
        self._p1_rows = np.array([p[0][0] for p in self._pairs])
        self._p1_cols = np.array([p[0][1] for p in self._pairs])
        self._p2_rows = np.array([p[1][0] for p in self._pairs])
        self._p2_cols = np.array([p[1][1] for p in self._pairs])

    # ─── 公共接口 ──────────────────────────────────────────

    def embed(self, image: Image.Image, text: str, strength: Optional[int] = None) -> Image.Image:
        """
        将 text 嵌入图片（DCT 中频鲁棒水印）。

        新方案（use_subject_mask=True，默认）：
          1. 检测主体掩膜（白底 → 跳过背景）
          2. 在主体块中按 AC 能量精选嵌入位置
          3. 确定性乱序 → 分散冗余 → 抗裁剪
          4. 自适应弱强度 → 纹理强处适度嵌入，平滑处接近不可见

        旧方案（use_subject_mask=False）：
          回退到全图能量门控模式，兼容旧版嵌入。

        注意：嵌入在 RGB 亮度空间（Y = 0.299R + 0.587G + 0.114B）中进行，
        避免 PIL YCbCr↔RGB 转换的 YCbCr 往返误差。
        修改 RGB 时均匀调整三通道 (delta_R = delta_G = delta_B = delta_Y)，
        近似保持色度不变。

        Args:
            image: 输入 PIL Image
            text:  待嵌入的文本（建议 ≤ 32 字节以最大化重复次数）
            strength: 可选，覆盖配置的强度
        Returns:
            含水印的 PIL Image (RGBA)
        """
        s = strength if strength is not None else self.config.strength
        data = text.encode("utf-8")

        # 1. ECC 编码
        ecc_data = self._ecc.encode(data)
        bits = self._bytes_to_bits(ecc_data)

        # 2. 转为 RGB 浮点数组
        rgb = np.array(image.convert("RGB"), dtype=np.float64)
        h, w = rgb.shape[:2]
        bh, bw = h // 8, w // 8
        if bh < 2 or bw < 2:
            raise ValueError(f"图片太小 ({h}x{w})，至少需要 16x16")

        # 3. 从 RGB 计算亮度 Y（ITU-R BT.601，与 PIL YCbCr 一致）
        Y = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]

        # 4. Y 通道 → 4D 块 → DCT 域
        blocks = _channel_to_blocks(Y, bh, bw)
        dct_blocks = _batch_dct(blocks)

        # 5. AC 能量计算（所有块）
        dct_flat = dct_blocks.reshape(bh * bw, 8, 8)
        ac_energy = _compute_ac_energy(dct_flat)

        n_pairs = len(self._pairs)
        min_blocks = (len(bits) * self.config.repeat_min + n_pairs - 1) // n_pairs
        # 主体掩膜已排除白底，能量门控排除中低纹理块
        # abs_floor 必须足够高以确保 DCT 修改在 uint8 量化后仍可提取
        # 经验值：20 是安全下限（对应平均像素变化 ≈ 1.0，刚好跨过 uint8 LSB）
        abs_floor = max(20.0, s * 0.8)

        # 6. 块选择：掩膜门控 或 纯能量门控
        if self.config.use_subject_mask:
            # ── 新方案：主体掩膜 + 能量门控 + 乱序 ──
            # 6a. 从 RGB 计算 YCbCr（仅用于掩膜检测）
            Cb = 128.0 - 0.168736 * rgb[:, :, 0] - 0.331264 * rgb[:, :, 1] + 0.5 * rgb[:, :, 2]
            Cr = 128.0 + 0.5 * rgb[:, :, 0] - 0.418688 * rgb[:, :, 1] - 0.081312 * rgb[:, :, 2]

            # 6b. 检测主体掩膜
            subject_mask = _compute_subject_mask(
                Y, Cb, Cr,
                luma_threshold=self.config.subject_luma_threshold,
                chroma_tolerance=self.config.subject_chroma_tolerance,
            )
            subject_mask = _morphological_cleanup(
                subject_mask,
                min_size=self.config.mask_min_size,
                edge_margin=self.config.mask_edge_margin,
            )

            # 6c. 计算块级掩膜覆盖率
            mask_overlap = _compute_block_mask_overlap(subject_mask, bh, bw)

            # 6d. 选择主体内的高纹理块
            selected_idx = _select_subject_blocks(
                ac_energy, mask_overlap,
                keep_pct=self.config.energy_keep_pct,
                min_blocks=min_blocks,
                abs_floor=abs_floor,
                mask_threshold=self.config.mask_overlap_threshold,
            )

            # 6e. 确定性乱序 → 分散冗余
            embed_order_idx = _get_embed_order(bh * bw, selected_idx, seed=42)
        else:
            # ── 旧方案：纯能量门控（兼容模式） ──
            selected_idx = _select_textured_blocks(
                ac_energy,
                self.config.energy_keep_pct,
                min_blocks,
                abs_floor=abs_floor,
            )
            embed_order_idx = selected_idx  # 无乱序

        n_selected = len(embed_order_idx)
        total_capacity = n_selected * n_pairs

        if len(bits) > total_capacity:
            raise ValueError(
                f"水印数据过长 ({len(bits)} bits)，"
                f"选中块容量为 {total_capacity} bits"
            )

        # 7. 重复填充 + 嵌入
        repeats = (total_capacity + len(bits) - 1) // len(bits)
        full_bits = (bits * repeats)[:total_capacity]
        bits_arr = np.array(full_bits, dtype=np.int64).reshape(n_selected, n_pairs)

        # 嵌入到乱序后的块（或原始顺序，取决于模式）
        embed_dct = dct_flat[embed_order_idx].copy()
        self._embed_data_bits_flat(embed_dct, bits_arr, s)
        dct_flat[embed_order_idx] = embed_dct

        # 8. 逆 DCT 得到修改后的亮度 Y'
        Y_modified = _blocks_to_channel(
            _batch_idct(dct_flat.reshape(bh, bw, 8, 8)),
            h, w,
        )

        # 9. 计算亮度变化 ΔY，均匀调整 RGB 三通道（保持色度近似不变）
        delta_Y = Y_modified - Y
        rgb[:, :, 0] += delta_Y
        rgb[:, :, 1] += delta_Y
        rgb[:, :, 2] += delta_Y

        # 10. 钳位并转回 PIL Image
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        result = Image.fromarray(rgb, "RGB").convert("RGBA")

        # 释放中间大数组（rgb float64、Y、Cb、Cr、块数组、ΔY 等）
        del rgb, Y, blocks, dct_blocks, dct_flat, ac_energy
        del Y_modified, delta_Y, embed_dct, bits_arr
        if self.config.use_subject_mask:
            del Cb, Cr, subject_mask, mask_overlap

        return result

    def extract(self, image: Image.Image, strength: Optional[int] = None) -> Optional[str]:
        """
        从图片中提取盲水印。自动多尺度盲搜以抗缩放。

        提取策略（多路径，按优先级）：
          Path A: 主体掩膜 + 乱序提取（新格式）
          Path B: 无掩膜全块提取（旧格式兼容）
          Path C: 能量门控提取（旧格式兼容）
          取置信度最高的结果。

        Args:
            image: 待提取的图片
            strength: 可选，覆盖配置强度
        Returns:
            提取的文本，失败返回 None
        """
        s = strength if strength is not None else self.config.strength

        # 先在原始尺度上提取（最可能成功）
        result = self._try_extract(image, s)
        if result is not None:
            return result[1]

        # 失败后再尝试其他尺度（抗缩放）
        for scale in self.config.scale_search:
            if abs(scale - 1.0) < 0.01:
                continue
            new_w = max(16, int(image.width * scale))
            new_h = max(16, int(image.height * scale))
            scaled = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
            result = self._try_extract(scaled, s)
            if result is not None:
                return result[1]

        return None

    # ─── 向量化嵌入（1D 块数组版本，操作 (K, 8, 8)） ────────

    def _embed_sync_template_flat(self, dct_flat: np.ndarray, strength: float):
        """
        向量化嵌入同步模板到 1D DCT 块数组。
        dct_flat shape: (K, 8, 8)
        """
        tpl = self._sync_template
        tpl_len = len(tpl)
        K = dct_flat.shape[0]

        r, c = _SYNC_COEFF
        step = max(1.0, strength * 0.4)

        coeffs = dct_flat[:, r, c]  # (K,)
        q_vals = coeffs / step
        targets = np.round(q_vals).astype(np.int64)

        idx = np.arange(K) % tpl_len
        t_bits = tpl[idx]  # (K,) 双极性 {-1, +1}

        is_odd = (targets % 2) == 1
        needs_odd = t_bits > 0
        mask = (needs_odd & ~is_odd) | (~needs_odd & is_odd)
        direction = np.where(q_vals < targets, 1, -1)
        targets[mask] += direction[mask]
        targets = np.where(targets == 0, 1, targets)

        dct_flat[:, r, c] = targets * step

    def _embed_data_bits_flat(self, dct_flat: np.ndarray, bits_arr: np.ndarray, strength: float):
        """
        向量化嵌入数据 bits 到 1D DCT 块数组的中频系数对中。
        dct_flat shape: (K, 8, 8)
        bits_arr shape: (K, n_pairs)

        使用自适应强度：基于每块每对系数的平均幅值动态缩放 delta。
        平滑块（系数接近 0）→ delta 缩小（避免可见伪影）
        纹理块（系数较大）→ delta 接近全量（保证鲁棒性）

        注意：主体掩膜已在上层跳过白底区域，
        此处的自适应强度是额外的安全网——进一步弱化主体内部平滑区域的嵌入。
        """
        K = dct_flat.shape[0]
        n_pairs = bits_arr.shape[1]

        p1_val = dct_flat[:, self._p1_rows, self._p1_cols]  # (K, n_pairs)
        p2_val = dct_flat[:, self._p2_rows, self._p2_cols]

        diff = p1_val - p2_val
        base_delta = float(strength)

        # 自适应强度：基于每块每对系数的平均幅值
        coeff_mag = (np.abs(p1_val) + np.abs(p2_val)) / 2.0  # (K, n_pairs)

        # 映射: mag→0 时 delta=0.55×base, mag→15 时 delta≈0.78×base,
        #       mag→50 时 delta≈0.94×base
        # 0.55× 地板确保单次 RGB→亮度往返 + JPEG q85 仍可提取
        ratio = coeff_mag / 30.0
        adaptive_scale = 0.55 + 0.45 * (1.0 - 1.0 / (1.0 + 4.0 * ratio))
        delta = base_delta * adaptive_scale

        adjust = np.zeros_like(diff)
        mask1 = (bits_arr == 1) & (diff < delta)
        adjust[mask1] = (delta[mask1] - diff[mask1]) / 2.0
        mask0 = (bits_arr == 0) & (diff > -delta)
        adjust[mask0] = -(delta[mask0] + diff[mask0]) / 2.0

        dct_flat[:, self._p1_rows, self._p1_cols] += adjust
        dct_flat[:, self._p2_rows, self._p2_cols] -= adjust

    # ─── 向量化提取 ────────────────────────────────────────

    def _try_extract(self, image: Image.Image, strength: float) -> Optional[tuple[int, str]]:
        """
        向量化单尺度提取，多路径搜索：
          Path A: 主体掩膜 + 乱序（新格式，RGB 亮度空间）
          Path B: 无掩膜全块（旧格式兼容，RGB 亮度空间）
          Path C: 能量门控（旧格式兼容，RGB 亮度空间）
          Path D: YCbCr 空间提取（旧格式兼容，PIL YCbCr）

        比较各路径得分，返回置信度最高的结果。

        注意：
          - Path A/B/C 在 RGB 亮度空间中提取（与新嵌入方案一致）
          - Path D 在 PIL YCbCr 空间中提取（与旧嵌入方案一致，向后兼容）
          - 各路径尝试多个 abs_floor 以匹配不同嵌入参数
        """
        rgb = np.array(image.convert("RGB"), dtype=np.float64)
        h, w = rgb.shape[:2]

        # 从 RGB 计算亮度 Y（与嵌入时相同的 ITU-R BT.601 公式）
        Y_full = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]

        # 预计算主体掩膜（所有偏移共用，基于完整图像）
        subject_mask = None
        has_mask = False
        if self.config.use_subject_mask:
            try:
                Cb = 128.0 - 0.168736 * rgb[:, :, 0] - 0.331264 * rgb[:, :, 1] + 0.5 * rgb[:, :, 2]
                Cr = 128.0 + 0.5 * rgb[:, :, 0] - 0.418688 * rgb[:, :, 1] - 0.081312 * rgb[:, :, 2]
                subject_mask = _compute_subject_mask(
                    Y_full, Cb, Cr,
                    luma_threshold=self.config.subject_luma_threshold,
                    chroma_tolerance=self.config.subject_chroma_tolerance,
                )
                subject_mask = _morphological_cleanup(
                    subject_mask,
                    min_size=self.config.mask_min_size,
                    edge_margin=self.config.mask_edge_margin,
                )
                has_mask = True
            except ImportError:
                has_mask = False

        # 按照"最可能"的顺序尝试偏移
        offsets_to_try = [(0, 0), (4, 4), (0, 4), (4, 0), (2, 2), (6, 6)]

        for y_off, x_off in offsets_to_try:
            bh = (h - y_off) // 8
            bw = (w - x_off) // 8
            if bh < 2 or bw < 2:
                continue
            ch = Y_full[y_off:, x_off:]
            blocks = _channel_to_blocks(ch, bh, bw)
            dct_blocks = _batch_dct(blocks)
            dct_flat = dct_blocks.reshape(bh * bw, 8, 8)

            best_result = None  # (score, text)

            # ── Path A: 主体掩膜 + 乱序提取（新格式） ──
            if has_mask and subject_mask is not None:
                mask_cropped = subject_mask[y_off:y_off + bh * 8, x_off:x_off + bw * 8]
                mask_overlap = _compute_block_mask_overlap(mask_cropped, bh, bw)
                ac_energy = _compute_ac_energy(dct_flat)

                # 尝试多个 abs_floor + keep_pct：覆盖不同嵌入参数
                for abs_floor in [20, 30]:
                    for keep_pct in [40, 30]:
                        selected_idx = _select_subject_blocks(
                            ac_energy, mask_overlap,
                            keep_pct=keep_pct,
                            min_blocks=16,
                            abs_floor=abs_floor,
                            mask_threshold=self.config.mask_overlap_threshold,
                        )
                        n_sel = len(selected_idx)
                        if n_sel < 16:
                            continue
                        shuffled_idx = _get_embed_order(bh * bw, selected_idx, seed=42)

                        p1_val = dct_flat[shuffled_idx][:, self._p1_rows, self._p1_cols]
                        p2_val = dct_flat[shuffled_idx][:, self._p2_rows, self._p2_cols]
                        bits_masked = (p1_val >= p2_val).astype(np.int64).ravel()

                        if len(bits_masked) >= 64:
                            r = self._decode_with_vote(bits_masked, n_sel, len(self._pairs))
                            if r is not None:
                                if best_result is None or r[0] > best_result[0]:
                                    best_result = r

            # ── Path B: 无掩膜全块提取（旧格式兼容，RGB 亮度） ──
            p1_all = dct_blocks[:, :, self._p1_rows, self._p1_cols]
            p2_all = dct_blocks[:, :, self._p2_rows, self._p2_cols]
            bits_all = (p1_all >= p2_all).astype(np.int64).ravel()
            if len(bits_all) >= 64:
                r = self._decode_with_vote(bits_all, bh * bw, len(self._pairs))
                if r is not None:
                    if best_result is None or r[0] > best_result[0]:
                        best_result = r

            # ── Path C: 能量门控提取（旧格式兼容，RGB 亮度） ──
            ac_energy_c = _compute_ac_energy(dct_flat)
            for abs_floor in [20, 30]:
                for keep_pct in [40, 30]:
                    selected_idx_c = _select_textured_blocks(
                        ac_energy_c, keep_pct, min_blocks=20, abs_floor=abs_floor
                    )
                    n_sel_c = len(selected_idx_c)
                    if n_sel_c < 20:
                        continue

                    p1_val = dct_flat[selected_idx_c][:, self._p1_rows, self._p1_cols]
                    p2_val = dct_flat[selected_idx_c][:, self._p2_rows, self._p2_cols]
                    bits_gated = (p1_val >= p2_val).astype(np.int64).ravel()

                    if len(bits_gated) >= 64:
                        r = self._decode_with_vote(bits_gated, n_sel_c, len(self._pairs))
                        if r is not None:
                            if best_result is None or r[0] > best_result[0]:
                                best_result = r

            if best_result is not None:
                return best_result

        return None

    def _decode_with_vote(self, extracted_bits: np.ndarray, n_blocks: int,
                          n_pairs: int) -> Optional[tuple[int, str]]:
        """
        多数投票 + RS 译码。

        从长到短搜索消息周期（长消息误报率远低于短消息），
        过滤 ECC 垃圾解碼（全零 / 过多不可打印字符），
        取置信度最高的结果。
        """
        total_bits = len(extracted_bits)
        candidates = []

        # 从长到短搜索：长消息误报率指数级低于短消息
        max_bytes = min(255, total_bits // 8)
        for seg_bytes in range(max_bytes, 0, -1):
            seg_bits = seg_bytes * 8
            rep = total_bits // seg_bits
            if rep < 1:
                continue

            # 多数投票
            seg = extracted_bits[:seg_bits * rep].reshape(rep, seg_bits)
            vote_sum = seg.sum(axis=0)
            voted = (vote_sum > rep // 2).astype(np.int64)

            avg_margin = float(np.abs(vote_sum / rep - 0.5).mean())

            # RS 译码
            byte_data = self._bits_to_bytes(voted.tolist())
            decoded = self._ecc.decode(byte_data)
            if decoded is None:
                continue

            # 过滤垃圾解碼
            if len(decoded) == 0:
                continue
            if all(b == 0 for b in decoded):
                continue

            # 严格 UTF-8 解码：拒绝非 UTF-8 字节序列
            try:
                text = decoded.decode("utf-8")
            except UnicodeDecodeError:
                continue

            # 过滤不可打印字符过多（>30%）的解码
            printable = sum(1 for c in text if c.isprintable())
            if printable / max(len(text), 1) < 0.7:
                continue

            # 评分：置信度为主，消息长度微调（长消息误报率低，给小幅加分）
            score = avg_margin * 100 + min(seg_bytes, 100) * 0.03
            candidates.append((-score, avg_margin, seg_bytes, text))

        if candidates:
            candidates.sort()
            _, margin, seg_bytes, text = candidates[0]
            return int(margin * 100), text

        return None

    def _detect_sync_template_vec(self, dct_blocks: np.ndarray) -> float:
        """
        向量化同步模板互相关检测，返回置信度 [0, 1]

        注意：当前默认关闭同步模板嵌入 (sync_length=0)，
        此方法保留供未来启用同步后使用。
        """
        if len(self._sync_template) == 0:
            return 0.0

        r, c = _SYNC_COEFF
        step = max(1.0, self.config.strength * 0.4)
        coeffs = dct_blocks[:, :, r, c].ravel()
        q_vals = np.round(coeffs / step).astype(np.int64)
        seq = np.where(q_vals % 2 == 1, 1.0, -1.0)

        tpl = self._sync_template
        tpl_len = len(tpl)
        n_seq = len(seq)

        best_corr = 0.0
        max_shift = min(tpl_len, n_seq)
        for shift in range(max_shift):
            n = n_seq - shift
            if n <= 0:
                break
            corr = np.dot(seq[shift:], np.tile(tpl, (n + tpl_len - 1) // tpl_len)[:n])
            corr /= n
            if corr > best_corr:
                best_corr = corr

        return max(0.0, best_corr / 1.0)

    # ─── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def _bytes_to_bits(data: bytes) -> list[int]:
        """字节 → 位列表 (MSB first)"""
        return [(byte >> (7 - i)) & 1 for byte in data for i in range(8)]

    @staticmethod
    def _bits_to_bytes(bits: list[int]) -> bytes:
        """位列表 → 字节 (MSB first)"""
        byte_list = []
        for i in range(0, len(bits) - 7, 8):
            byte = 0
            for j in range(8):
                byte = (byte << 1) | (bits[i + j] & 1)
            byte_list.append(byte)
        return bytes(byte_list)


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════

_DEFAULT_WATERMARKER = DCTWatermark()


def embed_watermark(image: Image.Image, text: str, strength: int = 16) -> Image.Image:
    """嵌入 DCT 鲁棒盲水印（默认使用主体掩膜方案）"""
    return _DEFAULT_WATERMARKER.embed(image, text, strength)


def extract_watermark(image: Image.Image) -> Optional[str]:
    """提取 DCT 鲁棒盲水印（自动多路径搜索，兼容新旧格式）"""
    return _DEFAULT_WATERMARKER.extract(image)
