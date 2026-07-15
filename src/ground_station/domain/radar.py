"""雷达站、航迹和时间字段的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class TargetType(IntEnum):
    UNKNOWN = 0
    VEHICLE = 1
    PERSON = 2
    UAV = 3
    RESERVED_4 = 4
    RESERVED_5 = 5
    RESERVED_6 = 6
    RESERVED_7 = 7


class TasTwsFlag(IntEnum):
    """协议 Bits1:0 的 TAS/TWS 标志；它不是坐标实时标志。"""

    TWS = 0
    TAS = 1
    RESERVED_2 = 2
    RESERVED_3 = 3


class HeightReference(str, Enum):
    """目标高度基准。

    当前只有 Demo 临时解释：相对地面高度，尚未经过实物核对。
    """

    DEMO_RELATIVE_GROUND_UNVERIFIED = "relative_ground_unverified"


@dataclass(frozen=True, slots=True)
class RadarTimeFields:
    dsp_time_ms: int
    gps_time_raw: int
    frame_count: int
    frame_time_us: int


@dataclass(frozen=True, slots=True)
class TargetTimeFields:
    gps_time_ms: int
    dsp_timestamp_ms_24bit: int


@dataclass(frozen=True, slots=True)
class RadarSiteState:
    longitude_deg: float
    latitude_deg: float
    altitude_m: int
    satellite_count: int
    heading_deg: float
    true_heading_deg: float
    roll_deg: float
    pitch_deg: float
    time: RadarTimeFields
    raw_header_words: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RadarTrack:
    """单条目标航迹。

    `absolute_id` 是后续内部关联应使用的身份；`display_id` 仅用于界面展示。
    """

    display_id: int
    absolute_id: int
    distance_m: float
    azimuth_deg: float
    elevation_deg: float
    target_type: TargetType
    speed_mps: float
    tas_tws_flag: TasTwsFlag
    is_cleared: bool
    original_point_target_type: TargetType
    longitude_deg: float
    latitude_deg: float
    height_m: int
    height_reference: HeightReference
    time: TargetTimeFields
    raw_words: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RadarTrackFrame:
    length_words: int
    target_count: int
    radar: RadarSiteState
    tracks: tuple[RadarTrack, ...]
    checksum: int
    raw_words: tuple[int, ...]

    def tracks_by_absolute_id(self) -> dict[int, RadarTrack]:
        """按绝对编号创建索引，不使用显示编号作为唯一标识。"""

        return {track.absolute_id: track for track in self.tracks}
