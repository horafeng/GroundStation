# PyQt5 Demo手动演示说明

## 1. 演示边界

本流程只演示雷达UDP、严格解析、航迹生命周期、人工选择、任务模式和64字节
Demo临时协议发送。不包含MAVLink、真实飞控、无人机飞行动作、自动目标识别、
自动重关联或在线地图。

雷达图采用经纬度差的局部等距圆柱近似，仅用于Demo显示。原始雷达经纬度会
原样进入航迹仓库和MissionSnapshot，该换算不会修改发给无人机的坐标。

## 2. 环境准备

在PowerShell中执行：

```powershell
cd D:\GroundStation
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

默认端口：雷达监听`127.0.0.1:6000`，无人机接收`127.0.0.1:7000`。

## 3. 三个终端

终端A，启动无人机模拟接收器：

```powershell
cd D:\GroundStation
.\.venv\Scripts\python.exe tools\drone_receiver_simulator.py --host 127.0.0.1 --port 7000
```

终端B，启动地面站（唯一推荐入口）：

```powershell
cd D:\GroundStation
.\.venv\Scripts\python.exe app.py
```

终端C暂不执行命令。

## 4. 雷达接收与多目标显示

1. 在UI中确认雷达监听地址为`127.0.0.1:6000`，小端、一报一帧提示可见。
2. 点击“启动雷达监听”，状态应变为“接收中”。
3. 在终端C启动四个不同类型的持续移动目标：

```powershell
cd D:\GroundStation
.\.venv\Scripts\python.exe tools\radar_simulator.py --scenario multi-moving --host 127.0.0.1 --port 6000 --count 0 --interval-ms 200
```

4. UI应显示雷达经纬度、海拔、卫星数和4条航迹；固定量程选择1km。
5. 雷达图应显示尾迹、显示编号7/12/21/33；类型3不会被自动选中或特殊高亮。

## 5. 人工选择、发送和模式

1. 点击航迹7。首次选择直接成功，表格和雷达图同步高亮。
2. 点击“启动无人机发送”。终端A应接近5Hz收到64字节报文，`target_valid=1`。
3. 点击航迹12，确认框文字应为“是否将跟踪目标由航迹7切换为航迹12？”，
   并显示双方绝对编号和坐标。
4. 点击取消，终端A继续显示航迹7的绝对编号`100007`。
5. 再点航迹12并确认，应立即出现一帧`reason=target_switch_confirmed`对应的新目标，
   随后周期帧继续发送绝对编号`100012`。
6. 依次点击待命、起飞、跟踪、返航、降落；终端A应依次解码模式0、1、2、3、4。
   每次实际模式改变都会请求立即帧。

## 6. 消除与超时

若当前选择航迹7，可先停止终端C的移动场景，然后发送带消除标志的同一绝对编号：

```powershell
.\.venv\Scripts\python.exe tools\radar_simulator.py --scenario multi-moving-clear --host 127.0.0.1 --port 6000 --count 5 --interval-ms 200
```

UI应保留航迹7及最后有效坐标，状态显示“最后有效坐标（目标丢失）”；终端A中
`target_valid=1`、`coordinate_realtime=0`，丢失持续时间从最后有效坐标的单调
接收时刻开始增加，而不是从消除报文到达时从0开始。

测试超时可重新启动`multi-moving`，选中任意目标后停止模拟器。超过默认2000ms，
同样应转为丢失并继续5Hz发送最后坐标。新出现的其他绝对编号不得替换当前选择。
例如停止更新2300ms且阈值为2000ms时，接收器应显示约2300ms，而不是约300ms。

## 7. 关闭检查

1. 点击“停止无人机发送”，确认终端A不再收到新帧。
2. 点击“停止雷达监听”。
3. 关闭地面站窗口。
4. 地面站按“发送调度器 → 雷达接收Socket/线程 → 日志资源”顺序退出。
5. 再次启动地面站并绑定6000端口应成功，不应残留线程或Socket。

## 8. 当前临时假设

- 雷达32位字暂按小端序解析、一UDP数据报暂按一完整帧处理，均未经过真实抓包验证。
- 航迹未更新超过2000ms判为丢失，尚未经过真实雷达更新频率验证。
- 目标高度暂按相对地面高度、单位米解释，待实物核对。
- 无人机报文为64字节Demo临时协议，不是正式无人机协议。
