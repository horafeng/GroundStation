"""Map-facing state derived from track lifecycle snapshots."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from ground_station.tracks import TrackLifecycleSnapshot


@dataclass(frozen=True, slots=True)
class MapTrackMarker:
    absolute_id: int
    display_id: int
    longitude_deg: float
    latitude_deg: float
    is_realtime: bool
    is_selected: bool
    history: tuple[tuple[float, float], ...]


class MapSceneModel(QObject):
    """Small, bounded map model; it contains no selection business rules."""

    changed = pyqtSignal()

    def __init__(
        self,
        *,
        history_limit: int = 60,
        refresh_interval_ms: int = 100,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if history_limit < 2:
            raise ValueError("history_limit must be at least 2")
        if refresh_interval_ms < 1:
            raise ValueError("refresh_interval_ms must be positive")
        self.history_limit = history_limit
        self.refresh_interval_ms = refresh_interval_ms
        self.home: tuple[float, float] | None = None
        self.selected_absolute_id: int | None = None
        self.markers: dict[int, MapTrackMarker] = {}
        self._history: dict[int, deque[tuple[float, float]]] = {}
        self._notify_timer = QTimer(self)
        self._notify_timer.setSingleShot(True)
        self._notify_timer.timeout.connect(self.changed)

    def set_home(self, longitude_deg: float, latitude_deg: float) -> None:
        value = (longitude_deg, latitude_deg)
        if self.home == value:
            return
        self.home = value
        self._schedule_changed()

    def update_tracks(self, tracks: Iterable[TrackLifecycleSnapshot]) -> None:
        updated: dict[int, MapTrackMarker] = {}
        for track in tracks:
            coordinate = track.last_valid_coordinate
            if coordinate is None:
                continue
            history = self._history.setdefault(
                track.absolute_id, deque(maxlen=self.history_limit)
            )
            point = (coordinate.longitude_deg, coordinate.latitude_deg)
            if not history or history[-1] != point:
                history.append(point)
            updated[track.absolute_id] = MapTrackMarker(
                absolute_id=track.absolute_id,
                display_id=track.display_id,
                longitude_deg=point[0],
                latitude_deg=point[1],
                is_realtime=track.is_realtime,
                is_selected=track.absolute_id == self.selected_absolute_id,
                history=tuple(history),
            )
        self.markers = updated
        self._schedule_changed()

    def set_selected_track(self, absolute_id: int | None) -> None:
        if self.selected_absolute_id == absolute_id:
            return
        self.selected_absolute_id = absolute_id
        self.markers = {
            key: MapTrackMarker(
                absolute_id=value.absolute_id,
                display_id=value.display_id,
                longitude_deg=value.longitude_deg,
                latitude_deg=value.latitude_deg,
                is_realtime=value.is_realtime,
                is_selected=key == absolute_id,
                history=value.history,
            )
            for key, value in self.markers.items()
        }
        self._schedule_changed()

    def set_track_history(
        self, absolute_id: int, points: Iterable[tuple[float, float]]
    ) -> None:
        history = deque(points, maxlen=self.history_limit)
        self._history[absolute_id] = history
        marker = self.markers.get(absolute_id)
        if marker is not None:
            self.markers[absolute_id] = MapTrackMarker(
                marker.absolute_id,
                marker.display_id,
                marker.longitude_deg,
                marker.latitude_deg,
                marker.is_realtime,
                marker.is_selected,
                tuple(history),
            )
        self._schedule_changed()

    def set_history_limit(self, history_limit: int) -> None:
        if not 2 <= history_limit <= 1000:
            raise ValueError("history_limit must be in 2..1000")
        if history_limit == self.history_limit:
            return
        self.history_limit = history_limit
        self._history = {
            key: deque(points, maxlen=history_limit)
            for key, points in self._history.items()
        }
        self.markers = {
            key: MapTrackMarker(
                marker.absolute_id,
                marker.display_id,
                marker.longitude_deg,
                marker.latitude_deg,
                marker.is_realtime,
                marker.is_selected,
                tuple(self._history.get(key, ())),
            )
            for key, marker in self.markers.items()
        }
        self._schedule_changed()

    def _schedule_changed(self) -> None:
        if not self._notify_timer.isActive():
            self._notify_timer.start(self.refresh_interval_ms)
