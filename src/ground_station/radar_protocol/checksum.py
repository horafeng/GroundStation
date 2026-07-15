"""32 位无符号累加校验和。"""

from __future__ import annotations

from collections.abc import Sequence

UINT32_MASK = 0xFFFFFFFF


def compute_word_sum_checksum(words: Sequence[int], checksum_index: int) -> int:
    """按正式协议累加帧头至帧尾，计算时将校验字段视为 0。"""

    if not 0 <= checksum_index < len(words):
        raise IndexError("checksum_index 超出报文范围")
    total = 0
    for index, word in enumerate(words):
        if index != checksum_index:
            total = (total + (word & UINT32_MASK)) & UINT32_MASK
    return total
