from pathlib import Path

import pytest

from ground_station.config import DemoAppSettings, load_demo_app_settings
from ground_station.ui import gps_to_local_display_m


def test_broken_config_is_not_overwritten_and_defaults_are_returned(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    original = b'{"radar_listen_port": invalid}'
    path.write_bytes(original)
    result = load_demo_app_settings(path)
    assert result.used_defaults
    assert result.error is not None and "配置加载失败" in result.error
    assert result.settings == DemoAppSettings()
    assert path.read_bytes() == original


def test_local_radar_conversion_is_display_only_and_meter_scale() -> None:
    radar = (109.006, 34.116)
    target = (109.007, 34.117)
    east, north = gps_to_local_display_m(*radar, *target)
    assert east == pytest.approx(92.3, abs=1.0)
    assert north == pytest.approx(110.54, abs=0.1)
    assert radar == (109.006, 34.116)
    assert target == (109.007, 34.117)
