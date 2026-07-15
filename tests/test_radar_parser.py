from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ground_station.config import DEMO_ASSUMPTION_NOTICE, RadarProtocolSettings
from ground_station.domain import HeightReference, TargetType, TasTwsFlag
from ground_station.radar_protocol import RadarParseErrorCode, RadarTrackFrameParser
from ground_station.radar_protocol.checksum import compute_word_sum_checksum
from ground_station.radar_protocol.constants import TRACK_FRAME_HEADER
from ground_station.radar_protocol.simulator import (
    SimulatedTrack,
    build_track_datagram,
    scenario_datagram,
    unpack_words,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "radar_frames"


def fixture_bytes(filename: str) -> bytes:
    return bytes.fromhex((FIXTURE_DIR / filename).read_text(encoding="ascii"))


def repack(words: list[int], byte_order: str = "little") -> bytes:
    words[-2] = 0
    words[-2] = compute_word_sum_checksum(words, len(words) - 2)
    prefix = "<" if byte_order == "little" else ">"
    return struct.pack(f"{prefix}{len(words)}I", *words)


def assert_error(data: bytes, code: RadarParseErrorCode) -> None:
    result = RadarTrackFrameParser().parse(data)
    assert not result.ok
    assert result.frame is None
    assert result.error is not None
    assert result.error.code is code
    assert result.error.to_dict()["code"] == code.value


def test_default_settings_expose_unverified_demo_assumptions() -> None:
    parser = RadarTrackFrameParser()
    assert parser.settings.byte_order == "little"
    assert parser.settings.single_frame_per_datagram is True
    assert all(DEMO_ASSUMPTION_NOTICE in message for message in parser.assumption_messages[:2])


def test_zero_target_frame() -> None:
    result = RadarTrackFrameParser().parse(fixture_bytes("valid_zero_targets.hex"))
    assert result.ok
    assert result.frame is not None
    assert result.frame.length_words == 22
    assert result.frame.target_count == 0
    assert result.frame.tracks == ()


def test_one_target_all_required_fields() -> None:
    result = RadarTrackFrameParser().parse(fixture_bytes("valid_one_target.hex"))
    assert result.ok and result.frame is not None
    frame = result.frame
    assert frame.radar.longitude_deg == pytest.approx(109.006)
    assert frame.radar.latitude_deg == pytest.approx(34.116)
    assert frame.radar.altitude_m == 1016
    assert frame.radar.satellite_count == 12
    assert frame.radar.time.dsp_time_ms == 123_456
    assert frame.radar.time.frame_time_us == 20_000
    target = frame.tracks[0]
    assert target.display_id == 7
    assert target.absolute_id == 100_007
    assert target.distance_m == pytest.approx(250.0)
    assert target.azimuth_deg == pytest.approx(45.0)
    assert target.elevation_deg == pytest.approx(3.0)
    assert target.target_type is TargetType.UAV
    assert target.speed_mps == pytest.approx(12.3)
    assert target.tas_tws_flag is TasTwsFlag.TWS
    assert target.is_cleared is False
    assert target.longitude_deg == pytest.approx(121.47546)
    assert target.latitude_deg == pytest.approx(31.23185)
    assert target.height_m == 48
    assert target.height_reference is HeightReference.DEMO_RELATIVE_GROUND_UNVERIFIED
    assert target.time.gps_time_ms == 45_678_000
    assert target.time.dsp_timestamp_ms_24bit == 123_456


def test_multi_target_frame_does_not_filter_types() -> None:
    result = RadarTrackFrameParser().parse(fixture_bytes("valid_multi_targets.hex"))
    assert result.ok and result.frame is not None
    assert result.frame.target_count == 4
    assert [track.target_type for track in result.frame.tracks] == [
        TargetType.PERSON,
        TargetType.VEHICLE,
        TargetType.UAV,
        TargetType.UNKNOWN,
    ]


def test_duplicate_display_ids_keep_distinct_absolute_ids() -> None:
    result = RadarTrackFrameParser().parse(fixture_bytes("valid_duplicate_display_id.hex"))
    assert result.ok and result.frame is not None
    assert [track.display_id for track in result.frame.tracks] == [7, 7]
    assert set(result.frame.tracks_by_absolute_id()) == {100_007, 900_007}


def test_cleared_flag_and_tas_tws_are_independent() -> None:
    result = RadarTrackFrameParser().parse(fixture_bytes("valid_cleared_target.hex"))
    assert result.ok and result.frame is not None
    target = result.frame.tracks[0]
    assert target.is_cleared is True
    assert target.tas_tws_flag is TasTwsFlag.TWS


def test_moving_target_fixture_changes_coordinates() -> None:
    initial = RadarTrackFrameParser().parse(scenario_datagram("moving", tick=0)).frame
    moved = RadarTrackFrameParser().parse(fixture_bytes("valid_moving_target_step_3.hex")).frame
    assert initial is not None and moved is not None
    assert moved.tracks[0].absolute_id == initial.tracks[0].absolute_id
    assert moved.tracks[0].longitude_deg > initial.tracks[0].longitude_deg
    assert moved.tracks[0].latitude_deg > initial.tracks[0].latitude_deg


@pytest.mark.parametrize(
    ("filename", "code"),
    [
        ("bad_length.hex", RadarParseErrorCode.LENGTH_FIELD_MISMATCH),
        ("bad_checksum.hex", RadarParseErrorCode.CHECKSUM_MISMATCH),
        ("bad_tail.hex", RadarParseErrorCode.INVALID_TAIL),
    ],
)
def test_bad_fixture_errors(filename: str, code: RadarParseErrorCode) -> None:
    assert_error(fixture_bytes(filename), code)


def test_empty_datagram() -> None:
    assert_error(b"", RadarParseErrorCode.EMPTY_DATAGRAM)


def test_byte_length_not_multiple_of_four() -> None:
    assert_error(
        fixture_bytes("valid_one_target.hex") + b"\x00",
        RadarParseErrorCode.BYTE_LENGTH_NOT_MULTIPLE_OF_FOUR,
    )


def test_frame_too_short() -> None:
    assert_error(struct.pack("<I", TRACK_FRAME_HEADER), RadarParseErrorCode.FRAME_TOO_SHORT)


def test_bad_header() -> None:
    words = unpack_words(fixture_bytes("valid_zero_targets.hex"))
    words[0] = 0x01020304
    assert_error(repack(words), RadarParseErrorCode.INVALID_HEADER)


def test_target_count_out_of_range() -> None:
    words = unpack_words(fixture_bytes("valid_zero_targets.hex"))
    words[2] = 501
    assert_error(repack(words), RadarParseErrorCode.TARGET_COUNT_OUT_OF_RANGE)


def test_target_length_formula_mismatch() -> None:
    words = unpack_words(fixture_bytes("valid_one_target.hex"))
    words[2] = 2
    assert_error(repack(words), RadarParseErrorCode.TARGET_LENGTH_FORMULA_MISMATCH)


def test_target_coordinate_out_of_physical_range() -> None:
    data = build_track_datagram(
        [SimulatedTrack(1, 123, 181.0, 31.0, 5, TargetType.UNKNOWN)]
    )
    assert_error(data, RadarParseErrorCode.TARGET_COORDINATE_OUT_OF_RANGE)


def test_radar_coordinate_out_of_physical_range() -> None:
    words = unpack_words(fixture_bytes("valid_zero_targets.hex"))
    words[6] = round(91.0 / 0.00001)
    assert_error(repack(words), RadarParseErrorCode.RADAR_COORDINATE_OUT_OF_RANGE)


def test_zero_absolute_id_is_rejected() -> None:
    data = build_track_datagram(
        [SimulatedTrack(1, 0, 121.0, 31.0, 5, TargetType.UNKNOWN)]
    )
    assert_error(data, RadarParseErrorCode.TARGET_ABSOLUTE_ID_OUT_OF_RANGE)


def test_out_of_range_angle_is_rejected() -> None:
    data = build_track_datagram(
        [SimulatedTrack(1, 123, 121.0, 31.0, 5, azimuth_deg=361.0)]
    )
    assert_error(data, RadarParseErrorCode.TARGET_ANGLE_OUT_OF_RANGE)


def test_byte_order_is_configurable_and_not_auto_detected() -> None:
    settings = RadarProtocolSettings(byte_order="big")
    data = scenario_datagram("one", settings=settings)
    assert RadarTrackFrameParser(settings).parse(data).ok
    wrong_result = RadarTrackFrameParser(RadarProtocolSettings(byte_order="little")).parse(data)
    assert wrong_result.error is not None
    assert wrong_result.error.code is RadarParseErrorCode.INVALID_HEADER


def test_non_single_frame_mode_is_explicitly_unsupported() -> None:
    parser = RadarTrackFrameParser(
        RadarProtocolSettings(single_frame_per_datagram=False)
    )
    result = parser.parse(fixture_bytes("valid_zero_targets.hex"))
    assert result.error is not None
    assert result.error.code is RadarParseErrorCode.UNSUPPORTED_DATAGRAM_MODE
