"""任务模式状态和与协议无关的 MissionSnapshot 构造。"""

from __future__ import annotations

import threading
import time
from typing import Callable

from ground_station.domain import (
    ImmediateSendEvent,
    ImmediateSendReason,
    MissionMode,
    MissionSnapshot,
)
from ground_station.selection import TargetSelectionService


class MissionStateService:
    def __init__(
        self,
        selection: TargetSelectionService,
        *,
        drone_id: int,
        initial_mode: MissionMode = MissionMode.STANDBY,
        event_sink: Callable[[ImmediateSendEvent], None] | None = None,
        unix_ms_clock: Callable[[], int] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 <= drone_id <= 0xFFFFFFFF:
            raise ValueError("drone_id 必须在uint32范围")
        self._selection = selection
        self._drone_id = drone_id
        self._mode = initial_mode
        self._event_sink = event_sink
        self._unix_ms_clock = unix_ms_clock or (lambda: time.time_ns() // 1_000_000)
        self._monotonic_clock = monotonic_clock
        self._lock = threading.RLock()

    @property
    def mode(self) -> MissionMode:
        with self._lock:
            return self._mode

    def set_mode(self, mode: MissionMode | int) -> ImmediateSendEvent | None:
        new_mode = MissionMode(mode)
        with self._lock:
            if new_mode == self._mode:
                return None
            self._mode = new_mode
        event = ImmediateSendEvent(ImmediateSendReason.MISSION_MODE_CHANGED)
        if self._event_sink is not None:
            self._event_sink(event)
        return event

    def build_snapshot(
        self,
        message_sequence: int,
        *,
        generated_unix_ms: int | None = None,
        now_monotonic: float | None = None,
    ) -> MissionSnapshot:
        generated = self._unix_ms_clock() if generated_unix_ms is None else generated_unix_ms
        mono = self._monotonic_clock() if now_monotonic is None else now_monotonic
        target = self._selection.selected_track(now_monotonic=mono)
        coordinate = None if target is None else target.last_valid_coordinate
        target_valid = target is not None and coordinate is not None
        with self._lock:
            mode = self._mode
        if not target_valid:
            return MissionSnapshot(
                message_sequence=message_sequence,
                drone_id=self._drone_id,
                mode=mode,
                target_valid=False,
                track_absolute_id=None,
                target_longitude_deg=None,
                target_latitude_deg=None,
                target_relative_ground_height_m=None,
                target_coordinate_timestamp_unix_ms=None,
                coordinate_realtime=False,
                target_lost_duration_ms=0,
                generated_timestamp_unix_ms=generated,
            )
        assert target is not None and coordinate is not None
        return MissionSnapshot(
            message_sequence=message_sequence,
            drone_id=self._drone_id,
            mode=mode,
            target_valid=True,
            track_absolute_id=target.absolute_id,
            target_longitude_deg=coordinate.longitude_deg,
            target_latitude_deg=coordinate.latitude_deg,
            target_relative_ground_height_m=coordinate.relative_ground_height_m,
            target_coordinate_timestamp_unix_ms=coordinate.received_unix_ms,
            coordinate_realtime=target.is_realtime,
            target_lost_duration_ms=target.lost_duration_ms,
            generated_timestamp_unix_ms=generated,
        )
