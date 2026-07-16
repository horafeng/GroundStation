"""工程演示导向的PyQt5 Widgets主窗口。"""

from __future__ import annotations

import json
from datetime import datetime

from PyQt5.QtCore import QItemSelectionModel, Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
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
from ground_station.video import VideoSourceConfig

from .controller import GroundStationController
from .main_workspace import MainWorkspace
from .settings_dialog import NetworkSettingsDialog
from .theme import DARK_THEME_QSS
from .widgets import CappedLogEdit, NumericTableItem

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
        self.settings_dialog = NetworkSettingsDialog(settings, self)
        # 保留既有公开控件属性，设置控件现归属于独立对话框。
        self.radar_host = self.settings_dialog.radar_host
        self.radar_port = self.settings_dialog.radar_port
        self.radar_source_host = self.settings_dialog.radar_source_host
        self.radar_source_port = self.settings_dialog.radar_source_port
        self.drone_host = self.settings_dialog.drone_host
        self.drone_port = self.settings_dialog.drone_port
        self.drone_id = self.settings_dialog.drone_id
        self.frequency = self.settings_dialog.frequency
        self.timeout_ms = self.settings_dialog.timeout_ms
        self.byte_order = self.settings_dialog.byte_order
        self.single_frame = self.settings_dialog.single_frame
        self._tracks: tuple[TrackLifecycleSnapshot, ...] = ()
        self._updating_table = False
        self.closed_cleanly = False
        self.setWindowTitle("无人机地面站 Demo — 地图主视角")
        self.resize(1600, 920)
        self.setMinimumSize(1120, 700)
        self._build_ui()
        self.workspace.configure_video(
            VideoSourceConfig(settings.video_source_mode, settings.video_rtsp_url)
        )
        self.status_labels["map"].setText(self.workspace.map_widget.status_label.text())
        self.status_labels["video"].setText(self.workspace.video_main.message.text())
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

        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.setObjectName("mainContentLogSplitter")
        self.business_splitter = QSplitter(Qt.Horizontal)
        self.business_splitter.setObjectName("businessSplitter")
        self.workspace = MainWorkspace(
            online_map=self.settings.map_mode == "online",
            tile_url=self.settings.map_tile_url,
            history_limit=self.settings.map_track_history_points,
        )
        self.workspace.setMinimumHeight(260)
        self.business_splitter.addWidget(self.workspace)

        self.right_splitter = QSplitter(Qt.Vertical)
        self.right_splitter.addWidget(self._build_radar_info())
        self.right_splitter.addWidget(self._build_target_details())
        self.right_splitter.addWidget(self._build_mode_panel())
        self.right_splitter.addWidget(self._build_network_panel())
        self.right_splitter.setMinimumWidth(390)
        self.right_splitter.setMaximumWidth(500)
        self.business_splitter.addWidget(self.right_splitter)
        self.business_splitter.setStretchFactor(0, 5)
        self.business_splitter.setStretchFactor(1, 2)
        self.main_splitter.addWidget(self.business_splitter)
        self.main_splitter.addWidget(self._build_track_table())
        self.main_splitter.addWidget(self._build_logs())
        self.main_splitter.setStretchFactor(0, 6)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setStretchFactor(2, 2)
        self.main_splitter.setSizes([560, 220, 180])
        root.addWidget(self.main_splitter, 1)
        self.setCentralWidget(central)

    def _build_status_bar(self) -> QWidget:
        box = QGroupBox("运行状态")
        layout = QGridLayout(box)
        self.status_labels: dict[str, QLabel] = {}
        definitions = [
            ("radar", "雷达监听", "未启动"),
            ("radar_data", "雷达数据", "尚未收到数据"),
            ("radar_age", "数据间隔", "--"),
            ("radar_time", "最近雷达报文", "--"),
            ("valid", "有效帧", "0"),
            ("invalid", "错误帧", "0"),
            ("send", "无人机UDP", "已停止（无接收确认）"),
            ("ack", "接收确认", "未知（Demo协议无ACK）"),
            ("mode", "当前模式", "待命(0)"),
            ("sequence", "发送序号", "--"),
            ("send_time", "最近发送时间", "--"),
            ("frequency", "实际频率", "0.00 Hz"),
            ("local_success", "本机发送成功", "0"),
            ("local_failure", "本机发送失败", "0"),
            ("target", "当前目标", "无效"),
            ("map", "地图状态", "本地Demo地图"),
            ("video", "视频状态", "未连接"),
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
            layout.addWidget(cell, index // 7, index % 7)
            self.status_labels[key] = label
        udp_tip = "本机发送成功仅表示UDP sendto未抛出异常，不代表无人机端已经收到。当前Demo协议无ACK。"
        self.status_labels["send"].setToolTip(udp_tip)
        self.status_labels["local_success"].setToolTip(udp_tip)
        self.status_labels["ack"].setToolTip(udp_tip)
        self.quick_settings_button = QPushButton("系统设置...")
        self.quick_settings_button.setMinimumHeight(32)
        layout.addWidget(self.quick_settings_button, 2, 5, 1, 2)
        return box

    def _build_track_table(self) -> QWidget:
        box = QGroupBox("航迹列表（内部始终按绝对编号关联）")
        box.setMinimumHeight(160)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(7, 12, 7, 7)
        layout.setSpacing(4)
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
        self.track_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.track_table.setMinimumHeight(145)
        self.track_table.setAlternatingRowColors(True)
        self.track_table.verticalHeader().setVisible(False)
        header = self.track_table.horizontalHeader()
        header.setMinimumHeight(28)
        header.setStretchLastSection(False)
        for column in (0, 1, 2, 5, 9, 11):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        for column in (3, 4, 6, 7, 8, 10):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        for column, width in ((3, 125), (4, 125), (6, 82), (7, 72), (8, 82), (10, 165)):
            self.track_table.setColumnWidth(column, width)
        layout.addWidget(self.track_table, 1)
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
        layout = QVBoxLayout(box)
        form = QFormLayout()
        self.config_summary: dict[str, QLabel] = {
            "radar": QLabel(), "source": QLabel(), "drone": QLabel(), "frequency": QLabel(),
            "timeout": QLabel(), "byte_order": QLabel(),
        }
        form.addRow("雷达监听", self.config_summary["radar"])
        form.addRow("来源过滤", self.config_summary["source"])
        form.addRow("无人机目标", self.config_summary["drone"])
        form.addRow("发送频率", self.config_summary["frequency"])
        form.addRow("航迹超时", self.config_summary["timeout"])
        form.addRow("雷达字节序", self.config_summary["byte_order"])
        layout.addLayout(form)
        self.settings_button = QPushButton("网络与配置...")
        self.settings_button.setObjectName("networkSettingsButton")
        self.settings_button.setMinimumHeight(32)
        layout.addWidget(self.settings_button)
        self.radar_toggle = QPushButton("启动雷达监听")
        self.radar_toggle.setObjectName("radarToggleButton")
        self.send_toggle = QPushButton("启动无人机发送")
        self.send_toggle.setObjectName("sendToggleButton")
        self.send_toggle.setToolTip(
            "本机发送成功仅表示UDP sendto未抛出异常；当前Demo协议无ACK，无法确认无人机已接收。"
        )
        buttons = QHBoxLayout()
        buttons.addWidget(self.radar_toggle)
        buttons.addWidget(self.send_toggle)
        layout.addLayout(buttons)
        self._update_config_summary()
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
        self.log_tabs.setMinimumHeight(140)
        self.log_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return self.log_tabs

    def _connect_signals(self) -> None:
        self.workspace.target_clicked.connect(self.select_target)
        self.workspace.map_status_changed.connect(
            lambda text: self.status_labels["map"].setText(text)
        )
        self.workspace.view_changed.connect(
            lambda text: self._append_log("runtime", f"主视角切换：{text}")
        )
        self.track_table.itemSelectionChanged.connect(self._table_selection_changed)
        self.mode_group.buttonClicked[int].connect(self._mode_clicked)
        self.radar_toggle.clicked.connect(self._toggle_radar)
        self.send_toggle.clicked.connect(self._toggle_sending)
        self.settings_button.clicked.connect(self._open_settings)
        self.quick_settings_button.clicked.connect(self._open_settings)
        self.settings_dialog.settings_applied.connect(self._apply_settings)
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

    def _open_settings(self) -> None:
        self.settings_dialog.set_running_state(
            radar_listening=self.controller.radar_receiver.running,
            sending=self.controller.sending,
        )
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _apply_settings(self) -> None:
        self.controller.repository.set_stale_timeout_ms(self.timeout_ms.value())
        online = self.settings_dialog.map_mode.currentData() == "online"
        self.workspace.set_online_map(online)
        self.workspace.set_tile_url(self.settings_dialog.map_tile_url.text().strip())
        self.workspace.set_history_limit(self.settings_dialog.map_history_points.value())
        video_config = VideoSourceConfig(
            mode=str(self.settings_dialog.video_mode.currentData()),
            rtsp_url=self.settings_dialog.video_rtsp_url.text().strip(),
        )
        self.workspace.configure_video(video_config)
        self.status_labels["video"].setText(self.workspace.video_main.message.text())
        self._update_config_summary()
        messages = ["航迹超时阈值、地图与视频展示设置已立即应用"]
        if self.controller.radar_receiver.running:
            messages.append("雷达监听相关设置需停止并重新启动监听后生效")
        if self.controller.sending:
            messages.append("无人机目标与频率需停止并重新启动发送后生效")
        self._append_log("runtime", "；".join(messages))

    def _update_config_summary(self) -> None:
        if not hasattr(self, "config_summary"):
            return
        self.config_summary["radar"].setText(
            f"{self.radar_host.text().strip()}:{self.radar_port.value()}"
        )
        source_host = self.radar_source_host.text().strip() or "不限"
        source_port = self.radar_source_port.value()
        self.config_summary["source"].setText(
            source_host if source_port == 0 else f"{source_host}:{source_port}"
        )
        self.config_summary["drone"].setText(
            f"{self.drone_host.text().strip()}:{self.drone_port.value()}"
        )
        self.config_summary["frequency"].setText(f"{self.frequency.value():.1f} Hz")
        self.config_summary["timeout"].setText(f"{self.timeout_ms.value()} ms（Demo假设）")
        self.config_summary["byte_order"].setText(self.byte_order.currentText())

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
        running = status in ("启动中", "监听中", "停止中")
        self.radar_toggle.setText("停止雷达监听" if running else "启动雷达监听")
        self.settings_dialog.set_running_state(
            radar_listening=running, sending=self.controller.sending
        )

    def _update_send_status(self, status: str) -> None:
        display = f"{status}（无接收确认）"
        self.status_labels["send"].setText(display)
        self.send_toggle.setText("停止无人机发送" if status == "发送中" else "启动无人机发送")
        running = status == "发送中"
        self.settings_dialog.set_running_state(
            radar_listening=self.controller.radar_receiver.running, sending=running
        )

    def _update_radar_state(self, frame: object) -> None:
        radar = frame.radar  # type: ignore[attr-defined]
        self.radar_labels["lon"].setText(f"{radar.longitude_deg:.5f}°")
        self.radar_labels["lat"].setText(f"{radar.latitude_deg:.5f}°")
        self.radar_labels["alt"].setText(f"{radar.altitude_m} m")
        self.radar_labels["sat"].setText(str(radar.satellite_count))
        timestamp = self._format_unix_ms(self.controller.last_radar_state_unix_ms)
        self.radar_labels["updated"].setText(timestamp)
        self.workspace.set_home(radar.longitude_deg, radar.latitude_deg)

    def _update_tracks(self, tracks: object) -> None:
        self._tracks = tuple(tracks)  # type: ignore[arg-type]
        selected = self.controller.selection.selected_absolute_id
        self.workspace.update_tracks(self._tracks)
        self.workspace.set_selected_track(selected)
        vertical_position = self.track_table.verticalScrollBar().value()
        horizontal_position = self.track_table.horizontalScrollBar().value()
        self._updating_table = True
        signals_were_blocked = self.track_table.blockSignals(True)
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
        if sort_column >= 0:
            self.track_table.sortItems(sort_column, sort_order)
        self._apply_table_selection(selected, scroll=False)
        self.track_table.verticalScrollBar().setValue(vertical_position)
        self.track_table.horizontalScrollBar().setValue(horizontal_position)
        self.track_table.blockSignals(signals_were_blocked)
        self._updating_table = False
        self._update_target_details()

    def _table_selection_changed(self) -> None:
        if self._updating_table:
            return
        selected_rows = self.track_table.selectionModel().selectedRows()
        row = selected_rows[0].row() if selected_rows else -1
        item = self.track_table.item(row, 0) if row >= 0 else None
        if item is not None:
            self.select_target(int(item.data(Qt.UserRole)))

    def select_target(self, absolute_id: int) -> None:
        scroll_after_selection = False
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
                scroll_after_selection = True
            else:
                self.controller.cancel_selection(decision.confirmation)
                self._append_log("runtime", "已取消目标切换，保持原目标")
        elif decision.status is SelectionStatus.SELECTED:
            scroll_after_selection = True
        self._sync_selection(
            self.controller.selection.selected_absolute_id, scroll=scroll_after_selection
        )

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

    def _sync_selection(self, absolute_id: object, *, scroll: bool = False) -> None:
        selected = None if absolute_id is None else int(absolute_id)
        self.workspace.set_selected_track(selected)
        self.status_labels["target"].setText(
            "无效" if selected is None else f"绝对编号 {selected}"
        )
        vertical_position = self.track_table.verticalScrollBar().value()
        horizontal_position = self.track_table.horizontalScrollBar().value()
        self._updating_table = True
        self._apply_table_selection(selected, scroll=scroll)
        if not scroll:
            self.track_table.verticalScrollBar().setValue(vertical_position)
            self.track_table.horizontalScrollBar().setValue(horizontal_position)
        self._updating_table = False
        self._update_target_details()

    def _apply_table_selection(self, absolute_id: int | None, *, scroll: bool) -> None:
        selection_model = self.track_table.selectionModel()
        selection_model.clearSelection()
        if absolute_id is None:
            return
        for row in range(self.track_table.rowCount()):
            item = self.track_table.item(row, 0)
            if item is None or int(item.data(Qt.UserRole)) != absolute_id:
                continue
            index = self.track_table.model().index(row, 0)
            selection_model.select(
                index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows
            )
            if scroll:
                self.track_table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
            return

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
        data_status = self.controller.radar_data_status()
        data_age = self.controller.radar_data_age_seconds()
        self.status_labels["radar_data"].setText(data_status)
        self.status_labels["radar_age"].setText(
            "--" if data_age is None else f"最近报文距今 {data_age:.1f} 秒"
        )
        self.status_labels["valid"].setText(str(self.controller.valid_radar_frames))
        self.status_labels["invalid"].setText(str(self.controller.invalid_radar_frames))
        self.status_labels["radar_time"].setText(self._format_unix_ms(self.controller.last_radar_unix_ms))
        self.status_labels["frequency"].setText(f"{self.controller.actual_send_frequency_hz:.2f} Hz")
        self.status_labels["local_success"].setText(str(self.controller.send_success_count))
        self.status_labels["local_failure"].setText(str(self.controller.send_failure_count))

    def _append_log(self, key: str, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.logs[key].appendPlainText(f"[{timestamp}] {text}")

    @staticmethod
    def _format_unix_ms(value: int | None) -> str:
        if value is None:
            return "--"
        # 2000-01-01之前的值在本项目中视为错误时钟域，避免把单调时钟显示成1970日期。
        if value < 946_684_800_000:
            return "时间无效（非Unix墙钟）"
        return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def closeEvent(self, event: object) -> None:
        self._timer.stop()
        workspace_ok = self.workspace.shutdown()
        controller_ok = self.controller.shutdown()
        self.closed_cleanly = workspace_ok and controller_ok
        event.accept()  # type: ignore[attr-defined]

    def _apply_style(self) -> None:
        self.setStyleSheet(DARK_THEME_QSS)
        self.settings_dialog.setStyleSheet(DARK_THEME_QSS)
