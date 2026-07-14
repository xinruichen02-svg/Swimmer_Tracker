# 游泳滑轨机器人视觉闭环实现计划

日期：2026-07-15  
依据：`docs/superpowers/specs/2026-07-15-swimmer-closed-loop-design.md`

## 实施原则

1. INO 串口协议是 Python 控制层的权威依据。
2. 摄像头直接测量相对位移；相对速度只能由相对位移时间序列计算。
3. Python 不包含 PID。
4. 所有控制公式放在无 GUI、无 OpenCV、无串口依赖的纯模块中。
5. 测试先覆盖公式、协议和安全状态，再接入真实设备层。
6. 未取得新鲜视觉测量和电机反馈时绝不生成可发送命令。
7. 真实硬件安全只能由分阶段实机验收确认，自动测试不冒充硬件验收。

## 当前环境约束

- Python 3.13.5 可用。
- OpenCV、Pillow 和 Tkinter 已安装。
- `pytest` 未安装，因此测试使用标准库 `unittest`，避免引入不必要的测试运行依赖。
- `pyserial` 未安装；将写入依赖文件，协议和状态测试使用假串口，不阻塞纯逻辑验证。
- `arduino-cli` 不可用；INO 做结构审查和源代码级验证，最终编译与硬件验证需在 Arduino 工具链中完成。

## 任务 1：建立测试骨架

创建：

- `vision_app/tests/__init__.py`
- `vision_app/tests/test_control_core.py`
- `vision_app/tests/test_motor_protocol.py`
- `vision_app/tests/test_safety_state.py`

先写失败测试，覆盖：

- 相对位移线性拟合得到相对速度；
- 机器人速度、运动员速度和目标 RPM 的符号与换算；
- 样本不足、异常时间、非法数值和限幅；
- INO 命令精确编码与中文遥测解析；
- 分片、噪声和无效遥测不刷新反馈；
- 合法/非法状态转换和故障锁定；
- 启动顺序必须是 `T` 后 `S`，连接后必须先 `P`。

验证命令：

```powershell
py -m unittest discover -s vision_app/tests -v
```

## 任务 2：实现设置模型

创建 `vision_app/settings.py`：

- `ControlSettings` 数据类；
- 默认 `pixels_per_meter=120.0`；
- 默认占位 `rpm_per_mps=1.0`；
- 方向值仅允许 `-1/+1`；
- 最大 RPM 不得超过 `2047`；
- 视觉、反馈超时和变化率限制必须为有限正数；
- 修改关键标定字段后由 APP 清除校准确认。

验证：设置合法/非法边界测试全部通过。

## 任务 3：实现纯控制核心

创建 `vision_app/control_core.py`：

- `RelativeDisplacementEstimator` 保存有限窗口的 `(time, offset_px)`；
- 将偏移转换为米并用最小二乘直线斜率计算相对速度；
- 时间戳必须严格递增，首帧和少于三个样本返回未就绪；
- `MotionSolution` 数据类保存相对位移、相对速度、机器人速度、运动员速度、原始 RPM、命令 RPM、饱和状态和原因；
- `solve_motion()` 实现批准公式；
- `RateLimiter` 对目标 RPM 的变化率做单独、可复位限制；
- 所有公共入口拒绝布尔值、`NaN`、无穷值和非法单位参数。

验证：基准断言、方向组合、拟合、限幅和异常测试全部通过。

## 任务 4：实现 INO 串口协议层

创建 `vision_app/motor_link.py`：

- 纯函数 `encode_start()`、`encode_stop()`、`encode_target_rpm()`；
- `TelemetryParser` 按行增量解析 UTF-8 中文遥测；
- `MotorTelemetry` 保存目标、实际、输出和接收单调时间；
- `MotorLink` 封装 pyserial，提供连接、发送和后台读取；
- pyserial 缺失时产生明确中文错误，不影响模块导入和纯协议测试；
- 所有后台事件进入线程安全队列，GUI 主线程消费。

验证：协议和假串口测试全部通过。

## 任务 5：实现安全状态机

在独立纯模块 `vision_app/safety.py` 中实现：

- `AppState`：`DISCONNECTED`、`STOPPED`、`CAMERA_READY`、`TARGET_LOCKED`、`RUNNING`、`FAULT`；
- 显式转换表；
- `SafetyInputs` 汇总串口、反馈、摄像头、目标、标定、方向和数值状态；
- `start_blockers()` 返回所有不可启动原因；
- `SafetyController` 锁存首个故障，只有人工确认才清除；
- 故障和关闭路径产生一次停机请求，重复处理保持幂等。

验证：覆盖每条允许转换、每条禁止转换和全部启动阻止条件。

## 任务 6：实现视觉相对位移模块

创建 `vision_app/vision_tracker.py`：

- 解析用户填写的摄像头源；
- 拒绝空值和无法打开的源；
- 手动 ROI 初始化 CSRT；
- 每帧返回目标中心、画面中心、带符号横向偏移和单调时间戳；
- 绘制中央十字准星、目标中心、偏移线和安全区域；
- 跟踪失败后不复用旧框，不自动重新锁定；
- 本地视频源标记为离线测试，禁止真实闭环。

验证：源解析和测量数据模型使用单元测试；CSRT 使用本机 OpenCV 做无硬件初始化检查。

## 任务 7：重写 GUI 并接入闭环

重写 `vision_app/swimming_app.py`，保留 `swimming_gui.py` 作为入口：

- 中文设置区：摄像头源、串口、标定、方向、安全阈值；
- 明确操作按钮：连接、打开摄像头、框选目标、启动闭环、停止、确认故障；
- 顶部彩色状态横幅持续显示当前状态和下一步；
- 禁用按钮时在状态区列出全部原因；
- 启动前模态确认汇总端口、标定、方向、反馈和首个目标 RPM；
- 故障时红色横幅和一次性弹窗同时提示原因、停机发送结果和恢复步骤；
- 20 Hz 控制任务只消费新鲜、有效数据；
- 启动严格发送 `T` 后发送 `S`；
- 停止、故障和关闭尽力发送 `P`；
- 重新连接、重新打开摄像头或修改标定不自动恢复运行。

验证：用假串口和可注入测量完成无设备闭环集成测试，手工启动 GUI 检查布局和提示。

## 任务 8：增加 INO 独立看门狗

修改 `motor_control/pidnew2_copy_20260714231054.ino`：

- 增加 `lastControlCommandTime`、500 ms 超时常量和看门狗锁存标志；
- 合法 `S`/`T` 更新最后命令时间；
- 电机启用且超时后关闭使能、目标归零、PID 安全复位并发送零速；
- 打印唯一看门狗故障行；
- 通信恢复不自动启用；
- 不修改 CAN ID、帧布局、波特率、控制周期和原有反馈解析。

验证：源代码审查确保超时判断使用无符号 `millis()` 差值；由于本机缺少 Arduino CLI，明确记录编译验证尚需 Arduino 工具链执行。

## 任务 9：清理旧逻辑与补齐说明

- 删除 `vision_app/swimming.py`；
- 删除 `vision_app/swimming - 副本.py`；
- 删除根目录 `tracker.py`；
- 保留 `1.py` 和用户的 `ai.py`；
- 添加 `requirements.txt`，声明 OpenCV contrib、Pillow 和 pyserial；
- 更新根 `README.md`，说明目录结构、安装、启动、控制公式、安全限制和硬件验收顺序。

## 任务 10：完整验证与审计

执行：

```powershell
py -m unittest discover -s vision_app/tests -v
py -m compileall -q vision_app
```

额外检查：

- 搜索 Python 中是否残留 PID 实现或旧速度公式；
- 搜索所有电机启动路径，确认均经过前置条件和确认弹窗；
- 搜索所有异常、关闭和丢失路径，确认均请求停机；
- 检查串口后台线程不直接访问 Tkinter；
- 检查命令 RPM 永不超出 `-2047..2047`；
- 检查所有速度均明确单位和符号方向；
- 检查 APP 提示覆盖下一步、禁用原因、启动风险和故障恢复；
- 记录无法在当前环境证明的 Arduino 编译和真实硬件验收项目，不作虚假完成声明。
