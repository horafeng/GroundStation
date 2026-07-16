"""Centralized dark theme shared by the main window and dialogs."""

DARK_THEME_QSS = """
QMainWindow, QDialog, QWidget { background:#13212c; color:#e7eef2; }
QGroupBox { border:1px solid #365263; border-radius:4px; margin-top:7px; padding-top:8px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; color:#e7eef2; }
QLabel { color:#e7eef2; }
QPushButton { background:#27485c; color:#edf5f8; border:1px solid #52758a; padding:6px 10px; border-radius:3px; min-height:20px; }
QPushButton:hover { background:#326078; border-color:#79a5bb; }
QPushButton:checked { background:#bb7228; border-color:#ffc16b; color:#ffffff; }
QPushButton:disabled { background:#1b2d38; color:#8295a0; border-color:#314854; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTableWidget, QPlainTextEdit {
    background:#0e1a23; color:#e7eef2; border:1px solid #365263; selection-background-color:#8c5a27;
    selection-color:#ffffff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border:1px solid #79a5bb; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { background:#172630; color:#8295a0; }
QComboBox QAbstractItemView { background:#172b37; color:#e7eef2; selection-background-color:#326078; }
QHeaderView::section { background:#203746; color:#e7eef2; padding:5px; border:1px solid #365263; }
QTableWidget { gridline-color:#294653; alternate-background-color:#12232e; }
QTableWidget::item:selected { background:#8c5a27; color:#ffffff; }
QTabWidget::pane { background:#0e1a23; border:1px solid #365263; top:-1px; }
QTabBar::tab { background:#1b303e; color:#dce8ed; border:1px solid #365263; border-bottom:2px solid #365263; padding:7px 14px; min-height:20px; }
QTabBar::tab:selected { background:#27485c; color:#ffc16b; border-bottom:3px solid #e3943a; }
QTabBar::tab:hover:!selected { background:#274454; color:#ffffff; }
QTabBar::tab:disabled { background:#172630; color:#8295a0; }
QScrollBar:vertical { background:#10212b; width:12px; margin:0; }
QScrollBar:horizontal { background:#10212b; height:12px; margin:0; }
QScrollBar::handle { background:#456779; border:2px solid #10212b; border-radius:4px; min-height:24px; min-width:24px; }
QScrollBar::handle:hover { background:#5c879c; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QSplitter::handle { background:#365263; }
#compactStatusBar { background:#101c25; border:1px solid #365263; border-radius:4px; }
#compactStatusBar QLabel { color:#dce8ed; font-weight:600; }
#missionControlOverlay { background:rgba(8,20,27,218); border:1px solid #49697a; border-radius:6px; }
#missionControlOverlay QPushButton { min-width:64px; text-align:left; padding:7px 9px; }
#targetSummaryCard { background:rgba(8,20,27,225); border:1px solid #49697a; border-radius:6px; }
#targetCardTitle { color:#ffffff; font-size:15px; font-weight:700; }
#targetCardState { color:#69d89c; font-weight:700; }
#targetCardState[lost="true"] { color:#f1ad58; }
#targetCardCompact { color:#dce8ed; font-weight:600; }
#targetCardCaption { color:#8fa9b8; }
#targetCardToggleHint { color:#f0a34b; }
#operationToast { background:rgba(15,29,38,235); color:#ffffff; border:1px solid #e3943a; border-radius:4px; padding:9px 16px; }
#runtimeInspectionDialog QTabWidget::pane { background:#0e1a23; }
#diagnosticCaption { color:#8fa9b8; }
#mapStatusLabel { background:rgba(8,20,27,205); padding:6px; border:1px solid #365263; }
#mapControls { background:rgba(8,20,27,180); border:1px solid #365263; }
#pictureInPicture { background:#0b171e; border:2px solid #e3943a; }
#videoStatusMessage { background:#0b171e; color:#dce8ed; padding:8px; }
#calibrationUnavailableMessage { color:#ffc16b; font-weight:600; padding:8px; }
"""
