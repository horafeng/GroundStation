"""结构化解析错误和 Result 类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from ground_station.domain import RadarTrackFrame


class RadarParseErrorCode(str, Enum):
    EMPTY_DATAGRAM = "empty_datagram"
    BYTE_LENGTH_NOT_MULTIPLE_OF_FOUR = "byte_length_not_multiple_of_four"
    FRAME_TOO_SHORT = "frame_too_short"
    INVALID_HEADER = "invalid_header"
    LENGTH_FIELD_MISMATCH = "length_field_mismatch"
    TARGET_COUNT_OUT_OF_RANGE = "target_count_out_of_range"
    TARGET_LENGTH_FORMULA_MISMATCH = "target_length_formula_mismatch"
    INVALID_TAIL = "invalid_tail"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    RADAR_COORDINATE_OUT_OF_RANGE = "radar_coordinate_out_of_range"
    TARGET_COORDINATE_OUT_OF_RANGE = "target_coordinate_out_of_range"
    TARGET_ABSOLUTE_ID_OUT_OF_RANGE = "target_absolute_id_out_of_range"
    TARGET_ANGLE_OUT_OF_RANGE = "target_angle_out_of_range"
    UNSUPPORTED_DATAGRAM_MODE = "unsupported_datagram_mode"


@dataclass(frozen=True, slots=True)
class RadarParseError:
    code: RadarParseErrorCode
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class RadarParseResult:
    frame: RadarTrackFrame | None = None
    error: RadarParseError | None = None

    def __post_init__(self) -> None:
        if (self.frame is None) == (self.error is None):
            raise ValueError("RadarParseResult 必须且只能包含 frame 或 error")

    @property
    def ok(self) -> bool:
        return self.frame is not None

    @classmethod
    def success(cls, frame: RadarTrackFrame) -> "RadarParseResult":
        return cls(frame=frame)

    @classmethod
    def failure(cls, error: RadarParseError) -> "RadarParseResult":
        return cls(error=error)
