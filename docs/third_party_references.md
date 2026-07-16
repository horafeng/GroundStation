# 第三方参考与在线服务

## OpenStreetMap 标准瓦片

- 服务：`https://tile.openstreetmap.org/{z}/{x}/{y}.png`
- 数据归属：© OpenStreetMap contributors，数据采用 ODbL。
- 官方版权说明：https://www.openstreetmap.org/copyright
- 官方瓦片使用政策：https://operations.osmfoundation.org/policies/tiles/
- 本项目用途：操作员当前可视区域的在线 Demo 背景；不下载离线区域、不预取城市或多级瓦片。
- 客户端行为：使用可识别 User-Agent、Qt 磁盘缓存并优先读取缓存；地图画面始终显示归属。
- 可用性：社区服务没有 SLA；失败时自动保留本地 Demo 底图与全部目标交互。

## QGroundControl

- 来源快照：`D:\QGroundControl\qgroundcontrol-master`（只读、本地无 `.git`）。
- 根目录许可文本：GPL v3、Apache License 2.0。
- 参考内容：地图、轨迹、视频和设置的职责划分与状态流。
- 使用代码：无。详见 `qgroundcontrol_functional_reference.md`。
