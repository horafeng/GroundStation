# 实施计划 v0.1

- 状态：待用户确认后执行
- 本轮不编写完整项目

## 1. 建议目录结构

```text
D:\GroundStation\
  README.md
  pyproject.toml
  requirements.txt
  config\
    ground_station.example.json
  docs\
    source_inventory.md
    requirements_v0.1.md
    protocol_findings.md
    architecture_v0.1.md
    assumptions_and_unknowns.md
    implementation_plan.md
    temporary_drone_protocol_v0.1.md       # 协议选择后创建
    third_party_references.md               # 使用外部代码前创建/更新
  src\ground_station\
    __init__.py
    app.py
    domain\
      models.py
      enums.py
      events.py
    config\
      loader.py
      schema.py
    radar_protocol\
      constants.py
      checksum.py
      parser.py
      errors.py
    tracks\
      repository.py
      lifecycle.py
      selection.py
    mission\
      state.py
      snapshot.py
    drone_protocol\
      base.py
      temporary_demo.py
    network\
      radar_receiver.py
      drone_transport.py
    sending\
      scheduler.py
      sequence.py
    ui\
      main_window.py
      radar_scope.py
      track_table_model.py
      dialogs.py
      view_models.py
    logging\
      setup.py
      hexlog.py
    lifecycle.py
  tools\
    radar_simulator.py
    drone_receiver_simulator.py
  tests\
    unit\
      test_radar_checksum.py
      test_radar_parser.py
      test_track_lifecycle.py
      test_target_selection.py
      test_mission_state.py
      test_temporary_encoder.py
    integration\
      test_radar_udp_pipeline.py
      test_drone_udp_pipeline.py
      test_shutdown.py
    fixtures\
      radar_frames\
```

## 2. 模块实施顺序

### 阶段 0：协议确认门

- 获取/确认雷达字节序和一报一帧规则。
- 由项目方确认目标切换确认范围、取消选择策略。
- 提交并确认临时无人机协议字段布局。
- 若仍无实报文，所有解析结果标记“仅模拟验证”。

验收物：更新后的 `assumptions_and_unknowns.md`、临时协议文档、至少 3 个已知雷达帧样本。

### 阶段 1：领域模型和严格雷达解析器（已完成）

- 建立数据类、枚举、错误码。
- 实现长度公式、帧尾和校验和验证。
- 实现雷达状态、N 个目标、显示/绝对编号、类型、速度、方位、清除位、经纬高解析。
- 保留原始字段，避免过早丢失信息。

验收：正常 0/1/N 目标帧通过；坏帧头、坏长度、坏校验、坏帧尾、越界坐标全部拒绝；不再试探字节序。

### 阶段 2：航迹仓库、丢失和人工选择（已完成）

- 绝对编号主键，显示编号为展示属性。
- 处理清除帧和超时丢失。
- 保留最后有效坐标、时间戳、实时标志、丢失时长。
- 实现选择/切换命令和确认状态机，不做自动选择/重关联。

验收：显示号复用不串目标；清除后坐标不清空；丢失时长增加；新近邻航迹不会替代原目标。

### 阶段 3：可替换编码器和发送调度（本轮核心已完成）

- 定义 `DroneProtocolEncoder` 接口。
- 按已确认的临时协议实现编码器和 golden vectors。
- 实现可配置 5 Hz 周期发送、模式/目标变化立即发送、统一序号。
- 无目标时明确编码无效；所有模式保留最后坐标。

验收：模拟接收器可解码；连续 10 秒发送平均 5 Hz、允许误差由测试定义；立即帧不等待 200 ms；序号无并发重复。

### 阶段 4：UDP 接收/发送和生命周期（Demo端到端已完成）

- 雷达接收在 worker 线程。
- 来源过滤可配置。
- transport 与编码器隔离。
- 退出顺序：停 scheduler -> 关接收 Socket -> 通知线程 -> 有界 join -> 关日志。

验收：UI 主线程无阻塞；重复连接/断开可恢复；退出后端口立即可重新绑定，无遗留线程。

### 阶段 5：PyQt5 Demo UI（已完成）

- 状态条、雷达自身状态、固定量程二维雷达盘、航迹表、目标详情。
- 五模式按钮、网络和频率配置。
- 目标切换确认框使用需求中的原文。
- 实时/丢失、丢失时长、序号、通信/十六进制日志。

验收：多目标同步显示；不同类型均可选择；切换取消保持原目标，确认后立即发送；UI 在高频雷达流下保持响应。

### 阶段 6：独立模拟器和端到端测试

雷达模拟器场景：

- 0/1/多目标。
- 车辆、行人、无人机、未知类型混合。
- 目标运动、显示编号变化、绝对编号保持。
- 显示编号复用但绝对编号改变。
- 协议清除、静默丢失、重新出现。
- 坏校验、坏长度、坏帧尾、错误字节序。

无人机模拟接收器：

- 显示来源、序号、模式、目标有效/实时、坐标时间戳、丢失时长。
- 校验临时协议并输出十六进制。
- 统计帧率、丢帧和乱序。

## 3. Demo 验收方法

### A. 启动与配置

1. 使用 Python 3.11 启动地面站。
2. 修改雷达端口、无人机目标端口和频率，重启后配置正确加载。
3. 启动时未选择目标，模拟接收器显示 `target_valid=0`，不得把 0/0 经纬度当有效。

### B. 多目标与人工选择

1. 雷达模拟器发送至少 4 个不同类型目标。
2. UI 同时显示全部目标和显示编号、类型、速度、方位、距离。
3. 选择航迹 7，模拟接收器立即收到其绝对编号和坐标。
4. 点击航迹 12，出现“是否将跟踪目标由航迹7切换为航迹12？”；取消不切换，确认才切换并立即发帧。

### C. 五任务模式

依次点击待命、起飞、跟踪、返航、降落；每次模拟接收器都在下一个周期前收到立即帧，模式值分别为 0..4，目标最后坐标始终保留。

### D. 目标丢失

1. 正常目标：`is_realtime=1`、丢失时长 0。
2. 发送清除标志：坐标保持，`is_realtime=0`，丢失时长增加，仍按 5 Hz 发送。
3. 在附近生成新绝对编号：不得自动切换。
4. 原绝对编号恢复时，是否自动恢复实时状态按最终产品决策测试；不得换到其他编号。

### E. 协议健壮性

依次注入坏长度、坏校验、坏帧尾、越界经纬度；UI 日志给出明确错误，航迹仓库和当前目标不被污染，无错误帧发往无人机。

### F. 性能与退出

- 雷达模拟器以预期峰值持续发送 10 分钟，UI 可操作，无无限增长队列/日志。
- 发送统计接近配置频率，模式和目标切换立即帧可识别。
- 关闭窗口后所有 Socket/线程正常退出，端口可立即被测试程序重新绑定。

## 4. GitHub 参考计划

本轮未搜索或引入 GitHub 代码。后续若确有需要，只参考小型局部实现并先核对许可证；每次使用前在 `docs/third_party_references.md` 记录仓库 URL、提交/版本、许可证、参考内容和对应本地文件。不得复制 Mission Planner、QGroundControl 等大型完整项目。

## 5. 下一步建议

用户确认本轮文档后，先执行“阶段 0 + 阶段 1”的最小完整增量：确认协议未知项、编写严格航迹解析器及单元测试。不要直接开始完整 UI 或真实无人机控制。
