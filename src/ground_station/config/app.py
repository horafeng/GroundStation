"""PyQt5 Demo应用配置；损坏文件不会被覆盖。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DemoAppSettings:
    radar_listen_host: str = "127.0.0.1"
    radar_listen_port: int = 6000
    radar_source_host: str = ""
    radar_source_port: int = 0
    radar_byte_order: str = "little"
    radar_single_frame_per_datagram: bool = True
    drone_host: str = "127.0.0.1"
    drone_port: int = 7000
    drone_id: int = 1
    send_frequency_hz: float = 5.0
    track_stale_timeout_ms: int = 2000
    radar_display_range_m: int = 1000
    log_max_lines: int = 1000

    def __post_init__(self) -> None:
        if not self.radar_listen_host:
            raise ValueError("radar_listen_host不能为空")
        if not 1 <= self.radar_listen_port <= 65535:
            raise ValueError("radar_listen_port必须在1..65535")
        if self.radar_source_port not in range(0, 65536):
            raise ValueError("radar_source_port必须在0..65535")
        if self.radar_byte_order not in ("little", "big"):
            raise ValueError("radar_byte_order只能为little或big")
        if not self.drone_host or not 1 <= self.drone_port <= 65535:
            raise ValueError("无人机目标地址无效")
        if not 0 <= self.drone_id <= 0xFFFFFFFF:
            raise ValueError("drone_id必须在uint32范围")
        if not 0.1 <= self.send_frequency_hz <= 100.0:
            raise ValueError("send_frequency_hz必须在0.1..100")
        if self.track_stale_timeout_ms <= 0:
            raise ValueError("track_stale_timeout_ms必须大于0")
        if self.radar_display_range_m not in (500, 1000, 2000, 5000):
            raise ValueError("radar_display_range_m必须为500/1000/2000/5000")
        if self.log_max_lines < 100:
            raise ValueError("log_max_lines至少为100")


@dataclass(frozen=True, slots=True)
class ConfigLoadResult:
    settings: DemoAppSettings
    error: str | None = None
    used_defaults: bool = False


def load_demo_app_settings(path: str | Path) -> ConfigLoadResult:
    config_path = Path(path)
    defaults = DemoAppSettings()
    try:
        raw: Any = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("配置根节点必须是JSON对象")
        allowed = set(asdict(defaults))
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"未知配置项: {', '.join(sorted(unknown))}")
        return ConfigLoadResult(DemoAppSettings(**raw))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        return ConfigLoadResult(defaults, f"配置加载失败，使用内存默认值：{error}", True)
