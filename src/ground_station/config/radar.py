"""雷达协议配置。

字节序和“一个 UDP 数据报一帧”均为 Demo 临时假设，尚未经过真实雷达
抓包或实物验证。它们必须由配置显式提供，解析器不会自行试探字节序。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEMO_ASSUMPTION_NOTICE = "Demo临时假设，尚未经过真实雷达抓包或实物验证"
TARGET_HEIGHT_NOTICE = "目标高度暂按相对地面高度、单位米处理，待实物核对"

ByteOrder = Literal["little", "big"]


@dataclass(frozen=True, slots=True)
class RadarProtocolSettings:
    """影响雷达数据报解释方式的显式配置。"""

    byte_order: ByteOrder = "little"
    single_frame_per_datagram: bool = True
    demo_assumption_notice: str = DEMO_ASSUMPTION_NOTICE
    target_height_reference: str = "relative_ground_unverified"
    target_height_notice: str = TARGET_HEIGHT_NOTICE

    def __post_init__(self) -> None:
        if self.byte_order not in ("little", "big"):
            raise ValueError(f"不支持的 byte_order: {self.byte_order!r}")
        if not self.demo_assumption_notice:
            raise ValueError("demo_assumption_notice 不能为空")

    @property
    def struct_prefix(self) -> str:
        return "<" if self.byte_order == "little" else ">"

    @property
    def assumption_messages(self) -> tuple[str, ...]:
        return (
            f"{self.demo_assumption_notice}：32位字节序={self.byte_order}",
            (
                f"{self.demo_assumption_notice}："
                f"一个UDP数据报按{'一帧完整报文' if self.single_frame_per_datagram else '非单帧模式'}处理"
            ),
            self.target_height_notice,
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "RadarProtocolSettings":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            byte_order=raw.get("byte_order", "little"),
            single_frame_per_datagram=bool(raw.get("single_frame_per_datagram", True)),
            demo_assumption_notice=raw.get("demo_assumption_notice", DEMO_ASSUMPTION_NOTICE),
            target_height_reference=raw.get(
                "target_height_reference", "relative_ground_unverified"
            ),
            target_height_notice=raw.get("target_height_notice", TARGET_HEIGHT_NOTICE),
        )
