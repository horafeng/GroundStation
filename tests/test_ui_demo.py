from __future__ import annotations

import socket
import time

import pytest
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication

from ground_station.config import DemoAppSettings
from ground_station.domain import MissionMode
from ground_station.network import RadarReceiverConfig, RadarUdpReceiver
from ground_station.radar_protocol import RadarTrackFrameParser
from ground_station.radar_protocol.simulator import scenario_datagram
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


def test_main_window_can_create_and_close_offscreen(qtbot) -> None:
    window = make_window(qtbot)
    assert window.windowTitle()
    window.close()
    assert window.closed_cleanly


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
    qtbot.waitUntil(lambda: window.status_labels["radar"].text() == "接收中")
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
    qtbot.waitUntil(lambda: window.status_labels["radar"].text() == "接收中")
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
    assert window.radar_display.selected_absolute_id == 100_007
    selected_item = window.track_table.item(window.track_table.currentRow(), 0)
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
    assert window.radar_display.selected_absolute_id == 100_012
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
    qtbot.waitUntil(lambda: window.status_labels["radar"].text() == "接收中")
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
    window.radar_display.track_clicked.emit(100_007)
    assert window.controller.selection.selected_absolute_id == 100_007
    monkeypatch.setattr(window, "_confirm_target_switch", lambda _: True)
    window.radar_display.track_clicked.emit(100_012)
    assert window.controller.selection.selected_absolute_id == 100_012
    current = window.track_table.item(window.track_table.currentRow(), 0)
    assert int(current.data(Qt.UserRole)) == 100_012
    window.close()
