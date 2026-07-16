from __future__ import annotations

import socket
import time

import pytest
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication, QDialogButtonBox, QLabel, QPushButton, QSizePolicy

from ground_station.config import DemoAppSettings
from ground_station.domain import MissionMode
from ground_station.network import RadarReceiverConfig, RadarUdpReceiver
from ground_station.radar_protocol import RadarTrackFrameParser
from ground_station.radar_protocol.simulator import (
    SimulatedTrack,
    build_track_datagram,
    scenario_datagram,
)
from ground_station.selection import SelectionStatus
from ground_station.ui import GroundStationMainWindow


def free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def parsed_frame(scenario: str = "multi-moving", tick: int = 0):
    result = RadarTrackFrameParser().parse(scenario_datagram(scenario, tick=tick))
    assert result.ok and result.frame is not None
    return result.frame


def make_window(qtbot, **overrides) -> GroundStationMainWindow:
    values = {
        "radar_listen_port": free_udp_port(),
        "drone_port": free_udp_port(),
        "log_max_lines": 100,
    }
    values.update(overrides)
    window = GroundStationMainWindow(DemoAppSettings(**values))
    qtbot.addWidget(window)
    window.show()
    return window


def send_udp(port: int, payload: bytes) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(payload, ("127.0.0.1", port))
    finally:
        sock.close()


def assert_tab_bar_uses_dark_background(tab_widget) -> None:
    """从实际离屏渲染结果验证页签底色，而不是只匹配QSS字符串。"""

    tab_bar = tab_widget.tabBar()
    for index in range(tab_widget.count()):
        tab_widget.setCurrentIndex(index)
        QApplication.processEvents()
        rect = tab_bar.tabRect(index)
        color = tab_bar.grab().toImage().pixelColor(rect.left() + 4, rect.top() + 4)
        assert color.red() + color.green() + color.blue() < 500


def test_main_window_can_create_and_close_offscreen(qtbot) -> None:
    window = make_window(qtbot)
    assert window.windowTitle()
    window.close()
    assert window.closed_cleanly


def test_layout_gives_logs_and_track_table_expandable_space(qtbot) -> None:
    window = make_window(qtbot)
    QApplication.processEvents()
    assert window.main_splitter.count() == 3
    assert window.log_tabs.minimumHeight() >= 140
    assert window.business_splitter.count() == 2
    assert window.right_splitter.count() == 4
    assert window.workspace.stack.count() == 2
    assert window.track_table.minimumHeight() >= 145
    assert window.track_table.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert window.findChild(QPushButton, "locateCurrentTargetButton") is None
    assert "source" in window.config_summary
    assert window.config_summary["radar"].text()
    assert window.config_summary["source"].text()
    assert window.settings_button.minimumHeight() >= 32
    window.close()


def test_log_tab_bar_renders_with_dark_selected_and_unselected_tabs(qtbot) -> None:
    window = make_window(qtbot)
    assert_tab_bar_uses_dark_background(window.log_tabs)
    window.close()


def test_radar_receiver_thread_does_not_block_qt_event_loop(qtbot) -> None:
    receiver = RadarUdpReceiver()
    port = free_udp_port()
    receiver.start(RadarReceiverConfig("127.0.0.1", port))
    qtbot.waitUntil(lambda: receiver.running, timeout=1000)
    ticks: list[bool] = []
    QTimer.singleShot(30, lambda: ticks.append(True))
    qtbot.waitUntil(lambda: bool(ticks), timeout=500)
    assert receiver.stop(2000)
    assert not receiver.running


def test_valid_udp_frame_updates_radar_and_track_table(qtbot) -> None:
    window = make_window(qtbot)
    port = window.radar_port.value()
    qtbot.mouseClick(window.radar_toggle, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.status_labels["radar"].text() == "监听中")
    send_udp(port, scenario_datagram("multi-moving", tick=0))
    qtbot.waitUntil(lambda: window.controller.valid_radar_frames == 1)
    assert window.track_table.rowCount() == 4
    assert window.radar_labels["lon"].text() == "109.00600°"
    assert window.radar_labels["sat"].text() == "12"
    window.close()


def test_bad_checksum_never_enters_track_repository(qtbot) -> None:
    window = make_window(qtbot)
    port = window.radar_port.value()
    window.radar_toggle.click()
    qtbot.waitUntil(lambda: window.status_labels["radar"].text() == "监听中")
    send_udp(port, scenario_datagram("bad-checksum"))
    qtbot.waitUntil(lambda: window.controller.invalid_radar_frames == 1)
    assert window.controller.repository.all() == ()
    assert window.track_table.rowCount() == 0
    assert "checksum_mismatch" in window.logs["protocol"].toPlainText()
    window.close()


def test_first_selection_and_table_radar_sync(qtbot) -> None:
    window = make_window(qtbot)
    window.controller.process_radar_frame(parsed_frame())
    decision = window.controller.request_selection(100_007)
    assert decision.status is SelectionStatus.SELECTED
    assert window.controller.selection.selected_absolute_id == 100_007
    assert window.workspace.map_model.selected_absolute_id == 100_007
    selected_rows = window.track_table.selectionModel().selectedRows()
    assert len(selected_rows) == 1
    selected_item = window.track_table.item(selected_rows[0].row(), 0)
    assert int(selected_item.data(Qt.UserRole)) == 100_007
    window.close()


def test_target_switch_cancel_then_confirm(qtbot, monkeypatch) -> None:
    window = make_window(qtbot)
    window.controller.process_radar_frame(parsed_frame())
    window.select_target(100_007)
    monkeypatch.setattr(window, "_confirm_target_switch", lambda _: False)
    window.select_target(100_012)
    assert window.controller.selection.selected_absolute_id == 100_007
    monkeypatch.setattr(window, "_confirm_target_switch", lambda _: True)
    window.select_target(100_012)
    assert window.controller.selection.selected_absolute_id == 100_012
    assert window.workspace.map_model.selected_absolute_id == 100_012
    window.close()


def test_switch_request_contains_old_and_new_target_details(qtbot) -> None:
    window = make_window(qtbot)
    window.controller.process_radar_frame(parsed_frame())
    window.controller.request_selection(100_007)
    decision = window.controller.request_selection(100_012)
    assert decision.status is SelectionStatus.CONFIRMATION_REQUIRED
    assert decision.confirmation is not None
    assert decision.confirmation.old_target.display_id == 7
    assert decision.confirmation.new_target.display_id == 12
    assert decision.confirmation.old_target.longitude_deg is not None
    assert decision.confirmation.new_target.longitude_deg is not None
    window.controller.cancel_selection(decision.confirmation)
    window.close()


@pytest.mark.parametrize("mode", list(MissionMode))
def test_five_mode_buttons_map_to_protocol_values(qtbot, mode: MissionMode) -> None:
    window = make_window(qtbot)
    window.mode_buttons[mode].click()
    assert window.controller.mission.mode is mode
    assert window.mode_group.checkedId() == int(mode)
    window.close()


def test_cleared_target_ui_keeps_coordinate_and_marks_lost(qtbot) -> None:
    window = make_window(qtbot)
    now = time.monotonic()
    window.controller.process_radar_frame(
        parsed_frame("multi-moving", 0), received_monotonic=now, received_unix_ms=1000
    )
    window.select_target(100_007)
    before = window.target_labels["coordinate"].text()
    window.controller.process_radar_frame(
        parsed_frame("multi-moving-clear", 1), received_monotonic=now + 0.1, received_unix_ms=1100
    )
    assert window.target_labels["coordinate"].text() == before
    assert "最后有效坐标" in window.target_labels["realtime"].text()
    assert window.controller.selection.selected_absolute_id == 100_007
    window.close()


def test_timeout_lost_duration_increases(qtbot) -> None:
    window = make_window(qtbot, track_stale_timeout_ms=100)
    window.controller.process_radar_frame(parsed_frame("one"))
    window.select_target(100_007)
    qtbot.wait(140)
    window.controller.refresh_tracks()
    first = window.controller.selection.selected_track().lost_duration_ms  # type: ignore[union-attr]
    qtbot.wait(60)
    window.controller.refresh_tracks()
    second = window.controller.selection.selected_track().lost_duration_ms  # type: ignore[union-attr]
    assert second > first >= 100
    assert "最后有效坐标" in window.target_labels["realtime"].text()
    window.close()


def test_ui_displays_about_2300ms_after_2300ms_without_update(qtbot) -> None:
    window = make_window(qtbot, track_stale_timeout_ms=2000)
    received = time.monotonic() - 2.3
    window.controller.process_radar_frame(
        parsed_frame("one"), received_monotonic=received, received_unix_ms=7777
    )
    window.select_target(100_007)
    window.controller.refresh_tracks()
    displayed = int(window.target_labels["lost"].text().split()[0])
    assert displayed == pytest.approx(2300, abs=100)
    assert "最后有效坐标" in window.target_labels["realtime"].text()
    assert window.controller.mission.build_snapshot(1).target_coordinate_timestamp_unix_ms == 7777
    window.close()


def test_mode_and_confirmed_switch_trigger_immediate_send(qtbot, monkeypatch) -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    window = make_window(qtbot, drone_port=receiver.getsockname()[1])
    window.controller.process_radar_frame(parsed_frame())
    window.select_target(100_007)
    window.send_toggle.click()
    qtbot.waitUntil(lambda: window.controller.send_success_count >= 1)
    window.mode_buttons[MissionMode.TRACK].click()
    qtbot.waitUntil(
        lambda: "mission_mode_changed" in window.logs["send"].toPlainText(), timeout=1000
    )
    monkeypatch.setattr(window, "_confirm_target_switch", lambda _: True)
    window.select_target(100_012)
    qtbot.waitUntil(
        lambda: "target_switch_confirmed" in window.logs["send"].toPlainText(), timeout=1000
    )
    window.close()
    receiver.close()


def test_start_send_near_5hz_and_stop_prevents_new_datagrams(qtbot) -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(1.5)
    window = make_window(qtbot, drone_port=receiver.getsockname()[1])
    window.send_toggle.click()
    arrivals = []
    for _ in range(6):
        receiver.recvfrom(1024)
        arrivals.append(time.monotonic())
    measured = 5 / (arrivals[-1] - arrivals[0])
    assert measured == pytest.approx(5.0, abs=0.5)
    window.send_toggle.click()
    qtbot.waitUntil(lambda: not window.controller.sending)
    receiver.settimeout(0.35)
    with pytest.raises(socket.timeout):
        receiver.recvfrom(1024)
    window.close()
    receiver.close()


def test_close_window_stops_threads_sockets_and_port_rebinds(qtbot) -> None:
    radar_port = free_udp_port()
    drone_port = free_udp_port()
    window = make_window(qtbot, radar_listen_port=radar_port, drone_port=drone_port)
    window.radar_toggle.click()
    qtbot.waitUntil(lambda: window.status_labels["radar"].text() == "监听中")
    window.send_toggle.click()
    qtbot.waitUntil(lambda: window.controller.sending)
    window.close()
    assert window.closed_cleanly
    assert not window.controller.radar_receiver.running
    assert not window.controller.sending
    rebound = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        rebound.bind(("127.0.0.1", radar_port))
    finally:
        rebound.close()


def test_logs_are_automatically_cropped(qtbot) -> None:
    window = make_window(qtbot, log_max_lines=100)
    for index in range(180):
        window._append_log("runtime", f"line {index}")
    QApplication.processEvents()
    assert window.logs["runtime"].document().blockCount() <= 100
    assert "line 179" in window.logs["runtime"].toPlainText()
    assert "line 0\n" not in window.logs["runtime"].toPlainText()
    window.close()


def test_radar_click_and_sorted_table_keep_absolute_id_selection(qtbot, monkeypatch) -> None:
    window = make_window(qtbot)
    window.controller.process_radar_frame(parsed_frame())
    window.track_table.sortItems(1, Qt.DescendingOrder)
    window.workspace.target_clicked.emit(100_007)
    assert window.controller.selection.selected_absolute_id == 100_007
    monkeypatch.setattr(window, "_confirm_target_switch", lambda _: True)
    window.workspace.target_clicked.emit(100_012)
    assert window.controller.selection.selected_absolute_id == 100_012
    selected_rows = window.track_table.selectionModel().selectedRows()
    current = window.track_table.item(selected_rows[0].row(), 0)
    assert int(current.data(Qt.UserRole)) == 100_012
    window.close()


def test_network_settings_dialog_is_usable_and_applies_live_timeout(qtbot) -> None:
    window = make_window(qtbot)
    window.settings_button.click()
    dialog = window.settings_dialog
    qtbot.waitUntil(dialog.isVisible)
    assert dialog.minimumWidth() >= 560
    assert dialog.tabs.count() == 2
    assert dialog.system_tabs.count() == 5
    assert "尚不可用" in dialog.calibration_page.findChild(
        QLabel, "calibrationUnavailableMessage"
    ).text()
    assert_tab_bar_uses_dark_background(dialog.tabs)
    assert_tab_bar_uses_dark_background(dialog.system_tabs)
    for control in (
        dialog.radar_host,
        dialog.radar_port,
        dialog.drone_host,
        dialog.drone_port,
        dialog.frequency,
        dialog.timeout_ms,
        dialog.byte_order,
    ):
        assert control.minimumHeight() >= 30
    assert dialog.radar_host.minimumWidth() >= 280
    dialog.timeout_ms.setValue(333)
    dialog.button_box.button(QDialogButtonBox.Apply).click()
    assert window.controller.repository.stale_timeout_ms == 333
    assert "333 ms" in window.config_summary["timeout"].text()
    dialog.set_running_state(radar_listening=True, sending=True)
    assert not dialog.radar_host.isEnabled()
    assert not dialog.drone_host.isEnabled()
    assert dialog.timeout_ms.isEnabled()
    window.close()


def test_periodic_track_refresh_preserves_manual_scroll_until_confirmed_switch(qtbot, monkeypatch) -> None:
    window = make_window(qtbot)
    tracks = [
        SimulatedTrack(
            display_id=index + 1,
            absolute_id=500_000 + index,
            longitude_deg=109.0 + index * 0.00001,
            latitude_deg=34.0 + index * 0.00001,
            height_m=10 + index,
        )
        for index in range(50)
    ]
    result = RadarTrackFrameParser().parse(build_track_datagram(tracks))
    assert result.ok and result.frame is not None
    window.controller.process_radar_frame(result.frame)
    window.select_target(500_001)
    QApplication.processEvents()
    scroll_bar = window.track_table.verticalScrollBar()
    scroll_bar.setValue(scroll_bar.maximum())
    bottom = scroll_bar.value()
    assert bottom > 0
    for _ in range(5):
        window.controller.refresh_tracks()
        QApplication.processEvents()
    assert scroll_bar.value() == bottom
    assert window.controller.selection.selected_absolute_id == 500_001
    selected_rows = window.track_table.selectionModel().selectedRows()
    assert len(selected_rows) == 1
    assert int(window.track_table.item(selected_rows[0].row(), 0).data(Qt.UserRole)) == 500_001

    monkeypatch.setattr(window, "_confirm_target_switch", lambda _: True)
    window.select_target(500_010)
    assert window.controller.selection.selected_absolute_id == 500_010
    assert scroll_bar.value() < bottom
    window.close()


def test_udp_status_does_not_claim_receiver_ack_after_receiver_closes(qtbot) -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    window = make_window(qtbot, drone_port=receiver.getsockname()[1])
    window.send_toggle.click()
    qtbot.waitUntil(lambda: window.controller.send_success_count >= 2, timeout=1500)
    before_close = window.controller.send_success_count
    receiver.close()
    qtbot.waitUntil(lambda: window.controller.send_success_count >= before_close + 2, timeout=1500)
    assert "发送中" in window.status_labels["send"].text()
    assert "无接收确认" in window.status_labels["send"].text()
    assert window.status_labels["ack"].text() == "未知（Demo协议无ACK）"
    assert window.controller.send_failure_count == 0
    window.close()


def test_listener_remains_active_while_radar_data_times_out(qtbot) -> None:
    window = make_window(qtbot, track_stale_timeout_ms=100)
    port = window.radar_port.value()
    window.radar_toggle.click()
    qtbot.waitUntil(lambda: window.status_labels["radar"].text() == "监听中")
    send_udp(port, scenario_datagram("one"))
    qtbot.waitUntil(lambda: window.controller.valid_radar_frames == 1)
    window.select_target(100_007)
    invalid_before = window.controller.invalid_radar_frames
    qtbot.waitUntil(lambda: window.status_labels["radar_data"].text() == "数据超时", timeout=1200)
    assert window.controller.radar_receiver.running
    assert window.status_labels["radar"].text() == "监听中"
    assert window.controller.invalid_radar_frames == invalid_before
    selected = window.controller.selection.selected_track()
    assert selected is not None and not selected.is_realtime
    assert selected.last_valid_coordinate is not None
    window.close()


def test_unix_wall_clock_is_used_for_dates_and_monotonic_is_not_rendered(qtbot) -> None:
    window = make_window(qtbot)
    received_monotonic = time.monotonic()
    received_unix_ms = 1_767_225_600_000  # 2026-01-01T00:00:00Z
    window.controller.process_radar_frame(
        parsed_frame("one"),
        received_monotonic=received_monotonic,
        received_unix_ms=received_unix_ms,
    )
    window._refresh_ui_tick()
    window.select_target(100_007)
    assert "2026" in window.status_labels["radar_time"].text()
    assert "2026" in window.radar_labels["updated"].text()
    assert "2026" in window.target_labels["timestamp"].text()
    assert "1970" not in window._format_unix_ms(int(received_monotonic * 1000))
    first_snapshot = window.controller.mission.build_snapshot(1)
    assert first_snapshot.target_coordinate_timestamp_unix_ms == received_unix_ms
    window.controller.process_radar_frame(
        parsed_frame("multi-moving-clear"),
        received_monotonic=received_monotonic + 0.1,
        received_unix_ms=received_unix_ms + 100,
    )
    lost_snapshot = window.controller.mission.build_snapshot(2)
    assert lost_snapshot.target_coordinate_timestamp_unix_ms == received_unix_ms
    window.close()
