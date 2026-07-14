# 游泳滑轨机器人视觉闭环

电脑视觉应用作为上位机，在滑轨前后一个方向上跟踪手动框选的游泳运动员，根据相对位移序列和电机反馈速度估算运动员速度，再向安全监督进程下发目标 RPM。电机可使用虚拟 CAN、Arduino Mega2560 + MCP2515，或 python-can 支持的 USB-CAN 适配器。

## 控制关系

摄像头直接测量的是运动员相对机器人中央准星的位移，不是速度。程序通过带单调时间戳的相对位移序列求斜率得到相对速度：

```text
运动员相对速度 = d(运动员相对位移) / dt
运动员速度 = 机器人反馈速度 + 运动员相对速度
目标RPM = 运动员速度 × RPM换算系数
```

默认使用电机驱动器内部 PID，Python 直接下发目标 RPM，不叠加第二层 PID。仅在兼容原 INO 调节结构时，可手动选择 `ino_pid_compat` 模式。

## 目录

```text
vision_app/       Python视觉、速度解算、CAN/串口后端、安全监督和中文GUI
motor_control/    Arduino INO控制程序
docs/             已批准的设计规格和实现计划
```

## 安装与启动

建议使用 Python 3.11 或更新版本：

```powershell
py -m pip install -r requirements.txt
py vision_app\swimming_gui.py
```

自动测试：

```powershell
py -m unittest discover -s vision_app/tests -v
```

## 操作顺序

1. 选择控制后端。默认 `virtual` 为仿真模式，不会驱动真实机器人；连接后先激活并发送零速。
2. 填写真实的像素/米、RPM/(米/秒)和方向参数，完成实测确认。
3. 手动填写摄像头索引、URL 或设备接口并打开摄像头。
4. 手动框选游泳运动员。
5. 等待相对位移序列和电机反馈使运动解算就绪。
6. 阅读启动摘要和强电机风险提示，人工确认后启动闭环。

本地视频可配合虚拟后端完成软件测试；APP 禁止用本地视频启动真实电机。

## 电机后端

- `virtual`：默认。通过 python-can 虚拟总线和模拟电机节点执行完整帧级控制与反馈，不访问硬件。
- `arduino_serial`：兼容已验证的 INO 文本协议，连接时先发送 `P`，启动顺序保持 `T0` 后 `S`。
- `python_can`：Python 直接编码 INO 中的 `0x300/0x202/0x208` CAN 帧。用户必须填写适配器对应的 `interface` 和 `channel`，固定默认波特率为 1 Mbps。

程序不会检测到设备后自动从仿真切换为真实模式，也不会在真实连接失败后偷偷回退仿真。配置保存在当前 Windows 用户的 `%APPDATA%\SwimmerTracker\settings.json`，解锁状态和目标速度不会持久化。

## 安全限制

- INO 只接受 `-2047..2047` 范围内的整数目标 RPM。
- APP 在摄像头断流、跟踪丢失、反馈超时、后端异常、非法计算或目标越界时发送停止命令并锁定故障。
- INO 增加了 500 ms 上位机命令看门狗；USB 断开或 Python 崩溃时独立停机。
- 真实后端由单独的 `motor_supervisor` 进程独占。GUI 每 100 ms 发送心跳；心跳或目标超过 500 ms 时，监督进程重复发送零速并锁存故障。
- 故障不会自动恢复，必须人工确认并重新打开摄像头、框选目标。
- 默认 `rpm_per_mps=1.0` 只是占位值。没有实测并确认换算值时，APP 不允许启动真实闭环。
- 软件监督无法覆盖 Windows 整体崩溃、USB 总线或适配器驱动完全失效。真实运行必须配置驱动器通信超时停车，或配备可触达的物理急停。

## 硬件验收

软件自动测试不能替代真实电机安全验收。当前电脑没有 USB-CAN/真实电机，真实 CAN 收发和停车反馈仍标记为“未验证”。首次联调必须先断开动力或架空滑轨，再使用最低 RPM 验证正反方向、拔除 USB 验证看门狗、遮挡目标验证故障停机，最后实测换算参数并逐级提高速度。

完整设计见 [闭环设计规格](docs/superpowers/specs/2026-07-15-swimmer-closed-loop-design.md)。

Python 电机层设计见 [Python 电机控制与安全监督设计](docs/superpowers/specs/2026-07-15-python-motor-control-design.md)。
