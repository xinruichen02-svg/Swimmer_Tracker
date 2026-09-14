# 游泳滑轨机器人视觉控制 APP

`vision_app` 是电脑端视觉与运动控制程序。当前真实电机路径使用 TCP 连接控制端，默认地址为 `192.168.1.177:8888`；`motor_tcp_client.py` 和下位机程序保持不变。

> TCP 第一版只有命令通道，没有实际转速、堵转或驱动故障反馈。界面中的机器人速度是根据最后成功下发的 RPM 计算出的“指令估算值”，不能当作实测值。真实运行必须配备物理急停，并确认下位机或驱动器具有失联停车能力。

## 文档导航

- [安装和启动](#安装和启动)
- [完整使用说明](#完整使用说明)
- [五层结构](#五层结构)
- [代码跳转入口](#代码跳转入口)
- [运行模式](#运行模式)
- [参数与安全](#参数与安全)
- [首次实机检查](#首次实机检查)

## 五层结构

```text
FrameSource（画面接收）
  -> FrameProcessor（画面处理，当前原样透传）
  -> TargetTracker（CSRT 框选和跟踪）
  -> MotionController（目标偏差到期望线速度）
  -> MotorCommandGateway（线速度/RPM换算、限幅和发送）
  -> 独立 motor_supervisor 进程
  -> TCP 电机控制端
```

GUI 只组合各层并显示状态。摄像头、OpenCV 跟踪、运动计算和 TCP 协议可以分别测试和替换。

## 代码跳转入口

| 层级 | 模块 | 职责 |
| --- | --- | --- |
| 1 | [motor_gateway.py](vision_app/motor_gateway.py)、[tcp_motor_backend.py](vision_app/tcp_motor_backend.py) | 单位换算、限幅、命令发送和 TCP 生命周期 |
| 2 | [motion_control.py](vision_app/motion_control.py) | 位置比例控制与速度估算控制 |
| 3 | [target_tracking.py](vision_app/target_tracking.py) | ROI 框选和 CSRT 跟踪 |
| 4 | [frame_processing.py](vision_app/frame_processing.py) | 预留画面处理接口，当前不改变图像 |
| 5 | [frame_source.py](vision_app/frame_source.py) | 摄像头、URL、本地视频的打开与读取 |
| 集成 | [swimming_app.py](vision_app/swimming_app.py) | GUI、状态展示和各层编排 |

其他常用入口：

- APP 启动入口：[swimming_gui.py](vision_app/swimming_gui.py)
- TCP 文本协议：[motor_protocol.py](vision_app/motor_protocol.py)
- 电机事件数据结构：[motor_events.py](vision_app/motor_events.py)
- 独立监督进程：[motor_supervisor.py](vision_app/motor_supervisor.py)
- GUI 与监督进程通信：[supervisor_client.py](vision_app/supervisor_client.py)
- 安全状态机：[safety.py](vision_app/safety.py)
- 参数定义与校验：[settings.py](vision_app/settings.py)
- 参数读取与保存：[app_config.py](vision_app/app_config.py)
- TCP 命令行联调工具：[motor_tcp_client.py](motor_tcp_client.py)
- 自动测试目录：[vision_app/tests](vision_app/tests)

## 安装和启动

建议使用 Python 3.11 或更新版本：

```powershell
cd D:\你的路径\Swimmer_Tracker
py -m pip install -r requirements.txt
py vision_app\swimming_gui.py
```

Linux/macOS：

```bash
cd /path/to/Swimmer_Tracker
python -m pip install -r requirements.txt
python vision_app/swimming_gui.py
```

运行测试：

```powershell
py -m unittest discover -s vision_app/tests -v
```

Linux 无图形桌面时 GUI 冒烟测试会跳过；纯计算、TCP 和监督进程测试仍可运行。

## 完整使用说明

### 1. 先用 virtual 验证软件

1. 启动 APP，后端选择 `virtual`，点击“连接”。
2. 设置运行模式、换算参数和高级安全参数。
3. 点击“应用并确认参数”。参数修改后确认状态会自动失效。
4. 手动模式可直接启动；视觉模式继续打开摄像头并框选目标。
5. 确认状态栏中的期望速度、换算前 RPM 和实际发送 RPM 符合预期。
6. 点击“停止电机”，确认状态回到“已停止”。

### 2. 手动控制

- `手动 RPM`：填写带正负号的目标转速，适合低速方向测试。
- `手动线速度`：填写 m/s，APP 使用 `RPM/(m/s)` 和电机方向换算目标 RPM。
- 两种模式都会执行 RPM 上限和 RPM 变化率限制。
- 目标值可以在运行中调整；标定、方向、限幅等控制参数不能在运行中修改。

### 3. 视觉跟随

1. 选择 `位置比例跟随` 或 `速度估算跟随`。
2. 填写摄像头索引，例如 `0`；也可以填写摄像头 URL。
3. 点击“打开画面”，再点击“框选 CSRT 目标”。
4. 在弹出的画面中拖动目标框，按 Enter 确认；取消后不会启动。
5. 确认目标偏差、期望速度和方向正确，再点击启动。
6. 目标丢失、摄像头断流或偏差超过安全区域时，APP 会锁存故障并请求停车。

### 4. 连接真实 TCP 控制端

1. 先运行 [motor_tcp_client.py](motor_tcp_client.py)，确认目标设备能接收 `S/P/T` 命令。
2. 关闭命令行客户端，避免两个程序同时占用控制连接。
3. APP 后端切换为 `tcp`，填写设备 IP 和端口；默认是 `192.168.1.177:8888`。
4. 点击“连接”后，APP 会先发送 `P`、`T0`，不会自动启动运动。
5. 首次测试只使用很低的手动 RPM；方向、停车和失联保护验证通过后再使用视觉模式。

### 5. 停车、故障与退出

- 正常停车：点击“停止电机”，APP 会重复请求 `P`。
- 故障停车：排除原因后点击“确认故障并复位”，不会自动恢复上次运动。
- 关闭窗口：运行中会要求再次确认，并在关闭 TCP 前发送停车命令。
- TCP 无反馈，因此“停车命令已发送”不代表已经测量确认电机静止。

### 6. 参数保存位置

参数会保存到当前用户配置目录：

- Windows：`%APPDATA%\SwimmerTracker\settings.json`
- Linux/macOS：`~/SwimmerTracker/settings.json`

旧配置中的串口或直接 CAN 后端会迁移为安全的 `virtual`，不会自动连接 TCP。

## 推荐操作顺序

1. 选择 `virtual` 或 `tcp`，填写 TCP 地址后连接。
2. 选择运行模式并填写基础/高级参数。
3. 点击“应用并确认参数”。参数发生变化后必须重新确认。
4. 手动模式可直接启动；视觉模式需先打开摄像头并框选 CSRT 目标。
5. 阅读启动风险提示并启动，运行中可随时点击停止。
6. 故障发生后先排除原因，再点击“确认故障并复位”；程序不会自动恢复运动。

## 后端

- `virtual`：软件仿真，不驱动真实设备，并提供仿真测量反馈。
- `tcp`：唯一真实后端。发送与 `motor_tcp_client.py` 相同的换行文本协议。

TCP 命令：

```text
S       启动
P       停止
T600    期望转速 +600 RPM
T-600   期望转速 -600 RPM
```

连接后先发送 `P`、`T0`；启动时发送 `T0`、`S`；运行时默认每 50 ms 更新 `T`；停车、故障和退出都会重复请求 `P`。程序不会自动重连，也不会在 TCP 失败后切换到 virtual。

## 运行模式

### 手动 RPM

直接输入期望 RPM。命令仍经过协议范围、用户 RPM 上限和变化率限制，适合低速联调。

### 手动线速度

输入期望线速度，第一层按下式换算：

```text
期望RPM = 电机方向 × 期望线速度 × RPM/(m/s)
```

### 位置比例跟随

默认让目标框中心保持在画面中心，也可以设置目标像素偏移：

```text
参考位置 = 画面宽度 / 2 + 目标偏移px
偏差m = 相机方向 × (目标中心x - 参考位置) / 像素每米
期望速度 = 位置P增益 × 偏差m
```

偏差进入死区后输出零速，结果受最大线速度限制。

### 速度估算跟随

对目标相对位移序列做线性拟合，估算相对速度：

```text
机器人估算速度 = 电机方向 × 最后发送RPM / RPM每米每秒
运动员估算速度 = 机器人估算速度 + 目标相对速度
```

该模式使用指令值估算机器人速度，不是闭环测量。

## 参数与安全

基础参数包括 TCP IP/端口、摄像头源、运行模式、手动目标、像素/米、RPM/(m/s)和位置 P 增益。高级区域包括方向、目标偏移、死区、速度/RPM上限、RPM变化率和速度估算窗口。

控制参数修改后必须重新确认。运行中切换模式或修改控制参数、TCP 断线、命令超时、摄像头断流、CSRT 丢失、目标越过安全区域或计算异常都会进入锁存故障。故障不会自动恢复。

本地视频只允许配合 `virtual`；APP 禁止用离线视频驱动真实 TCP 电机。旧配置中的 `arduino_serial` 或 `python_can` 会安全迁移为 `virtual`，不会自动连接真实设备。

## 首次实机检查

1. 架空滑轨或断开机械负载，并确保物理急停可触达。
2. 用 `motor_tcp_client.py` 验证 TCP 地址和 `S/P/T` 协议。
3. 在 APP 中先用 `virtual` 验证四种运行模式。
4. 切换 TCP，只用很低的手动 RPM 验证正反方向和停车。
5. 断开网络验证下位机失联停车；若断线后仍保持转速，不得进入视觉运行。
6. 实测像素/米、RPM/(m/s)、安全速度、死区和位置增益，再进行载荷测试。
