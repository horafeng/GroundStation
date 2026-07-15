# GroundStation 核心业务闭环

当前已实现雷达严格解析、航迹生命周期、人工目标选择、五种任务状态、
MissionSnapshot、64字节Demo临时协议、UDP循环发送和独立模拟工具。
仍不包含完整UI、雷达盘、MAVLink、真实飞控或无人机飞行动作。

项目资料目录 `D:\Drone` 只读；所有代码、配置、文档和测试均位于
`D:\GroundStation`。

## 运行环境

- Windows 10/11
- Python 3.11（`pyproject.toml` 明确限制为 `>=3.11,<3.12`）
- pytest 8.x（仅开发/测试依赖）

```powershell
cd D:\GroundStation
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

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
`duplicate-display`、`bad-length`、`bad-checksum`、`bad-tail`。模拟器启动时会
把所有临时假设写入 WARNING 日志。

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

核心业务配置示例：`config\core_demo.example.json`。默认发送频率5Hz、目标端点
`127.0.0.1:7000`；真实部署前必须创建本地配置，不应直接修改示例文件。
