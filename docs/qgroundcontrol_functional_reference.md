# QGroundControl 功能性参考记录

## 范围与版本状态

本轮只读分析了 `D:\QGroundControl\qgroundcontrol-master`。该目录没有 `.git`，因此
无法给出可靠提交哈希，只能记录为“2026-07-16 本地 master 源码快照”。根目录同时包含
`LICENSE-GPL`（GPL v3）和 `LICENSE-APACHE`（Apache License 2.0）；本项目未复制或改写
QGroundControl 的具体代码，因而没有把其源码许可内容引入 GroundStation。

## 实际阅读文件与职责

| 文件 | 解决的问题 | 本项目判断 |
|---|---|---|
| `src/FlightMap/FlightMap.qml` | 地图源/类型、首次位置居中、拖动、滚轮/触控缩放、地图事件 | 借鉴“地图交互控件与业务状态分开”；不采用 QtLocation/QML 体系 |
| `src/FlightMap/Widgets/CenterMapDropPanel.qml` | 把 Home、载具、当前位置等居中动作显式交给操作员 | 简化为一个“回到 Home”按钮 |
| `src/FlightMap/MapItems/VehicleMapItem.qml` | 独立渲染载具标记及活动/非活动外观 | 借鉴标记状态与地图背景分层；不复制图标或 QML |
| `src/Vehicle/TrajectoryPoints.h/.cc` | 从位置变化形成航迹点并控制地图绘制负担 | 采用更简单的每绝对编号有界 `deque`，不采用 Vehicle 信号体系 |
| `src/FlyView/FlyView.qml` | 用 PiP 状态在地图和视频主视角之间切换 | 借鉴可逆主/副视角状态；用 `QStackedWidget` 简化实现 |
| `src/FlyView/FlightDisplayViewVideo.qml` | 视频不可用提示、画面呈现与叠加层 | 本轮只实现明确“未连接/测试图案/RTSP未启用解码”状态 |
| `src/VideoManager/VideoManager.h/.cc` | 管理视频源设置、接收器生命周期和公开状态 | 只借鉴管理状态不等于后端解码；不引入其管线 |
| `src/VideoManager/VideoReceiver/VideoReceiver.h` | 用稳定接口隔离不同视频后端，并暴露开始/停止/失败状态 | 本轮不做真实接收器，仅保留小型 `VideoSourceConfig` |
| `src/Settings/SettingsManager.h/.cc` | 按职责分组设置并统一向 UI 暴露 | 继续使用本项目不可变 dataclass 和独立设置对话框 |
| `src/Settings/FlightMapSettings.h/.cc` | 把地图提供者与地图类型作为独立设置 | 简化为 `local_demo/online` 两种模式和瓦片 URL |

## 采用的简化设计

1. `MapSceneModel` 只接收航迹生命周期快照，按绝对编号产生地图标记和有界历史。
2. `TileMapCanvas` 只处理投影、瓦片、本地底图和鼠标交互，不处理目标选择规则。
3. `MapWidget` 只暴露 `set_home`、`update_tracks`、`set_selected_track`、
   `set_track_history`、`center_on_home` 等少量接口。
4. 主窗口把地图点击接回原有人工选择服务，切换目标仍由原服务二次确认。
5. `MainWorkspace` 只管理地图/视频主副视角，不拥有雷达解析、任务或 UDP 状态。
6. 视频保持占位与测试图案，不实现 QGroundControl 的接收、录像、云台或插件系统。

## 明确不适用的设计

- QML/QtLocation 完整地图系统、Vehicle 体系、FactSystem、插件框架；
- 多载具、任务规划、地理围栏、离线地图下载器；
- GStreamer/QtMultimedia 视频后端、录像和热成像管线；
- MAVLink、飞控状态、云台控制与自动视频源发现。

## 代码与许可结论

没有借鉴具体符号实现、常量、QML 结构、图标或资源文件。参考仅限职责划分和状态流，
GroundStation 的实现由 PyQt5 Widgets 独立编写。若未来确需复制或改写具体代码，必须先
确定目标文件的适用许可证并另行记录来源、符号和改写方式。
