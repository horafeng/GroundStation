from __future__ import annotations

import time

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QLabel

from ground_station.config import DemoAppSettings
from ground_station.map import MapSceneModel, MapWidget
from ground_station.radar_protocol import RadarTrackFrameParser
from ground_station.radar_protocol.simulator import scenario_datagram
from ground_station.tracks import TrackRepository
from ground_station.ui import GroundStationMainWindow
from ground_station.ui.main_workspace import MainWorkspace
from ground_station.video import VideoSourceConfig


def snapshots(
    scenario: str = "multi-moving", tick: int = 0, *, now: float = 100.0
):
    result = RadarTrackFrameParser().parse(scenario_datagram(scenario, tick=tick))
    assert result.ok and result.frame is not None
    repository = TrackRepository(stale_timeout_ms=2000)
    repository.update_frame(
        result.frame, received_monotonic=now, received_unix_ms=1_767_225_600_000
    )
    return repository, repository.all(now_monotonic=now)


def test_map_model_home_markers_selection_and_lost_state(qtbot) -> None:
    model = MapSceneModel(refresh_interval_ms=10)
    repository, tracks = snapshots()
    model.set_home(109.006, 34.116)
    model.update_tracks(tracks)
    model.set_selected_track(100_007)
    qtbot.wait(20)
    assert model.home == (109.006, 34.116)
    assert len(model.markers) == 4
    assert model.markers[100_007].is_selected
    lost_tracks = repository.refresh(now_monotonic=102.3)
    model.update_tracks(lost_tracks)
    qtbot.wait(20)
    assert not model.markers[100_007].is_realtime
    assert model.markers[100_007].is_selected


def test_track_history_has_configured_upper_bound(qtbot) -> None:
    model = MapSceneModel(history_limit=3, refresh_interval_ms=1)
    repository = TrackRepository()
    for tick in range(7):
        result = RadarTrackFrameParser().parse(
            scenario_datagram("multi-moving", tick=tick)
        )
        assert result.ok and result.frame is not None
        repository.update_frame(
            result.frame,
            received_monotonic=100.0 + tick / 10,
            received_unix_ms=1_767_225_600_000 + tick * 100,
        )
        model.update_tracks(repository.all(now_monotonic=100.0 + tick / 10))
    qtbot.wait(5)
    assert len(model.markers[100_007].history) == 3
    model.set_history_limit(2)
    assert len(model.markers[100_007].history) == 2


def test_map_refresh_notifications_are_coalesced_to_ten_hz(qtbot) -> None:
    model = MapSceneModel(refresh_interval_ms=100)
    emissions: list[float] = []
    model.changed.connect(lambda: emissions.append(time.monotonic()))
    _, tracks = snapshots()
    for _ in range(30):
        model.update_tracks(tracks)
    qtbot.wait(130)
    assert len(emissions) == 1


def test_local_map_is_interactive_and_can_center_on_home(qtbot) -> None:
    widget = MapWidget(online=False)
    qtbot.addWidget(widget)
    widget.resize(800, 500)
    widget.show()
    widget.set_home(110.25, 35.5)
    widget.center_on_home()
    before = widget.canvas.zoom
    qtbot.mouseClick(widget.zoom_in_button, Qt.LeftButton)
    assert widget.canvas.center == (110.25, 35.5)
    assert widget.canvas.zoom == before + 1
    assert "本地Demo地图" in widget.status_label.text()


def test_online_map_identifies_openstreetmap_attribution(qtbot) -> None:
    widget = MapWidget(online=True)
    qtbot.addWidget(widget)
    assert "OpenStreetMap contributors" in widget.status_label.text()
    widget.set_online(False)
    assert "本地Demo地图" in widget.status_label.text()


def test_map_target_signal_uses_absolute_id(qtbot) -> None:
    widget = MapWidget(online=False)
    qtbot.addWidget(widget)
    clicked: list[int] = []
    widget.target_clicked.connect(clicked.append)
    widget.canvas.target_clicked.emit(100_012)
    assert clicked == [100_012]


def test_map_and_video_main_views_switch_without_decoder(qtbot) -> None:
    workspace = MainWorkspace()
    qtbot.addWidget(workspace)
    assert workspace.stack.currentIndex() == MainWorkspace.MAP_VIEW
    workspace.show_video_view()
    assert workspace.stack.currentIndex() == MainWorkspace.VIDEO_VIEW
    workspace.configure_video(VideoSourceConfig("test_pattern"))
    assert "测试图案" in workspace.video_main.message.text()
    workspace.show_map_view()
    assert workspace.stack.currentIndex() == MainWorkspace.MAP_VIEW
    assert workspace.shutdown()


def test_mission_controls_are_vertical_icon_text_overlay(qtbot) -> None:
    workspace = MainWorkspace()
    qtbot.addWidget(workspace)
    workspace.resize(1000, 700)
    workspace.show()
    QApplication.processEvents()
    buttons = list(workspace.mode_buttons.values())
    assert [button.text() for button in buttons] == ["待命", "起飞", "跟踪", "返航", "降落"]
    assert all(not button.icon().isNull() for button in buttons)
    assert all(button.parent() is workspace.mission_controls for button in buttons)
    assert all(first.y() < second.y() for first, second in zip(buttons, buttons[1:]))
    assert workspace.mission_controls.geometry().left() >= workspace.rect().left()


def test_target_card_click_expand_is_stable_across_refresh_and_view_switch(qtbot) -> None:
    repository, tracks = snapshots()
    workspace = MainWorkspace()
    qtbot.addWidget(workspace)
    workspace.resize(1000, 700)
    workspace.show()
    target = tracks[0]
    workspace.set_target_summary(target)
    QApplication.processEvents()
    card = workspace.target_card
    details_identity = id(card.details)
    assert not card.expanded

    qtbot.mouseClick(card, Qt.LeftButton)
    QApplication.processEvents()
    assert card.expanded and card.details.isVisible()
    assert id(card.details) == details_identity
    workspace.show_video_view()
    workspace.set_target_summary(target)
    QApplication.processEvents()
    assert card.expanded and card.details.isVisible()

    lost = repository.refresh(now_monotonic=102.3)[0]
    coordinate_timestamp = card.detail_labels["timestamp"].text()
    workspace.set_target_summary(lost)
    QApplication.processEvents()
    assert card.expanded
    assert "最后有效坐标" in card.detail_labels["status"].text()
    assert card.detail_labels["timestamp"].text() == coordinate_timestamp
    assert workspace.rect().contains(card.geometry())

    qtbot.mouseClick(card, Qt.LeftButton)
    QApplication.processEvents()
    assert not card.expanded and not card.details.isVisible()
    assert id(card.details) == details_identity
    assert workspace.shutdown()


def test_rtsp_placeholder_does_not_claim_connection(qtbot) -> None:
    workspace = MainWorkspace()
    qtbot.addWidget(workspace)
    workspace.configure_video(VideoSourceConfig("rtsp", "rtsp://127.0.0.1/demo"))
    assert "已配置" in workspace.video_main.message.text()
    assert "未启用解码器" in workspace.video_main.message.text()


def test_map_click_routes_to_existing_selection_and_confirmation(qtbot, monkeypatch) -> None:
    window = GroundStationMainWindow(DemoAppSettings())
    qtbot.addWidget(window)
    result = RadarTrackFrameParser().parse(scenario_datagram("multi-moving"))
    assert result.ok and result.frame is not None
    window.controller.process_radar_frame(result.frame)
    window.workspace.target_clicked.emit(100_007)
    assert window.controller.selection.selected_absolute_id == 100_007
    monkeypatch.setattr(window, "_confirm_target_switch", lambda _: False)
    window.workspace.target_clicked.emit(100_012)
    assert window.controller.selection.selected_absolute_id == 100_007
    monkeypatch.setattr(window, "_confirm_target_switch", lambda _: True)
    window.workspace.target_clicked.emit(100_012)
    assert window.controller.selection.selected_absolute_id == 100_012
    window.close()


def test_settings_have_two_primary_tabs_and_unavailable_calibration(qtbot) -> None:
    window = GroundStationMainWindow(DemoAppSettings())
    qtbot.addWidget(window)
    dialog = window.settings_dialog
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        "系统设置",
        "人机校验",
    ]
    message = dialog.calibration_page.findChild(
        QLabel, "calibrationUnavailableMessage"
    )
    assert message is not None and "尚不可用" in message.text()
    assert all(not button.isEnabled() for button in dialog.calibration_page.findChildren(type(window.settings_button)))
    window.close()


def test_map_is_dominant_at_supported_window_sizes(qtbot) -> None:
    window = GroundStationMainWindow(DemoAppSettings())
    qtbot.addWidget(window)
    for size in ((1366, 768), (1920, 1080)):
        window.resize(*size)
        window.show()
        QApplication.processEvents()
        assert window.workspace.width() >= window.centralWidget().width() - 24
        assert window.workspace.height() >= window.centralWidget().height() - 100
        assert not window.runtime_inspection.isVisible()
        assert window.workspace.mission_controls.isVisible()
        assert window.workspace.target_card.isVisible()
    window.close()
