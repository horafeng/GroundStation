"""Honest placeholder for unavailable human-machine calibration."""

from __future__ import annotations

from PyQt5.QtWidgets import QGroupBox, QLabel, QPushButton, QVBoxLayout, QWidget


class CalibrationUnavailablePage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        message = QLabel("当前未接入飞控双向协议，校准功能尚不可用。")
        message.setObjectName("calibrationUnavailableMessage")
        message.setWordWrap(True)
        layout.addWidget(message)
        for name in ("磁罗盘校准", "加速度计校准", "陀螺仪校准"):
            box = QGroupBox(name)
            box_layout = QVBoxLayout(box)
            detail = QLabel("功能占位：不会发送 MAVLink 命令，也不会伪造校准结果。")
            detail.setWordWrap(True)
            button = QPushButton("当前不可用")
            button.setEnabled(False)
            box_layout.addWidget(detail)
            box_layout.addWidget(button)
            layout.addWidget(box)
        layout.addStretch(1)
