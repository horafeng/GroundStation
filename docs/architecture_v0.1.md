# 无人机地面站 Demo 架构 v0.1

- 状态：雷达解析、航迹/选择/任务、Demo编码、UDP发送调度、QThread雷达接收和PyQt5 Demo UI已实现；真实设备联调待后续阶段
- 原则：协议事实与业务状态分离；网络、解析、航迹、选择、模式、编码、发送和 UI 解耦

## 1. 逻辑数据流

```text
Radar UDP Receiver
  -> Radar Frame Parser
  -> Radar/Track Events
  -> Track Repository + Lifecycle Manager
  -> Operator Selection Service
  -> Mission State Service
  -> MissionSnapshot
  -> Pluggable Drone Protocol Encoder
  -> Drone UDP Sender (periodic + immediate triggers)
```

UI 只订阅只读视图模型并发出操作命令，不直接解析字节、不持有 Socket、不拼二进制报文。

## 2. 分层和模块边界

### 2.1 `domain`

纯 Python 数据类和枚举，无 PyQt、Socket、`struct` 依赖：

- `RadarSiteState`
- `RadarTrackObservation`
- `TrackIdentity`（`absolute_id` 主键、`display_id` 展示）
- `TrackSnapshot`
- `SelectedTargetState`
- `MissionMode`
- `MissionSnapshot`
- `TargetValidity` / `TrackPresence`

### 2.2 `radar_protocol`

- `RadarDatagramDecoder`：将 UDP 数据报切成候选帧；若协议未确认多帧/分片，首版明确只接受“一报一帧”。
- `RadarTrackFrameParser`：只处理正式航迹帧；严格校验长度、目标数、帧尾、校验和。
- `RadarProtocolConfig`：已确认字节序、允许来源、版本。
- `RadarProtocolError`：结构化错误码，供日志和测试断言。

解析器输出不可变领域对象，不触碰 UI 或航迹仓库。

### 2.3 `network`

- `RadarUdpReceiver`：专用线程中阻塞接收；收到字节后投递事件。
- `DroneUdpTransport`：只负责发送编码后的 `bytes`。
- Socket 使用超时或可取消机制；`stop()` 后关闭 Socket，并在主线程外有界等待 worker 退出。

建议 PyQt 方案：`QObject` worker 移入 `QThread`，用信号跨线程传递不可变对象。也可用 Python `threading.Thread`，但必须由统一生命周期管理器 join，禁止散落 daemon 线程。

### 2.4 `tracks`

`TrackRepository` 以绝对编号为键：

- 保存最新协议观测和最后有效坐标。
- 保存显示编号历史、首次/最后出现时间、消除时间。
- 处理协议清除标志。
- 依据可配置 `track_stale_timeout_ms` 判定未更新丢失。
- 不进行邻近目标自动重关联。

同一显示编号出现不同绝对编号时必须视为不同航迹；绝对编号不变而显示编号变化时仍保持同一内部目标。

### 2.5 `selection`

`TargetSelectionService` 管理人工选择：

- 从未选择：`has_valid_target=False`。
- 初次选择：写入绝对编号并立即触发发送。
- 切换选择：先生成确认请求；UI 确认后原子切换并立即触发发送。
- 目标丢失：保留选择和最后有效坐标。
- 取消选择是否允许、是否需要确认，列为产品决策；首版建议允许显式取消并把目标标记无效。

### 2.6 `mission`

`MissionStateService` 是唯一任务状态源：

- 当前模式 0..4。
- 当前目标有效性、最后有效坐标、坐标时间戳。
- 实时标志和丢失持续时间。
- 构造与二进制格式无关的 `MissionSnapshot`。
- 模式切换产生立即发送事件。

丢失持续时间使用单调时钟计算，起点固定为最后一次有效坐标的单调接收时刻；
超时阈值只负责触发非实时状态。对外坐标时间戳继续使用Unix毫秒，两套时间不得混用。

### 2.7 `drone_protocol`

定义稳定接口：

```python
class DroneProtocolEncoder(Protocol):
    def encode(self, snapshot: MissionSnapshot) -> bytes: ...
```

- `TemporaryDemoEncoder`：单独模块，所有字段宽度、字节序、校验和、帧头/尾均标注为 Demo 约定。
- 将来替换正式协议时新增编码器，不改 UI、雷达解析、航迹管理或 UDP transport。
- 编码器应有 `protocol_name`、`version` 和自描述诊断信息，供 UI 显示。

### 2.8 `sending`

`MissionSendScheduler`：

- 默认 5 Hz，可配置并在合法范围内校验。
- 周期发送使用单调调度，避免每帧处理时间累积漂移。
- 接收“模式改变”“目标确认”立即发送触发。
- 立即帧与周期帧共享同一序号生成器和发送锁，避免并发乱序。
- 无选中目标时仍可发送模式，但 `has_valid_target=0`，坐标不能用 0 冒充有效值。
- 非跟踪模式仍保留最后一次有效目标坐标。

### 2.9 `ui`

建议主窗口区域：

1. 顶部状态条：雷达连接、发送状态、当前模式、序号。
2. 左侧雷达自身状态和离线雷达盘。
3. 中部航迹表和当前目标详情。
4. 右侧五模式按钮、网络/频率设置。
5. 底部通信日志与十六进制日志分页。

二维雷达盘采用固定量程或操作员可选量程，不能随当前最远目标自动缩放，否则目标视觉位置会跳变。所有类型使用中性色，选中目标单独高亮，避免类型 3 被默认强调为“正确目标”。

## 3. 关键事件

| 事件 | 生产者 | 消费者 | 结果 |
|---|---|---|---|
| `RadarFrameReceived` | UDP receiver | parser | 严格解析或错误日志 |
| `RadarTrackObserved` | parser | track manager/UI | 更新航迹和雷达盘 |
| `RadarTrackCleared` | parser | track manager | 选中目标转为丢失，保留坐标 |
| `TargetSelectionRequested` | UI | selection service | 首次选择或返回确认请求 |
| `TargetSelectionConfirmed` | UI | mission/scheduler | 切换并立即发送 |
| `MissionModeChanged` | UI | mission/scheduler | 更新模式并立即发送 |
| `SendTick` | scheduler | encoder/transport | 周期帧 |
| `ShutdownRequested` | app | lifecycle manager | 停调度、关 Socket、退线程 |

## 4. 时间与状态定义

- `observation_received_monotonic`：最后有效坐标的本机单调接收时刻，是丢失持续时间起点。
- `coordinate_timestamp`：最后有效坐标所对应的时间；优先使用已确认雷达时间，否则使用本机接收 UTC 时间并标注来源。
- `lost_since_monotonic`：航迹进入丢失状态后指向最后有效坐标的单调接收时刻，
  不指向超时阈值跨越时刻或消除报文到达时刻。
- 实时状态不是旧源码的 TAS/TWS 标志；它由“选中航迹当前是否有效、未消除且未超时”派生。

## 5. 配置设计

建议 TOML 或 JSON，至少包括：

- 雷达本地 IP/端口、允许来源 IP/端口。
- 已确认的雷达字节序。
- 航迹超时阈值。
- 无人机目标 IP/端口、可选本地绑定。
- 发送频率。
- 无人机 ID。
- 当前编码器名称及临时协议参数。
- 日志级别、十六进制日志长度限制。

配置加载失败不得静默覆盖原文件；应显示错误并回退到内存默认值。

## 6. 可测试性

- 解析器使用固定十六进制夹具，无 Socket 依赖。
- 航迹生命周期使用可注入时钟，精确测试丢失持续时间。
- 编码器通过字段级 golden vector 测试。
- scheduler 使用 fake clock 或短周期集成测试，验证平均 5 Hz 和立即发送。
- UI 只测试信号、确认框和状态映射，不通过真实网络驱动业务。

## 7. 明确不复用的旧设计

- 自动过滤/选择类型 3。
- 以显示编号作为持续关联键。
- 目标超过实时阈值后停止发送。
- 把 TAS/TWS 标志当“实时点”。
- 未校验校验和/帧尾的宽松解析。
- 把雷达目标高度直接加 Home 海拔。
- 把 UI、协议编码和网络发送放在同一类中。
# UI状态与时钟补充（v0.1）

UI展示层不把UDP Socket监听、雷达数据新鲜度和无人机接收确认混为一个状态。控制器保留
`received_unix_ms`用于可见日期和MissionSnapshot坐标时间戳；保留
`received_monotonic`用于航迹超时、丢失持续时间和发送调度。单调时钟值不得格式化为
日期时间。雷达监听中但未收到报文或报文超时均是允许状态；当前Demo无人机协议没有ACK，
因此UDP本机发送成功不代表无人机接收成功。
