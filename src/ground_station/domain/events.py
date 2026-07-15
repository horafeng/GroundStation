"""核心业务立即发送事件。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ImmediateSendReason(str, Enum):
    INITIAL_TARGET_SELECTED = "initial_target_selected"
    TARGET_SWITCH_CONFIRMED = "target_switch_confirmed"
    MISSION_MODE_CHANGED = "mission_mode_changed"


@dataclass(frozen=True, slots=True)
class ImmediateSendEvent:
    reason: ImmediateSendReason
