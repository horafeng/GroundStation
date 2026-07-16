"""Demo专用Widgets；局部坐标换算只影响显示，不修改原始经纬度。"""

from __future__ import annotations

import math
from collections import defaultdict, deque

from PyQt5.QtCore import QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QPlainTextEdit, QTableWidgetItem, QWidget

from ground_station.tracks import TrackLifecycleSnapshot


def gps_to_local_display_m(
    radar_longitude_deg: float,
    radar_latitude_deg: float,
    target_longitude_deg: float,
    target_latitude_deg: float,
) -> tuple[float, float]:
    """等距圆柱近似，仅供Demo雷达图显示，绝不回写任务坐标。"""

    east = (
        (target_longitude_deg - radar_longitude_deg)
        * 111_320.0
        * math.cos(math.radians(radar_latitude_deg))
    )
    north = (target_latitude_deg - radar_latitude_deg) * 110_540.0
    return east, north


class CappedLogEdit(QPlainTextEdit):
    def __init__(self, max_lines: int = 1000, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.document().setMaximumBlockCount(max_lines)


class NumericTableItem(QTableWidgetItem):
    SORT_ROLE = Qt.UserRole + 1

    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(self.SORT_ROLE)
        right = other.data(self.SORT_ROLE)
        if left is not None and right is not None:
            return left < right
        return super().__lt__(other)


class RadarDisplayWidget(QWidget):
    track_clicked = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 保持足够的绘制空间，同时允许1366×768窗口通过Splitter调整雷达盘与航迹表。
        self.setMinimumSize(420, 200)
        self.setToolTip("经纬度到局部平面的近似换算仅用于Demo展示，不修改发送坐标")
        self._range_m = 1000
        self._radar_position: tuple[float, float] | None = None
        self._tracks: tuple[TrackLifecycleSnapshot, ...] = ()
        self._selected_id: int | None = None
        self._trails: dict[int, deque[tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=30)
        )
        self._screen_positions: dict[int, QPointF] = {}

    @property
    def selected_absolute_id(self) -> int | None:
        return self._selected_id

    def set_range_m(self, value: int) -> None:
        if value not in (500, 1000, 2000, 5000):
            raise ValueError("显示量程必须为500/1000/2000/5000m")
        self._range_m = value
        self.update()

    def set_radar_position(self, longitude_deg: float, latitude_deg: float) -> None:
        self._radar_position = (longitude_deg, latitude_deg)
        self.update()

    def set_selected_absolute_id(self, absolute_id: int | None) -> None:
        self._selected_id = absolute_id
        self.update()

    def set_tracks(self, tracks: tuple[TrackLifecycleSnapshot, ...]) -> None:
        self._tracks = tracks
        if self._radar_position is not None:
            radar_lon, radar_lat = self._radar_position
            for track in tracks:
                coordinate = track.last_valid_coordinate
                if coordinate is None:
                    continue
                point = gps_to_local_display_m(
                    radar_lon,
                    radar_lat,
                    coordinate.longitude_deg,
                    coordinate.latitude_deg,
                )
                trail = self._trails[track.absolute_id]
                if not trail or trail[-1] != point:
                    trail.append(point)
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b1722"))
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = max(20.0, min(self.width(), self.height()) / 2 - 32)
        painter.setPen(QPen(QColor("#315064"), 1))
        for fraction in (0.25, 0.5, 0.75, 1.0):
            r = radius * fraction
            painter.drawEllipse(center, r, r)
        painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - radius), QPointF(center.x(), center.y() + radius))
        painter.setPen(QColor("#a9c2d2"))
        painter.drawText(12, 22, f"固定量程 {self._range_m:g} m / Demo局部近似")
        painter.drawText(int(center.x()) + 8, int(center.y()) - 8, "雷达")
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(center, 4, 4)

        self._screen_positions.clear()
        for track in self._tracks:
            coordinate = track.last_valid_coordinate
            if coordinate is None or self._radar_position is None:
                continue
            trail = self._trails.get(track.absolute_id, ())
            screen_trail = [self._to_screen(point, center, radius) for point in trail]
            if len(screen_trail) > 1:
                painter.setPen(QPen(QColor("#365d72"), 1))
                painter.drawPolyline(QPolygonF(screen_trail))
            local = gps_to_local_display_m(
                self._radar_position[0],
                self._radar_position[1],
                coordinate.longitude_deg,
                coordinate.latitude_deg,
            )
            point = self._to_screen(local, center, radius)
            self._screen_positions[track.absolute_id] = point
            selected = track.absolute_id == self._selected_id
            color = QColor("#ffb347") if selected else QColor("#35c7e8")
            pen = QPen(color if track.is_realtime else QColor("#9aa5ad"), 3 if selected else 2)
            if not track.is_realtime:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(point, 8 if selected else 5, 8 if selected else 5)
            painter.drawText(int(point.x()) + 8, int(point.y()) - 6, str(track.display_id))

    def mousePressEvent(self, event: object) -> None:
        position = event.pos()  # type: ignore[attr-defined]
        closest: tuple[float, int] | None = None
        for absolute_id, point in self._screen_positions.items():
            distance = math.hypot(position.x() - point.x(), position.y() - point.y())
            if distance <= 14 and (closest is None or distance < closest[0]):
                closest = (distance, absolute_id)
        if closest is not None:
            self.track_clicked.emit(closest[1])
        super().mousePressEvent(event)  # type: ignore[arg-type]

    def _to_screen(self, local: tuple[float, float], center: QPointF, radius: float) -> QPointF:
        scale = radius / self._range_m
        return QPointF(center.x() + local[0] * scale, center.y() - local[1] * scale)
