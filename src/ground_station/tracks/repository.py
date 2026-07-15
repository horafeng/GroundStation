"""以航迹绝对编号为主键的线程安全航迹仓库。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from ground_station.config import TRACK_TIMEOUT_NOTICE
from ground_station.domain import RadarTrack, RadarTrackFrame


@dataclass(frozen=True, slots=True)
class LastValidCoordinate:
    """最后有效坐标同时保存Unix展示时间和丢失计时所需的单调时刻。"""
    longitude_deg: float
    latitude_deg: float
    relative_ground_height_m: float
    received_unix_ms: int
    received_monotonic: float = 0.0


@dataclass(frozen=True, slots=True)
class TrackLifecycleSnapshot:
    absolute_id: int
    display_id: int
    latest_observation: RadarTrack
    last_valid_coordinate: LastValidCoordinate | None
    first_seen_monotonic: float
    last_updated_monotonic: float
    radar_marked_cleared: bool
    is_realtime: bool
    lost_since_monotonic: float | None
    lost_duration_ms: int
    first_seen_unix_ms: int = 0
    last_updated_unix_ms: int = 0


@dataclass(slots=True)
class _TrackRecord:
    absolute_id: int
    display_id: int
    latest_observation: RadarTrack
    last_valid_coordinate: LastValidCoordinate | None
    first_seen_monotonic: float
    last_updated_monotonic: float
    radar_marked_cleared: bool
    lost_since_monotonic: float | None
    first_seen_unix_ms: int
    last_updated_unix_ms: int


class TrackRepository:
    """维护实时/丢失状态，不进行类型过滤或邻近目标重关联。

    超时阈值只触发非实时状态；丢失持续时间从最后有效坐标的
    ``received_monotonic`` 起算。恢复实时后清零。
    """

    timeout_assumption_notice = TRACK_TIMEOUT_NOTICE

    def __init__(
        self,
        stale_timeout_ms: int = 2_000,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
        unix_ms_clock: Callable[[], int] | None = None,
    ) -> None:
        if stale_timeout_ms <= 0:
            raise ValueError("stale_timeout_ms 必须大于0")
        self.stale_timeout_ms = stale_timeout_ms
        self._stale_timeout_s = stale_timeout_ms / 1000.0
        self._monotonic_clock = monotonic_clock
        self._unix_ms_clock = unix_ms_clock or (lambda: time.time_ns() // 1_000_000)
        self._records: dict[int, _TrackRecord] = {}
        self._lock = threading.RLock()

    def update_frame(
        self,
        frame: RadarTrackFrame,
        *,
        received_monotonic: float | None = None,
        received_unix_ms: int | None = None,
    ) -> tuple[TrackLifecycleSnapshot, ...]:
        mono = self._monotonic_clock() if received_monotonic is None else received_monotonic
        unix_ms = self._unix_ms_clock() if received_unix_ms is None else received_unix_ms
        with self._lock:
            updated = [self._update_observation(track, mono, unix_ms) for track in frame.tracks]
            return tuple(self._snapshot(record, mono) for record in updated)

    def set_stale_timeout_ms(self, value: int) -> None:
        """在UI线程中应用新的超时阈值；现有航迹身份和坐标不变。"""

        if value <= 0:
            raise ValueError("stale_timeout_ms 必须大于0")
        with self._lock:
            self.stale_timeout_ms = value
            self._stale_timeout_s = value / 1000.0

    def update_observation(
        self,
        observation: RadarTrack,
        *,
        received_monotonic: float | None = None,
        received_unix_ms: int | None = None,
    ) -> TrackLifecycleSnapshot:
        mono = self._monotonic_clock() if received_monotonic is None else received_monotonic
        unix_ms = self._unix_ms_clock() if received_unix_ms is None else received_unix_ms
        with self._lock:
            return self._snapshot(self._update_observation(observation, mono, unix_ms), mono)

    def _update_observation(
        self, observation: RadarTrack, mono: float, unix_ms: int
    ) -> _TrackRecord:
        record = self._records.get(observation.absolute_id)
        coordinate = LastValidCoordinate(
            observation.longitude_deg,
            observation.latitude_deg,
            observation.height_m,
            unix_ms,
            mono,
        )
        if record is None:
            record = _TrackRecord(
                absolute_id=observation.absolute_id,
                display_id=observation.display_id,
                latest_observation=observation,
                last_valid_coordinate=None if observation.is_cleared else coordinate,
                first_seen_monotonic=mono,
                last_updated_monotonic=mono,
                radar_marked_cleared=observation.is_cleared,
                lost_since_monotonic=(
                    coordinate.received_monotonic if observation.is_cleared else None
                ),
                first_seen_unix_ms=unix_ms,
                last_updated_unix_ms=unix_ms,
            )
            self._records[observation.absolute_id] = record
            return record

        record.display_id = observation.display_id
        record.latest_observation = observation
        record.last_updated_monotonic = mono
        record.last_updated_unix_ms = unix_ms
        record.radar_marked_cleared = observation.is_cleared
        if observation.is_cleared:
            if record.lost_since_monotonic is None:
                record.lost_since_monotonic = (
                    record.last_valid_coordinate.received_monotonic
                    if record.last_valid_coordinate is not None
                    else mono
                )
        else:
            record.last_valid_coordinate = coordinate
            record.lost_since_monotonic = None
        return record

    def refresh(self, now_monotonic: float | None = None) -> tuple[TrackLifecycleSnapshot, ...]:
        now = self._monotonic_clock() if now_monotonic is None else now_monotonic
        with self._lock:
            for record in self._records.values():
                self._apply_timeout(record, now)
            return tuple(self._snapshot(record, now) for record in self._records.values())

    def get(
        self, absolute_id: int, *, now_monotonic: float | None = None
    ) -> TrackLifecycleSnapshot | None:
        now = self._monotonic_clock() if now_monotonic is None else now_monotonic
        with self._lock:
            record = self._records.get(absolute_id)
            if record is None:
                return None
            self._apply_timeout(record, now)
            return self._snapshot(record, now)

    def all(self, *, now_monotonic: float | None = None) -> tuple[TrackLifecycleSnapshot, ...]:
        now = self._monotonic_clock() if now_monotonic is None else now_monotonic
        with self._lock:
            for record in self._records.values():
                self._apply_timeout(record, now)
            return tuple(self._snapshot(record, now) for record in self._records.values())

    def _apply_timeout(self, record: _TrackRecord, now: float) -> None:
        if record.lost_since_monotonic is None and now - record.last_updated_monotonic > self._stale_timeout_s:
            record.lost_since_monotonic = (
                record.last_valid_coordinate.received_monotonic
                if record.last_valid_coordinate is not None
                else record.last_updated_monotonic
            )

    @staticmethod
    def _snapshot(record: _TrackRecord, now: float) -> TrackLifecycleSnapshot:
        is_realtime = record.lost_since_monotonic is None and not record.radar_marked_cleared
        lost_ms = (
            0
            if record.lost_since_monotonic is None
            else max(0, int((now - record.lost_since_monotonic) * 1000))
        )
        return TrackLifecycleSnapshot(
            absolute_id=record.absolute_id,
            display_id=record.display_id,
            latest_observation=record.latest_observation,
            last_valid_coordinate=record.last_valid_coordinate,
            first_seen_monotonic=record.first_seen_monotonic,
            last_updated_monotonic=record.last_updated_monotonic,
            radar_marked_cleared=record.radar_marked_cleared,
            is_realtime=is_realtime,
            lost_since_monotonic=record.lost_since_monotonic,
            lost_duration_ms=lost_ms,
            first_seen_unix_ms=record.first_seen_unix_ms,
            last_updated_unix_ms=record.last_updated_unix_ms,
        )
