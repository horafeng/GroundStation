from __future__ import annotations

import socket
import threading
import time

import pytest

from ground_station.domain import (
    HeightReference,
    MissionMode,
    MissionSnapshot,
    RadarTrack,
    TargetTimeFields,
    TargetType,
    TasTwsFlag,
)
from ground_station.drone_protocol import TemporaryDemoDecoder, TemporaryDemoEncoder
from ground_station.mission import MissionStateService
from ground_station.network import DroneUdpTransport
from ground_station.selection import TargetSelectionService
from ground_station.sending import MissionSendScheduler, SendKind, SequenceGenerator
from ground_station.tracks import TrackRepository


def snapshot(sequence: int, mode: MissionMode = MissionMode.STANDBY) -> MissionSnapshot:
    return MissionSnapshot(
        message_sequence=sequence,
        drone_id=1,
        mode=mode,
        target_valid=False,
        track_absolute_id=None,
        target_longitude_deg=None,
        target_latitude_deg=None,
        target_relative_ground_height_m=None,
        target_coordinate_timestamp_unix_ms=None,
        coordinate_realtime=False,
        target_lost_duration_ms=0,
        generated_timestamp_unix_ms=time.time_ns() // 1_000_000,
    )


class CaptureTransport:
    def __init__(self, failures: int = 0) -> None:
        self.payloads: list[tuple[float, bytes]] = []
        self.closed = False
        self.failures = failures
        self.event = threading.Event()

    def send(self, payload: bytes) -> int:
        if self.failures:
            self.failures -= 1
            raise OSError("simulated UDP failure")
        self.payloads.append((time.monotonic(), payload))
        self.event.set()
        return len(payload)

    def close(self) -> None:
        self.closed = True


def wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("等待条件超时")


def test_uint32_sequence_wraps_to_zero() -> None:
    generator = SequenceGenerator(0xFFFFFFFE)
    assert [generator.next() for _ in range(4)] == [0xFFFFFFFE, 0xFFFFFFFF, 0, 1]


def test_default_5hz_periodic_send_measured() -> None:
    transport = CaptureTransport()
    scheduler = MissionSendScheduler(snapshot, TemporaryDemoEncoder(), transport, frequency_hz=5.0)
    scheduler.start()
    try:
        wait_until(lambda: len(transport.payloads) >= 6, timeout=1.3)
    finally:
        scheduler.stop()
    times = [item[0] for item in transport.payloads[:6]]
    measured_hz = (len(times) - 1) / (times[-1] - times[0])
    assert measured_hz == pytest.approx(5.0, abs=0.35)
    assert all(record.kind is SendKind.PERIODIC for record in scheduler.send_records[:6])
    assert transport.closed
    assert not scheduler.running


def test_immediate_and_periodic_share_ordered_unique_sequences() -> None:
    transport = CaptureTransport()
    scheduler = MissionSendScheduler(snapshot, TemporaryDemoEncoder(), transport, frequency_hz=5.0)
    scheduler.start()
    try:
        wait_until(lambda: len(transport.payloads) >= 1)
        scheduler.request_immediate("mission_mode_changed")
        scheduler.request_immediate("target_switch_confirmed")
        wait_until(lambda: len(transport.payloads) >= 3)
    finally:
        scheduler.stop()
    decoded = [TemporaryDemoDecoder().decode(payload) for _, payload in transport.payloads]
    sequences = [frame.message_sequence for frame in decoded]
    assert sequences == list(range(len(sequences)))
    reasons = [record.reason for record in scheduler.send_records]
    assert "mission_mode_changed" in reasons
    assert "target_switch_confirmed" in reasons


def test_udp_failure_is_structured_and_worker_continues() -> None:
    transport = CaptureTransport(failures=1)
    scheduler = MissionSendScheduler(snapshot, TemporaryDemoEncoder(), transport, frequency_hz=20.0)
    scheduler.start()
    try:
        wait_until(lambda: len(scheduler.send_errors) == 1)
        wait_until(lambda: len(transport.payloads) >= 1)
    finally:
        scheduler.stop()
    assert scheduler.send_errors[0].error_type == "OSError"
    assert scheduler.send_errors[0].to_dict()["kind"] == "periodic"
    assert scheduler.send_records[0].sequence == 1


def test_real_udp_transport_sends_bytes_and_closes_socket() -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(1.0)
    port = receiver.getsockname()[1]
    transport = DroneUdpTransport("127.0.0.1", port)
    try:
        assert transport.send(b"abc") == 3
        payload, _ = receiver.recvfrom(10)
        assert payload == b"abc"
    finally:
        transport.close()
        receiver.close()
    assert transport.closed
    with pytest.raises(OSError):
        transport.send(b"after-close")


def test_mode_change_and_confirmed_target_switch_trigger_service_integrated_immediate_frames() -> None:
    def track(absolute_id: int, display_id: int) -> RadarTrack:
        return RadarTrack(
            display_id, absolute_id, 10.0, 20.0, 1.0, TargetType.UNKNOWN, 2.0,
            TasTwsFlag.TWS, False, TargetType.UNKNOWN, 121.0 + absolute_id / 10000,
            31.0, 5, HeightReference.DEMO_RELATIVE_GROUND_UNVERIFIED,
            TargetTimeFields(1, 1), (0,) * 16,
        )

    repository = TrackRepository()
    repository.update_observation(track(100, 7))
    repository.update_observation(track(200, 12))
    scheduler_holder: list[MissionSendScheduler] = []
    event_sink = lambda event: scheduler_holder[0].request_immediate(event)
    selection = TargetSelectionService(repository, event_sink=event_sink)
    mission = MissionStateService(selection, drone_id=1, event_sink=event_sink)
    transport = CaptureTransport()
    scheduler = MissionSendScheduler(mission.build_snapshot, TemporaryDemoEncoder(), transport)
    scheduler_holder.append(scheduler)
    scheduler.start()
    try:
        wait_until(lambda: len(transport.payloads) >= 1)
        selection.request_selection(100)
        wait_until(lambda: any(r.reason == "initial_target_selected" for r in scheduler.send_records))
        mission.set_mode(MissionMode.TRACK)
        wait_until(lambda: any(r.reason == "mission_mode_changed" for r in scheduler.send_records))
        pending = selection.request_selection(200).confirmation
        assert pending is not None
        count_before_confirm = len(scheduler.send_records)
        time.sleep(0.03)
        assert not any(r.reason == "target_switch_confirmed" for r in scheduler.send_records)
        selection.confirm_switch(pending)
        wait_until(lambda: any(r.reason == "target_switch_confirmed" for r in scheduler.send_records))
        assert len(scheduler.send_records) > count_before_confirm
    finally:
        scheduler.stop()
    frames = [TemporaryDemoDecoder().decode(payload) for _, payload in transport.payloads]
    assert [frame.message_sequence for frame in frames] == list(range(len(frames)))
    assert frames[-1].track_absolute_id == 200


def test_5hz_over_real_udp_loopback() -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(1.5)
    transport = DroneUdpTransport("127.0.0.1", receiver.getsockname()[1])
    scheduler = MissionSendScheduler(snapshot, TemporaryDemoEncoder(), transport, frequency_hz=5.0)
    arrival_times = []
    scheduler.start()
    try:
        for _ in range(6):
            payload, _ = receiver.recvfrom(1024)
            TemporaryDemoDecoder().decode(payload)
            arrival_times.append(time.monotonic())
    finally:
        scheduler.stop()
        receiver.close()
    measured_hz = 5 / (arrival_times[-1] - arrival_times[0])
    assert measured_hz == pytest.approx(5.0, abs=0.4)
