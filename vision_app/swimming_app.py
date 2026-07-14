from __future__ import annotations

import queue
import time
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk

import cv2
from PIL import Image, ImageTk

from vision_app.control_core import (
    ControlInputError,
    MotionSolution,
    RelativeDisplacementEstimator,
    RelativeMotionEstimate,
    RpmRateLimiter,
    solve_motion,
)
from vision_app.motor_link import MotorLink, MotorLinkError, MotorTelemetry
from vision_app.safety import AppState, SafetyController, SafetyInputs, StateTransitionError
from vision_app.settings import CalibrationConfirmation, ControlSettings, SettingsError
from vision_app.vision_tracker import (
    TargetSelectionCancelled,
    TrackingLostError,
    TrackingMeasurement,
    VisionInputError,
    VisionRuntimeError,
    VisionTracker,
)


STATE_LABELS = {
    AppState.DISCONNECTED: "未连接",
    AppState.STOPPED: "电机已停止",
    AppState.CAMERA_READY: "摄像头已就绪",
    AppState.TARGET_LOCKED: "目标已锁定",
    AppState.RUNNING: "闭环运行中",
    AppState.FAULT: "故障锁定",
}

STATE_COLORS = {
    AppState.DISCONNECTED: ("#475569", "#f8fafc"),
    AppState.STOPPED: ("#1d4ed8", "#eff6ff"),
    AppState.CAMERA_READY: ("#1d4ed8", "#eff6ff"),
    AppState.TARGET_LOCKED: ("#a16207", "#fefce8"),
    AppState.RUNNING: ("#15803d", "#f0fdf4"),
    AppState.FAULT: ("#b91c1c", "#fef2f2"),
}


class SwimControlApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("游泳滑轨机器人视觉闭环")
        self.root.geometry("1420x900")
        self.root.minsize(1180, 760)

        self.motor = MotorLink()
        self.vision = VisionTracker()
        self.safety = SafetyController()
        self.settings = ControlSettings().validated()
        self.calibration = CalibrationConfirmation()
        self.estimator: RelativeDisplacementEstimator | None = None
        self.rate_limiter = RpmRateLimiter(self.settings.max_rpm_rate_per_s)

        self.latest_telemetry: MotorTelemetry | None = None
        self.latest_measurement: TrackingMeasurement | None = None
        self.latest_estimate: RelativeMotionEstimate | None = None
        self.latest_solution: MotionSolution | None = None
        self.last_command_rpm = 0
        self._photo = None
        self._closing = False
        self._fault_popup_shown = False

        self.camera_source_var = tk.StringVar(value="0")
        self.serial_port_var = tk.StringVar(value="")
        self.pixels_per_meter_var = tk.StringVar(value="120.0")
        self.rpm_per_mps_var = tk.StringVar(value="1.0")
        self.camera_sign_var = tk.StringVar(value="+1")
        self.motor_sign_var = tk.StringVar(value="+1")
        self.rpm_limit_var = tk.StringVar(value="2047")
        self.rpm_rate_var = tk.StringVar(value="500.0")
        self.calibration_status_var = tk.StringVar(value="未确认")

        self.banner_var = tk.StringVar(value="未连接：请填写串口和摄像头源。")
        self.detail_var = tk.StringVar(value="系统默认保持停止，不会自动启动电机。")
        self.state_var = tk.StringVar(value=STATE_LABELS[self.safety.state])
        self.offset_var = tk.StringVar(value="-- px / -- m")
        self.relative_speed_var = tk.StringVar(value="-- m/s")
        self.robot_speed_var = tk.StringVar(value="-- m/s")
        self.swimmer_speed_var = tk.StringVar(value="-- m/s")
        self.target_rpm_var = tk.StringVar(value="0 RPM")
        self.actual_rpm_var = tk.StringVar(value="-- RPM")
        self.feedback_age_var = tk.StringVar(value="-- ms")

        self._build_ui()
        self._install_setting_traces()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(30, self._camera_tick)
        self.root.after(50, self._poll_motor_events)
        self.root.after(50, self._control_tick)
        self.root.after(100, self._refresh_status)

    def _build_ui(self) -> None:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")

        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=4)
        outer.columnconfigure(1, weight=2)
        outer.rowconfigure(2, weight=1)

        title = ttk.Label(outer, text="游泳滑轨机器人视觉闭环", font=("Microsoft YaHei UI", 18, "bold"))
        title.grid(row=0, column=0, columnspan=2, sticky="w")

        self.banner = tk.Label(
            outer,
            textvariable=self.banner_var,
            anchor="w",
            padx=12,
            pady=9,
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        self.banner.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 12))

        left = ttk.Frame(outer)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 14))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.video_label = tk.Label(
            left,
            text="请先连接串口并打开摄像头",
            bg="#0f172a",
            fg="#e2e8f0",
            font=("Microsoft YaHei UI", 14),
        )
        self.video_label.grid(row=0, column=0, sticky="nsew")

        metrics = ttk.LabelFrame(left, text="实时测量（摄像头原始量为相对位移）", padding=10)
        metrics.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        metric_items = [
            ("目标相对位移", self.offset_var),
            ("相对速度（位移序列求导）", self.relative_speed_var),
            ("机器人速度", self.robot_speed_var),
            ("运动员估算速度", self.swimmer_speed_var),
            ("发送目标", self.target_rpm_var),
            ("电机实际反馈", self.actual_rpm_var),
            ("反馈年龄", self.feedback_age_var),
        ]
        for index, (label, variable) in enumerate(metric_items):
            row, column_group = divmod(index, 4)
            base_column = column_group * 2
            ttk.Label(metrics, text=label).grid(row=row, column=base_column, sticky="w", padx=(0, 8), pady=3)
            ttk.Label(metrics, textvariable=variable, font=("Consolas", 10, "bold")).grid(
                row=row, column=base_column + 1, sticky="w", padx=(0, 18), pady=3
            )

        right = ttk.Frame(outer)
        right.grid(row=2, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        connection = ttk.LabelFrame(right, text="1. 设备连接", padding=10)
        connection.grid(row=0, column=0, sticky="ew")
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text="串口（如 COM3）").grid(row=0, column=0, sticky="w")
        ttk.Entry(connection, textvariable=self.serial_port_var).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(connection, text="摄像头源").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(connection, textvariable=self.camera_source_var).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0)
        )
        self.connect_button = ttk.Button(connection, text="连接串口（自动先停止）", command=self.connect_serial)
        self.connect_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.disconnect_button = ttk.Button(connection, text="断开串口", command=self.disconnect_serial)
        self.disconnect_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        calibration = ttk.LabelFrame(right, text="2. 标定与方向", padding=10)
        calibration.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        calibration.columnconfigure(1, weight=1)
        fields = [
            ("像素/米", self.pixels_per_meter_var),
            ("RPM/(米/秒)", self.rpm_per_mps_var),
            ("RPM绝对上限", self.rpm_limit_var),
            ("RPM变化率/秒", self.rpm_rate_var),
        ]
        for row, (label, variable) in enumerate(fields):
            ttk.Label(calibration, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(calibration, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(calibration, text="画面向右代表").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Combobox(
            calibration, textvariable=self.camera_sign_var, values=("+1", "-1"), state="readonly", width=6
        ).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(calibration, text="正RPM代表").grid(row=5, column=0, sticky="w", pady=3)
        ttk.Combobox(
            calibration, textvariable=self.motor_sign_var, values=("+1", "-1"), state="readonly", width=6
        ).grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(calibration, text="标定状态").grid(row=6, column=0, sticky="w", pady=(6, 0))
        self.calibration_label = ttk.Label(calibration, textvariable=self.calibration_status_var)
        self.calibration_label.grid(row=6, column=1, sticky="e", pady=(6, 0))
        self.confirm_calibration_button = ttk.Button(
            calibration, text="应用并确认实测标定", command=self.confirm_calibration
        )
        self.confirm_calibration_button.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        actions = ttk.LabelFrame(right, text="3. 按顺序操作", padding=10)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        self.open_camera_button = ttk.Button(actions, text="打开摄像头", command=self.open_camera)
        self.open_camera_button.grid(row=0, column=0, sticky="ew")
        self.select_target_button = ttk.Button(actions, text="手动框选运动员", command=self.select_target)
        self.select_target_button.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.start_button = ttk.Button(actions, text="确认风险并启动闭环", command=self.start_closed_loop)
        self.start_button.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.stop_button = ttk.Button(actions, text="停止电机", command=self.manual_stop)
        self.stop_button.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.ack_fault_button = ttk.Button(actions, text="确认故障并复位", command=self.acknowledge_fault)
        self.ack_fault_button.grid(row=4, column=0, sticky="ew", pady=(6, 0))

        status_box = ttk.LabelFrame(right, text="操作提示", padding=10)
        status_box.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(status_box, textvariable=self.state_var, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        ttk.Label(status_box, textvariable=self.detail_var, wraplength=390, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(
            status_box,
            text="紧急情况：立即点击“停止电机”；通信完全断开时 Arduino 看门狗将在 500 ms 后停机。",
            foreground="#b91c1c",
            wraplength=390,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

    def _install_setting_traces(self) -> None:
        for variable in (
            self.pixels_per_meter_var,
            self.rpm_per_mps_var,
            self.camera_sign_var,
            self.motor_sign_var,
            self.rpm_limit_var,
            self.rpm_rate_var,
        ):
            variable.trace_add("write", self._on_setting_edited)

    def _on_setting_edited(self, *_args) -> None:
        if self._closing:
            return
        was_confirmed = self.calibration.confirmed
        self.calibration.invalidate()
        self.calibration_status_var.set("未确认")
        if was_confirmed:
            self.detail_var.set("标定或方向已修改：确认状态已自动失效，请重新实测确认。")
        if self.safety.state is AppState.RUNNING:
            self._trigger_fault("运行中修改了标定或方向参数")

    def _settings_from_ui(self) -> ControlSettings:
        try:
            settings = replace(
                self.settings,
                pixels_per_meter=float(self.pixels_per_meter_var.get().strip()),
                rpm_per_mps=float(self.rpm_per_mps_var.get().strip()),
                camera_axis_sign=int(self.camera_sign_var.get()),
                motor_axis_sign=int(self.motor_sign_var.get()),
                rpm_limit=int(self.rpm_limit_var.get().strip()),
                max_rpm_rate_per_s=float(self.rpm_rate_var.get().strip()),
            )
        except ValueError as exc:
            raise SettingsError("标定、方向、限幅和变化率必须填写有效数字") from exc
        return settings.validated()

    def confirm_calibration(self) -> None:
        if self.safety.state in (AppState.RUNNING, AppState.FAULT):
            messagebox.showwarning("不能修改", "请先停止并处理故障，再确认标定。")
            return
        try:
            settings = self._settings_from_ui()
        except SettingsError as exc:
            messagebox.showerror("标定无效", str(exc))
            return
        prompt = (
            "请确认这些值来自实测或经过核对：\n\n"
            f"像素/米：{settings.pixels_per_meter}\n"
            f"RPM/(米/秒)：{settings.rpm_per_mps}\n"
            f"画面方向：{settings.camera_axis_sign:+d}\n"
            f"电机方向：{settings.motor_axis_sign:+d}\n"
            f"RPM上限：±{settings.rpm_limit}\n\n"
            "默认占位换算值不能用于真实电机。确认错误方向可能导致机器人反向运动。"
        )
        if not messagebox.askyesno("确认实测标定", prompt, icon="warning"):
            return
        self.settings = settings
        self.calibration.confirm(settings)
        self.calibration_status_var.set("已确认")
        self.rate_limiter = RpmRateLimiter(settings.max_rpm_rate_per_s)
        if self.vision.target_locked:
            self.vision.clear_target()
            self.safety.target_cleared()
            self._reset_motion()
            self.detail_var.set("标定已确认。参数变化后必须重新框选运动员。")
        else:
            self.detail_var.set("标定已确认。下一步请打开摄像头并框选运动员。")

    def connect_serial(self) -> None:
        if self.motor.connected:
            messagebox.showinfo("提示", "串口已经连接。")
            return
        port = self.serial_port_var.get().strip()
        if not port:
            messagebox.showerror("缺少串口", "请填写串口名称，例如 COM3。")
            return
        try:
            self.motor.connect(port)
            self.safety.serial_connected()
        except (MotorLinkError, StateTransitionError) as exc:
            messagebox.showerror("串口连接失败", str(exc))
            return
        self.latest_telemetry = None
        self.detail_var.set("串口已连接并发送停止命令。等待电机反馈后再继续。")

    def disconnect_serial(self) -> None:
        stop_sent = self.motor.disconnect(send_stop=True)
        self.vision.release()
        self.safety.disconnected("用户断开串口")
        self._reset_motion()
        self.video_label.configure(image="", text="串口已断开，电机应由 Arduino 看门狗保持停止")
        self._photo = None
        self.detail_var.set("已断开串口。" + ("断开前已发送停止命令。" if stop_sent else "未确认停止命令已送达。"))

    def open_camera(self) -> None:
        if not self.motor.connected:
            messagebox.showwarning("操作顺序", "请先连接串口；连接时 APP 会先发送停止命令。")
            return
        if self.safety.state in (AppState.RUNNING, AppState.FAULT):
            messagebox.showwarning("不能打开", "请先停止运行或确认故障。")
            return
        try:
            frame = self.vision.open(self.camera_source_var.get())
            self.safety.camera_opened()
        except (VisionInputError, VisionRuntimeError, StateTransitionError) as exc:
            try:
                self.safety.camera_closed()
            except StateTransitionError:
                pass
            messagebox.showerror("摄像头打开失败", str(exc))
            return
        self._reset_motion()
        source = self.vision.source
        if source is not None and source.offline_file:
            self.detail_var.set("已打开离线视频：仅允许视觉测试，禁止启动真实电机。")
        else:
            self.detail_var.set("摄像头已就绪。下一步点击“手动框选运动员”。")
        self._render_frame(self.vision.annotate(frame, None, max_offset_fraction=self.settings.max_offset_fraction))

    def select_target(self) -> None:
        if not self.vision.is_open:
            messagebox.showwarning("操作顺序", "请先打开摄像头。")
            return
        if self.safety.state is not AppState.CAMERA_READY:
            messagebox.showwarning("不能框选", "当前状态不允许框选，请先停止并重新打开摄像头。")
            return
        try:
            settings = self._settings_from_ui()
        except SettingsError as exc:
            messagebox.showerror("参数无效", str(exc))
            return
        messagebox.showinfo("框选提示", "将在独立画面中框选运动员。拖动矩形后按 Enter 确认，按 Esc 取消。")
        try:
            measurement = self.vision.select_target()
            self.safety.target_locked()
        except TargetSelectionCancelled as exc:
            self.detail_var.set(str(exc))
            return
        except (VisionInputError, VisionRuntimeError, StateTransitionError) as exc:
            messagebox.showerror("目标框选失败", str(exc))
            return
        self.settings = settings
        self.estimator = RelativeDisplacementEstimator(
            settings.pixels_per_meter,
            settings.camera_axis_sign,
            max_samples=settings.displacement_window_size,
            max_age_s=settings.displacement_window_s,
        )
        self.latest_measurement = measurement
        self.latest_estimate = self.estimator.add_sample(measurement.timestamp, measurement.offset_px)
        self.latest_solution = None
        self.rate_limiter.reset()
        self.detail_var.set("目标已锁定。正在收集相对位移序列并等待运动解算就绪。")

    def start_closed_loop(self) -> None:
        try:
            settings = self._settings_from_ui()
        except SettingsError as exc:
            messagebox.showerror("参数无效", str(exc))
            return
        inputs = self._safety_inputs(settings)
        blockers = inputs.start_blockers()
        if blockers:
            messagebox.showwarning("尚不能启动", "请先处理以下问题：\n\n- " + "\n- ".join(blockers))
            return
        solution = self.latest_solution
        telemetry = self.latest_telemetry
        if solution is None or telemetry is None:
            messagebox.showwarning("尚不能启动", "运动解算或电机反馈尚未就绪。")
            return
        source_text = self.camera_source_var.get().strip()
        confirmation = (
            "强电机启动确认\n\n"
            f"串口：{self.serial_port_var.get().strip()}\n"
            f"摄像头：{source_text}\n"
            f"像素/米：{settings.pixels_per_meter}\n"
            f"RPM/(米/秒)：{settings.rpm_per_mps}\n"
            f"画面方向：{settings.camera_axis_sign:+d}\n"
            f"电机方向：{settings.motor_axis_sign:+d}\n"
            f"当前实际RPM：{telemetry.actual_rpm:+.1f}\n"
            f"当前相对速度：{solution.relative_speed_mps:+.3f} m/s\n"
            f"运动员估算速度：{solution.swimmer_speed_mps:+.3f} m/s\n"
            f"原始目标：{solution.raw_target_rpm:+.1f} RPM\n\n"
            "启动后请随时准备点击“停止电机”。是否确认周围无人、方向正确并启动？"
        )
        if not messagebox.askyesno("确认启动闭环", confirmation, icon="warning"):
            self.detail_var.set("用户取消启动，电机保持停止。")
            return
        try:
            self.safety.start(inputs)
            self.rate_limiter.reset()
            initial_rpm = int(round(self.rate_limiter.update(solution.command_rpm, time.monotonic())))
            self.motor.send_target_rpm(initial_rpm)
            self.motor.send_start()
            self.last_command_rpm = initial_rpm
        except (StateTransitionError, ControlInputError, MotorLinkError) as exc:
            self._trigger_fault(f"启动失败：{exc}")
            return
        self.detail_var.set("闭环已启动：APP 正以 20 Hz 更新目标，Arduino 看门狗负责失联停机。")

    def manual_stop(self) -> None:
        fault_remains_latched = self.safety.state is AppState.FAULT
        stop_sent = False
        if self.motor.connected:
            try:
                self.motor.send_stop()
                stop_sent = True
            except MotorLinkError as exc:
                self.detail_var.set(f"停止命令发送失败：{exc}；等待 Arduino 看门狗停机。")
        self.safety.manual_stop()
        self.vision.release()
        self._reset_motion()
        self.video_label.configure(image="", text="电机已请求停止。请重新打开摄像头并框选目标。")
        self._photo = None
        if fault_remains_latched:
            delivery = "已再次发送停止命令。" if stop_sent else "停止命令未确认送达，等待 Arduino 看门狗。"
            self.detail_var.set(f"{delivery} 故障仍保持锁定，请点击“确认故障并复位”。")
        elif stop_sent:
            self.detail_var.set("已发送停止命令。重新启动前必须重新打开摄像头并框选运动员。")

    def acknowledge_fault(self) -> None:
        if self.safety.state is not AppState.FAULT:
            messagebox.showinfo("提示", "当前没有待确认故障。")
            return
        try:
            self.safety.acknowledge_fault()
        except StateTransitionError as exc:
            messagebox.showerror("故障复位失败", str(exc))
            return
        if not self.motor.connected:
            self.safety.disconnected("故障确认后串口仍未连接")
        self.vision.release()
        self._reset_motion()
        self._fault_popup_shown = False
        self.video_label.configure(image="", text="故障已确认。请重新打开摄像头并框选目标。")
        self._photo = None
        self.detail_var.set("故障已确认，电机保持停止。必须重新完成摄像头和目标步骤。")

    def _camera_tick(self) -> None:
        if self._closing:
            return
        if self.vision.is_open:
            try:
                frame, measurement = self.vision.read()
                if measurement is not None:
                    self._accept_measurement(measurement)
                    if abs(measurement.offset_px) > measurement.frame_width * self.settings.max_offset_fraction:
                        if self.safety.state is AppState.RUNNING:
                            self._trigger_fault("运动员相对位移超过安全区域")
                        else:
                            self.detail_var.set("目标接近画面边缘，请重新调整或框选。")
                annotated = self.vision.annotate(
                    frame,
                    measurement,
                    max_offset_fraction=self.settings.max_offset_fraction,
                )
                self._render_frame(annotated)
            except TrackingLostError as exc:
                if self.safety.state is AppState.RUNNING:
                    self._trigger_fault(str(exc))
                else:
                    try:
                        self.safety.target_cleared()
                    except StateTransitionError:
                        pass
                    self._reset_motion()
                    self.detail_var.set(str(exc))
            except VisionRuntimeError as exc:
                if self.safety.state is AppState.RUNNING:
                    self._trigger_fault(str(exc))
                else:
                    self.vision.release()
                    try:
                        self.safety.camera_closed()
                    except StateTransitionError:
                        pass
                    self._reset_motion()
                    self.detail_var.set(str(exc))
        self.root.after(30, self._camera_tick)

    def _accept_measurement(self, measurement: TrackingMeasurement) -> None:
        self.latest_measurement = measurement
        estimator = self.estimator
        if estimator is None:
            return
        try:
            estimate = estimator.add_sample(measurement.timestamp, measurement.offset_px)
        except ControlInputError as exc:
            if self.safety.state is AppState.RUNNING:
                self._trigger_fault(f"相对位移序列无效：{exc}")
            return
        self.latest_estimate = estimate
        self.offset_var.set(
            f"{measurement.offset_px:+.1f} px / {estimate.relative_displacement_m:+.3f} m"
        )
        if not estimate.ready or estimate.relative_speed_mps is None:
            self.relative_speed_var.set("样本收集中")
            self.latest_solution = None
            return
        self.relative_speed_var.set(f"{estimate.relative_speed_mps:+.3f} m/s")
        telemetry = self.latest_telemetry
        if telemetry is None:
            self.latest_solution = None
            return
        try:
            solution = solve_motion(
                telemetry.actual_rpm,
                estimate.relative_speed_mps,
                self.settings.rpm_per_mps,
                self.settings.motor_axis_sign,
                self.settings.rpm_limit,
            )
        except ControlInputError as exc:
            self.latest_solution = None
            if self.safety.state is AppState.RUNNING:
                self._trigger_fault(f"运动速度解算失败：{exc}")
            return
        self.latest_solution = solution
        self.robot_speed_var.set(f"{solution.robot_speed_mps:+.3f} m/s")
        self.swimmer_speed_var.set(f"{solution.swimmer_speed_mps:+.3f} m/s")

    def _poll_motor_events(self) -> None:
        if self._closing:
            return
        while True:
            try:
                event = self.motor.events.get_nowait()
            except queue.Empty:
                break
            if event.kind == "telemetry" and event.telemetry is not None:
                self.latest_telemetry = event.telemetry
                self.actual_rpm_var.set(f"{event.telemetry.actual_rpm:+.1f} RPM")
            elif event.kind == "error":
                self._trigger_fault(event.message)
                self.motor.disconnect(send_stop=False)
        self.root.after(50, self._poll_motor_events)

    def _control_tick(self) -> None:
        if self._closing:
            return
        if self.safety.state is AppState.RUNNING:
            now = time.monotonic()
            fault_reason = self._runtime_fault_reason(now)
            if fault_reason is not None:
                self._trigger_fault(fault_reason)
            else:
                solution = self.latest_solution
                if solution is not None:
                    try:
                        limited = self.rate_limiter.update(solution.command_rpm, now)
                        command = max(-self.settings.rpm_limit, min(self.settings.rpm_limit, int(round(limited))))
                        self.motor.send_target_rpm(command)
                        self.last_command_rpm = command
                        suffix = "（已限幅）" if solution.saturated else ""
                        self.target_rpm_var.set(f"{command:+d} RPM {suffix}")
                    except (ControlInputError, MotorLinkError) as exc:
                        self._trigger_fault(f"控制命令发送失败：{exc}")
        interval_ms = max(10, int(round(self.settings.command_interval_s * 1000)))
        self.root.after(interval_ms, self._control_tick)

    def _runtime_fault_reason(self, now: float) -> str | None:
        if not self.motor.connected:
            return "运行中串口断开"
        telemetry = self.latest_telemetry
        if telemetry is None or now - telemetry.received_at > self.settings.telemetry_timeout_s:
            return "电机反馈超时"
        measurement = self.latest_measurement
        if measurement is None or now - measurement.timestamp > self.settings.vision_timeout_s:
            return "视觉相对位移测量超时"
        if not self.vision.target_locked:
            return "目标跟踪丢失"
        if self.latest_estimate is None or not self.latest_estimate.ready or self.latest_solution is None:
            return "运动速度解算失效"
        if not self.calibration.is_confirmed_for(self.settings):
            return "标定确认失效"
        return None

    def _safety_inputs(self, settings: ControlSettings | None = None) -> SafetyInputs:
        active_settings = settings or self.settings
        now = time.monotonic()
        telemetry_fresh = (
            self.latest_telemetry is not None
            and 0.0 <= now - self.latest_telemetry.received_at <= active_settings.telemetry_timeout_s
        )
        measurement_fresh = (
            self.latest_measurement is not None
            and 0.0 <= now - self.latest_measurement.timestamp <= active_settings.vision_timeout_s
        )
        source = self.vision.source
        return SafetyInputs(
            serial_connected=self.motor.connected,
            telemetry_fresh=telemetry_fresh,
            camera_ready=self.vision.is_open,
            target_locked=self.vision.target_locked and measurement_fresh,
            calibration_confirmed=self.calibration.is_confirmed_for(active_settings),
            directions_valid=(active_settings.camera_axis_sign in (-1, 1) and active_settings.motor_axis_sign in (-1, 1)),
            motion_solution_valid=self.latest_solution is not None,
            offline_source=bool(source is not None and source.offline_file),
        )

    def _trigger_fault(self, reason: str) -> None:
        first_fault = self.safety.fault(reason)
        stop_sent = False
        if self.motor.connected:
            try:
                self.motor.send_stop()
                stop_sent = True
            except MotorLinkError:
                stop_sent = False
        self.vision.clear_target()
        self.rate_limiter.reset()
        self.estimator = None
        self.latest_solution = None
        if first_fault:
            delivery = "已发送停止命令。" if stop_sent else "停止命令未确认送达，等待 Arduino 500 ms 看门狗。"
            self.detail_var.set(f"故障：{reason}。{delivery} 请确认故障后重新连接/框选，系统不会自动恢复。")
            if not self._fault_popup_shown:
                self._fault_popup_shown = True
                messagebox.showerror(
                    "闭环故障，电机已请求停止",
                    f"故障原因：{reason}\n\n{delivery}\n\n"
                    "关闭此窗口不会恢复运行。请检查设备后点击“确认故障并复位”。",
                )

    def _reset_motion(self) -> None:
        self.estimator = None
        self.rate_limiter.reset()
        self.latest_measurement = None
        self.latest_estimate = None
        self.latest_solution = None
        self.latest_telemetry = None if not self.motor.connected else self.latest_telemetry
        self.last_command_rpm = 0
        self.offset_var.set("-- px / -- m")
        self.relative_speed_var.set("-- m/s")
        self.robot_speed_var.set("-- m/s")
        self.swimmer_speed_var.set("-- m/s")
        self.target_rpm_var.set("0 RPM")

    def _refresh_status(self) -> None:
        if self._closing:
            return
        state = self.safety.state
        self.state_var.set(STATE_LABELS[state])
        foreground, background = STATE_COLORS[state]
        self.banner.configure(fg=foreground, bg=background)

        if state is AppState.DISCONNECTED:
            message = "未连接：请填写串口，连接后系统会先发送停止命令。"
        elif state is AppState.STOPPED:
            message = "电机已停止：请确认标定，然后打开摄像头。"
        elif state is AppState.CAMERA_READY:
            message = "摄像头已就绪：请手动框选游泳运动员。"
        elif state is AppState.TARGET_LOCKED:
            blockers = self._safety_inputs().start_blockers()
            message = "目标已锁定，可以启动。" if not blockers else "尚不能启动：" + "；".join(blockers)
        elif state is AppState.RUNNING:
            message = f"闭环运行中：当前发送 {self.last_command_rpm:+d} RPM；保持准备随时停止。"
        else:
            message = f"故障锁定：{self.safety.fault_reason or '未知故障'}；电机已请求停止。"
        self.banner_var.set(message)

        now = time.monotonic()
        if self.latest_telemetry is None:
            self.feedback_age_var.set("-- ms")
        else:
            age_ms = max(0.0, (now - self.latest_telemetry.received_at) * 1000.0)
            self.feedback_age_var.set(f"{age_ms:.0f} ms")

        self.connect_button.configure(state="disabled" if self.motor.connected else "normal")
        self.disconnect_button.configure(state="normal" if self.motor.connected else "disabled")
        self.open_camera_button.configure(
            state="normal"
            if self.motor.connected and state not in (AppState.RUNNING, AppState.FAULT)
            else "disabled"
        )
        self.select_target_button.configure(
            state="normal" if self.vision.is_open and state is AppState.CAMERA_READY else "disabled"
        )
        start_ready = state is AppState.TARGET_LOCKED and not self._safety_inputs().start_blockers()
        self.start_button.configure(state="normal" if start_ready else "disabled")
        self.stop_button.configure(state="normal" if self.motor.connected else "disabled")
        self.ack_fault_button.configure(state="normal" if state is AppState.FAULT else "disabled")
        self.confirm_calibration_button.configure(
            state="disabled" if state in (AppState.RUNNING, AppState.FAULT) else "normal"
        )
        self.root.after(100, self._refresh_status)

    def _render_frame(self, frame) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        target_width = max(320, self.video_label.winfo_width())
        target_height = max(240, self.video_label.winfo_height())
        image.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(image)
        self.video_label.configure(image=self._photo, text="")

    def on_close(self) -> None:
        if self._closing:
            return
        if self.safety.state is AppState.RUNNING:
            if not messagebox.askyesno("确认退出", "闭环正在运行。退出将立即发送停止命令，是否继续？", icon="warning"):
                return
        self._closing = True
        stop_sent = self.motor.disconnect(send_stop=True)
        self.vision.release()
        if not stop_sent and self.safety.state is AppState.RUNNING:
            messagebox.showwarning("停止未确认", "未确认停止命令送达，请等待 Arduino 看门狗停机并检查设备。")
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    SwimControlApp().run()


if __name__ == "__main__":
    main()
