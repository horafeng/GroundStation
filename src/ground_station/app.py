"""推荐启动入口：python -m ground_station.app"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtCore import QCoreApplication, Qt
from PyQt5.QtWidgets import QApplication

from ground_station.config import load_demo_app_settings
from ground_station.ui import GroundStationMainWindow


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("GroundStation Demo")
    config_result = load_demo_app_settings(project_root() / "config" / "demo_ui.json")
    window = GroundStationMainWindow(
        config_result.settings,
        config_error=config_result.error,
    )
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
