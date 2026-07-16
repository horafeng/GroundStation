"""Map-first center workspace with a reversible video placeholder view."""

from __future__ import annotations

from typing import Iterable

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QGridLayout, QPushButton, QStackedWidget, QWidget

from ground_station.map import MapSceneModel, MapWidget
from ground_station.tracks import TrackLifecycleSnapshot
from ground_station.video import VideoPlaceholderWidget, VideoSourceConfig


class MainWorkspace(QWidget):
    target_clicked = pyqtSignal(int)
    view_changed = pyqtSignal(str)
    map_status_changed = pyqtSignal(str)

    MAP_VIEW = 0
    VIDEO_VIEW = 1

    def __init__(
        self,
        *,
        online_map: bool = False,
        tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        history_limit: int = 60,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.map_model = MapSceneModel(history_limit=history_limit, parent=self)
        self.map_widget = MapWidget(
            self.map_model, online=online_map, tile_url=tile_url
        )
        self.mini_map = MapWidget(self.map_model, online=False)
        self.video_main = VideoPlaceholderWidget()
        self.video_preview = VideoPlaceholderWidget()
        self.stack = QStackedWidget()
        self.stack.addWidget(self._map_page())
        self.stack.addWidget(self._video_page())
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.map_widget.target_clicked.connect(self.target_clicked)
        self.mini_map.target_clicked.connect(self.target_clicked)
        self.map_widget.status_changed.connect(self.map_status_changed)

    def _map_page(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.map_widget, 0, 0)
        preview, button = self._preview_frame(self.video_preview, "视频主视角")
        button.clicked.connect(self.show_video_view)
        layout.addWidget(preview, 0, 0, Qt.AlignLeft | Qt.AlignBottom)
        return page

    def _video_page(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video_main, 0, 0)
        preview, button = self._preview_frame(self.mini_map, "恢复地图主视角")
        button.clicked.connect(self.show_map_view)
        layout.addWidget(preview, 0, 0, Qt.AlignLeft | Qt.AlignBottom)
        return page

    @staticmethod
    def _preview_frame(content: QWidget, button_text: str) -> tuple[QFrame, QPushButton]:
        button = QPushButton(button_text)
        button.setObjectName("viewSwitchButton")
        button.setMinimumSize(180, 42)
        frame = QFrame()
        frame.setObjectName("pictureInPicture")
        frame.setMinimumSize(260, 170)
        frame.setMaximumSize(360, 240)
        layout = QGridLayout(frame)
        layout.addWidget(content, 0, 0)
        layout.addWidget(button, 0, 0, Qt.AlignRight | Qt.AlignBottom)
        return frame, button

    def show_map_view(self) -> None:
        self.stack.setCurrentIndex(self.MAP_VIEW)
        self.view_changed.emit("地图主视角")

    def show_video_view(self) -> None:
        self.stack.setCurrentIndex(self.VIDEO_VIEW)
        self.view_changed.emit("视频主视角（Demo占位）")

    def set_home(self, longitude_deg: float, latitude_deg: float) -> None:
        first_home = self.map_model.home is None
        self.map_model.set_home(longitude_deg, latitude_deg)
        if first_home:
            self.map_widget.center_on_home()
            self.mini_map.center_on_home()

    def update_tracks(self, tracks: Iterable[TrackLifecycleSnapshot]) -> None:
        self.map_model.update_tracks(tracks)

    def set_selected_track(self, absolute_id: int | None) -> None:
        self.map_model.set_selected_track(absolute_id)

    def center_on_home(self) -> None:
        self.map_widget.center_on_home()

    def set_online_map(self, online: bool) -> None:
        self.map_widget.set_online(online)

    def set_tile_url(self, tile_url: str) -> None:
        self.map_widget.set_tile_url(tile_url)

    def set_history_limit(self, history_limit: int) -> None:
        self.map_model.set_history_limit(history_limit)

    def configure_video(self, config: VideoSourceConfig) -> None:
        self.video_main.configure(config)
        self.video_preview.configure(config)

    def shutdown(self) -> bool:
        return self.video_main.shutdown() and self.video_preview.shutdown()
