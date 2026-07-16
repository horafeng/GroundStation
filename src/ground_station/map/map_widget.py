"""Public map facade used by the ground-station UI."""

from __future__ import annotations

from typing import Iterable

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ground_station.tracks import TrackLifecycleSnapshot

from .map_models import MapSceneModel
from .tile_map import TileMapCanvas


class MapWidget(QWidget):
    target_clicked = pyqtSignal(int)
    status_changed = pyqtSignal(str)

    def __init__(
        self,
        model: MapSceneModel | None = None,
        *,
        online: bool = False,
        tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = model or MapSceneModel(parent=self)
        self.canvas = TileMapCanvas(self.model, online=online, tile_url=tile_url)
        self.canvas.target_clicked.connect(self.target_clicked)
        self.canvas.status_changed.connect(self._set_status)
        self.status_label = QLabel(self.canvas.mode_text)
        self.status_label.setObjectName("mapStatusLabel")
        self.home_button = QPushButton("回到 Home")
        self.home_button.setObjectName("mapHomeButton")
        self.zoom_in_button = QPushButton("+")
        self.zoom_out_button = QPushButton("−")
        self.home_button.clicked.connect(self.center_on_home)
        self.zoom_in_button.clicked.connect(self.canvas.zoom_in)
        self.zoom_out_button.clicked.connect(self.canvas.zoom_out)
        self._build_layout()

    def _build_layout(self) -> None:
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas, 0, 0)
        controls = QWidget()
        controls.setObjectName("mapControls")
        row = QVBoxLayout(controls)
        row.setContentsMargins(5, 5, 5, 5)
        row.addWidget(self.home_button)
        row.addWidget(self.zoom_in_button)
        row.addWidget(self.zoom_out_button)
        layout.addWidget(controls, 0, 0, Qt.AlignRight | Qt.AlignBottom)
        layout.addWidget(self.status_label, 0, 0, Qt.AlignHCenter | Qt.AlignBottom)

    def set_home(self, longitude_deg: float, latitude_deg: float) -> None:
        first_home = self.model.home is None
        self.model.set_home(longitude_deg, latitude_deg)
        if first_home:
            self.canvas.center_on_home()

    def update_tracks(self, tracks: Iterable[TrackLifecycleSnapshot]) -> None:
        self.model.update_tracks(tracks)

    def set_selected_track(self, absolute_id: int | None) -> None:
        self.model.set_selected_track(absolute_id)

    def set_track_history(
        self, absolute_id: int, points: Iterable[tuple[float, float]]
    ) -> None:
        self.model.set_track_history(absolute_id, points)

    def center_on_home(self) -> None:
        self.canvas.center_on_home()

    def set_online(self, online: bool) -> None:
        self.canvas.set_online(online)

    def set_tile_url(self, tile_url: str) -> None:
        self.canvas.set_tile_url(tile_url)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_changed.emit(text)
