"""本阶段核心业务的可配置 Demo 参数。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

TRACK_TIMEOUT_NOTICE = (
    "Demo临时假设，航迹未更新超过2000ms判定为丢失，"
    "尚未经过真实雷达更新频率验证"
)


@dataclass(frozen=True, slots=True)
class CoreDemoSettings:
    track_stale_timeout_ms: int = 2_000
    send_frequency_hz: float = 5.0
    drone_id: int = 1
    drone_host: str = "127.0.0.1"
    drone_port: int = 7000
    track_timeout_notice: str = TRACK_TIMEOUT_NOTICE

    def __post_init__(self) -> None:
        if self.track_stale_timeout_ms <= 0:
            raise ValueError("track_stale_timeout_ms 必须大于0")
        if not 0.1 <= self.send_frequency_hz <= 100.0:
            raise ValueError("send_frequency_hz 必须在0.1..100.0")
        if not 0 <= self.drone_id <= 0xFFFFFFFF:
            raise ValueError("drone_id 必须在uint32范围")
        if not self.drone_host:
            raise ValueError("drone_host 不能为空")
        if not 1 <= self.drone_port <= 65535:
            raise ValueError("drone_port 必须在1..65535")

    @classmethod
    def from_json(cls, path: str | Path) -> "CoreDemoSettings":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**raw)
