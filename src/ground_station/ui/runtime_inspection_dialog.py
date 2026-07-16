"""Non-modal inspection window for tracks, communications and logs."""

from __future__ import annotations

from collections.abc import Mapping

from PyQt5.QtWidgets import QDialog, QTabWidget, QVBoxLayout, QWidget

from .widgets import CappedLogEdit


class RuntimeInspectionDialog(QDialog):
    """Keep detailed verification information outside the operation canvas."""

    TRACK_TAB = 0
    COMMUNICATION_TAB = 1

    def __init__(
        self,
        track_page: QWidget,
        communication_page: QWidget,
        logs: Mapping[str, CappedLogEdit],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("runtimeInspectionDialog")
        self.setWindowTitle("运行检查")
        self.setModal(False)
        self.setMinimumSize(900, 600)
        self.resize(1160, 720)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("runtimeInspectionTabs")
        self.tabs.addTab(track_page, "航迹")
        self.tabs.addTab(communication_page, "通信")
        self.tabs.addTab(logs["runtime"], "运行日志")

        self.packet_tabs = QTabWidget()
        self.packet_tabs.setObjectName("packetInspectionTabs")
        self.packet_tabs.addTab(logs["radar"], "雷达报文")
        self.packet_tabs.addTab(logs["send"], "无人机发送")
        self.packet_tabs.addTab(logs["hex"], "十六进制")
        self.tabs.addTab(self.packet_tabs, "报文")
        self.tabs.addTab(logs["protocol"], "协议错误")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.tabs)

    def show_track_page(self) -> None:
        self.tabs.setCurrentIndex(self.TRACK_TAB)
        self.show()
        self.raise_()
        self.activateWindow()

    def show_communication_page(self) -> None:
        self.tabs.setCurrentIndex(self.COMMUNICATION_TAB)
        self.show()
        self.raise_()
        self.activateWindow()
