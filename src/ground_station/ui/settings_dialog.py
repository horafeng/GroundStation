"""System settings and an honest calibration placeholder."""

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

from .calibration_page import CalibrationUnavailablePage
from .theme import DARK_THEME_QSS


class NetworkSettingsDialog(QDialog):
    settings_applied = pyqtSignal()

    def __init__(self, settings: DemoAppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("系统设置")
        self.setObjectName("networkSettingsDialog")
        self.setMinimumWidth(640)
        self.resize(760, 560)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("primarySettingsTabs")
        self.system_tabs = QTabWidget()
        self.system_tabs.setObjectName("systemSettingsTabs")
        self._build_system_tabs(settings)
        self.tabs.addTab(self.system_tabs, "系统设置")
        self.calibration_page = CalibrationUnavailablePage()
        self.tabs.addTab(self.calibration_page, "人机校验")
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Apply | QDialogButtonBox.Close
        )
        self.button_box.button(QDialogButtonBox.Apply).setText("应用")
        self.button_box.button(QDialogButtonBox.Close).setText("关闭")
        self.button_box.button(QDialogButtonBox.Apply).clicked.connect(
            self.settings_applied
        )
        self.button_box.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(self.button_box)
        self._set_control_sizes()
        self._set_tab_order()
        self.setStyleSheet(DARK_THEME_QSS)

    def _build_system_tabs(self, settings: DemoAppSettings) -> None:
        self._build_radar_tab(settings)
        self._build_drone_tab(settings)
        self._build_protocol_tab(settings)
        self._build_map_tab(settings)
        self._build_video_tab(settings)

    def _build_radar_tab(self, settings: DemoAppSettings) -> None:
        form = self._new_form("雷达接收")
        self.radar_host = QLineEdit(settings.radar_listen_host)
        self.radar_port = self._spin(1, 65535, settings.radar_listen_port)
        self.radar_source_host = QLineEdit(settings.radar_source_host)
        self.radar_source_host.setPlaceholderText("留空表示不限制来源IP")
        self.radar_source_port = self._spin(0, 65535, settings.radar_source_port)
        form.addRow("本地监听IP", self.radar_host)
        form.addRow("本地监听端口", self.radar_port)
        form.addRow("来源IP过滤（可选）", self.radar_source_host)
        form.addRow("来源端口过滤（0表示不限）", self.radar_source_port)
        self._add_note(form, "监听参数需停止雷达监听后，重新启动监听生效。")

    def _build_drone_tab(self, settings: DemoAppSettings) -> None:
        form = self._new_form("无人机发送")
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
        self._add_note(form, "发送参数需停止并重新启动发送；sendto成功不代表对端已收到。")

    def _build_protocol_tab(self, settings: DemoAppSettings) -> None:
        form = self._new_form("协议与航迹")
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
        self._add_note(form, "超时阈值立即生效；字节序需重启雷达监听。")

    def _build_map_tab(self, settings: DemoAppSettings) -> None:
        form = self._new_form("地图")
        self.map_mode = QComboBox()
        self.map_mode.addItem("本地Demo地图", "local_demo")
        self.map_mode.addItem("在线 OpenStreetMap", "online")
        self.map_mode.setCurrentIndex(max(0, self.map_mode.findData(settings.map_mode)))
        self.map_tile_url = QLineEdit(settings.map_tile_url)
        self.map_history_points = self._spin(2, 1000, settings.map_track_history_points)
        form.addRow("地图模式", self.map_mode)
        form.addRow("在线瓦片模板", self.map_tile_url)
        form.addRow("每条航迹历史点上限", self.map_history_points)
        self._add_note(form, "地图模式点击“应用”后立即生效；在线瓦片注明来源归属。")

    def _build_video_tab(self, settings: DemoAppSettings) -> None:
        form = self._new_form("视频与存储")
        self.video_mode = QComboBox()
        self.video_mode.addItem("未连接", "disabled")
        self.video_mode.addItem("测试图案", "test_pattern")
        self.video_mode.addItem("RTSP地址占位", "rtsp")
        self.video_mode.setCurrentIndex(
            max(0, self.video_mode.findData(settings.video_source_mode))
        )
        self.video_rtsp_url = QLineEdit(settings.video_rtsp_url)
        self.image_directory = QLineEdit(settings.image_directory)
        self.recording_directory = QLineEdit(settings.recording_directory)
        form.addRow("视频源", self.video_mode)
        form.addRow("RTSP地址", self.video_rtsp_url)
        form.addRow("图片目录预留", self.image_directory)
        form.addRow("录像目录预留", self.recording_directory)
        self._add_note(form, "本轮不启用RTSP解码、录像、云台控制或AI识别。")

    def _new_form(self, title: str) -> QFormLayout:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.system_tabs.addTab(tab, title)
        return form

    @staticmethod
    def _add_note(form: QFormLayout, text: str) -> None:
        note = QLabel(text)
        note.setWordWrap(True)
        form.addRow(note)

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
        self.timeout_ms.setEnabled(True)

    def _set_control_sizes(self) -> None:
        control_types = (QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox)
        for widget in self.findChildren(QWidget):
            if isinstance(widget, control_types):
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
            self.map_mode,
            self.map_tile_url,
            self.map_history_points,
            self.video_mode,
            self.video_rtsp_url,
        ]
        for first, second in zip(order, order[1:]):
            self.setTabOrder(first, second)

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin
