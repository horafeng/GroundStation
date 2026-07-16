"""把既有核心模块编排为Qt可消费的应用服务。"""

from __future__ import annotations

import time
from collections import deque

from PyQt5.QtCore import QObject, pyqtSignal

from ground_station.config import DemoAppSettings
from ground_station.domain import ImmediateSendEvent, MissionMode
from ground_station.drone_protocol import TemporaryDemoEncoder
from ground_station.mission import MissionStateService
from ground_station.network import (
    DroneUdpTransport,
    RadarReceiverConfig,
    RadarUdpReceiver,
)
from ground_station.selection import (
    SelectionDecision,
    TargetSelectionService,
    TargetSwitchConfirmation,
)
from ground_station.sending import MissionSendScheduler, SendError, SendRecord
from ground_station.tracks import TrackLifecycleSnapshot, TrackRepository


class GroundStationController(QObject):
    _send_worker_record = pyqtSignal(object)
    _send_worker_error = pyqtSignal(object)
    tracks_changed = pyqtSignal(object)
    radar_state_changed = pyqtSignal(object)
    radar_status_changed = pyqtSignal(str)
    radar_frame_logged = pyqtSignal(str)
    protocol_error_logged = pyqtSignal(object)
    send_status_changed = pyqtSignal(str)
    send_recorded = pyqtSignal(object)
    send_error_logged = pyqtSignal(object)
    mission_mode_changed = pyqtSignal(object)
    selection_changed = pyqtSignal(object)
    runtime_log = pyqtSignal(str)

    def __init__(self, settings: DemoAppSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.repository = TrackRepository(settings.track_stale_timeout_ms)
        self._scheduler: MissionSendScheduler | None = None
        self.selection = TargetSelectionService(
            self.repository, event_sink=self._handle_immediate_event
        )
        self.mission = MissionStateService(
            self.selection,
            drone_id=settings.drone_id,
            event_sink=self._handle_immediate_event,
        )
        self.radar_receiver = RadarUdpReceiver(self)
        self.radar_receiver.started.connect(self._on_radar_started)
        self.radar_receiver.stopped.connect(self._on_radar_stopped)
        self.radar_receiver.frame_received.connect(self._on_radar_frame)
        self.radar_receiver.parse_error.connect(self._on_radar_parse_error)
        self.radar_receiver.network_error.connect(self._on_radar_network_error)
        self.latest_radar_frame = None
        self.last_radar_unix_ms: int | None = None
        self.last_radar_state_unix_ms: int | None = None
        self.last_radar_datagram_monotonic: float | None = None
        self.valid_radar_frames = 0
        self.invalid_radar_frames = 0
        self.send_success_count = 0
        self.send_failure_count = 0
        self.last_send_record: SendRecord | None = None
        self._send_times: deque[float] = deque(maxlen=30)
        self._send_worker_record.connect(self._apply_send_record)
        self._send_worker_error.connect(self._apply_send_error)

    @property
    def sending(self) -> bool:
        return self._scheduler is not None and self._scheduler.running

    @property
    def actual_send_frequency_hz(self) -> float:
        if len(self._send_times) < 2:
            return 0.0
        elapsed = self._send_times[-1] - self._send_times[0]
        return 0.0 if elapsed <= 0 else (len(self._send_times) - 1) / elapsed

    def start_radar(self, config: RadarReceiverConfig) -> None:
        self.radar_status_changed.emit("启动中")
        self.last_radar_unix_ms = None
        self.last_radar_state_unix_ms = None
        self.last_radar_datagram_monotonic = None
        self.runtime_log.emit(
            f"启动雷达监听 {config.listen_host}:{config.listen_port}；"
            f"Demo临时假设 byte_order={config.byte_order}, 一报一帧={config.single_frame_per_datagram}"
        )
        self.radar_receiver.start(config)

    def stop_radar(self) -> bool:
        if not self.radar_receiver.running:
            self.radar_status_changed.emit("未启动")
            return True
        self.radar_status_changed.emit("停止中")
        stopped = self.radar_receiver.stop(2000)
        if not stopped:
            self.runtime_log.emit("错误：雷达接收线程未在2秒内退出")
        return stopped

    def process_radar_frame(
        self,
        frame: object,
        *,
        received_monotonic: float | None = None,
        received_unix_ms: int | None = None,
        raw_payload: bytes = b"",
    ) -> None:
        mono = time.monotonic() if received_monotonic is None else received_monotonic
        unix_ms = time.time_ns() // 1_000_000 if received_unix_ms is None else received_unix_ms
        self.latest_radar_frame = frame
        self.last_radar_unix_ms = unix_ms
        self.last_radar_state_unix_ms = unix_ms
        self.last_radar_datagram_monotonic = mono
        self.valid_radar_frames += 1
        self.repository.update_frame(  # type: ignore[arg-type]
            frame, received_monotonic=mono, received_unix_ms=unix_ms
        )
        self.radar_state_changed.emit(frame)
        self.tracks_changed.emit(self.repository.all(now_monotonic=mono))
        if raw_payload:
            self.radar_frame_logged.emit(raw_payload.hex(" ").upper())

    def refresh_tracks(self) -> tuple[TrackLifecycleSnapshot, ...]:
        tracks = self.repository.refresh()
        self.tracks_changed.emit(tracks)
        return tracks

    def radar_data_age_seconds(self, now_monotonic: float | None = None) -> float | None:
        received = self.last_radar_datagram_monotonic
        if received is None:
            return None
        now = time.monotonic() if now_monotonic is None else now_monotonic
        return max(0.0, now - received)

    def radar_data_status(self, now_monotonic: float | None = None) -> str:
        age = self.radar_data_age_seconds(now_monotonic)
        if age is None:
            return "尚未收到数据"
        return "数据实时" if age * 1000 <= self.repository.stale_timeout_ms else "数据超时"

    def request_selection(self, absolute_id: int) -> SelectionDecision:
        decision = self.selection.request_selection(absolute_id)
        if decision.confirmation is None:
            self.selection_changed.emit(self.selection.selected_absolute_id)
        return decision

    def confirm_selection(self, confirmation: TargetSwitchConfirmation) -> None:
        self.selection.confirm_switch(confirmation)
        self.selection_changed.emit(self.selection.selected_absolute_id)

    def cancel_selection(self, confirmation: TargetSwitchConfirmation) -> None:
        self.selection.cancel_switch(confirmation)
        self.selection_changed.emit(self.selection.selected_absolute_id)

    def set_mode(self, mode: MissionMode | int) -> None:
        event = self.mission.set_mode(mode)
        if event is not None:
            self.mission_mode_changed.emit(self.mission.mode)

    def start_sending(
        self,
        *,
        host: str,
        port: int,
        drone_id: int,
        frequency_hz: float,
        track_timeout_ms: int,
    ) -> None:
        if self.sending:
            raise RuntimeError("无人机发送已经运行")
        self.mission.set_drone_id(drone_id)
        self.repository.set_stale_timeout_ms(track_timeout_ms)
        transport = DroneUdpTransport(host, port)
        scheduler = MissionSendScheduler(
            self.mission.build_snapshot,
            TemporaryDemoEncoder(),
            transport,
            frequency_hz=frequency_hz,
            on_sent=self._on_send_record_worker,
            on_error=self._on_send_error_worker,
        )
        self._send_times.clear()
        self._scheduler = scheduler
        scheduler.start()
        self.send_status_changed.emit("发送中")
        self.runtime_log.emit(f"启动无人机UDP发送 {host}:{port} @ {frequency_hz:.3g}Hz")

    def stop_sending(self) -> bool:
        scheduler = self._scheduler
        if scheduler is None:
            self.send_status_changed.emit("已停止")
            return True
        try:
            scheduler.stop(2.0)
        except TimeoutError as error:
            self.runtime_log.emit(f"错误：{error}")
            return False
        finally:
            self._scheduler = None
        self.send_status_changed.emit("已停止")
        self.runtime_log.emit("无人机UDP发送已停止，Socket已关闭")
        return True

    def shutdown(self) -> bool:
        """按要求先停发送，再停雷达接收及其Socket/线程。"""

        send_ok = self.stop_sending()
        radar_ok = self.stop_radar()
        self.runtime_log.emit("应用网络资源关闭完成")
        return send_ok and radar_ok

    def _handle_immediate_event(self, event: ImmediateSendEvent) -> None:
        scheduler = self._scheduler
        if scheduler is not None and scheduler.running:
            scheduler.request_immediate(event)

    def _on_radar_started(self, host: str, port: int) -> None:
        self.radar_status_changed.emit("监听中")
        self.runtime_log.emit(f"雷达UDP已绑定 {host}:{port}")

    def _on_radar_stopped(self) -> None:
        self.radar_status_changed.emit("未启动")

    def _on_radar_frame(
        self,
        frame: object,
        source_host: str,
        source_port: int,
        mono: float,
        unix_ms: int,
        payload: bytes,
    ) -> None:
        self.process_radar_frame(
            frame,
            received_monotonic=mono,
            received_unix_ms=unix_ms,
            raw_payload=payload,
        )
        self.runtime_log.emit(f"雷达有效帧 source={source_host}:{source_port}")

    def _on_radar_parse_error(
        self,
        error: object,
        _source_host: str,
        _source_port: int,
        mono: float,
        unix_ms: int,
        payload: bytes,
    ) -> None:
        self.invalid_radar_frames += 1
        self.last_radar_unix_ms = unix_ms
        self.last_radar_datagram_monotonic = mono
        self.protocol_error_logged.emit(error)
        self.radar_frame_logged.emit(f"拒绝 {payload.hex(' ').upper()}")

    def _on_radar_network_error(self, error: object) -> None:
        self.protocol_error_logged.emit(error)
        self.radar_status_changed.emit("监听错误")

    def _on_send_record_worker(self, record: SendRecord) -> None:
        self._send_worker_record.emit(record)

    def _apply_send_record(self, record: SendRecord) -> None:
        self.send_success_count += 1
        self.last_send_record = record
        self._send_times.append(record.sent_monotonic)
        self.send_recorded.emit(record)

    def _on_send_error_worker(self, error: SendError) -> None:
        self._send_worker_error.emit(error)

    def _apply_send_error(self, error: SendError) -> None:
        self.send_failure_count += 1
        self.send_error_logged.emit(error)
