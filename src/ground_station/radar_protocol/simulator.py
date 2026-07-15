"""仅用于 Demo 和测试的雷达航迹帧构造器。

构造器遵循正式协议确认的字段布局；默认小端和一数据报一帧仍是 Demo 临时
假设，尚未经过真实雷达抓包或实物验证。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from pathlib import Path

from ground_station.config import RadarProtocolSettings
from ground_station.domain import TargetType, TasTwsFlag

from .checksum import compute_word_sum_checksum
from .constants import (
    FIXED_HEADER_WORDS,
    TRACK_FRAME_HEADER,
    TRACK_FRAME_TAIL,
    TRACK_WORDS,
    TRAILER_WORDS,
)


@dataclass(frozen=True, slots=True)
class SimulatedRadarSite:
    longitude_deg: float = 109.00600
    latitude_deg: float = 34.11600
    altitude_m: int = 1016
    satellite_count: int = 12
    heading_deg: float = 15.25
    true_heading_deg: float = 14.90
    roll_deg: float = -1.25
    pitch_deg: float = 2.50
    dsp_time_ms: int = 123_456
    gps_time_raw: int = 45_678_000
    frame_count: int = 77
    frame_time_us: int = 20_000


@dataclass(frozen=True, slots=True)
class SimulatedTrack:
    display_id: int
    absolute_id: int
    longitude_deg: float
    latitude_deg: float
    height_m: int
    target_type: TargetType = TargetType.UNKNOWN
    distance_m: float = 250.0
    azimuth_deg: float = 45.0
    elevation_deg: float = 3.0
    speed_mps: float = 10.0
    tas_tws_flag: TasTwsFlag = TasTwsFlag.TWS
    is_cleared: bool = False
    gps_time_ms: int = 45_678_000
    dsp_timestamp_ms_24bit: int = 123_456
    original_point_target_type: TargetType = TargetType.UNKNOWN


def _u32(value: int) -> int:
    return value & 0xFFFFFFFF


def _coord_word(value_deg: float) -> int:
    return _u32(round(value_deg / 0.00001))


def _pack_words(words: list[int], byte_order: str) -> bytes:
    prefix = "<" if byte_order == "little" else ">"
    return struct.pack(f"{prefix}{len(words)}I", *(_u32(word) for word in words))


def unpack_words(datagram: bytes, byte_order: str = "little") -> list[int]:
    prefix = "<" if byte_order == "little" else ">"
    return list(struct.unpack(f"{prefix}{len(datagram) // 4}I", datagram))


def repack_with_checksum(words: list[int], byte_order: str = "little") -> bytes:
    words[-2] = 0
    words[-2] = compute_word_sum_checksum(words, len(words) - 2)
    return _pack_words(words, byte_order)


def build_track_datagram(
    tracks: list[SimulatedTrack],
    *,
    radar: SimulatedRadarSite | None = None,
    settings: RadarProtocolSettings | None = None,
) -> bytes:
    radar = radar or SimulatedRadarSite()
    settings = settings or RadarProtocolSettings()
    word_count = FIXED_HEADER_WORDS + len(tracks) * TRACK_WORDS + TRAILER_WORDS
    words = [0] * word_count
    words[0] = TRACK_FRAME_HEADER
    words[1] = word_count
    words[2] = len(tracks)
    words[3] = radar.dsp_time_ms
    words[4] = radar.gps_time_raw
    words[5] = _coord_word(radar.longitude_deg)
    words[6] = _coord_word(radar.latitude_deg)
    words[7] = ((radar.altitude_m & 0xFFFF) << 16) | (radar.satellite_count & 0xFFFF)
    words[8] = round(radar.heading_deg * 100)
    words[9] = round(radar.true_heading_deg * 100)
    words[10] = _u32(round(radar.roll_deg * 100))
    words[11] = _u32(round(radar.pitch_deg * 100))
    words[18] = radar.frame_count
    words[19] = radar.frame_time_us

    for index, track in enumerate(tracks):
        start = FIXED_HEADER_WORDS + index * TRACK_WORDS
        elevation_raw = round(track.elevation_deg * 10) & 0xFFFF
        azimuth_raw = round(track.azimuth_deg * 10) & 0xFFFF
        speed_raw = round(track.speed_mps * 10) & 0xFFFF
        status = (
            ((1 if track.is_cleared else 0) << 31)
            | ((int(track.original_point_target_type) & 0x7) << 24)
            | (track.dsp_timestamp_ms_24bit & 0xFFFFFF)
        )
        words[start] = track.display_id
        words[start + 1] = track.absolute_id
        words[start + 2] = round(track.distance_m * 10)
        words[start + 3] = (elevation_raw << 16) | azimuth_raw
        words[start + 7] = ((int(track.target_type) & 0x7) << 19) | speed_raw
        words[start + 9] = int(track.tas_tws_flag) & 0x3
        words[start + 10] = track.gps_time_ms
        words[start + 11] = status
        words[start + 12] = _coord_word(track.longitude_deg)
        words[start + 13] = _coord_word(track.latitude_deg)
        words[start + 15] = track.height_m & 0xFFFF

    words[-1] = TRACK_FRAME_TAIL
    return repack_with_checksum(words, settings.byte_order)


def scenario_datagram(
    scenario: str,
    *,
    tick: int = 0,
    settings: RadarProtocolSettings | None = None,
) -> bytes:
    settings = settings or RadarProtocolSettings()
    base = SimulatedTrack(
        display_id=7,
        absolute_id=100_007,
        longitude_deg=121.47546,
        latitude_deg=31.23185,
        height_m=48,
        target_type=TargetType.UAV,
        speed_mps=12.3,
        tas_tws_flag=TasTwsFlag.TWS,
        original_point_target_type=TargetType.UAV,
    )

    if scenario == "zero":
        return build_track_datagram([], settings=settings)
    if scenario == "one":
        return build_track_datagram([base], settings=settings)
    if scenario == "multi":
        tracks = [
            SimulatedTrack(3, 200_003, 121.47400, 31.23010, 2, TargetType.PERSON, speed_mps=1.4),
            SimulatedTrack(4, 200_004, 121.47600, 31.23210, 0, TargetType.VEHICLE, speed_mps=8.5),
            base,
            SimulatedTrack(9, 200_009, 121.47800, 31.23410, 15, TargetType.UNKNOWN, speed_mps=-0.5),
        ]
        return build_track_datagram(tracks, settings=settings)
    if scenario in {"multi-moving", "multi-moving-clear"}:
        tracks = [
            replace(
                base,
                display_id=7,
                absolute_id=100_007,
                longitude_deg=109.00700 + tick * 0.00001,
                latitude_deg=34.11680 + tick * 0.000004,
                is_cleared=scenario == "multi-moving-clear",
            ),
            SimulatedTrack(
                12, 100_012, 109.00380 - tick * 0.000006, 34.11720,
                3, TargetType.PERSON, speed_mps=1.6, azimuth_deg=310.0,
            ),
            SimulatedTrack(
                21, 100_021, 109.00850, 34.11350 + tick * 0.000008,
                0, TargetType.VEHICLE, speed_mps=7.8, azimuth_deg=145.0,
            ),
            SimulatedTrack(
                33, 100_033, 109.00180 + tick * 0.000004, 34.11420 - tick * 0.000003,
                18, TargetType.UNKNOWN, speed_mps=3.2, azimuth_deg=225.0,
            ),
        ]
        return build_track_datagram(tracks, settings=settings)
    if scenario == "moving":
        moving = replace(
            base,
            longitude_deg=base.longitude_deg + tick * 0.00002,
            latitude_deg=base.latitude_deg + tick * 0.00001,
            gps_time_ms=base.gps_time_ms + tick * 200,
            dsp_timestamp_ms_24bit=base.dsp_timestamp_ms_24bit + tick * 200,
        )
        return build_track_datagram([moving], settings=settings)
    if scenario == "cleared":
        cleared = replace(base, is_cleared=True)
        return build_track_datagram([cleared], settings=settings)
    if scenario == "duplicate-display":
        tracks = [
            base,
            SimulatedTrack(
                display_id=7,
                absolute_id=900_007,
                longitude_deg=121.48000,
                latitude_deg=31.24000,
                height_m=5,
                target_type=TargetType.VEHICLE,
            ),
        ]
        return build_track_datagram(tracks, settings=settings)
    if scenario in {"bad-length", "bad-checksum", "bad-tail"}:
        valid = build_track_datagram([base], settings=settings)
        words = unpack_words(valid, settings.byte_order)
        if scenario == "bad-length":
            words[1] += 1
            return repack_with_checksum(words, settings.byte_order)
        if scenario == "bad-checksum":
            words[-2] ^= 0x00000001
            return _pack_words(words, settings.byte_order)
        words[-1] = 0xDEADBEEF
        return repack_with_checksum(words, settings.byte_order)
    raise ValueError(f"未知模拟场景: {scenario}")


FIXTURE_SCENARIOS = {
    "valid_zero_targets.hex": ("zero", 0),
    "valid_one_target.hex": ("one", 0),
    "valid_multi_targets.hex": ("multi", 0),
    "valid_moving_target_step_3.hex": ("moving", 3),
    "valid_cleared_target.hex": ("cleared", 0),
    "valid_duplicate_display_id.hex": ("duplicate-display", 0),
    "bad_length.hex": ("bad-length", 0),
    "bad_checksum.hex": ("bad-checksum", 0),
    "bad_tail.hex": ("bad-tail", 0),
}


def write_hex_fixtures(
    directory: str | Path,
    settings: RadarProtocolSettings | None = None,
) -> list[Path]:
    settings = settings or RadarProtocolSettings()
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for filename, (scenario, tick) in FIXTURE_SCENARIOS.items():
        data = scenario_datagram(scenario, tick=tick, settings=settings)
        path = output / filename
        path.write_text(data.hex(" ").upper() + "\n", encoding="ascii")
        paths.append(path)
    return paths
