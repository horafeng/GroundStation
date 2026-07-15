"""与二进制协议无关的任务领域对象。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class MissionMode(IntEnum):
    STANDBY = 0
    TAKEOFF = 1
    TRACK = 2
    RETURN_HOME = 3
    LAND = 4


@dataclass(frozen=True, slots=True)
class MissionSnapshot:
    """某一发送时刻的完整业务快照。

    目标高度仅按 Demo 临时假设解释为相对地面高度、单位米，待实物核对。
    `target_coordinate_timestamp_unix_ms` 是最后收到该坐标的本机 Unix 毫秒，
    不是本报文生成时间。
    """

    message_sequence: int
    drone_id: int
    mode: MissionMode
    target_valid: bool
    track_absolute_id: int | None
    target_longitude_deg: float | None
    target_latitude_deg: float | None
    target_relative_ground_height_m: float | None
    target_coordinate_timestamp_unix_ms: int | None
    coordinate_realtime: bool
    target_lost_duration_ms: int
    generated_timestamp_unix_ms: int

    def __post_init__(self) -> None:
        if not 0 <= self.message_sequence <= 0xFFFFFFFF:
            raise ValueError("message_sequence 必须在uint32范围")
        if not 0 <= self.drone_id <= 0xFFFFFFFF:
            raise ValueError("drone_id 必须在uint32范围")
        target_values = (
            self.track_absolute_id,
            self.target_longitude_deg,
            self.target_latitude_deg,
            self.target_relative_ground_height_m,
            self.target_coordinate_timestamp_unix_ms,
        )
        if self.target_valid and any(value is None for value in target_values):
            raise ValueError("有效目标必须包含编号、坐标、高度和坐标时间戳")
        if not self.target_valid and any(value is not None for value in target_values):
            raise ValueError("无效目标的目标字段必须为None")
        if self.coordinate_realtime and not self.target_valid:
            raise ValueError("无效目标不能标记为实时")
        if self.target_lost_duration_ms < 0:
            raise ValueError("target_lost_duration_ms 不能为负数")
