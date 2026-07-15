"""周期帧和立即帧统一串行化的任务发送调度器。"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from ground_station.domain import ImmediateSendEvent, MissionSnapshot
from ground_station.drone_protocol import DroneProtocolEncoder


class BytesTransport(Protocol):
    def send(self, payload: bytes) -> int: ...
    def close(self) -> None: ...


class SendKind(str, Enum):
    PERIODIC = "periodic"
    IMMEDIATE = "immediate"


@dataclass(frozen=True, slots=True)
class SendRecord:
    sequence: int
    kind: SendKind
    reason: str
    sent_monotonic: float
    byte_count: int


@dataclass(frozen=True, slots=True)
class SendError:
    sequence: int
    kind: SendKind
    reason: str
    error_type: str
    message: str
    occurred_monotonic: float

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "kind": self.kind.value,
            "reason": self.reason,
            "error_type": self.error_type,
            "message": self.message,
            "occurred_monotonic": self.occurred_monotonic,
        }


class SequenceGenerator:
    def __init__(self, initial: int = 0) -> None:
        if not 0 <= initial <= 0xFFFFFFFF:
            raise ValueError("initial必须在uint32范围")
        self._next_value = initial
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            value = self._next_value
            self._next_value = (value + 1) & 0xFFFFFFFF
            return value


class MissionSendScheduler:
    """单一worker完成编码和发送，避免立即帧与周期帧并发乱序。"""

    def __init__(
        self,
        snapshot_factory: Callable[[int], MissionSnapshot],
        encoder: DroneProtocolEncoder,
        transport: BytesTransport,
        *,
        frequency_hz: float = 5.0,
        initial_sequence: int = 0,
        monotonic_clock: Callable[[], float] = time.monotonic,
        on_sent: Callable[[SendRecord], None] | None = None,
        on_error: Callable[[SendError], None] | None = None,
    ) -> None:
        if not 0.1 <= frequency_hz <= 100.0:
            raise ValueError("frequency_hz必须在0.1..100.0")
        self.frequency_hz = frequency_hz
        self.interval_s = 1.0 / frequency_hz
        self._snapshot_factory = snapshot_factory
        self._encoder = encoder
        self._transport = transport
        self._sequence = SequenceGenerator(initial_sequence)
        self._clock = monotonic_clock
        self._on_sent = on_sent
        self._on_error = on_error
        self._condition = threading.Condition()
        self._immediate_reasons: deque[str] = deque()
        self._stopping = False
        self._thread: threading.Thread | None = None
        self.send_records: list[SendRecord] = []
        self.send_errors: list[SendError] = []

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        with self._condition:
            if self.running:
                raise RuntimeError("MissionSendScheduler已经运行")
            self._stopping = False
            self._thread = threading.Thread(
                target=self._run,
                name="mission-send-scheduler",
                daemon=False,
            )
            self._thread.start()

    def request_immediate(self, event: ImmediateSendEvent | str) -> None:
        reason = event.reason.value if isinstance(event, ImmediateSendEvent) else str(event)
        with self._condition:
            if self._stopping:
                return
            self._immediate_reasons.append(reason)
            self._condition.notify()

    def stop(self, timeout: float = 2.0) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("MissionSendScheduler线程未在期限内退出")
        self._transport.close()

    def _run(self) -> None:
        next_deadline = self._clock()
        while True:
            with self._condition:
                now = self._clock()
                while (
                    not self._stopping
                    and not self._immediate_reasons
                    and now < next_deadline
                ):
                    self._condition.wait(next_deadline - now)
                    now = self._clock()
                if self._stopping:
                    return
                if self._immediate_reasons:
                    kind = SendKind.IMMEDIATE
                    reason = self._immediate_reasons.popleft()
                else:
                    kind = SendKind.PERIODIC
                    reason = "periodic_tick"
                    next_deadline += self.interval_s
                    now = self._clock()
                    while next_deadline <= now:
                        next_deadline += self.interval_s
            self._send_once(kind, reason)

    def _send_once(self, kind: SendKind, reason: str) -> None:
        sequence = self._sequence.next()
        try:
            snapshot = self._snapshot_factory(sequence)
            payload = self._encoder.encode(snapshot)
            byte_count = self._transport.send(payload)
            record = SendRecord(sequence, kind, reason, self._clock(), byte_count)
            self.send_records.append(record)
            if self._on_sent is not None:
                self._on_sent(record)
        except Exception as error:  # 调度线程必须记录并继续下一帧
            send_error = SendError(
                sequence,
                kind,
                reason,
                type(error).__name__,
                str(error),
                self._clock(),
            )
            self.send_errors.append(send_error)
            if self._on_error is not None:
                self._on_error(send_error)
