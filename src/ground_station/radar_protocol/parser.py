"""严格目标航迹帧解析器。

正式协议确认字段顺序、长度公式、校验和与帧尾；32 位字节序和“一 UDP
数据报一帧”是可配置的 Demo 临时假设，尚未经过真实雷达抓包或实物验证。
解析器不会试探另一种字节序，也不会静默接受坏报文。
"""

from __future__ import annotations

import struct

from ground_station.config import RadarProtocolSettings
from ground_station.domain import (
    HeightReference,
    RadarSiteState,
    RadarTimeFields,
    RadarTrack,
    RadarTrackFrame,
    TargetTimeFields,
    TargetType,
    TasTwsFlag,
)

from .checksum import compute_word_sum_checksum
from .constants import (
    COORDINATE_SCALE_DEG,
    FIXED_HEADER_WORDS,
    MAX_TRACK_COUNT,
    MIN_FRAME_WORDS,
    TRACK_FRAME_HEADER,
    TRACK_FRAME_TAIL,
    TRACK_WORDS,
    TRAILER_WORDS,
)
from .errors import RadarParseError, RadarParseErrorCode, RadarParseResult


def _signed(value: int, bits: int) -> int:
    sign_bit = 1 << (bits - 1)
    mask = (1 << bits) - 1
    value &= mask
    return value - (1 << bits) if value & sign_bit else value


class _ParseFailure(Exception):
    def __init__(self, error: RadarParseError):
        super().__init__(error.message)
        self.error = error


class RadarTrackFrameParser:
    def __init__(self, settings: RadarProtocolSettings | None = None):
        self.settings = settings or RadarProtocolSettings()

    @property
    def assumption_messages(self) -> tuple[str, ...]:
        return self.settings.assumption_messages

    def parse(self, datagram: bytes) -> RadarParseResult:
        try:
            return RadarParseResult.success(self._parse(datagram))
        except _ParseFailure as failure:
            return RadarParseResult.failure(failure.error)

    def _fail(
        self,
        code: RadarParseErrorCode,
        message: str,
        **details: object,
    ) -> None:
        raise _ParseFailure(RadarParseError(code, message, details))

    def _parse(self, datagram: bytes) -> RadarTrackFrame:
        if not self.settings.single_frame_per_datagram:
            self._fail(
                RadarParseErrorCode.UNSUPPORTED_DATAGRAM_MODE,
                "当前解析基础只支持一个 UDP 数据报包含一帧完整报文",
                configured_value=False,
            )
        if not datagram:
            self._fail(RadarParseErrorCode.EMPTY_DATAGRAM, "收到空 UDP 数据报")
        if len(datagram) % 4 != 0:
            self._fail(
                RadarParseErrorCode.BYTE_LENGTH_NOT_MULTIPLE_OF_FOUR,
                "雷达数据长度不是 4 字节的整数倍",
                byte_length=len(datagram),
            )

        word_count = len(datagram) // 4
        if word_count < MIN_FRAME_WORDS:
            self._fail(
                RadarParseErrorCode.FRAME_TOO_SHORT,
                "航迹帧短于正式协议最小长度",
                actual_words=word_count,
                minimum_words=MIN_FRAME_WORDS,
            )

        words = struct.unpack(f"{self.settings.struct_prefix}{word_count}I", datagram)
        if words[0] != TRACK_FRAME_HEADER:
            self._fail(
                RadarParseErrorCode.INVALID_HEADER,
                "目标航迹帧头不正确",
                expected=f"0x{TRACK_FRAME_HEADER:08X}",
                actual=f"0x{words[0]:08X}",
                configured_byte_order=self.settings.byte_order,
            )

        length_words = words[1]
        if length_words != word_count:
            self._fail(
                RadarParseErrorCode.LENGTH_FIELD_MISMATCH,
                "长度字段与 UDP 数据报实际字数不一致",
                declared_words=length_words,
                actual_words=word_count,
            )

        target_count = words[2]
        if target_count > MAX_TRACK_COUNT:
            self._fail(
                RadarParseErrorCode.TARGET_COUNT_OUT_OF_RANGE,
                "航迹目标数量超出正式协议范围",
                target_count=target_count,
                minimum=0,
                maximum=MAX_TRACK_COUNT,
            )

        expected_words = target_count * TRACK_WORDS + FIXED_HEADER_WORDS + TRAILER_WORDS
        if length_words != expected_words:
            self._fail(
                RadarParseErrorCode.TARGET_LENGTH_FORMULA_MISMATCH,
                "报文长度不满足 N*16+22",
                target_count=target_count,
                declared_words=length_words,
                expected_words=expected_words,
            )

        if words[-1] != TRACK_FRAME_TAIL:
            self._fail(
                RadarParseErrorCode.INVALID_TAIL,
                "目标航迹帧尾不正确",
                expected=f"0x{TRACK_FRAME_TAIL:08X}",
                actual=f"0x{words[-1]:08X}",
            )

        checksum_index = word_count - 2
        calculated_checksum = compute_word_sum_checksum(words, checksum_index)
        if words[checksum_index] != calculated_checksum:
            self._fail(
                RadarParseErrorCode.CHECKSUM_MISMATCH,
                "目标航迹帧校验和不正确",
                expected=f"0x{calculated_checksum:08X}",
                actual=f"0x{words[checksum_index]:08X}",
            )

        radar = self._parse_radar_site(words)
        tracks = tuple(
            self._parse_track(words, index)
            for index in range(target_count)
        )
        return RadarTrackFrame(
            length_words=length_words,
            target_count=target_count,
            radar=radar,
            tracks=tracks,
            checksum=words[checksum_index],
            raw_words=tuple(words),
        )

    def _parse_radar_site(self, words: tuple[int, ...]) -> RadarSiteState:
        longitude = _signed(words[5], 32) * COORDINATE_SCALE_DEG
        latitude = _signed(words[6], 32) * COORDINATE_SCALE_DEG
        self._validate_coordinate(longitude, latitude, radar=True)
        altitude_satellites = words[7]
        return RadarSiteState(
            longitude_deg=longitude,
            latitude_deg=latitude,
            altitude_m=(altitude_satellites >> 16) & 0xFFFF,
            satellite_count=altitude_satellites & 0xFFFF,
            heading_deg=words[8] * 0.01,
            true_heading_deg=words[9] * 0.01,
            roll_deg=_signed(words[10], 32) * 0.01,
            pitch_deg=_signed(words[11], 32) * 0.01,
            time=RadarTimeFields(
                dsp_time_ms=words[3],
                gps_time_raw=words[4],
                frame_count=words[18],
                frame_time_us=words[19],
            ),
            raw_header_words=tuple(words[:FIXED_HEADER_WORDS]),
        )

    def _parse_track(self, words: tuple[int, ...], target_index: int) -> RadarTrack:
        start = FIXED_HEADER_WORDS + target_index * TRACK_WORDS
        block = tuple(words[start : start + TRACK_WORDS])
        absolute_id = block[1]
        if absolute_id == 0:
            self._fail(
                RadarParseErrorCode.TARGET_ABSOLUTE_ID_OUT_OF_RANGE,
                "航迹绝对编号不在正式协议范围 [1, 2^32-1]",
                target_index=target_index,
                absolute_id=absolute_id,
            )

        angle_word = block[3]
        elevation_raw = _signed((angle_word >> 16) & 0xFFFF, 16)
        azimuth_raw = angle_word & 0xFFFF
        if not -300 <= elevation_raw <= 300 or not 0 <= azimuth_raw <= 3600:
            self._fail(
                RadarParseErrorCode.TARGET_ANGLE_OUT_OF_RANGE,
                "航迹俯仰角或方位角超出正式协议范围",
                target_index=target_index,
                elevation_raw=elevation_raw,
                azimuth_raw=azimuth_raw,
            )

        track_info = block[7]
        status_word = block[11]
        longitude = _signed(block[12], 32) * COORDINATE_SCALE_DEG
        latitude = _signed(block[13], 32) * COORDINATE_SCALE_DEG
        self._validate_coordinate(
            longitude,
            latitude,
            radar=False,
            target_index=target_index,
            absolute_id=absolute_id,
        )
        return RadarTrack(
            display_id=block[0],
            absolute_id=absolute_id,
            distance_m=block[2] * 0.1,
            azimuth_deg=azimuth_raw * 0.1,
            elevation_deg=elevation_raw * 0.1,
            target_type=TargetType((track_info >> 19) & 0x7),
            speed_mps=_signed(track_info & 0xFFFF, 16) * 0.1,
            tas_tws_flag=TasTwsFlag(block[9] & 0x3),
            is_cleared=bool((status_word >> 31) & 0x1),
            original_point_target_type=TargetType((status_word >> 24) & 0x7),
            longitude_deg=longitude,
            latitude_deg=latitude,
            height_m=_signed(block[15] & 0xFFFF, 16),
            height_reference=HeightReference.DEMO_RELATIVE_GROUND_UNVERIFIED,
            time=TargetTimeFields(
                gps_time_ms=block[10],
                dsp_timestamp_ms_24bit=status_word & 0xFFFFFF,
            ),
            raw_words=block,
        )

    def _validate_coordinate(
        self,
        longitude: float,
        latitude: float,
        *,
        radar: bool,
        **details: object,
    ) -> None:
        if -180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0:
            return
        code = (
            RadarParseErrorCode.RADAR_COORDINATE_OUT_OF_RANGE
            if radar
            else RadarParseErrorCode.TARGET_COORDINATE_OUT_OF_RANGE
        )
        self._fail(
            code,
            "雷达自身经纬度超出物理范围" if radar else "目标经纬度超出物理范围",
            longitude_deg=longitude,
            latitude_deg=latitude,
            **details,
        )
