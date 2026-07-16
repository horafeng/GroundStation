"""独立、可缩放的网络与协议设置对话框。"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ground_station.config import DemoAppSettings


class NetworkSettingsDialog(QDialog):
    settings_applied = pyqtSignal()

    def __init__(self, settings: DemoAppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("网络与配置")
        self.setObjectName("networkSettingsDialog")
        self.setMinimumWidth(560)
        self.resize(640, 480)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self._build_radar_tab(settings)
        self._build_drone_tab(settings)
        self._build_protocol_tab(settings)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Close)
        self.button_box = buttons
        buttons.button(QDialogButtonBox.Apply).setText("应用")
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.settings_applied)
        buttons.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)
        self._set_control_sizes()
        self._set_tab_order()

    def _build_radar_tab(self, settings: DemoAppSettings) -> None:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.radar_host = QLineEdit(settings.radar_listen_host)
        self.radar_port = self._spin(1, 65535, settings.radar_listen_port)
        self.radar_source_host = QLineEdit(settings.radar_source_host)
        self.radar_source_host.setPlaceholderText("留空表示不限制来源IP")
        self.radar_source_port = self._spin(0, 65535, settings.radar_source_port)
        form.addRow("本地监听IP", self.radar_host)
        form.addRow("本地监听端口", self.radar_port)
        form.addRow("来源IP过滤（可选）", self.radar_source_host)
        form.addRow("来源端口过滤（0表示不限）", self.radar_source_port)
        note = QLabel("监听地址和来源过滤：需停止雷达监听后，重新启动监听生效。")
        note.setWordWrap(True)
        note.setObjectName("radarRestartNote")
        form.addRow(note)
        self.tabs.addTab(tab, "雷达接收")

    def _build_drone_tab(self, settings: DemoAppSettings) -> None:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.drone_host = QLineEdit(settings.drone_host)
        self.drone_port = self._spin(1, 65535, settings.drone_port)
        self.drone_id = QDoubleSpinBox()
        self.drone_id.setDecimals(0)
        self.drone_id.setRange(0, 0xFFFFFFFF)
        self.drone_id.setValue(settings.drone_id)
        self.frequency = QDoubleSpinBox()
        self.frequency.setRange(0.1, 100.0)
        self.frequency.setDecimals(1)
        self.frequency.setSuffix(" Hz")
        self.frequency.setValue(settings.send_frequency_hz)
        form.addRow("无人机目标IP", self.drone_host)
        form.addRow("无人机目标端口", self.drone_port)
        form.addRow("无人机ID", self.drone_id)
        form.addRow("循环发送频率", self.frequency)
        note = QLabel(
            "目标地址、无人机ID和频率：需停止发送后，重新启动发送生效。"
            "UDP sendto成功不代表无人机已接收。"
        )
        note.setWordWrap(True)
        note.setObjectName("droneRestartNote")
        form.addRow(note)
        self.tabs.addTab(tab, "无人机发送")

    def _build_protocol_tab(self, settings: DemoAppSettings) -> None:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.timeout_ms = self._spin(100, 60000, settings.track_stale_timeout_ms)
        self.timeout_ms.setSuffix(" ms")
        self.byte_order = QComboBox()
        self.byte_order.addItems(["little", "big"])
        self.byte_order.setCurrentText(settings.radar_byte_order)
        self.single_frame = QLabel("是；Demo临时假设，尚未经过真实雷达抓包验证")
        self.single_frame.setWordWrap(True)
        form.addRow("航迹超时阈值", self.timeout_ms)
        form.addRow("雷达32位字节序", self.byte_order)
        form.addRow("一个UDP数据报一帧", self.single_frame)
        note = QLabel(
            "航迹超时阈值点击“应用”后立即生效；雷达字节序需停止并重新启动雷达监听。"
        )
        note.setWordWrap(True)
        note.setObjectName("protocolApplyNote")
        form.addRow(note)
        self.tabs.addTab(tab, "协议与航迹")

    def set_running_state(self, *, radar_listening: bool, sending: bool) -> None:
        for widget in (
            self.radar_host,
            self.radar_port,
            self.radar_source_host,
            self.radar_source_port,
            self.byte_order,
        ):
            widget.setEnabled(not radar_listening)
        for widget in (self.drone_host, self.drone_port, self.drone_id, self.frequency):
            widget.setEnabled(not sending)
        # 航迹超时可立即应用，因此运行时仍可编辑。
        self.timeout_ms.setEnabled(True)

    def _set_control_sizes(self) -> None:
        for widget in self.findChildren(QWidget):
            if isinstance(widget, (QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox)):
                widget.setMinimumHeight(30)
                widget.setMinimumWidth(280)
        for button in self.findChildren(QPushButton):
            button.setMinimumHeight(30)

    def _set_tab_order(self) -> None:
        order = [
            self.radar_host,
            self.radar_port,
            self.radar_source_host,
            self.radar_source_port,
            self.drone_host,
            self.drone_port,
            self.drone_id,
            self.frequency,
            self.timeout_ms,
            self.byte_order,
        ]
        for first, second in zip(order, order[1:]):
            self.setTabOrder(first, second)

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin
