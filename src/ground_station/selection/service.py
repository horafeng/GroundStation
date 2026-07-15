"""不依赖 UI 的人工目标选择服务。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from ground_station.domain import ImmediateSendEvent, ImmediateSendReason
from ground_station.tracks import TrackLifecycleSnapshot, TrackRepository


class SelectionStatus(str, Enum):
    SELECTED = "selected"
    ALREADY_SELECTED = "already_selected"
    CONFIRMATION_REQUIRED = "confirmation_required"


@dataclass(frozen=True, slots=True)
class TargetSelectionDescriptor:
    display_id: int
    absolute_id: int
    longitude_deg: float | None
    latitude_deg: float | None
    relative_ground_height_m: float | None


@dataclass(frozen=True, slots=True)
class TargetSwitchConfirmation:
    request_id: int
    old_target: TargetSelectionDescriptor
    new_target: TargetSelectionDescriptor


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    status: SelectionStatus
    selected_absolute_id: int
    immediate_event: ImmediateSendEvent | None = None
    confirmation: TargetSwitchConfirmation | None = None


class TargetSelectionService:
    def __init__(
        self,
        repository: TrackRepository,
        *,
        event_sink: Callable[[ImmediateSendEvent], None] | None = None,
    ) -> None:
        self._repository = repository
        self._event_sink = event_sink
        self._selected_absolute_id: int | None = None
        self._pending: TargetSwitchConfirmation | None = None
        self._request_id = 0
        self._lock = threading.RLock()

    @property
    def selected_absolute_id(self) -> int | None:
        with self._lock:
            return self._selected_absolute_id

    @property
    def pending_confirmation(self) -> TargetSwitchConfirmation | None:
        with self._lock:
            return self._pending

    def request_selection(self, absolute_id: int) -> SelectionDecision:
        target = self._require_target(absolute_id)
        with self._lock:
            if self._selected_absolute_id is None:
                self._selected_absolute_id = absolute_id
                self._pending = None
                event = ImmediateSendEvent(ImmediateSendReason.INITIAL_TARGET_SELECTED)
                self._emit(event)
                return SelectionDecision(SelectionStatus.SELECTED, absolute_id, event)
            if self._selected_absolute_id == absolute_id:
                return SelectionDecision(SelectionStatus.ALREADY_SELECTED, absolute_id)

            old = self._require_target(self._selected_absolute_id)
            self._request_id += 1
            confirmation = TargetSwitchConfirmation(
                request_id=self._request_id,
                old_target=self._descriptor(old),
                new_target=self._descriptor(target),
            )
            self._pending = confirmation
            return SelectionDecision(
                SelectionStatus.CONFIRMATION_REQUIRED,
                self._selected_absolute_id,
                confirmation=confirmation,
            )

    def confirm_switch(self, confirmation: TargetSwitchConfirmation) -> ImmediateSendEvent:
        with self._lock:
            if confirmation != self._pending:
                raise ValueError("待确认目标切换请求已失效或不匹配")
            if self._selected_absolute_id != confirmation.old_target.absolute_id:
                raise ValueError("当前目标已改变，不能确认旧请求")
            self._require_target(confirmation.new_target.absolute_id)
            self._selected_absolute_id = confirmation.new_target.absolute_id
            self._pending = None
            event = ImmediateSendEvent(ImmediateSendReason.TARGET_SWITCH_CONFIRMED)
            self._emit(event)
            return event

    def cancel_switch(self, confirmation: TargetSwitchConfirmation) -> None:
        with self._lock:
            if confirmation != self._pending:
                raise ValueError("待取消目标切换请求已失效或不匹配")
            self._pending = None

    def selected_track(self, *, now_monotonic: float | None = None) -> TrackLifecycleSnapshot | None:
        selected = self.selected_absolute_id
        if selected is None:
            return None
        return self._repository.get(selected, now_monotonic=now_monotonic)

    def _require_target(self, absolute_id: int) -> TrackLifecycleSnapshot:
        target = self._repository.get(absolute_id)
        if target is None:
            raise KeyError(f"不存在航迹绝对编号 {absolute_id}")
        return target

    @staticmethod
    def _descriptor(target: TrackLifecycleSnapshot) -> TargetSelectionDescriptor:
        coordinate = target.last_valid_coordinate
        return TargetSelectionDescriptor(
            target.display_id,
            target.absolute_id,
            None if coordinate is None else coordinate.longitude_deg,
            None if coordinate is None else coordinate.latitude_deg,
            None if coordinate is None else coordinate.relative_ground_height_m,
        )

    def _emit(self, event: ImmediateSendEvent) -> None:
        if self._event_sink is not None:
            self._event_sink(event)
