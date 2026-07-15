from pathlib import Path

import pytest

from ground_station.domain import MissionMode, MissionSnapshot
from ground_station.drone_protocol import (
    SequenceMonitor,
    TemporaryDemoDecoder,
    TemporaryDemoEncoder,
    TemporaryProtocolError,
    TemporaryProtocolErrorCode,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "drone_protocol"
    / "temporary_demo_golden_v0.1.hex"
)


def golden_snapshot() -> MissionSnapshot:
    return MissionSnapshot(
        message_sequence=0x01020304,
        drone_id=0x11223344,
        mode=MissionMode.TRACK,
        target_valid=True,
        track_absolute_id=0x0A0B0C0D,
        target_longitude_deg=-73.9876543,
        target_latitude_deg=40.1234567,
        target_relative_ground_height_m=-12.34,
        target_coordinate_timestamp_unix_ms=1_700_000_000_123,
        coordinate_realtime=False,
        target_lost_duration_ms=2500,
        generated_timestamp_unix_ms=1_700_000_000_999,
    )


def test_encoder_matches_hand_written_complete_64_byte_golden_frame() -> None:
    expected = bytes.fromhex(FIXTURE.read_text(encoding="ascii"))
    assert len(expected) == 64
    assert TemporaryDemoEncoder().encode(golden_snapshot()) == expected


def test_decoder_reads_all_golden_fields() -> None:
    frame = TemporaryDemoDecoder().decode(bytes.fromhex(FIXTURE.read_text(encoding="ascii")))
    assert frame.mode is MissionMode.TRACK
    assert frame.frame_length == 64
    assert frame.status_flags == 1
    assert frame.target_valid
    assert not frame.coordinate_realtime
    assert frame.message_sequence == 0x01020304
    assert frame.drone_id == 0x11223344
    assert frame.track_absolute_id == 0x0A0B0C0D
    assert frame.target_longitude_deg == pytest.approx(-73.9876543)
    assert frame.target_latitude_deg == pytest.approx(40.1234567)
    assert frame.target_relative_ground_height_m == pytest.approx(-12.34)
    assert frame.target_coordinate_timestamp_unix_ms == 1_700_000_000_123
    assert frame.target_lost_duration_ms == 2500
    assert frame.generated_timestamp_unix_ms == 1_700_000_000_999
    assert frame.reserved == b"\x00" * 6
    assert frame.crc32 == 0xAA9A39E9


def test_no_target_encodes_zero_target_fields_and_valid_flag_zero() -> None:
    snapshot = MissionSnapshot(
        message_sequence=3,
        drone_id=4,
        mode=MissionMode.STANDBY,
        target_valid=False,
        track_absolute_id=None,
        target_longitude_deg=None,
        target_latitude_deg=None,
        target_relative_ground_height_m=None,
        target_coordinate_timestamp_unix_ms=None,
        coordinate_realtime=False,
        target_lost_duration_ms=0,
        generated_timestamp_unix_ms=10,
    )
    packet = TemporaryDemoEncoder().encode(snapshot)
    decoded = TemporaryDemoDecoder().decode(packet)
    assert len(packet) == 64
    assert not decoded.target_valid
    assert decoded.track_absolute_id == 0
    assert decoded.target_longitude_deg == 0
    assert decoded.target_latitude_deg == 0
    assert decoded.target_relative_ground_height_m == 0
    assert decoded.target_coordinate_timestamp_unix_ms == 0


def test_crc_corruption_is_rejected_by_receiver_decoder() -> None:
    packet = bytearray(bytes.fromhex(FIXTURE.read_text(encoding="ascii")))
    packet[20] ^= 0x01
    with pytest.raises(TemporaryProtocolError) as raised:
        TemporaryDemoDecoder().decode(bytes(packet))
    assert raised.value.code is TemporaryProtocolErrorCode.CRC_MISMATCH


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("actual_length", TemporaryProtocolErrorCode.INVALID_LENGTH),
        ("header", TemporaryProtocolErrorCode.INVALID_HEADER),
        ("declared_length", TemporaryProtocolErrorCode.INVALID_DECLARED_LENGTH),
        ("tail", TemporaryProtocolErrorCode.INVALID_TAIL),
    ],
)
def test_receiver_rejects_bad_framing(mutation: str, code: TemporaryProtocolErrorCode) -> None:
    packet = bytearray(bytes.fromhex(FIXTURE.read_text(encoding="ascii")))
    if mutation == "actual_length":
        packet.pop()
    elif mutation == "header":
        packet[0] ^= 0x01
    elif mutation == "declared_length":
        packet[4] = 63
    else:
        packet[62] ^= 0x01
    with pytest.raises(TemporaryProtocolError) as raised:
        TemporaryDemoDecoder().decode(bytes(packet))
    assert raised.value.code is code


def test_receiver_sequence_diagnostics_include_wrap_duplicate_missing_and_disorder() -> None:
    monitor = SequenceMonitor()
    cases = [
        (0xFFFFFFFE, "first"),
        (0xFFFFFFFF, "ok"),
        (0, "ok"),
        (0, "duplicate"),
        (2, "missing"),
        (1, "out_of_order"),
    ]
    assert [monitor.observe(sequence, index * 0.2).status for index, (sequence, _) in enumerate(cases)] == [
        expected for _, expected in cases
    ]
    assert monitor.duplicates == 1
    assert monitor.missing == 1
    assert monitor.out_of_order == 1
    assert monitor.measured_frequency_hz == pytest.approx(5.0)
