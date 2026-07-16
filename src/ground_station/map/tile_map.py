"""PyQt5 tile canvas with a deterministic local-demo fallback."""

from __future__ import annotations

import math
from collections import OrderedDict
from pathlib import Path

from PyQt5.QtCore import QPoint, QPointF, QRectF, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QWheelEvent,
)
from PyQt5.QtNetwork import (
    QNetworkAccessManager,
    QNetworkDiskCache,
    QNetworkReply,
    QNetworkRequest,
)
from PyQt5.QtWidgets import QWidget

from .map_models import MapSceneModel, MapTrackMarker

TILE_SIZE = 256


def _geo_to_world(longitude: float, latitude: float, zoom: int) -> QPointF:
    scale = TILE_SIZE * (2**zoom)
    latitude = max(-85.0511, min(85.0511, latitude))
    x = (longitude + 180.0) / 360.0 * scale
    sin_lat = math.sin(math.radians(latitude))
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * scale
    return QPointF(x, y)


def _world_to_geo(point: QPointF, zoom: int) -> tuple[float, float]:
    scale = TILE_SIZE * (2**zoom)
    longitude = point.x() / scale * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * point.y() / scale
    latitude = math.degrees(math.atan(math.sinh(n)))
    return longitude, latitude


class TileMapCanvas(QWidget):
    """Interactive map surface; network failures never escape into business code."""

    target_clicked = pyqtSignal(int)
    status_changed = pyqtSignal(str)

    def __init__(
        self,
        model: MapSceneModel,
        *,
        online: bool = False,
        tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = model
        self.online = online
        self.tile_url = tile_url
        self.zoom = 15
        self.center = (109.006, 34.116)
        self._drag_origin: QPoint | None = None
        self._center_at_drag: QPointF | None = None
        self._marker_positions: dict[int, QPointF] = {}
        self._cache: OrderedDict[tuple[int, int, int], QPixmap] = OrderedDict()
        self._pending: set[tuple[int, int, int]] = set()
        self._network = QNetworkAccessManager(self)
        self._disk_cache = QNetworkDiskCache(self)
        cache_path = Path(__file__).resolve().parents[3] / ".runtime" / "map_tiles"
        cache_path.mkdir(parents=True, exist_ok=True)
        self._disk_cache.setCacheDirectory(str(cache_path))
        self._disk_cache.setMaximumCacheSize(64 * 1024 * 1024)
        self._network.setCache(self._disk_cache)
        self._network.finished.connect(self._tile_finished)
        self.setMinimumSize(420, 300)
        self.setMouseTracking(True)
        self.model.changed.connect(self.update)
        self.status_changed.emit(self.mode_text)

    @property
    def mode_text(self) -> str:
        return "在线地图 · © OpenStreetMap contributors" if self.online else "本地Demo地图"

    def set_online(self, online: bool) -> None:
        if self.online == online:
            return
        self.online = online
        self.status_changed.emit(self.mode_text)
        self.update()

    def set_tile_url(self, tile_url: str) -> None:
        if self.tile_url == tile_url:
            return
        self.tile_url = tile_url
        self._cache.clear()
        self.update()

    def center_on_home(self) -> None:
        if self.model.home is not None:
            self.center = self.model.home
        self.update()

    def zoom_in(self) -> None:
        self.zoom = min(19, self.zoom + 1)
        self.update()

    def zoom_out(self) -> None:
        self.zoom = max(3, self.zoom - 1)
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self._paint_local_background(painter)
        if self.online:
            self._paint_tiles(painter)
        self._paint_history(painter)
        self._paint_markers(painter)
        self._paint_attribution(painter)

    def _paint_local_background(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), QColor("#102733"))
        painter.setPen(QPen(QColor("#234654"), 1))
        for x in range(0, self.width(), 64):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 64):
            painter.drawLine(0, y, self.width(), y)
        painter.setPen(QPen(QColor("#286578"), 26))
        painter.drawLine(0, int(self.height() * 0.72), self.width(), int(self.height() * 0.43))
        painter.setPen(QPen(QColor("#786c48"), 7))
        painter.drawLine(0, int(self.height() * 0.28), self.width(), int(self.height() * 0.62))
        painter.drawLine(int(self.width() * 0.34), 0, int(self.width() * 0.58), self.height())

    def _paint_tiles(self, painter: QPainter) -> None:
        center_world = _geo_to_world(*self.center, self.zoom)
        left = center_world.x() - self.width() / 2
        top = center_world.y() - self.height() / 2
        first_x, first_y = math.floor(left / TILE_SIZE), math.floor(top / TILE_SIZE)
        last_x = math.floor((left + self.width()) / TILE_SIZE)
        last_y = math.floor((top + self.height()) / TILE_SIZE)
        tile_count = 2**self.zoom
        for tile_y in range(first_y, last_y + 1):
            if not 0 <= tile_y < tile_count:
                continue
            for tile_x in range(first_x, last_x + 1):
                wrapped_x = tile_x % tile_count
                key = (self.zoom, wrapped_x, tile_y)
                target = QPointF(tile_x * TILE_SIZE - left, tile_y * TILE_SIZE - top)
                pixmap = self._cache.get(key)
                if pixmap is None:
                    self._request_tile(key)
                else:
                    self._cache.move_to_end(key)
                    painter.drawPixmap(target, pixmap)

    def _request_tile(self, key: tuple[int, int, int]) -> None:
        if key in self._pending:
            return
        zoom, tile_x, tile_y = key
        url = self.tile_url.format(z=zoom, x=tile_x, y=tile_y)
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(
            b"User-Agent",
            b"GroundStationDemo/0.1 (+https://github.com/horafeng/GroundStation)",
        )
        request.setAttribute(
            QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.PreferCache
        )
        reply = self._network.get(request)
        reply.setProperty("tile_key", key)
        self._pending.add(key)

    def _tile_finished(self, reply: QNetworkReply) -> None:
        key = reply.property("tile_key")
        self._pending.discard(key)
        if reply.error() == QNetworkReply.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self._cache[key] = pixmap
                while len(self._cache) > 256:
                    self._cache.popitem(last=False)
                self.update()
        else:
            self.status_changed.emit("地图瓦片不可用 · 已保留本地Demo底图")
        reply.deleteLater()

    def _screen_point(self, longitude: float, latitude: float) -> QPointF:
        center = _geo_to_world(*self.center, self.zoom)
        point = _geo_to_world(longitude, latitude, self.zoom)
        return QPointF(
            point.x() - center.x() + self.width() / 2,
            point.y() - center.y() + self.height() / 2,
        )

    def _paint_history(self, painter: QPainter) -> None:
        for marker in self.model.markers.values():
            if len(marker.history) < 2:
                continue
            color = QColor("#ffb457") if marker.is_selected else QColor("#6db1d3")
            if not marker.is_realtime:
                color.setAlpha(120)
            painter.setPen(QPen(color, 2))
            points = [self._screen_point(*point) for point in marker.history]
            painter.drawPolyline(QPolygonF(points))

    def _paint_markers(self, painter: QPainter) -> None:
        self._marker_positions.clear()
        if self.model.home is not None:
            point = self._screen_point(*self.model.home)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.setBrush(QColor("#2aa8df"))
            painter.drawRect(QRectF(point.x() - 8, point.y() - 8, 16, 16))
            painter.drawText(point + QPointF(12, -8), "Home / 雷达")
        for marker in self.model.markers.values():
            self._paint_marker(painter, marker)

    def _paint_marker(self, painter: QPainter, marker: MapTrackMarker) -> None:
        point = self._screen_point(marker.longitude_deg, marker.latitude_deg)
        self._marker_positions[marker.absolute_id] = point
        radius = 11 if marker.is_selected else 8
        fill = QColor("#ff9f32") if marker.is_selected else QColor("#3ddc84")
        if not marker.is_realtime:
            fill = QColor("#7d8b91")
        painter.setBrush(fill)
        painter.setPen(QPen(QColor("#ffffff") if marker.is_selected else fill.lighter(), 2))
        painter.drawEllipse(point, radius, radius)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(point + QPointF(radius + 4, 4), str(marker.display_id))

    def _paint_attribution(self, painter: QPainter) -> None:
        text = self.mode_text
        bounds = painter.fontMetrics().boundingRect(text)
        box = QRectF(8, self.height() - bounds.height() - 12, bounds.width() + 12, bounds.height() + 6)
        painter.fillRect(box, QColor(9, 20, 27, 205))
        painter.setPen(QColor("#dbe8ed"))
        painter.drawText(box.adjusted(6, 0, -2, 0), Qt.AlignVCenter, text)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        for absolute_id, point in self._marker_positions.items():
            if (point - event.localPos()).manhattanLength() <= 16:
                self.target_clicked.emit(absolute_id)
                return
        self._drag_origin = event.pos()
        self._center_at_drag = _geo_to_world(*self.center, self.zoom)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is None or self._center_at_drag is None:
            return
        delta = event.pos() - self._drag_origin
        world = QPointF(self._center_at_drag.x() - delta.x(), self._center_at_drag.y() - delta.y())
        self.center = _world_to_geo(world, self.zoom)
        self.update()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._drag_origin = None
        self._center_at_drag = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() > 0:
            self.zoom_in()
        elif event.angleDelta().y() < 0:
            self.zoom_out()
