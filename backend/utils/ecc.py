# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

"""
Reed-Solomon 纠错编码模块
用于盲水印的 ECC（前向纠错），增强抗 JPEG 压缩和噪声的鲁棒性
"""

from reedsolo import RSCodec, ReedSolomonError


class ECC:
    """Reed-Solomon 纠错编码封装"""

    def __init__(self, nsym: int = 12):
        """
        Args:
            nsym: RS 纠错符号数（每 255 字节块），可纠正 nsym//2 个符号错误
                  推荐值：8-16，越大纠错越强但数据容量越小
        """
        self.nsym = nsym
        self._codec = RSCodec(nsym)

    def encode(self, data: bytes) -> bytes:
        """
        Reed-Solomon 编码，附加纠错校验码
        Args:
            data: 原始字节数据
        Returns:
            编码后的字节（原始数据 + 校验码），长度 = len(data) + nsym * num_blocks
        """
        return bytes(self._codec.encode(data))

    def decode(self, data: bytes) -> bytes | None:
        """
        Reed-Solomon 译码，自动纠正错误
        Args:
            data: 待解码的字节（含校验码）
        Returns:
            解码后的原始字节；若错误过多无法纠正则返回 None
        """
        try:
            decoded, _, _ = self._codec.decode(data)
            return bytes(decoded)
        except ReedSolomonError:
            return None

    def max_data_length(self, total_bytes: int) -> int:
        """给定总字节数，计算最多能编码多少原始数据字节"""
        block_size = 255
        # RS 在 GF(256) 上操作，以 255 字节为一块
        num_full_blocks = total_bytes // block_size
        remainder = total_bytes % block_size
        capacity = num_full_blocks * (block_size - self.nsym) + max(0, remainder - self.nsym)
        return max(0, capacity)
