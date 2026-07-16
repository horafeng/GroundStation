"""Map-first operation workspace with stable overlay controls."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from PyQt5.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ground_station.domain import MissionMode
from ground_station.map import MapSceneModel, MapWidget
from ground_station.tracks import TrackLifecycleSnapshot
from ground_station.video import VideoPlaceholderWidget, VideoSourceConfig


MODE_NAMES = {
    MissionMode.STANDBY: "待命",
    MissionMode.TAKEOFF: "起飞",
    MissionMode.TRACK: "跟踪",
    MissionMode.RETURN_HOME: "返航",
    MissionMode.LAND: "降落",
}
TARGET_TYPE_NAMES = {
    0: "未知",
    1: "车辆",
    2: "人员",
    3: "无人机",
    4: "保留4",
    5: "保留5",
    6: "保留6",
    7: "保留7",
}


class _ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()
        super().mouseReleaseEvent(event)  # type: ignore[arg-type]


class TargetSummaryCard(QFrame):
    """Compact target summary that expands without replacing the widget."""

    expanded_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("targetSummaryCard")
        self.setMaximumWidth(350)
        self.setMinimumWidth(285)
        self._expanded = False
        self._has_target = False
        self._track: TrackLifecycleSnapshot | None = None

        self.title = QLabel("尚未选择目标")
        self.title.setObjectName("targetCardTitle")
        self.state = QLabel("单击地图目标或在运行检查中选择")
        self.state.setObjectName("targetCardState")
        self.compact = QLabel("目标坐标无效")
        self.compact.setObjectName("targetCardCompact")
        self.toggle_hint = QLabel("展开 ▾")
        self.toggle_hint.setObjectName("targetCardToggleHint")

        header = QHBoxLayout()
        header.addWidget(self.title, 1)
        header.addWidget(self.state)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(5)
        root.addLayout(header)
        root.addWidget(self.compact)

        self.details = QWidget()
        detail_layout = QGridLayout(self.details)
        detail_layout.setContentsMargins(0, 5, 0, 0)
        detail_layout.setHorizontalSpacing(12)
        detail_layout.setVerticalSpacing(4)
        self.detail_labels: dict[str, QLabel] = {}
        for row, (key, heading) in enumerate(
            (
                ("type", "类型"),
                ("absolute", "绝对编号"),
                ("coordinate", "经纬度"),
                ("timestamp", "坐标时间"),
                ("status", "发送坐标"),
            )
        ):
            caption = QLabel(heading)
            caption.setObjectName("targetCardCaption")
            value = QLabel("--")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            detail_layout.addWidget(caption, row, 0, Qt.AlignTop)
            detail_layout.addWidget(value, row, 1)
            self.detail_labels[key] = value
        self.details.hide()
        root.addWidget(self.details)
        root.addWidget(self.toggle_hint, 0, Qt.AlignRight)

        for widget in self.findChildren(QWidget):
            if isinstance(widget, QLabel):
                widget.installEventFilter(self)
        self.installEventFilter(self)
        self._refresh_visibility()

    @property
    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded) and self._has_target
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._refresh_visibility()
        self.expanded_changed.emit(expanded)

    def toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def set_target(self, track: TrackLifecycleSnapshot | None) -> None:
        self._track = track
        self._has_target = track is not None and track.last_valid_coordinate is not None
        if not self._has_target:
            self._expanded = False
            self.title.setText("尚未选择目标")
            self.state.setText("等待人工选择")
            self.compact.setText("单击地图目标或打开“运行检查”选择")
            self._refresh_visibility()
            return

        assert track is not None and track.last_valid_coordinate is not None
        coordinate = track.last_valid_coordinate
        observation = track.latest_observation
        self.title.setText(f"航迹 {track.display_id}")
        if track.is_realtime:
            self.state.setText("● 实时")
            self.state.setProperty("lost", False)
        else:
            self.state.setText("● 已丢失")
            self.state.setProperty("lost", True)
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        self.compact.setText(
            f"{observation.distance_m:.0f} m   {observation.speed_mps:.1f} m/s   "
            f"{coordinate.relative_ground_height_m:.1f} m"
            + ("" if track.is_realtime else f"   丢失 {track.lost_duration_ms / 1000:.1f} s")
        )
        self.detail_labels["type"].setText(TARGET_TYPE_NAMES[int(observation.target_type)])
        self.detail_labels["absolute"].setText(str(track.absolute_id))
        self.detail_labels["coordinate"].setText(
            f"{coordinate.longitude_deg:.7f}, {coordinate.latitude_deg:.7f}"
        )
        self.detail_labels["timestamp"].setText(
            datetime.fromtimestamp(coordinate.received_unix_ms / 1000).strftime(
                "%Y-%m-%d %H:%M:%S.%f"
            )[:-3]
        )
        self.detail_labels["status"].setText(
            "最新实时坐标" if track.is_realtime else "最后有效坐标（继续循环发送）"
        )
        self._refresh_visibility()

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() == QEvent.MouseButtonRelease and self._has_target:
            if event.button() == Qt.LeftButton:  # type: ignore[attr-defined]
                self.toggle_expanded()
                return True
        return super().eventFilter(watched, event)

    def _refresh_visibility(self) -> None:
        self.details.setVisible(self._expanded and self._has_target)
        self.toggle_hint.setVisible(self._has_target)
        self.toggle_hint.setText("收起 ▴" if self._expanded else "展开 ▾")


class MissionControlOverlay(QFrame):
    mode_clicked = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("missionControlOverlay")
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[MissionMode, QPushButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        icons = {
            MissionMode.STANDBY: QStyle.SP_MediaPause,
            MissionMode.TAKEOFF: QStyle.SP_ArrowUp,
            MissionMode.TRACK: QStyle.SP_DialogYesButton,
            MissionMode.RETURN_HOME: QStyle.SP_ArrowBack,
            MissionMode.LAND: QStyle.SP_ArrowDown,
        }
        for mode in MissionMode:
            button = QPushButton(MODE_NAMES[mode])
            button.setObjectName(f"modeButton{int(mode)}")
            button.setIcon(self.style().standardIcon(icons[mode]))
            button.setCheckable(True)
            button.setMinimumSize(76, 40)
            button.setToolTip(f"任务模式：{MODE_NAMES[mode]}（{int(mode)}）")
            self.mode_group.addButton(button, int(mode))
            self.mode_buttons[mode] = button
            layout.addWidget(button)
        self.mode_group.buttonClicked[int].connect(self.mode_clicked)


class OperationToast(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("operationToast")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(280)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, duration_ms: int = 3500) -> None:
        self.setText(text)
        self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(duration_ms)


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
        self.mission_controls = MissionControlOverlay()
        self.mode_group = self.mission_controls.mode_group
        self.mode_buttons = self.mission_controls.mode_buttons
        self.target_card = TargetSummaryCard()
        self.toast = OperationToast()
        self.stack = QStackedWidget()
        self.stack.addWidget(self._map_page())
        self.stack.addWidget(self._video_page())
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        layout.addWidget(self.mission_controls, 0, 0, Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self.target_card, 0, 0, Qt.AlignRight | Qt.AlignTop)
        layout.addWidget(self.toast, 0, 0, Qt.AlignHCenter | Qt.AlignTop)
        layout.setContentsMargins(10, 10, 10, 10)
        self.map_widget.target_clicked.connect(self.target_clicked)
        self.mini_map.target_clicked.connect(self.target_clicked)
        self.map_widget.status_changed.connect(self.map_status_changed)

    def _map_page(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.map_widget, 0, 0)
        preview, button = self._preview_frame(self.video_preview, "切换为视频主视角")
        button.clicked.connect(self.show_video_view)
        preview.clicked.connect(self.show_video_view)
        layout.addWidget(preview, 0, 0, Qt.AlignLeft | Qt.AlignBottom)
        return page

    def _video_page(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video_main, 0, 0)
        preview, button = self._preview_frame(self.mini_map, "恢复地图主视角")
        button.clicked.connect(self.show_map_view)
        preview.clicked.connect(self.show_map_view)
        layout.addWidget(preview, 0, 0, Qt.AlignLeft | Qt.AlignBottom)
        return page

    @staticmethod
    def _preview_frame(content: QWidget, button_text: str) -> tuple[_ClickableFrame, QPushButton]:
        button = QPushButton(button_text)
        button.setObjectName("viewSwitchButton")
        button.setMinimumSize(180, 42)
        frame = _ClickableFrame()
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

    def set_target_summary(self, track: TrackLifecycleSnapshot | None) -> None:
        self.target_card.set_target(track)

    def show_notification(self, text: str, duration_ms: int = 3500) -> None:
        self.toast.show_message(text, duration_ms)

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
