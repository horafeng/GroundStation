"""可替换无人机协议编码器的稳定接口。"""

from __future__ import annotations

from typing import Protocol

from ground_station.domain import MissionSnapshot


class DroneProtocolEncoder(Protocol):
    protocol_name: str
    version: int

    def encode(self, snapshot: MissionSnapshot) -> bytes: ...
