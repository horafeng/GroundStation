"""配置模型。"""

from .core import CoreDemoSettings, TRACK_TIMEOUT_NOTICE
from .radar import DEMO_ASSUMPTION_NOTICE, RadarProtocolSettings

__all__ = [
    "CoreDemoSettings",
    "DEMO_ASSUMPTION_NOTICE",
    "RadarProtocolSettings",
    "TRACK_TIMEOUT_NOTICE",
    "ConfigLoadResult",
    "DemoAppSettings",
    "load_demo_app_settings",
]
from .app import ConfigLoadResult, DemoAppSettings, load_demo_app_settings
