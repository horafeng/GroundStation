from __future__ import annotations

from dataclasses import replace

import pytest

from ground_station.domain import (
    HeightReference,
    MissionMode,
    RadarTrack,
    TargetTimeFields,
    TargetType,
    TasTwsFlag,
)
from ground_station.mission import MissionStateService
from ground_station.selection import SelectionStatus, TargetSelectionService
from ground_station.tracks import TrackRepository


class FakeTime:
    monotonic = 0.0
    unix_ms = 1_700_000_000_000


def observation(
    absolute_id: int,
    display_id: int,
    *,
    longitude: float = 121.1,
    latitude: float = 31.2,
    height: int = 50,
    cleared: bool = False,
) -> RadarTrack:
    return RadarTrack(
        display_id=display_id,
        absolute_id=absolute_id,
        distance_m=100.0,
        azimuth_deg=20.0,
        elevation_deg=1.0,
        target_type=TargetType.UNKNOWN,
        speed_mps=3.0,
        tas_tws_flag=TasTwsFlag.TWS,
        is_cleared=cleared,
        original_point_target_type=TargetType.UNKNOWN,
        longitude_deg=longitude,
        latitude_deg=latitude,
        height_m=height,
        height_reference=HeightReference.DEMO_RELATIVE_GROUND_UNVERIFIED,
        time=TargetTimeFields(1000, 1000),
        raw_words=(0,) * 16,
    )


@pytest.fixture
def clock() -> FakeTime:
    return FakeTime()


@pytest.fixture
def repository(clock: FakeTime) -> TrackRepository:
    return TrackRepository(
        2000,
        monotonic_clock=lambda: clock.monotonic,
        unix_ms_clock=lambda: clock.unix_ms,
    )


def test_same_display_id_different_absolute_ids_are_distinct(repository: TrackRepository) -> None:
    repository.update_observation(observation(100, 7))
    repository.update_observation(observation(200, 7, longitude=122.0))
    tracks = repository.all()
    assert {track.absolute_id for track in tracks} == {100, 200}
    assert [track.display_id for track in tracks] == [7, 7]


def test_same_absolute_id_display_change_is_same_track(repository: TrackRepository, clock: FakeTime) -> None:
    first = repository.update_observation(observation(100, 7))
    clock.monotonic = 1.0
    changed = repository.update_observation(observation(100, 12, longitude=121.5))
    assert len(repository.all()) == 1
    assert changed.first_seen_monotonic == first.first_seen_monotonic
    assert changed.display_id == 12
    assert changed.last_valid_coordinate is not None
    assert changed.last_valid_coordinate.longitude_deg == 121.5


def test_normal_update_replaces_latest_coordinate_and_timestamp(repository: TrackRepository, clock: FakeTime) -> None:
    repository.update_observation(observation(100, 7), received_unix_ms=1000)
    clock.monotonic = 0.5
    updated = repository.update_observation(
        observation(100, 7, longitude=122.2, latitude=-20.5, height=-3),
        received_unix_ms=1500,
    )
    assert updated.is_realtime
    assert updated.lost_duration_ms == 0
    assert updated.last_valid_coordinate is not None
    assert updated.last_valid_coordinate.received_unix_ms == 1500
    assert updated.last_valid_coordinate.longitude_deg == 122.2
    assert updated.last_valid_coordinate.latitude_deg == -20.5
    assert updated.last_valid_coordinate.relative_ground_height_m == -3


def test_cleared_track_keeps_last_valid_coordinate(repository: TrackRepository, clock: FakeTime) -> None:
    repository.update_observation(observation(100, 7), received_unix_ms=1000)
    clock.monotonic = 1.0
    cleared = repository.update_observation(
        observation(100, 7, longitude=0.0, latitude=0.0, height=0, cleared=True),
        received_unix_ms=2000,
    )
    assert not cleared.is_realtime
    assert cleared.radar_marked_cleared
    assert cleared.last_valid_coordinate is not None
    assert cleared.last_valid_coordinate.longitude_deg == 121.1
    assert cleared.last_valid_coordinate.received_unix_ms == 1000


def test_timeout_marks_lost_and_duration_grows_monotonically(repository: TrackRepository, clock: FakeTime) -> None:
    repository.update_observation(observation(100, 7))
    clock.monotonic = 2.001
    first_lost = repository.get(100)
    assert first_lost is not None and not first_lost.is_realtime
    assert first_lost.lost_since_monotonic == pytest.approx(2.0)
    clock.monotonic = 2.501
    later = repository.get(100)
    assert later is not None
    assert later.lost_duration_ms >= 500
    assert later.lost_duration_ms > first_lost.lost_duration_ms


def test_same_absolute_id_recovers_after_loss(repository: TrackRepository, clock: FakeTime) -> None:
    repository.update_observation(observation(100, 7))
    clock.monotonic = 3.0
    assert repository.get(100).is_realtime is False  # type: ignore[union-attr]
    clock.monotonic = 3.1
    recovered = repository.update_observation(observation(100, 8, longitude=123.0))
    assert recovered.is_realtime
    assert recovered.lost_since_monotonic is None
    assert recovered.lost_duration_ms == 0
    assert recovered.display_id == 8


def test_selection_initial_pending_cancel_and_confirm(repository: TrackRepository) -> None:
    events = []
    repository.update_observation(observation(100, 7))
    repository.update_observation(observation(200, 12, longitude=122.0))
    service = TargetSelectionService(repository, event_sink=events.append)

    initial = service.request_selection(100)
    assert initial.status is SelectionStatus.SELECTED
    assert service.selected_absolute_id == 100
    assert len(events) == 1

    switch = service.request_selection(200)
    assert switch.status is SelectionStatus.CONFIRMATION_REQUIRED
    assert switch.confirmation is not None
    assert switch.confirmation.old_target.display_id == 7
    assert switch.confirmation.old_target.absolute_id == 100
    assert switch.confirmation.new_target.display_id == 12
    assert switch.confirmation.new_target.longitude_deg == 122.0
    assert service.selected_absolute_id == 100

    service.cancel_switch(switch.confirmation)
    assert service.selected_absolute_id == 100
    assert len(events) == 1

    switch = service.request_selection(200)
    assert switch.confirmation is not None
    event = service.confirm_switch(switch.confirmation)
    assert event.reason.value == "target_switch_confirmed"
    assert service.selected_absolute_id == 200
    assert len(events) == 2


def test_new_absolute_id_never_auto_replaces_selected(repository: TrackRepository) -> None:
    repository.update_observation(observation(100, 7))
    selection = TargetSelectionService(repository)
    selection.request_selection(100)
    repository.update_observation(observation(999, 7, longitude=121.10001))
    assert selection.selected_absolute_id == 100


def test_mission_modes_values_and_all_preserve_coordinates(repository: TrackRepository, clock: FakeTime) -> None:
    assert [int(mode) for mode in MissionMode] == [0, 1, 2, 3, 4]
    repository.update_observation(observation(100, 7), received_unix_ms=1234)
    selection = TargetSelectionService(repository)
    selection.request_selection(100)
    mission = MissionStateService(
        selection,
        drone_id=9,
        unix_ms_clock=lambda: 9000,
        monotonic_clock=lambda: clock.monotonic,
    )
    for sequence, mode in enumerate(MissionMode):
        mission.set_mode(mode)
        snapshot = mission.build_snapshot(sequence)
        assert snapshot.mode is mode
        assert snapshot.target_valid
        assert snapshot.track_absolute_id == 100
        assert snapshot.target_longitude_deg == 121.1
        assert snapshot.target_coordinate_timestamp_unix_ms == 1234


def test_no_selection_has_invalid_target(repository: TrackRepository) -> None:
    mission = MissionStateService(TargetSelectionService(repository), drone_id=1)
    snapshot = mission.build_snapshot(0, generated_unix_ms=100)
    assert not snapshot.target_valid
    assert snapshot.track_absolute_id is None
    assert snapshot.target_longitude_deg is None
    assert not snapshot.coordinate_realtime


def test_mission_keeps_mode_and_last_coordinate_after_clear(repository: TrackRepository, clock: FakeTime) -> None:
    repository.update_observation(observation(100, 7), received_unix_ms=1000)
    selection = TargetSelectionService(repository)
    selection.request_selection(100)
    mission = MissionStateService(selection, drone_id=1, monotonic_clock=lambda: clock.monotonic)
    mission.set_mode(MissionMode.TRACK)
    clock.monotonic = 1.0
    repository.update_observation(replace(observation(100, 7), is_cleared=True))
    clock.monotonic = 1.5
    snapshot = mission.build_snapshot(1, generated_unix_ms=2000)
    assert snapshot.mode is MissionMode.TRACK
    assert snapshot.target_valid
    assert snapshot.target_longitude_deg == 121.1
    assert not snapshot.coordinate_realtime
    assert snapshot.target_lost_duration_ms == 500
