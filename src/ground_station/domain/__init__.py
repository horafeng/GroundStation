"""与 UI 和网络无关的领域数据模型。"""

from .radar import (
    HeightReference,
    RadarSiteState,
    RadarTimeFields,
    RadarTrack,
    RadarTrackFrame,
    TargetTimeFields,
    TargetType,
    TasTwsFlag,
)
from .events import ImmediateSendEvent, ImmediateSendReason
from .mission import MissionMode, MissionSnapshot

__all__ = [
    "HeightReference",
    "RadarSiteState",
    "RadarTimeFields",
    "RadarTrack",
    "RadarTrackFrame",
    "TargetTimeFields",
    "TargetType",
    "TasTwsFlag",
    "ImmediateSendEvent",
    "ImmediateSendReason",
    "MissionMode",
    "MissionSnapshot",
]
