"""工程演示导向的PyQt5 Widgets主窗口。"""

from __future__ import annotations

import json
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ground_station.config import DemoAppSettings
from ground_station.domain import MissionMode
from ground_station.network import RadarReceiverConfig
from ground_station.selection import SelectionStatus, TargetSwitchConfirmation
from ground_station.sending import SendError, SendRecord
from ground_station.tracks import TrackLifecycleSnapshot

from .controller import GroundStationController
from .widgets import CappedLogEdit, NumericTableItem, RadarDisplayWidget

TARGET_TYPE_NAMES = {
    0: "未知",
    1: "车辆",
    2: "人员",
    3: "无人机",
    4: "保留4",
    5: "保留5",
    6: "保留6",
    7: "保留7",
}
MODE_NAMES = {
    MissionMode.STANDBY: "待命",
    MissionMode.TAKEOFF: "起飞",
    MissionMode.TRACK: "跟踪",
    MissionMode.RETURN_HOME: "返航",
    MissionMode.LAND: "降落",
}


class GroundStationMainWindow(QMainWindow):
    def __init__(
        self,
        settings: DemoAppSettings,
        *,
        config_error: str | None = None,
        controller: GroundStationController | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.controller = controller or GroundStationController(settings, self)
        self._tracks: tuple[TrackLifecycleSnapshot, ...] = ()
        self._updating_table = False
        self.closed_cleanly = False
        self.setWindowTitle("无人机地面站 Demo — 雷达航迹与任务发送")
        self.resize(1600, 920)
        self.setMinimumSize(1120, 700)
        self._build_ui()
        self._connect_signals()
        self._apply_style()
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh_ui_tick)
        self._timer.start()
        self._set_mode_checked(MissionMode.STANDBY)
        self._append_log("runtime", "应用已启动；默认不启动无人机发送")
        if config_error:
            self._append_log("protocol", config_error)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        root.addWidget(self._build_status_bar())

        horizontal = QSplitter(Qt.Horizontal)
        left = QSplitter(Qt.Vertical)
        left.addWidget(self._build_radar_panel())
        left.addWidget(self._build_track_table())
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 2)
        horizontal.addWidget(left)

        right = QSplitter(Qt.Vertical)
        right.addWidget(self._build_radar_info())
        right.addWidget(self._build_target_details())
        right.addWidget(self._build_mode_panel())
        right.addWidget(self._build_network_panel())
        right.setMinimumWidth(390)
        horizontal.addWidget(right)
        horizontal.setStretchFactor(0, 4)
        horizontal.setStretchFactor(1, 2)
        root.addWidget(horizontal, 1)
        root.addWidget(self._build_logs(), 0)
        self.setCentralWidget(central)

    def _build_status_bar(self) -> QWidget:
        box = QGroupBox("运行状态")
        layout = QGridLayout(box)
        self.status_labels: dict[str, QLabel] = {}
        definitions = [
            ("radar", "雷达UDP", "已停止"),
            ("radar_time", "最近雷达报文", "--"),
            ("valid", "有效帧", "0"),
            ("invalid", "错误帧", "0"),
            ("send", "无人机UDP", "已停止"),
            ("mode", "当前模式", "待命(0)"),
            ("sequence", "发送序号", "--"),
            ("send_time", "最近发送时间", "--"),
            ("frequency", "实际频率", "0.00 Hz"),
            ("success", "成功/失败", "0 / 0"),
        ]
        for index, (key, title, value) in enumerate(definitions):
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(5, 1, 5, 1)
            heading = QLabel(title)
            heading.setStyleSheet("color:#8fa9b8;font-size:11px")
            label = QLabel(value)
            label.setObjectName(f"status_{key}")
            label.setStyleSheet("font-weight:600")
            cell_layout.addWidget(heading)
            cell_layout.addWidget(label)
            layout.addWidget(cell, 0, index)
            self.status_labels[key] = label
        return box

    def _build_radar_panel(self) -> QWidget:
        box = QGroupBox("离线二维雷达显示")
        layout = QVBoxLayout(box)
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("固定量程："))
        self.range_combo = QComboBox()
        self.range_combo.setObjectName("rangeCombo")
        for value, label in ((500, "500 m"), (1000, "1 km"), (2000, "2 km"), (5000, "5 km")):
            self.range_combo.addItem(label, value)
        self.range_combo.setCurrentIndex(self.range_combo.findData(self.settings.radar_display_range_m))
        range_row.addWidget(self.range_combo)
        note = QLabel("局部平面换算仅用于Demo展示")
        note.setStyleSheet("color:#d3a84e")
        range_row.addWidget(note)
        range_row.addStretch()
        layout.addLayout(range_row)
        self.radar_display = RadarDisplayWidget()
        self.radar_display.setObjectName("radarDisplay")
        self.radar_display.set_range_m(self.settings.radar_display_range_m)
        layout.addWidget(self.radar_display, 1)
        return box

    def _build_track_table(self) -> QWidget:
        box = QGroupBox("航迹列表（内部始终按绝对编号关联）")
        layout = QVBoxLayout(box)
        columns = [
            "显示编号", "绝对编号", "类型", "经度", "纬度", "高度m", "距离m",
            "方位°", "速度m/s", "状态", "最后更新", "丢失ms",
        ]
        self.track_table = QTableWidget(0, len(columns))
        self.track_table.setObjectName("trackTable")
        self.track_table.setHorizontalHeaderLabels(columns)
        self.track_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.track_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.track_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.track_table.setSortingEnabled(True)
        self.track_table.verticalHeader().setVisible(False)
        self.track_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.track_table)
        return box

    def _build_radar_info(self) -> QWidget:
        box = QGroupBox("雷达自身信息")
        form = QFormLayout(box)
        self.radar_labels = {key: QLabel("--") for key in ("lon", "lat", "alt", "sat", "updated")}
        form.addRow("GPS经度", self.radar_labels["lon"])
        form.addRow("GPS纬度", self.radar_labels["lat"])
        form.addRow("GPS海拔", self.radar_labels["alt"])
        form.addRow("卫星数量", self.radar_labels["sat"])
        form.addRow("更新时间", self.radar_labels["updated"])
        warning = QLabel("高度基准：待实物核对")
        warning.setStyleSheet("color:#d3a84e;font-weight:600")
        form.addRow(warning)
        return box

    def _build_target_details(self) -> QWidget:
        box = QGroupBox("当前人工选中目标")
        form = QFormLayout(box)
        keys = ("valid", "display", "absolute", "coordinate", "timestamp", "realtime", "lost")
        self.target_labels = {key: QLabel("--") for key in keys}
        self.target_labels["valid"].setText("目标无效（尚未选择）")
        form.addRow("有效目标", self.target_labels["valid"])
        form.addRow("显示编号", self.target_labels["display"])
        form.addRow("绝对编号", self.target_labels["absolute"])
        form.addRow("经纬高", self.target_labels["coordinate"])
        form.addRow("坐标时间戳", self.target_labels["timestamp"])
        form.addRow("坐标状态", self.target_labels["realtime"])
        form.addRow("丢失持续", self.target_labels["lost"])
        return box

    def _build_mode_panel(self) -> QWidget:
        box = QGroupBox("任务模式（地面站仅保存和发送模式）")
        layout = QGridLayout(box)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[MissionMode, QPushButton] = {}
        for index, mode in enumerate(MissionMode):
            button = QPushButton(f"{MODE_NAMES[mode]}  {int(mode)}")
            button.setObjectName(f"modeButton{int(mode)}")
            button.setCheckable(True)
            self.mode_group.addButton(button, int(mode))
            self.mode_buttons[mode] = button
            layout.addWidget(button, index // 3, index % 3)
        return box

    def _build_network_panel(self) -> QWidget:
        box = QGroupBox("网络与配置")
        layout = QGridLayout(box)
        self.radar_host = QLineEdit(self.settings.radar_listen_host)
        self.radar_port = self._spin(1, 65535, self.settings.radar_listen_port)
        self.radar_source_host = QLineEdit(self.settings.radar_source_host)
        self.radar_source_host.setPlaceholderText("留空不过滤")
        self.radar_source_port = self._spin(0, 65535, self.settings.radar_source_port)
        self.drone_host = QLineEdit(self.settings.drone_host)
        self.drone_port = self._spin(1, 65535, self.settings.drone_port)
        self.drone_id = QDoubleSpinBox()
        self.drone_id.setDecimals(0)
        self.drone_id.setRange(0, 0xFFFFFFFF)
        self.drone_id.setValue(self.settings.drone_id)
        self.frequency = QDoubleSpinBox()
        self.frequency.setRange(0.1, 100.0)
        self.frequency.setDecimals(1)
        self.frequency.setValue(self.settings.send_frequency_hz)
        self.timeout_ms = self._spin(100, 60000, self.settings.track_stale_timeout_ms)
        self.byte_order = QComboBox()
        self.byte_order.addItems(["little", "big"])
        self.byte_order.setCurrentText(self.settings.radar_byte_order)
        self.single_frame = QLabel("是 — Demo临时假设，尚未经过真实抓包验证")
        apply_note = QLabel("配置在启动对应网络时应用；运行中修改需先停止")
        apply_note.setStyleSheet("color:#8fa9b8")
        fields = [
            ("雷达监听IP", self.radar_host), ("雷达监听端口", self.radar_port),
            ("来源IP过滤", self.radar_source_host), ("来源端口过滤", self.radar_source_port),
            ("无人机目标IP", self.drone_host), ("无人机目标端口", self.drone_port),
            ("无人机ID", self.drone_id), ("发送频率Hz", self.frequency),
            ("航迹超时ms（Demo假设）", self.timeout_ms), ("雷达字节序", self.byte_order),
            ("一报一帧", self.single_frame),
        ]
        for row, (label, widget) in enumerate(fields):
            layout.addWidget(QLabel(label), row, 0)
            layout.addWidget(widget, row, 1)
        self.radar_toggle = QPushButton("启动雷达监听")
        self.radar_toggle.setObjectName("radarToggleButton")
        self.send_toggle = QPushButton("启动无人机发送")
        self.send_toggle.setObjectName("sendToggleButton")
        layout.addWidget(self.radar_toggle, len(fields), 0)
        layout.addWidget(self.send_toggle, len(fields), 1)
        layout.addWidget(apply_note, len(fields) + 1, 0, 1, 2)
        return box

    def _build_logs(self) -> QWidget:
        self.log_tabs = QTabWidget()
        self.log_tabs.setObjectName("logTabs")
        self.logs: dict[str, CappedLogEdit] = {}
        for key, title in (
            ("runtime", "运行日志"), ("radar", "雷达报文"), ("send", "无人机发送"),
            ("hex", "十六进制"), ("protocol", "协议错误"),
        ):
            edit = CappedLogEdit(self.settings.log_max_lines)
            edit.setObjectName(f"log_{key}")
            self.logs[key] = edit
            self.log_tabs.addTab(edit, title)
        self.log_tabs.setMaximumHeight(220)
        return self.log_tabs

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def _connect_signals(self) -> None:
        self.range_combo.currentIndexChanged.connect(
            lambda: self.radar_display.set_range_m(int(self.range_combo.currentData()))
        )
        self.radar_display.track_clicked.connect(self.select_target)
        self.track_table.itemSelectionChanged.connect(self._table_selection_changed)
        self.mode_group.buttonClicked[int].connect(self._mode_clicked)
        self.radar_toggle.clicked.connect(self._toggle_radar)
        self.send_toggle.clicked.connect(self._toggle_sending)
        self.controller.tracks_changed.connect(self._update_tracks)
        self.controller.radar_state_changed.connect(self._update_radar_state)
        self.controller.radar_status_changed.connect(self._update_radar_status)
        self.controller.radar_frame_logged.connect(lambda text: self._append_log("radar", text))
        self.controller.protocol_error_logged.connect(self._protocol_error)
        self.controller.send_status_changed.connect(self._update_send_status)
        self.controller.send_recorded.connect(self._send_record)
        self.controller.send_error_logged.connect(self._send_error)
        self.controller.mission_mode_changed.connect(self._mission_mode_changed)
        self.controller.selection_changed.connect(self._sync_selection)
        self.controller.runtime_log.connect(lambda text: self._append_log("runtime", text))

    def _toggle_radar(self) -> None:
        if self.controller.radar_receiver.running:
            self.controller.stop_radar()
            return
        try:
            self.controller.start_radar(
                RadarReceiverConfig(
                    self.radar_host.text().strip(),
                    self.radar_port.value(),
                    self.radar_source_host.text().strip(),
                    self.radar_source_port.value(),
                    self.byte_order.currentText(),
                    True,
                )
            )
        except (ValueError, RuntimeError) as error:
            self._append_log("protocol", str(error))

    def _toggle_sending(self) -> None:
        if self.controller.sending:
            self.controller.stop_sending()
            return
        try:
            self.controller.start_sending(
                host=self.drone_host.text().strip(),
                port=self.drone_port.value(),
                drone_id=int(self.drone_id.value()),
                frequency_hz=self.frequency.value(),
                track_timeout_ms=self.timeout_ms.value(),
            )
        except (ValueError, RuntimeError, OSError) as error:
            self._append_log("protocol", str(error))

    def _mode_clicked(self, mode_value: int) -> None:
        self.controller.set_mode(MissionMode(mode_value))

    def _mission_mode_changed(self, mode: MissionMode) -> None:
        self._set_mode_checked(mode)
        self.status_labels["mode"].setText(f"{MODE_NAMES[mode]}({int(mode)})")
        self._append_log("runtime", f"任务模式切换为 {MODE_NAMES[mode]}({int(mode)})，请求立即发送")

    def _set_mode_checked(self, mode: MissionMode) -> None:
        self.mode_buttons[mode].setChecked(True)

    def _update_radar_status(self, status: str) -> None:
        self.status_labels["radar"].setText(status)
        running = status in ("启动中", "接收中", "停止中") and status != "已停止"
        self.radar_toggle.setText("停止雷达监听" if running else "启动雷达监听")
        for widget in (
            self.radar_host, self.radar_port, self.radar_source_host,
            self.radar_source_port, self.byte_order,
        ):
            widget.setEnabled(not running)

    def _update_send_status(self, status: str) -> None:
        self.status_labels["send"].setText(status)
        self.send_toggle.setText("停止无人机发送" if status == "发送中" else "启动无人机发送")
        running = status == "发送中"
        for widget in (
            self.drone_host, self.drone_port, self.drone_id, self.frequency, self.timeout_ms,
        ):
            widget.setEnabled(not running)

    def _update_radar_state(self, frame: object) -> None:
        radar = frame.radar  # type: ignore[attr-defined]
        self.radar_labels["lon"].setText(f"{radar.longitude_deg:.5f}°")
        self.radar_labels["lat"].setText(f"{radar.latitude_deg:.5f}°")
        self.radar_labels["alt"].setText(f"{radar.altitude_m} m")
        self.radar_labels["sat"].setText(str(radar.satellite_count))
        timestamp = self._format_unix_ms(self.controller.last_radar_unix_ms)
        self.radar_labels["updated"].setText(timestamp)
        self.radar_display.set_radar_position(radar.longitude_deg, radar.latitude_deg)

    def _update_tracks(self, tracks: object) -> None:
        self._tracks = tuple(tracks)  # type: ignore[arg-type]
        selected = self.controller.selection.selected_absolute_id
        self.radar_display.set_tracks(self._tracks)
        self.radar_display.set_selected_absolute_id(selected)
        self._updating_table = True
        sort_column = self.track_table.horizontalHeader().sortIndicatorSection()
        sort_order = self.track_table.horizontalHeader().sortIndicatorOrder()
        self.track_table.setSortingEnabled(False)
        self.track_table.setRowCount(len(self._tracks))
        for row, track in enumerate(self._tracks):
            coordinate = track.last_valid_coordinate
            observation = track.latest_observation
            values = [
                (str(track.display_id), track.display_id),
                (str(track.absolute_id), track.absolute_id),
                (TARGET_TYPE_NAMES[int(observation.target_type)], int(observation.target_type)),
                ("--" if coordinate is None else f"{coordinate.longitude_deg:.7f}", -999 if coordinate is None else coordinate.longitude_deg),
                ("--" if coordinate is None else f"{coordinate.latitude_deg:.7f}", -999 if coordinate is None else coordinate.latitude_deg),
                ("--" if coordinate is None else f"{coordinate.relative_ground_height_m:.1f}", -999999 if coordinate is None else coordinate.relative_ground_height_m),
                (f"{observation.distance_m:.1f}", observation.distance_m),
                (f"{observation.azimuth_deg:.1f}", observation.azimuth_deg),
                (f"{observation.speed_mps:.1f}", observation.speed_mps),
                ("实时" if track.is_realtime else "丢失/最后有效", 1 if track.is_realtime else 0),
                (self._format_unix_ms(track.last_updated_unix_ms), track.last_updated_unix_ms),
                (str(track.lost_duration_ms), track.lost_duration_ms),
            ]
            for column, (text, sort_value) in enumerate(values):
                item = NumericTableItem(text)
                item.setData(NumericTableItem.SORT_ROLE, sort_value)
                item.setData(Qt.UserRole, track.absolute_id)
                self.track_table.setItem(row, column, item)
        self.track_table.setSortingEnabled(True)
        self.track_table.sortItems(sort_column, sort_order)
        self._updating_table = False
        self._sync_selection(selected)
        self._update_target_details()

    def _table_selection_changed(self) -> None:
        if self._updating_table:
            return
        row = self.track_table.currentRow()
        item = self.track_table.item(row, 0) if row >= 0 else None
        if item is not None:
            self.select_target(int(item.data(Qt.UserRole)))

    def select_target(self, absolute_id: int) -> None:
        try:
            decision = self.controller.request_selection(absolute_id)
        except KeyError as error:
            self._append_log("protocol", str(error))
            return
        if decision.status is SelectionStatus.CONFIRMATION_REQUIRED:
            assert decision.confirmation is not None
            if self._confirm_target_switch(decision.confirmation):
                self.controller.confirm_selection(decision.confirmation)
                self._append_log("runtime", "已确认切换目标，触发立即发送")
            else:
                self.controller.cancel_selection(decision.confirmation)
                self._append_log("runtime", "已取消目标切换，保持原目标")
        self._sync_selection(self.controller.selection.selected_absolute_id)

    def _confirm_target_switch(self, confirmation: TargetSwitchConfirmation) -> bool:
        old = confirmation.old_target
        new = confirmation.new_target
        question = f"是否将跟踪目标由航迹{old.display_id}切换为航迹{new.display_id}？"
        details = (
            f"原目标：显示编号 {old.display_id}，绝对编号 {old.absolute_id}\n"
            f"原坐标：{old.longitude_deg}, {old.latitude_deg}, {old.relative_ground_height_m}m\n\n"
            f"新目标：显示编号 {new.display_id}，绝对编号 {new.absolute_id}\n"
            f"新坐标：{new.longitude_deg}, {new.latitude_deg}, {new.relative_ground_height_m}m"
        )
        box = QMessageBox(QMessageBox.Question, "确认切换目标", question, parent=self)
        box.setInformativeText(details)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        return box.exec_() == QMessageBox.Yes

    def _sync_selection(self, absolute_id: object) -> None:
        selected = None if absolute_id is None else int(absolute_id)
        self.radar_display.set_selected_absolute_id(selected)
        self._updating_table = True
        self.track_table.clearSelection()
        if selected is not None:
            for row in range(self.track_table.rowCount()):
                item = self.track_table.item(row, 0)
                if item is not None and int(item.data(Qt.UserRole)) == selected:
                    self.track_table.selectRow(row)
                    break
        self._updating_table = False
        self._update_target_details()

    def _update_target_details(self) -> None:
        target = self.controller.selection.selected_track()
        if target is None or target.last_valid_coordinate is None:
            self.target_labels["valid"].setText("目标无效（尚未选择或无有效坐标）")
            for key in ("display", "absolute", "coordinate", "timestamp", "realtime", "lost"):
                self.target_labels[key].setText("--")
            return
        coordinate = target.last_valid_coordinate
        self.target_labels["valid"].setText("1 — 存在有效选中目标")
        self.target_labels["display"].setText(str(target.display_id))
        self.target_labels["absolute"].setText(str(target.absolute_id))
        self.target_labels["coordinate"].setText(
            f"{coordinate.longitude_deg:.7f}, {coordinate.latitude_deg:.7f}, "
            f"{coordinate.relative_ground_height_m:.1f}m"
        )
        self.target_labels["timestamp"].setText(self._format_unix_ms(coordinate.received_unix_ms))
        self.target_labels["realtime"].setText("实时坐标" if target.is_realtime else "最后有效坐标（目标丢失）")
        self.target_labels["lost"].setText(f"{target.lost_duration_ms} ms")

    def _send_record(self, record: SendRecord) -> None:
        self.status_labels["sequence"].setText(str(record.sequence))
        self.status_labels["send_time"].setText(datetime.now().strftime("%H:%M:%S.%f")[:-3])
        self._append_log(
            "send",
            f"seq={record.sequence} kind={record.kind.value} reason={record.reason} bytes={record.byte_count}",
        )
        self._append_log("hex", record.payload.hex(" ").upper())

    def _send_error(self, error: SendError) -> None:
        self._append_log("protocol", json.dumps(error.to_dict(), ensure_ascii=False))

    def _protocol_error(self, error: object) -> None:
        self._append_log("protocol", json.dumps(error, ensure_ascii=False, default=str))

    def _refresh_ui_tick(self) -> None:
        self.controller.refresh_tracks()
        self.status_labels["valid"].setText(str(self.controller.valid_radar_frames))
        self.status_labels["invalid"].setText(str(self.controller.invalid_radar_frames))
        self.status_labels["radar_time"].setText(self._format_unix_ms(self.controller.last_radar_unix_ms))
        self.status_labels["frequency"].setText(f"{self.controller.actual_send_frequency_hz:.2f} Hz")
        self.status_labels["success"].setText(
            f"{self.controller.send_success_count} / {self.controller.send_failure_count}"
        )

    def _append_log(self, key: str, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.logs[key].appendPlainText(f"[{timestamp}] {text}")

    @staticmethod
    def _format_unix_ms(value: int | None) -> str:
        if value is None:
            return "--"
        return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def closeEvent(self, event: object) -> None:
        self._timer.stop()
        self.closed_cleanly = self.controller.shutdown()
        event.accept()  # type: ignore[attr-defined]

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow,QWidget { background:#13212c; color:#e7eef2; }
            QGroupBox { border:1px solid #365263; border-radius:4px; margin-top:7px; padding-top:8px; font-weight:600; }
            QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; }
            QPushButton { background:#27485c; border:1px solid #52758a; padding:6px; border-radius:3px; }
            QPushButton:hover { background:#326078; }
            QPushButton:checked { background:#bb7228; border-color:#ffc16b; }
            QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QTableWidget,QPlainTextEdit,QTabWidget::pane {
                background:#0e1a23; border:1px solid #365263; selection-background-color:#8c5a27;
            }
            QHeaderView::section { background:#203746; color:#e7eef2; padding:4px; border:1px solid #365263; }
            """
        )
