"""在QThread中阻塞接收并严格解析雷达UDP数据报。"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

from PyQt5.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot

from ground_station.config import RadarProtocolSettings
from ground_station.radar_protocol import RadarTrackFrameParser


@dataclass(frozen=True, slots=True)
class RadarReceiverConfig:
    listen_host: str
    listen_port: int
    source_host: str = ""
    source_port: int = 0
    byte_order: str = "little"
    single_frame_per_datagram: bool = True

    def __post_init__(self) -> None:
        if not self.listen_host or not 1 <= self.listen_port <= 65535:
            raise ValueError("雷达监听地址无效")
        if not 0 <= self.source_port <= 65535:
            raise ValueError("雷达来源端口必须在0..65535")


class _RadarReceiverWorker(QObject):
    started = pyqtSignal(str, int)
    stopped = pyqtSignal()
    frame_received = pyqtSignal(object, str, int, float, int, bytes)
    parse_error = pyqtSignal(object, str, int, float, int, bytes)
    network_error = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(self, config: RadarReceiverConfig) -> None:
        super().__init__()
        self.config = config
        self._stop_event = threading.Event()
        self._socket_lock = threading.Lock()
        self._socket: socket.socket | None = None
        settings = RadarProtocolSettings(
            byte_order=config.byte_order,  # type: ignore[arg-type]
            single_frame_per_datagram=config.single_frame_per_datagram,
        )
        self._parser = RadarTrackFrameParser(settings)

    @pyqtSlot()
    def run(self) -> None:
        sock: socket.socket | None = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            sock.settimeout(0.2)
            sock.bind((self.config.listen_host, self.config.listen_port))
            with self._socket_lock:
                self._socket = sock
            self.started.emit(self.config.listen_host, self.config.listen_port)
            while not self._stop_event.is_set():
                try:
                    payload, source = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError as error:
                    if not self._stop_event.is_set():
                        self.network_error.emit(
                            {"operation": "recvfrom", "type": type(error).__name__, "message": str(error)}
                        )
                    break
                source_host, source_port = source
                if self.config.source_host and source_host != self.config.source_host:
                    continue
                if self.config.source_port and source_port != self.config.source_port:
                    continue
                mono = time.monotonic()
                unix_ms = time.time_ns() // 1_000_000
                result = self._parser.parse(payload)
                if result.ok:
                    self.frame_received.emit(
                        result.frame, source_host, source_port, mono, unix_ms, payload
                    )
                else:
                    assert result.error is not None
                    details = result.error.to_dict()
                    details["source_host"] = source_host
                    details["source_port"] = source_port
                    self.parse_error.emit(
                        details, source_host, source_port, mono, unix_ms, payload
                    )
        except OSError as error:
            self.network_error.emit(
                {"operation": "bind", "type": type(error).__name__, "message": str(error)}
            )
        finally:
            with self._socket_lock:
                self._socket = None
            if sock is not None:
                sock.close()
            self.stopped.emit()
            self.finished.emit()

    def request_stop(self) -> None:
        self._stop_event.set()
        with self._socket_lock:
            if self._socket is not None:
                self._socket.close()


class RadarUdpReceiver(QObject):
    """管理worker/QThread；所有接收结果通过Qt信号交给UI线程。"""

    started = pyqtSignal(str, int)
    stopped = pyqtSignal()
    frame_received = pyqtSignal(object, str, int, float, int, bytes)
    parse_error = pyqtSignal(object, str, int, float, int, bytes)
    network_error = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _RadarReceiverWorker | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, config: RadarReceiverConfig) -> None:
        if self.running:
            raise RuntimeError("雷达UDP接收器已经运行")
        thread = QThread()
        thread.setObjectName("radar-udp-receiver")
        worker = _RadarReceiverWorker(config)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.started.connect(self.started)
        worker.stopped.connect(self.stopped)
        worker.frame_received.connect(self.frame_received)
        worker.parse_error.connect(self.parse_error)
        worker.network_error.connect(self.network_error)
        worker.finished.connect(thread.quit, Qt.DirectConnection)
        self._thread = thread
        self._worker = worker
        thread.start()

    def stop(self, timeout_ms: int = 2000) -> bool:
        thread = self._thread
        worker = self._worker
        if thread is None:
            return True
        if worker is not None:
            worker.request_stop()
        stopped = thread.wait(timeout_ms)
        if stopped:
            self._worker = None
            self._thread = None
        return stopped
