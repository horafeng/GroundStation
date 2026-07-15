"""模拟接收器使用的序号与接收频率诊断。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SequenceDiagnostic:
    status: str
    missing_count: int = 0


class SequenceMonitor:
    def __init__(self, frequency_window: int = 20) -> None:
        if frequency_window < 2:
            raise ValueError("frequency_window至少为2")
        self.last_sequence: int | None = None
        self.duplicates = 0
        self.missing = 0
        self.out_of_order = 0
        self._arrival_times: deque[float] = deque(maxlen=frequency_window)

    def observe(self, sequence: int, received_monotonic: float) -> SequenceDiagnostic:
        self._arrival_times.append(received_monotonic)
        if self.last_sequence is None:
            self.last_sequence = sequence
            return SequenceDiagnostic("first")
        if sequence == self.last_sequence:
            self.duplicates += 1
            return SequenceDiagnostic("duplicate")
        expected = (self.last_sequence + 1) & 0xFFFFFFFF
        if sequence == expected:
            self.last_sequence = sequence
            return SequenceDiagnostic("ok")
        forward = (sequence - expected) & 0xFFFFFFFF
        if forward < 0x80000000:
            self.missing += forward
            self.last_sequence = sequence
            return SequenceDiagnostic("missing", forward)
        self.out_of_order += 1
        return SequenceDiagnostic("out_of_order")

    @property
    def measured_frequency_hz(self) -> float | None:
        if len(self._arrival_times) < 2:
            return None
        elapsed = self._arrival_times[-1] - self._arrival_times[0]
        return None if elapsed <= 0 else (len(self._arrival_times) - 1) / elapsed
