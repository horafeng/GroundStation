from pathlib import Path

import pytest

from ground_station.domain import TargetType, TasTwsFlag
from ground_station.radar_protocol import RadarTrackFrameParser


def test_manual_one_target_golden_vector() -> None:
    """预期值来自同目录md手工字段表，不调用模拟构造器。"""

    path = Path(__file__).parent / "fixtures" / "radar_golden" / "manual_one_target_v0.1.hex"
    result = RadarTrackFrameParser().parse(bytes.fromhex(path.read_text(encoding="ascii")))
    assert result.ok and result.frame is not None
    frame = result.frame
    assert frame.length_words == 38
    assert frame.target_count == 1
    assert frame.checksum == 0x52F71504
    assert frame.radar.longitude_deg == pytest.approx(120.12345)
    assert frame.radar.latitude_deg == pytest.approx(-30.54321)
    assert frame.radar.altitude_m == 321
    assert frame.radar.satellite_count == 9
    assert frame.radar.heading_deg == pytest.approx(12.34)
    assert frame.radar.true_heading_deg == pytest.approx(12.50)
    assert frame.radar.roll_deg == pytest.approx(-1.50)
    assert frame.radar.pitch_deg == pytest.approx(2.25)
    assert frame.radar.time.dsp_time_ms == 1000
    assert frame.radar.time.gps_time_raw == 2000
    assert frame.radar.time.frame_count == 42
    assert frame.radar.time.frame_time_us == 50_000

    target = frame.tracks[0]
    assert target.display_id == 17
    assert target.absolute_id == 0x01020304
    assert target.distance_m == pytest.approx(123.4)
    assert target.azimuth_deg == pytest.approx(278.9)
    assert target.elevation_deg == pytest.approx(-1.2)
    assert target.target_type is TargetType.VEHICLE
    assert target.speed_mps == pytest.approx(-3.2)
    assert target.tas_tws_flag is TasTwsFlag.TAS
    assert not target.is_cleared
    assert target.original_point_target_type is TargetType.PERSON
    assert target.time.gps_time_ms == 3000
    assert target.time.dsp_timestamp_ms_24bit == 0x123456
    assert target.longitude_deg == pytest.approx(-73.98765)
    assert target.latitude_deg == pytest.approx(40.12345)
    assert target.height_m == -15
    assert target.raw_words[4:7] == (0x11111111, 0x22222222, 0x33333333)
    assert target.raw_words[8] == 0x44444444
    assert target.raw_words[14] == 0x55555555
