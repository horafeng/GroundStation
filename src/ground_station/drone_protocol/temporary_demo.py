"""可替换的64字节 Demo 临时无人机协议。

这不是正式无人机协议。字段布局见 docs/temporary_drone_protocol_v0.1.md。
"""

from __future__ import annotations

import binascii
import struct
from dataclasses import dataclass
from enum import Enum

from ground_station.domain import MissionMode, MissionSnapshot

FRAME_HEADER = 0x55AA
FRAME_TAIL = 0xAA55
PROTOCOL_VERSION = 1
FRAME_LENGTH = 64
CRC_OFFSET = 58
TAIL_OFFSET = 62
FLAG_TARGET_VALID = 1 << 0
FLAG_COORDINATE_REALTIME = 1 << 1


class TemporaryProtocolErrorCode(str, Enum):
    INVALID_LENGTH = "invalid_length"
    INVALID_HEADER = "invalid_header"
    INVALID_VERSION = "invalid_version"
    INVALID_MODE = "invalid_mode"
    INVALID_DECLARED_LENGTH = "invalid_declared_length"
    INVALID_TAIL = "invalid_tail"
    CRC_MISMATCH = "crc_mismatch"


class TemporaryProtocolError(ValueError):
    def __init__(self, code: TemporaryProtocolErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class DecodedTemporaryDemoFrame:
    protocol_version: int
    mode: MissionMode
    frame_length: int
    status_flags: int
    target_valid: bool
    coordinate_realtime: bool
    message_sequence: int
    drone_id: int
    track_absolute_id: int
    target_longitude_deg: float
    target_latitude_deg: float
    target_relative_ground_height_m: float
    target_coordinate_timestamp_unix_ms: int
    target_lost_duration_ms: int
    generated_timestamp_unix_ms: int
    reserved: bytes
    crc32: int


def crc32_ieee(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


class TemporaryDemoEncoder:
    """把 MissionSnapshot 编为固定64字节；不持有 Socket 或业务状态。"""

    protocol_name = "Demo临时协议（非正式无人机协议）"
    version = PROTOCOL_VERSION

    def encode(self, snapshot: MissionSnapshot) -> bytes:
        packet = bytearray(FRAME_LENGTH)
        flags = 0
        if snapshot.target_valid:
            flags |= FLAG_TARGET_VALID
        if snapshot.coordinate_realtime:
            flags |= FLAG_COORDINATE_REALTIME

        absolute_id = snapshot.track_absolute_id or 0
        longitude_e7 = self._scaled_coordinate(snapshot.target_longitude_deg, "经度")
        latitude_e7 = self._scaled_coordinate(snapshot.target_latitude_deg, "纬度")
        height_cm = self._scaled_height(snapshot.target_relative_ground_height_m)
        coordinate_timestamp = snapshot.target_coordinate_timestamp_unix_ms or 0
        lost_duration = snapshot.target_lost_duration_ms if snapshot.target_valid else 0

        struct.pack_into(
            "<HBBHHIIIiiiQI",
            packet,
            0,
            FRAME_HEADER,
            PROTOCOL_VERSION,
            int(snapshot.mode),
            FRAME_LENGTH,
            flags,
            snapshot.message_sequence,
            snapshot.drone_id,
            absolute_id,
            longitude_e7,
            latitude_e7,
            height_cm,
            coordinate_timestamp,
            lost_duration,
        )
        struct.pack_into("<Q", packet, 44, snapshot.generated_timestamp_unix_ms)
        packet[52:58] = b"\x00" * 6
        checksum = crc32_ieee(bytes(packet[:CRC_OFFSET]))
        struct.pack_into("<I", packet, CRC_OFFSET, checksum)
        struct.pack_into("<H", packet, TAIL_OFFSET, FRAME_TAIL)
        return bytes(packet)

    @staticmethod
    def _scaled_coordinate(value: float | None, name: str) -> int:
        if value is None:
            return 0
        if name == "经度" and not -180.0 <= value <= 180.0:
            raise ValueError("经度超出物理范围")
        if name == "纬度" and not -90.0 <= value <= 90.0:
            raise ValueError("纬度超出物理范围")
        scaled = round(value * 10_000_000)
        if not -0x80000000 <= scaled <= 0x7FFFFFFF:
            raise ValueError(f"{name}缩放后超出int32")
        return scaled

    @staticmethod
    def _scaled_height(value: float | None) -> int:
        if value is None:
            return 0
        scaled = round(value * 100)
        if not -0x80000000 <= scaled <= 0x7FFFFFFF:
            raise ValueError("目标高度缩放后超出int32")
        return scaled


class TemporaryDemoDecoder:
    """供测试和模拟接收器使用的严格解码器。"""

    def decode(self, packet: bytes) -> DecodedTemporaryDemoFrame:
        if len(packet) != FRAME_LENGTH:
            raise TemporaryProtocolError(
                TemporaryProtocolErrorCode.INVALID_LENGTH,
                f"报文实际长度应为64，收到{len(packet)}",
            )
        header, version, mode_raw, declared_length, flags = struct.unpack_from(
            "<HBBHH", packet, 0
        )
        if header != FRAME_HEADER:
            raise TemporaryProtocolError(
                TemporaryProtocolErrorCode.INVALID_HEADER, "Demo临时协议帧头错误"
            )
        if version != PROTOCOL_VERSION:
            raise TemporaryProtocolError(
                TemporaryProtocolErrorCode.INVALID_VERSION, "Demo临时协议版本错误"
            )
        try:
            mode = MissionMode(mode_raw)
        except ValueError as error:
            raise TemporaryProtocolError(
                TemporaryProtocolErrorCode.INVALID_MODE, "任务模式不在0..4"
            ) from error
        if declared_length != FRAME_LENGTH:
            raise TemporaryProtocolError(
                TemporaryProtocolErrorCode.INVALID_DECLARED_LENGTH, "长度字段不是64"
            )
        tail = struct.unpack_from("<H", packet, TAIL_OFFSET)[0]
        if tail != FRAME_TAIL:
            raise TemporaryProtocolError(
                TemporaryProtocolErrorCode.INVALID_TAIL, "Demo临时协议帧尾错误"
            )
        actual_crc = struct.unpack_from("<I", packet, CRC_OFFSET)[0]
        expected_crc = crc32_ieee(packet[:CRC_OFFSET])
        if actual_crc != expected_crc:
            raise TemporaryProtocolError(
                TemporaryProtocolErrorCode.CRC_MISMATCH,
                f"CRC32错误，期望0x{expected_crc:08X}，实际0x{actual_crc:08X}",
            )
        (
            sequence,
            drone_id,
            absolute_id,
            longitude_e7,
            latitude_e7,
            height_cm,
            coordinate_timestamp,
            lost_duration,
        ) = struct.unpack_from("<IIIiiiQI", packet, 8)
        generated = struct.unpack_from("<Q", packet, 44)[0]
        return DecodedTemporaryDemoFrame(
            protocol_version=version,
            mode=mode,
            frame_length=declared_length,
            status_flags=flags,
            target_valid=bool(flags & FLAG_TARGET_VALID),
            coordinate_realtime=bool(flags & FLAG_COORDINATE_REALTIME),
            message_sequence=sequence,
            drone_id=drone_id,
            track_absolute_id=absolute_id,
            target_longitude_deg=longitude_e7 / 10_000_000,
            target_latitude_deg=latitude_e7 / 10_000_000,
            target_relative_ground_height_m=height_cm / 100,
            target_coordinate_timestamp_unix_ms=coordinate_timestamp,
            target_lost_duration_ms=lost_duration,
            generated_timestamp_unix_ms=generated,
            reserved=bytes(packet[52:58]),
            crc32=actual_crc,
        )
