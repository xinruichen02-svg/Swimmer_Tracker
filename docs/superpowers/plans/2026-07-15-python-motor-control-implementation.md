# Python 电机控制与安全监督实施计划

日期：2026-07-15  
依据：`docs/superpowers/specs/2026-07-15-python-motor-control-design.md`

## 任务 1：建立 CAN 协议黄金测试和编解码模块

创建 `vision_app/can_protocol.py` 与 `vision_app/tests/test_can_protocol.py`：

- 固化 INO 中的 CAN ID、1 Mbps、2 号电机、DLC 和 `-2047..2047` 范围；
- 覆盖激活帧、正负速度、零速、边界、字节序、反馈符号扩展和非法帧；
- 使用与 python-can 解耦的不可变 `CanFrame` 数据模型，保证纯逻辑测试不依赖设备。

## 任务 2：实现统一后端、虚拟电机和直接 CAN 后端

创建：

- `vision_app/motor_backend.py`
- `vision_app/virtual_motor_backend.py`
- `vision_app/python_can_backend.py`
- `vision_app/simulated_motor.py`

统一后端提供连接、激活、目标下发、反馈读取、重复零速、健康状态和关闭。虚拟后端通过 python-can virtual bus 与独立模拟节点收发真实帧；直接后端把接口、通道、波特率原样交给 python-can，并拒绝隐式回退到仿真。

## 任务 3：为现有 Arduino 串口建立兼容适配器

在不破坏 `MotorLink` 现有 API 和测试的前提下添加 `ArduinoSerialBackend`：

- `connect()` 后保持固件当前的先停车行为；
- `activate()` 对应先写目标零再发送 `S`；
- `set_target_rpm()` 对应 `T`；
- `stop()` 对应 `P`；
- 串口遥测转换为统一反馈。

## 任务 4：实现可选 INO PID 兼容模式和 Python 控制器

创建 `vision_app/pid_compat.py`、`vision_app/python_motor_controller.py` 及测试：

- 默认直接目标模式，不增加 Python PID；
- 可选 10 ms PID 兼容模式，参数默认 `1.0/0.05/0.02`；
- 输出限幅、反计算抗饱和、停止复位、反馈过期故障；
- 控制器显式实现安全连接、解锁、运行、停车、故障状态。

## 任务 5：实现独立监督进程与客户端

创建 `vision_app/motor_supervisor.py`、`vision_app/supervisor_client.py` 及跨进程测试：

- Windows `spawn` 兼容的本地 Pipe 通信；
- 监督进程唯一持有后端；
- 100 ms 心跳、500 ms 心跳/目标超时、递增序号和单调时间戳检查；
- GUI/IPC 消失、异常和数据过期时重复发零并锁存故障；
- 客户端提供与 GUI 使用习惯一致的事件队列和控制方法。

## 任务 6：扩展设置、安全输入和 GUI

修改 `settings.py`、`safety.py`、`swimming_app.py`：

- 默认后端为 `virtual`，增加串口、python-can 和控制模式配置；
- 安全输入从“串口连接”抽象为“电机后端连接”；
- GUI 增加醒目的仿真标识、后端配置、监督状态、心跳、反馈和故障提示；
- 真实模式必须二次确认物理急停/驱动器通信超时；
- 仿真和真实连接失败均明确提示，绝不静默切换后端；
- 保持手动框选、相对位移测速、标定输入和现有美化风格。

## 任务 7：依赖、文档和启动兼容

- 在 `requirements.txt` 增加 `python-can>=4.4,<5`；
- 安装缺失依赖；
- 更新 README 的三后端说明、仿真启动流程、真实硬件限制和首次联调步骤；
- 保持 `vision_app/swimming_gui.py` 为启动入口。

## 任务 8：完整验证与交付门禁

执行：

```powershell
py -m unittest discover -s vision_app/tests -v
py -m compileall -q vision_app
py -m ruff check vision_app
```

同时完成：

- python-can 虚拟总线全链路和监督进程超时停车测试；
- GUI 构造及中文提示冒烟测试；
- INO Mega2560 编译回归；
- 工作区差异、安全路径和项目进程审计。

无真实 USB-CAN 时，验收记录明确列为“实机未验证”。所有可执行门禁通过后提交实现，推送并核对远端 `main`。只有远端一致、工作区干净、真实电机未运行且项目进程已安全关闭时，才安排 60 秒延迟的 Windows 安全关机。
