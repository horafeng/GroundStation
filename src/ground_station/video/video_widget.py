"""Non-blocking video placeholder and test-pattern source."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


@dataclass(frozen=True, slots=True)
class VideoSourceConfig:
    mode: str = "disabled"
    rtsp_url: str = ""


class _TestPattern(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._advance)

    def set_running(self, running: bool) -> None:
        self._timer.start() if running else self._timer.stop()
        self.update()

    def _advance(self) -> None:
        self._phase = (self._phase + 1) % 10
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        colors = ["#263d4b", "#315769", "#387285", "#bf7832"]
        width = max(1, self.width() // len(colors))
        for index, color in enumerate(colors):
            painter.fillRect(index * width, 0, width + 1, self.height(), QColor(color))
        painter.setPen(QPen(QColor("#ffffff"), 2))
        x = int((self._phase + 1) / 11 * self.width())
        painter.drawLine(x, 0, x, self.height())


class VideoPlaceholderWidget(QWidget):
    """Video-facing widget without a decoder or blocking network work."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = VideoSourceConfig()
        self.pattern = _TestPattern()
        self.message = QLabel("视频未连接")
        self.message.setObjectName("videoStatusMessage")
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.pattern, 1)
        layout.addWidget(self.message)
        self.pattern.hide()

    def configure(self, config: VideoSourceConfig) -> None:
        self.config = config
        self.pattern.set_running(False)
        if config.mode == "test_pattern":
            self.pattern.show()
            self.pattern.set_running(True)
            self.message.setText("视频测试图案 · 非真实相机")
            return
        self.pattern.hide()
        if config.mode == "rtsp" and config.rtsp_url:
            self.message.setText("RTSP 地址已配置 · 本轮未启用解码器")
        else:
            self.message.setText("视频未连接")

    def shutdown(self) -> bool:
        self.pattern.set_running(False)
        return True
