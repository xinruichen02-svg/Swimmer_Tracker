from __future__ import annotations

import queue
import math
import threading
import time
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk

import cv2
from PIL import Image, ImageTk

from vision_app.app_config import AppConfigError, load_settings, save_settings
from vision_app.control_core import (
    ControlInputError,
    MotionSolution,
    RelativeDisplacementEstimator,
    RelativeMotionEstimate,
    RpmRateLimiter,
    constant_speed_to_rpm,
    solve_motion,
)
from vision_app.motor_link import MotorTelemetry
from vision_app.motor_backend import MotorBackendError
from vision_app.motor_supervisor import BackendConfig
from vision_app.safety import AppState, SafetyController, SafetyInputs, StateTransitionError
from vision_app.settings import CalibrationConfirmation, ControlSettings, SettingsError
from vision_app.supervisor_client import MotorSupervisorClient, SupervisorClientError
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
    AppState.RUNNING: "机器人运行中",
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
        self.root.title("swimmer_Tracker")
        self.root.geometry("1420x900")
        self.root.minsize(1180, 760)

        self.motor = MotorSupervisorClient()
        self.vision = VisionTracker()
        self.safety = SafetyController()
        self._config_warning: str | None = None
        try:
            self.settings = load_settings()
        except AppConfigError as exc:
            self.settings = ControlSettings().validated()
            self._config_warning = str(exc)
        self.calibration = CalibrationConfirmation()
        self.estimator: RelativeDisplacementEstimator | None = None
        self.rate_limiter = RpmRateLimiter(self.settings.max_rpm_rate_per_s)

        self.latest_telemetry: MotorTelemetry | None = None
        self.latest_measurement: TrackingMeasurement | None = None
        self.latest_estimate: RelativeMotionEstimate | None = None
        self.latest_solution: MotionSolution | None = None
        self.last_command_rpm = 0
        self.active_run_mode: str | None = None
        self.constant_command_rpm = 0
        self._photo = None
        self._closing = False
        self._fault_popup_shown = False
        self._camera_scan_running = False
        self._camera_scan_results: queue.Queue[tuple[list[str], str | None]] = queue.Queue()

        self.camera_source_var = tk.StringVar(value="0")
        self.backend_var = tk.StringVar(value=self.settings.backend)
        self.serial_port_var = tk.StringVar(value=self.settings.serial_port)
        self.can_interface_var = tk.StringVar(value=self.settings.can_interface)
        self.can_channel_var = tk.StringVar(value=self.settings.can_channel)
        self.can_bitrate_var = tk.StringVar(value=str(self.settings.can_bitrate))
        self.control_mode_var = tk.StringVar(value=self.settings.control_mode)
        self.pixels_per_meter_var = tk.StringVar(value=str(self.settings.pixels_per_meter))
        self.rpm_per_mps_var = tk.StringVar(value=str(self.settings.rpm_per_mps))
        self.camera_sign_var = tk.StringVar(value=f"{self.settings.camera_axis_sign:+d}")
        self.motor_sign_var = tk.StringVar(value=f"{self.settings.motor_axis_sign:+d}")
        self.rpm_limit_var = tk.StringVar(value=str(self.settings.rpm_limit))
        self.rpm_rate_var = tk.StringVar(value=str(self.settings.max_rpm_rate_per_s))
        self.pid_kp_var = tk.StringVar(value="1.0")
        self.pid_ki_var = tk.StringVar(value="0.05")
        self.pid_kd_var = tk.StringVar(value="0.02")
        self.constant_speed_var = tk.StringVar(value="0.0")
        self.constant_rpm_preview_var = tk.StringVar(value="请输入非零速度")
        self.calibration_status_var = tk.StringVar(value="未确认")

        self.banner_var = tk.StringVar(value="未连接：默认虚拟模式，不会驱动真实机器人。")
        self.detail_var = tk.StringVar(value="系统默认保持停止，不会自动启动电机。")
        self.state_var = tk.StringVar(value=STATE_LABELS[self.safety.state])
        self.offset_var = tk.StringVar(value="-- px / -- m")
        self.relative_speed_var = tk.StringVar(value="-- m/s")
        self.robot_speed_var = tk.StringVar(value="-- m/s")
        self.swimmer_speed_var = tk.StringVar(value="-- m/s")
        self.target_rpm_var = tk.StringVar(value="0 RPM")
        self.actual_rpm_var = tk.StringVar(value="-- RPM")
        self.feedback_age_var = tk.StringVar(value="-- ms")
        self.backend_badge_var = tk.StringVar(value="仿真模式｜不会驱动真实机器人")
        self.supervisor_state_var = tk.StringVar(value="未启动")

        self._build_ui()
        self._on_backend_selected()
        if self._config_warning:
            self.detail_var.set(self._config_warning + "；已使用安全默认值。")
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

        title = ttk.Label(outer, text="swimmer_Tracker", font=("Microsoft YaHei UI", 18, "bold"))
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
            text="请先连接电机后端并打开摄像头",
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

        right_host = ttk.Frame(outer)
        right_host.grid(row=2, column=1, sticky="nsew")
        right_host.columnconfigure(0, weight=1)
        right_host.rowconfigure(0, weight=1)

        self.right_canvas = tk.Canvas(right_host, highlightthickness=0, borderwidth=0)
        self.right_canvas.grid(row=0, column=0, sticky="nsew")
        self.right_scrollbar = ttk.Scrollbar(right_host, orient="vertical", command=self.right_canvas.yview)
        self.right_scrollbar.grid(row=0, column=1, sticky="ns")
        self.right_canvas.configure(yscrollcommand=self.right_scrollbar.set)

        right = ttk.Frame(self.right_canvas)
        self._right_canvas_window = self.right_canvas.create_window((0, 0), window=right, anchor="nw")
        right.bind(
            "<Configure>",
            lambda _event: self.right_canvas.configure(scrollregion=self.right_canvas.bbox("all")),
        )
        self.right_canvas.bind(
            "<Configure>",
            lambda event: self.right_canvas.itemconfigure(self._right_canvas_window, width=event.width),
        )
        right_host.bind("<Enter>", self._bind_right_mousewheel)
        right_host.bind("<Leave>", self._unbind_right_mousewheel)
        right.columnconfigure(0, weight=1)

        connection = ttk.LabelFrame(right, text="1. 设备连接", padding=10)
        connection.grid(row=0, column=0, sticky="ew")
        connection.columnconfigure(1, weight=1)
        self.backend_badge = tk.Label(
            connection,
            textvariable=self.backend_badge_var,
            bg="#dbeafe",
            fg="#1d4ed8",
            padx=8,
            pady=5,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.backend_badge.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(connection, text="控制后端").grid(row=1, column=0, sticky="w")
        backend_box = ttk.Combobox(
            connection,
            textvariable=self.backend_var,
            values=("virtual", "arduino_serial", "python_can"),
            state="readonly",
        )
        backend_box.grid(row=1, column=1, sticky="ew", padx=(8, 0))
        backend_box.bind("<<ComboboxSelected>>", self._on_backend_selected)
        ttk.Label(connection, text="控制模式").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            connection,
            textvariable=self.control_mode_var,
            values=("driver_pid", "ino_pid_compat"),
            state="readonly",
        ).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        ttk.Label(connection, text="串口（如 COM3）").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(connection, textvariable=self.serial_port_var).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        ttk.Label(connection, text="CAN interface").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(connection, textvariable=self.can_interface_var).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        ttk.Label(connection, text="CAN channel").grid(row=5, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(connection, textvariable=self.can_channel_var).grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        ttk.Label(connection, text="CAN bitrate").grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(connection, textvariable=self.can_bitrate_var).grid(row=6, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        ttk.Label(connection, text="摄像头源").grid(row=7, column=0, sticky="w", pady=(8, 0))
        camera_controls = ttk.Frame(connection)
        camera_controls.grid(row=7, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        camera_controls.columnconfigure(0, weight=1)
        self.camera_source_box = ttk.Combobox(
            camera_controls,
            textvariable=self.camera_source_var,
            values=("0",),
            state="normal",
        )
        self.camera_source_box.grid(row=0, column=0, sticky="ew")
        self.scan_camera_button = ttk.Button(
            camera_controls,
            text="扫描",
            width=6,
            command=self.scan_camera_sources,
        )
        self.scan_camera_button.grid(row=0, column=1, padx=(6, 0))
        self.open_camera_button = ttk.Button(
            camera_controls,
            text="打开",
            width=6,
            command=self.open_camera,
        )
        self.open_camera_button.grid(row=0, column=2, padx=(6, 0))
        self.connect_button = ttk.Button(connection, text="启动安全监督并连接", command=self.connect_serial)
        self.connect_button.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.disconnect_button = ttk.Button(connection, text="停车并断开后端", command=self.disconnect_serial)
        self.disconnect_button.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(connection, text="监督进程").grid(row=10, column=0, sticky="w", pady=(6, 0))
        ttk.Label(connection, textvariable=self.supervisor_state_var).grid(row=10, column=1, sticky="e", pady=(6, 0))

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

        pid_frame = ttk.LabelFrame(right, text="3. INO 在线 PID 调参", padding=10)
        pid_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        for column in range(3):
            pid_frame.columnconfigure(column, weight=1)
        for column, (label, variable) in enumerate(
            (("Kp", self.pid_kp_var), ("Ki", self.pid_ki_var), ("Kd", self.pid_kd_var))
        ):
            ttk.Label(pid_frame, text=label).grid(row=0, column=column, sticky="w")
            ttk.Entry(pid_frame, textvariable=variable, width=10).grid(
                row=1, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0)
            )
        self.apply_pid_button = ttk.Button(
            pid_frame,
            text="发送 KP/KI/KD 到 Arduino",
            command=self.apply_pid_tunings,
            state="disabled",
        )
        self.apply_pid_button.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(
            pid_frame,
            text="仅 arduino_serial 后端可用；参数通过 KP=/KI=/KD= 串口命令在线生效。",
            foreground="#64748b",
            wraplength=390,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        constant_frame = ttk.LabelFrame(right, text="4. 定速巡航", padding=10)
        constant_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        constant_frame.columnconfigure(1, weight=1)
        ttk.Label(constant_frame, text="目标线速度（m/s）").grid(row=0, column=0, sticky="w")
        self.constant_speed_entry = ttk.Entry(constant_frame, textvariable=self.constant_speed_var)
        self.constant_speed_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(constant_frame, text="换算目标 RPM").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(constant_frame, textvariable=self.constant_rpm_preview_var).grid(
            row=1, column=1, sticky="e", pady=(6, 0)
        )
        self.start_constant_button = ttk.Button(
            constant_frame,
            text="确认风险并启动定速巡航",
            command=self.start_constant_speed,
            state="disabled",
        )
        self.start_constant_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.constant_stop_button = ttk.Button(
            constant_frame, text="停止电机", command=self.manual_stop, state="disabled"
        )
        self.constant_stop_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(
            constant_frame,
            text="速度可正可负；启动后保持该目标，直到手动停止或安全保护触发。",
            foreground="#64748b",
            wraplength=390,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        actions = ttk.LabelFrame(right, text="5. 视觉跟随", padding=10)
        actions.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        self.select_target_button = ttk.Button(actions, text="手动框选运动员", command=self.select_target)
        self.select_target_button.grid(row=0, column=0, sticky="ew")
        self.start_button = ttk.Button(actions, text="确认风险并启动闭环", command=self.start_closed_loop)
        self.start_button.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.stop_button = ttk.Button(actions, text="停止电机", command=self.manual_stop)
        self.stop_button.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.ack_fault_button = ttk.Button(actions, text="确认故障并复位", command=self.acknowledge_fault)
        self.ack_fault_button.grid(row=3, column=0, sticky="ew", pady=(6, 0))

        status_box = ttk.LabelFrame(right, text="操作提示", padding=10)
        status_box.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(status_box, textvariable=self.state_var, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        ttk.Label(status_box, textvariable=self.detail_var, wraplength=390, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(
            status_box,
            text="紧急情况：立即点击“停止电机”。软件监督能处理 GUI 失联，但系统/USB 整体失效仍需驱动器超时或物理急停。",
            foreground="#b91c1c",
            wraplength=390,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

    def _bind_right_mousewheel(self, _event=None) -> None:
        self.root.bind_all("<MouseWheel>", self._scroll_right_panel)

    def _unbind_right_mousewheel(self, _event=None) -> None:
        self.root.unbind_all("<MouseWheel>")

    def _scroll_right_panel(self, event) -> None:
        if event.delta:
            self.right_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

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

    def _on_backend_selected(self, _event=None) -> None:
        backend = self.backend_var.get()
        if backend == "virtual":
            self.backend_badge_var.set("仿真模式｜不会驱动真实机器人")
            self.backend_badge.configure(bg="#dbeafe", fg="#1d4ed8")
            self.detail_var.set("当前选择虚拟 CAN：适合完整软件测试，不会自动切换到真实设备。")
        elif backend == "arduino_serial":
            self.control_mode_var.set("driver_pid")
            self.backend_badge_var.set("真实模式｜Arduino 串口 + INO")
            self.backend_badge.configure(bg="#fee2e2", fg="#b91c1c")
            self.detail_var.set("真实串口模式：固定由INO执行本地PID，并要求物理急停。")
        else:
            self.backend_badge_var.set("真实模式｜Python 直接 USB-CAN")
            self.backend_badge.configure(bg="#fee2e2", fg="#b91c1c")
            self.detail_var.set("真实 CAN 模式：请填写适配器对应的 interface/channel，不会失败后回退仿真。")

    def _backend_config_from_ui(self) -> BackendConfig:
        try:
            bitrate = int(self.can_bitrate_var.get().strip())
        except ValueError as exc:
            raise SettingsError("CAN bitrate 必须是整数") from exc
        return BackendConfig(
            backend=self.backend_var.get(),
            serial_port=self.serial_port_var.get().strip(),
            can_interface=self.can_interface_var.get().strip(),
            can_channel=self.can_channel_var.get().strip(),
            can_bitrate=bitrate,
            control_mode=self.control_mode_var.get(),
            feedback_timeout_s=0.5,
        ).validated()

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
                backend=self.backend_var.get(),
                serial_port=self.serial_port_var.get().strip(),
                can_interface=self.can_interface_var.get().strip(),
                can_channel=self.can_channel_var.get().strip(),
                can_bitrate=int(self.can_bitrate_var.get().strip()),
                control_mode=self.control_mode_var.get(),
                pixels_per_meter=float(self.pixels_per_meter_var.get().strip()),
                rpm_per_mps=float(self.rpm_per_mps_var.get().strip()),
                camera_axis_sign=int(self.camera_sign_var.get()),
                motor_axis_sign=int(self.motor_sign_var.get()),
                rpm_limit=int(self.rpm_limit_var.get().strip()),
                max_rpm_rate_per_s=float(self.rpm_rate_var.get().strip()),
            )
        except ValueError as exc:
            raise SettingsError("标定、方向、限幅、变化率和 CAN 波特率必须填写有效数字") from exc
        return settings.validated()

    def _constant_target_from_ui(self, settings: ControlSettings) -> tuple[float, int]:
        try:
            speed_mps = float(self.constant_speed_var.get().strip())
        except ValueError as exc:
            raise ControlInputError("定速目标必须填写数字，单位为 m/s") from exc
        if speed_mps == 0.0:
            raise ControlInputError("定速目标不能为 0；如需停车请点击“停止电机”")
        command_rpm = constant_speed_to_rpm(
            speed_mps,
            settings.rpm_per_mps,
            settings.motor_axis_sign,
            settings.rpm_limit,
        )
        return speed_mps, command_rpm

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
        self._save_current_settings()
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

    def apply_pid_tunings(self) -> None:
        if not self.motor.connected:
            messagebox.showwarning("尚未连接", "请先连接 Arduino 串口后端。")
            return
        if self.backend_var.get() != "arduino_serial":
            messagebox.showwarning("后端不支持", "在线 PID 调参仅用于 arduino_serial + driver_pid。")
            return
        try:
            kp, ki, kd = (
                float(self.pid_kp_var.get().strip()),
                float(self.pid_ki_var.get().strip()),
                float(self.pid_kd_var.get().strip()),
            )
        except ValueError:
            messagebox.showerror("PID 参数错误", "Kp、Ki、Kd 必须填写数字。")
            return
        if any(not math.isfinite(value) or value < 0.0 for value in (kp, ki, kd)):
            messagebox.showerror("PID 参数错误", "Kp、Ki、Kd 必须是非负有限数。")
            return
        try:
            self.motor.send_pid_tunings(kp, ki, kd)
        except SupervisorClientError as exc:
            self._trigger_fault(f"PID 参数发送失败: {exc}")
            return
        self.detail_var.set(f"已请求 Arduino 在线更新 PID：Kp={kp:g}, Ki={ki:g}, Kd={kd:g}。")

    def _save_current_settings(self) -> None:
        try:
            save_settings(self.settings)
        except AppConfigError as exc:
            self.detail_var.set(f"设置已应用，但持久化失败：{exc}")

    def connect_serial(self) -> None:
        if self.motor.connected:
            messagebox.showinfo("提示", "电机安全监督已经连接。")
            return
        try:
            config = self._backend_config_from_ui()
        except (SettingsError, MotorBackendError, ValueError) as exc:
            messagebox.showerror("后端配置无效", str(exc))
            return
        if config.backend != "virtual":
            warning = (
                "即将连接真实电机后端。\n\n"
                "独立监督进程只能处理 GUI 崩溃或心跳中断，不能保证 Windows、USB 或驱动整体失效时继续停车。\n\n"
                "请确认现场有可触达的物理急停，或电机驱动器已经配置通信超时自动停车。是否继续？"
            )
            if not messagebox.askyesno("真实电机安全确认", warning, icon="warning"):
                self.detail_var.set("用户取消真实后端连接，电机保持未连接状态。")
                return
        try:
            self.motor.connect(config)
            self.safety.serial_connected()
        except (SupervisorClientError, StateTransitionError, MotorBackendError) as exc:
            messagebox.showerror("电机后端连接失败", str(exc))
            return
        self.latest_telemetry = None
        try:
            self.settings = self._settings_from_ui()
            self._save_current_settings()
        except SettingsError:
            pass
        self.supervisor_state_var.set("CONNECTED_SAFE")
        if not self.vision.is_open:
            self.video_label.configure(
                image="",
                text="电机后端已连接。请在右侧“摄像头源”旁点击“打开”。",
            )
            self._photo = None
        if config.backend == "virtual":
            self.detail_var.set("虚拟 CAN 已连接并完成零速启动；当前不会驱动真实机器人。")
        else:
            self.detail_var.set("真实后端已连接，监督进程已先发送零速。等待新鲜反馈后再继续。")

    def disconnect_serial(self) -> None:
        stop_sent = self.motor.disconnect(send_stop=True)
        self.active_run_mode = None
        self.constant_command_rpm = 0
        self.vision.release()
        self.safety.disconnected("用户断开电机后端")
        self._reset_motion()
        self.supervisor_state_var.set("已关闭")
        self.video_label.configure(image="", text="电机后端已断开，系统保持零速安全状态")
        self._photo = None
        self.detail_var.set("已断开电机后端。" + ("断开前已请求并确认停车流程。" if stop_sent else "未确认停止命令已送达。"))

    @staticmethod
    def _probe_camera_indices(max_index: int = 5) -> list[str]:
        found: list[str] = []
        for index in range(max_index + 1):
            capture = cv2.VideoCapture(index)
            try:
                if capture.isOpened():
                    ok, _frame = capture.read()
                    if ok:
                        found.append(str(index))
            finally:
                capture.release()
        return found

    def scan_camera_sources(self) -> None:
        if self._camera_scan_running:
            return
        if self.vision.is_open:
            messagebox.showinfo("摄像头已打开", "当前摄像头正在使用，无需扫描。停止后可重新扫描其他摄像头。")
            return
        self._camera_scan_running = True
        self.detail_var.set("正在后台扫描摄像头 0～5，界面可以继续操作……")

        def worker() -> None:
            try:
                sources = self._probe_camera_indices()
                self._camera_scan_results.put((sources, None))
            except Exception as exc:  # OpenCV backend errors vary by Windows camera driver.
                self._camera_scan_results.put(([], str(exc)))

        threading.Thread(target=worker, name="camera-source-scan", daemon=True).start()

    def _consume_camera_scan_results(self) -> None:
        try:
            sources, error = self._camera_scan_results.get_nowait()
        except queue.Empty:
            return
        self._camera_scan_running = False
        current = self.camera_source_var.get().strip()
        choices = list(sources)
        if current and current not in choices:
            choices.append(current)
        self.camera_source_box.configure(values=tuple(choices))
        if error:
            self.detail_var.set(f"摄像头扫描失败：{error}。仍可手动填写编号、视频路径或网络地址。")
        elif sources:
            self.detail_var.set(f"扫描到摄像头：{', '.join(sources)}。请选择后点击旁边的“打开”。")
        else:
            self.detail_var.set("未扫描到可读取的摄像头；可手动填写视频文件路径或 RTSP/HTTP 地址。")

    def open_camera(self) -> None:
        if not self.motor.connected:
            messagebox.showwarning("操作顺序", "请先启动安全监督并连接电机后端；连接时会先发送零速。")
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
            f"后端：{self.backend_var.get()}\n"
            f"控制模式：{self.control_mode_var.get()}\n"
            f"摄像头：{source_text}\n"
            f"像素/米：{settings.pixels_per_meter}\n"
            f"RPM/(米/秒)：{settings.rpm_per_mps}\n"
            f"画面方向：{settings.camera_axis_sign:+d}\n"
            f"电机方向：{settings.motor_axis_sign:+d}\n"
            f"当前实际RPM：{telemetry.actual_rpm:+.1f}\n"
            f"当前相对速度：{solution.relative_speed_mps:+.3f} m/s\n"
            f"运动员估算速度：{solution.swimmer_speed_mps:+.3f} m/s\n"
            f"原始目标：{solution.raw_target_rpm:+.1f} RPM\n\n"
            "启动后请随时准备点击“停止电机”。真实模式还要求物理急停或驱动器通信超时可用。\n"
            "是否确认周围无人、方向正确并启动？"
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
            self.active_run_mode = "vision"
        except (StateTransitionError, ControlInputError, SupervisorClientError) as exc:
            self._trigger_fault(f"启动失败：{exc}")
            return
        self.detail_var.set("闭环已启动：APP 以 20 Hz 更新目标，独立监督进程以 10 ms 周期控制并执行 500 ms 失联停车。")

    def start_constant_speed(self) -> None:
        try:
            settings = self._settings_from_ui()
            speed_mps, command_rpm = self._constant_target_from_ui(settings)
        except (SettingsError, ControlInputError) as exc:
            messagebox.showerror("定速参数无效", str(exc))
            return

        inputs = self._safety_inputs(settings)
        blockers = inputs.constant_speed_blockers()
        if blockers:
            messagebox.showwarning("尚不能启动定速巡航", "请先处理以下问题：\n\n- " + "\n- ".join(blockers))
            return
        telemetry = self.latest_telemetry
        if telemetry is None:
            messagebox.showwarning("尚不能启动定速巡航", "尚未收到电机实际转速反馈。")
            return

        confirmation = (
            "强电机定速启动确认\n\n"
            f"后端：{self.backend_var.get()}\n"
            f"目标线速度：{speed_mps:+.3f} m/s\n"
            f"换算目标：{command_rpm:+d} RPM\n"
            f"RPM/(米/秒)：{settings.rpm_per_mps}\n"
            f"电机方向：{settings.motor_axis_sign:+d}\n"
            f"当前实际RPM：{telemetry.actual_rpm:+.1f}\n\n"
            "启动后系统将持续发送同一速度目标，直到点击“停止电机”或安全保护触发。\n"
            "请确认运动方向、轨道区域、限位和物理急停均正常，是否启动？"
        )
        if not messagebox.askyesno("确认启动定速巡航", confirmation, icon="warning"):
            self.detail_var.set("用户取消定速启动，电机保持停止。")
            return

        try:
            if self.vision.is_open:
                self.vision.release()
                self.safety.camera_closed()
            self._reset_motion()
            self.settings = settings
            self.rate_limiter = RpmRateLimiter(settings.max_rpm_rate_per_s)
            self.safety.start_constant_speed(inputs)
            self.constant_command_rpm = command_rpm
            self.motor.send_target_rpm(0)
            self.motor.send_start()
            self.last_command_rpm = 0
            self.active_run_mode = "constant"
            self.video_label.configure(
                image="",
                text=f"定速巡航运行中\n目标 {speed_mps:+.3f} m/s / {command_rpm:+d} RPM\n点击“停止电机”结束",
            )
            self._photo = None
        except (StateTransitionError, ControlInputError, SupervisorClientError) as exc:
            self._trigger_fault(f"定速启动失败：{exc}")
            return
        self.detail_var.set(
            f"定速巡航已启动：目标 {speed_mps:+.3f} m/s（{command_rpm:+d} RPM），将保持到手动停止。"
        )

    def manual_stop(self) -> None:
        stopped_mode = self.active_run_mode
        fault_remains_latched = self.safety.state is AppState.FAULT
        stop_sent = False
        if self.motor.connected:
            try:
                self.motor.send_stop()
                stop_sent = True
            except SupervisorClientError as exc:
                self.detail_var.set(f"停止命令发送失败：{exc}；请立即使用物理急停并检查设备。")
        self.safety.manual_stop()
        self.active_run_mode = None
        self.constant_command_rpm = 0
        self.vision.release()
        self._reset_motion()
        stop_text = (
            "定速巡航已停止。可修改速度后再次启动。"
            if stopped_mode == "constant"
            else "电机已请求停止。请重新打开摄像头并框选目标。"
        )
        self.video_label.configure(image="", text=stop_text)
        self._photo = None
        if fault_remains_latched:
            delivery = "已再次发送停止命令。" if stop_sent else "停止命令未确认送达，请使用物理急停。"
            self.detail_var.set(f"{delivery} 故障仍保持锁定，请点击“确认故障并复位”。")
        elif stop_sent and stopped_mode == "constant":
            self.detail_var.set("定速巡航已停止。可修改速度后再次启动，或切换到视觉跟随。")
        elif stop_sent:
            self.detail_var.set("已发送停止命令。重新启动视觉跟随前必须重新打开摄像头并框选运动员。")

    def acknowledge_fault(self) -> None:
        if self.safety.state is not AppState.FAULT:
            messagebox.showinfo("提示", "当前没有待确认故障。")
            return
        try:
            if self.motor.connected:
                self.motor.reset_fault()
            self.safety.acknowledge_fault()
        except (StateTransitionError, SupervisorClientError) as exc:
            messagebox.showerror("故障复位失败", str(exc))
            return
        if not self.motor.connected:
            self.safety.disconnected("故障确认后电机后端仍未连接")
        self.active_run_mode = None
        self.constant_command_rpm = 0
        self.vision.release()
        self._reset_motion()
        self._fault_popup_shown = False
        self.video_label.configure(image="", text="故障已确认。可重新启动定速巡航，或打开摄像头进行视觉跟随。")
        self._photo = None
        self.detail_var.set("故障已确认，电机保持停止；下一次运行仍需重新人工确认。")

    def _camera_tick(self) -> None:
        if self._closing:
            return
        if self.vision.is_open:
            try:
                frame, measurement = self.vision.read()
                if measurement is not None:
                    self._accept_measurement(measurement)
                    if abs(measurement.offset_px) > measurement.frame_width * self.settings.max_offset_fraction:
                        if self.safety.state is AppState.RUNNING and self.active_run_mode == "vision":
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
                if self.safety.state is AppState.RUNNING and self.active_run_mode == "vision":
                    self._trigger_fault(str(exc))
                else:
                    try:
                        self.safety.target_cleared()
                    except StateTransitionError:
                        pass
                    self._reset_motion()
                    self.detail_var.set(str(exc))
            except VisionRuntimeError as exc:
                if self.safety.state is AppState.RUNNING and self.active_run_mode == "vision":
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
            if self.safety.state is AppState.RUNNING and self.active_run_mode == "vision":
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
            if self.safety.state is AppState.RUNNING and self.active_run_mode == "vision":
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
                if self.active_run_mode == "constant":
                    robot_speed = (
                        self.settings.motor_axis_sign
                        * event.telemetry.actual_rpm
                        / self.settings.rpm_per_mps
                    )
                    self.robot_speed_var.set(f"{robot_speed:+.3f} m/s")
            elif event.kind == "status":
                self.supervisor_state_var.set(event.message or "--")
            elif event.kind == "error":
                self._trigger_fault(event.message)
            elif event.kind in ("notice", "warning"):
                self.detail_var.set(event.message)
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
                target_rpm: int | None = None
                suffix = ""
                if self.active_run_mode == "constant":
                    target_rpm = self.constant_command_rpm
                    suffix = "（定速）"
                elif self.active_run_mode == "vision" and self.latest_solution is not None:
                    target_rpm = self.latest_solution.command_rpm
                    suffix = "（已限幅）" if self.latest_solution.saturated else "（视觉）"
                if target_rpm is not None:
                    try:
                        limited = self.rate_limiter.update(target_rpm, now)
                        command = max(-self.settings.rpm_limit, min(self.settings.rpm_limit, int(round(limited))))
                        self.motor.send_target_rpm(command)
                        self.last_command_rpm = command
                        self.target_rpm_var.set(f"{command:+d} RPM {suffix}")
                    except (ControlInputError, SupervisorClientError) as exc:
                        self._trigger_fault(f"控制命令发送失败：{exc}")
        interval_ms = max(10, int(round(self.settings.command_interval_s * 1000)))
        self.root.after(interval_ms, self._control_tick)

    def _runtime_fault_reason(self, now: float) -> str | None:
        if not self.motor.connected:
            return "运行中电机监督进程断开"
        telemetry = self.latest_telemetry
        if telemetry is None or now - telemetry.received_at > self.settings.telemetry_timeout_s:
            return "电机反馈超时"
        if not self.calibration.is_confirmed_for(self.settings):
            return "标定确认失效"
        if self.active_run_mode == "constant":
            return None
        if self.active_run_mode != "vision":
            return "运行模式无效"
        measurement = self.latest_measurement
        if measurement is None or now - measurement.timestamp > self.settings.vision_timeout_s:
            return "视觉相对位移测量超时"
        if not self.vision.target_locked:
            return "目标跟踪丢失"
        if self.latest_estimate is None or not self.latest_estimate.ready or self.latest_solution is None:
            return "运动速度解算失效"
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
            real_backend=self.motor.is_real,
        )

    def _trigger_fault(self, reason: str) -> None:
        first_fault = self.safety.fault(reason)
        stop_sent = False
        if self.motor.connected:
            try:
                self.motor.send_stop()
                stop_sent = True
            except SupervisorClientError:
                stop_sent = False
        self.vision.clear_target()
        self.rate_limiter.reset()
        self.estimator = None
        self.latest_solution = None
        if first_fault:
            delivery = "已发送停止命令。" if stop_sent else "停止命令未确认送达，请立即使用物理急停。"
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
        self._consume_camera_scan_results()
        state = self.safety.state
        self.state_var.set(STATE_LABELS[state])
        foreground, background = STATE_COLORS[state]
        self.banner.configure(fg=foreground, bg=background)

        if state is AppState.DISCONNECTED:
            message = "未连接：请选择控制后端；默认虚拟模式不会驱动真实机器人。"
        elif state is AppState.STOPPED:
            message = "电机已停止：可输入速度启动定速巡航，或打开摄像头进行视觉跟随。"
        elif state is AppState.CAMERA_READY:
            message = "摄像头已就绪：请手动框选游泳运动员。"
        elif state is AppState.TARGET_LOCKED:
            blockers = self._safety_inputs().start_blockers()
            message = "目标已锁定，可以启动。" if not blockers else "尚不能启动：" + "；".join(blockers)
        elif state is AppState.RUNNING:
            backend_mode = "真实" if self.motor.is_real else "仿真"
            run_mode = "定速巡航" if self.active_run_mode == "constant" else "视觉跟随"
            message = f"{backend_mode}{run_mode}运行中：当前发送 {self.last_command_rpm:+d} RPM；保持准备随时停止。"
        else:
            message = f"故障锁定：{self.safety.fault_reason or '未知故障'}；电机已请求停止。"
        self.banner_var.set(message)

        now = time.monotonic()
        if self.latest_telemetry is None:
            self.feedback_age_var.set("-- ms")
        else:
            age_ms = max(0.0, (now - self.latest_telemetry.received_at) * 1000.0)
            self.feedback_age_var.set(f"{age_ms:.0f} ms")

        constant_settings: ControlSettings | None = None
        constant_valid = False
        try:
            constant_settings = self._settings_from_ui()
            speed_mps, preview_rpm = self._constant_target_from_ui(constant_settings)
            self.constant_rpm_preview_var.set(f"{preview_rpm:+d} RPM（{speed_mps:+.3f} m/s）")
            constant_valid = True
        except (SettingsError, ControlInputError):
            self.constant_rpm_preview_var.set("请输入有效的非零速度")

        self.connect_button.configure(state="disabled" if self.motor.connected else "normal")
        self.disconnect_button.configure(state="normal" if self.motor.connected else "disabled")
        self.open_camera_button.configure(
            state="normal"
            if self.motor.connected and state not in (AppState.RUNNING, AppState.FAULT)
            else "disabled"
        )
        self.scan_camera_button.configure(
            state="disabled"
            if self._camera_scan_running or self.vision.is_open or state in (AppState.RUNNING, AppState.FAULT)
            else "normal"
        )
        self.select_target_button.configure(
            state="normal" if self.vision.is_open and state is AppState.CAMERA_READY else "disabled"
        )
        start_ready = state is AppState.TARGET_LOCKED and not self._safety_inputs().start_blockers()
        self.start_button.configure(state="normal" if start_ready else "disabled")
        self.stop_button.configure(state="normal" if self.motor.connected else "disabled")
        constant_ready = False
        if constant_valid and constant_settings is not None:
            constant_ready = (
                state in (AppState.STOPPED, AppState.CAMERA_READY, AppState.TARGET_LOCKED)
                and not self._safety_inputs(constant_settings).constant_speed_blockers()
            )
        self.start_constant_button.configure(state="normal" if constant_ready else "disabled")
        self.constant_stop_button.configure(state="normal" if self.motor.connected else "disabled")
        self.constant_speed_entry.configure(
            state="disabled" if state in (AppState.RUNNING, AppState.FAULT) else "normal"
        )
        self.ack_fault_button.configure(state="normal" if state is AppState.FAULT else "disabled")
        self.confirm_calibration_button.configure(
            state="disabled" if state in (AppState.RUNNING, AppState.FAULT) else "normal"
        )
        pid_ready = (
            self.motor.connected
            and self.backend_var.get() == "arduino_serial"
            and state is not AppState.FAULT
        )
        self.apply_pid_button.configure(state="normal" if pid_ready else "disabled")
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
            messagebox.showwarning("停止未确认", "未确认停止命令送达，请立即使用物理急停并检查设备。")
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    SwimControlApp().run()


if __name__ == "__main__":
    main()
