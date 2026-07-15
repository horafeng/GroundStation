# GroundStation PyQt5 Demo地面站

当前已实现雷达严格解析、航迹生命周期、人工目标选择、五种任务状态、
MissionSnapshot、64字节Demo临时协议、UDP循环发送、PyQt5 Widgets主界面、
离线二维雷达图和独立模拟工具。仍不包含MAVLink、真实飞控或无人机飞行动作。

项目资料目录 `D:\Drone` 只读；所有代码、配置、文档和测试均位于
`D:\GroundStation`。

## 运行环境

- Windows 10/11
- Python 3.11（`pyproject.toml` 明确限制为 `>=3.11,<3.12`）
- pytest 8.x（仅开发/测试依赖）
- PyQt5 5.15.x、pytest-qt 4.x

```powershell
cd D:\GroundStation
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## 启动地面站

从项目根目录使用唯一推荐入口：

```powershell
cd D:\GroundStation
.\.venv\Scripts\python.exe app.py
```

程序启动后默认不监听雷达、也不向无人机发送；由操作人员分别点击启动按钮。
可直接运行的配置为`config\demo_ui.json`。配置损坏时不会覆盖原文件，界面会记录
明确错误并使用内存默认值继续启动。运行中的网络参数会被锁定，需停止对应连接后修改。

## Demo 配置与边界

示例配置为 `config\radar_demo.example.json`。当前配置明确采用：

- 32 位字按小端序解释；
- 一个 UDP 数据报按一帧完整雷达报文解释；
- 目标高度暂按相对地面高度、单位米解释。

前两项均为“Demo临时假设，尚未经过真实雷达抓包或实物验证”，不是正式协议
事实。目标高度基准也尚未经过实物核对。解析器不会自动尝试另一种字节序；
`single_frame_per_datagram=false` 在当前阶段会返回结构化“不支持”错误。

正式协议已经确认的帧头、字段位置、`N*16+22`、帧尾和累加校验规则，与
仍待确认的事项见 `docs\protocol_findings.md` 和
`docs\assumptions_and_unknowns.md`。

航迹未更新超过2000ms暂判为丢失，阈值来自
`config\core_demo.example.json`，可配置。这是尚未经过真实雷达更新频率验证的
Demo临时假设。消除或超时后保留最后坐标，丢失持续时间使用单调时钟。
2000ms阈值只决定何时判为非实时；判丢后，`lost_duration_ms`从最后一次有效
目标坐标的单调接收时刻起算，因此停止更新2300ms时约为2300ms，而不是300ms。

无人机报文是固定64字节的小端Demo临时协议，不是正式无人机协议。完整布局和
CRC32/IEEE规则见 `docs\temporary_drone_protocol_v0.1.md`。

## 运行测试

```powershell
cd D:\GroundStation
.\.venv\Scripts\python.exe -m pytest
```

测试夹具位于 `tests\fixtures\radar_frames`，是便于代码评审和回归的 ASCII
十六进制文件。需要重新生成时运行：

```powershell
.\.venv\Scripts\python.exe tools\radar_simulator.py `
  --write-fixtures tests\fixtures\radar_frames
```

## 运行雷达模拟器

仅打印一个多目标报文，不发送 UDP：

```powershell
.\.venv\Scripts\python.exe tools\radar_simulator.py `
  --scenario multi --hex-only
```

以 200 ms 间隔向本机 UDP 6000 端口持续发送移动目标，按 `Ctrl+C` 停止：

```powershell
.\.venv\Scripts\python.exe tools\radar_simulator.py `
  --scenario moving --host 127.0.0.1 --port 6000 --count 0 --interval-ms 200
```

`--scenario` 支持：`zero`、`one`、`multi`、`moving`、`cleared`、
`multi-moving`、`multi-moving-clear`、`duplicate-display`、`bad-length`、
`bad-checksum`、`bad-tail`。模拟器启动时会
把所有临时假设写入 WARNING 日志。

持续发送4个不同类型的移动目标：

```powershell
.\.venv\Scripts\python.exe tools\radar_simulator.py `
  --scenario multi-moving --host 127.0.0.1 --port 6000 --count 0 --interval-ms 200
```

## 解析结果

`RadarTrackFrameParser.parse(datagram)` 返回 `RadarParseResult`：成功时只有
`frame`，失败时只有包含错误码、中文消息和细节字典的 `error`。坏帧不会静默
进入后续处理。航迹内部关联应使用 `absolute_id`；`display_id` 仅供显示。
类型 3 不会被自动过滤或自动选中，TAS/TWS 标志也不会被解释成坐标实时标志。

## 运行无人机模拟接收器

先启动接收器：

```powershell
.\.venv\Scripts\python.exe tools\drone_receiver_simulator.py `
  --host 0.0.0.0 --port 7000
```

接收器严格验证帧头、版本、模式、长度、CRC32和帧尾，打印完整字段及十六进制，
并统计接收频率、重复序号、丢帧和乱序。按`Ctrl+C`会关闭Socket并正常退出。

UI可运行配置：`config\demo_ui.json`。默认发送频率5Hz、目标端点
`127.0.0.1:7000`；界面在对应网络停止时允许修改运行参数。

完整三终端演示、目标切换、消除、超时和关闭检查见
`docs\demo_ui_manual_test.md`。
