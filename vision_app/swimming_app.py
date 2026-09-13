from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from vision_app.app_config import AppConfigError, load_settings, save_settings
from vision_app.frame_processing import FrameProcessor
from vision_app.frame_renderer import FrameRenderer
from vision_app.frame_source import FrameSample, FrameSource, FrameSourceError
from vision_app.motion_control import FollowMode, MotionControlConfig, MotionControlError, MotionController, MotionSetpoint
from vision_app.motor_backend import MotorBackendError
from vision_app.motor_gateway import MotorCommandGateway
from vision_app.motor_supervisor import BackendConfig
from vision_app.safety import AppState, SafetyController, SafetyInputs, StateTransitionError
from vision_app.settings import CalibrationConfirmation, ControlSettings, SettingsError
from vision_app.supervisor_client import SupervisorClientError
from vision_app.target_tracking import TargetObservation, TargetSelectionCancelled, TargetTracker, TargetTrackingError, TrackingLostError


FOLLOW_MODES = {FollowMode.POSITION.value, FollowMode.VELOCITY_ESTIMATE.value}
MODE_LABELS = {
    "manual_rpm": "手动 RPM", "manual_speed": "手动线速度",
    "position_follow": "位置比例跟随", "velocity_estimate_follow": "速度估算跟随",
}
STATE_LABELS = {
    AppState.DISCONNECTED: "未连接", AppState.STOPPED: "已停止",
    AppState.CAMERA_READY: "摄像头就绪", AppState.TARGET_LOCKED: "目标已锁定",
    AppState.RUNNING: "运行中", AppState.FAULT: "故障锁定",
}


class SwimControlApp:
    """GUI composition root; calculations and device I/O stay in their layers."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("swimmer_Tracker · TCP 分层版")
        self.root.geometry("1420x900")
        self.root.minsize(1120, 720)
        self.gateway = MotorCommandGateway()
        self.motor = self.gateway  # compatibility alias
        self.frame_source, self.frame_processor = FrameSource(), FrameProcessor()
        self.target_tracker, self.renderer = TargetTracker(), FrameRenderer()
        self.safety, self.calibration = SafetyController(), CalibrationConfirmation()
        self.motion_controller: MotionController | None = None
        self.latest_sample: FrameSample | None = None
        self.latest_observation: TargetObservation | None = None
        self.latest_motion: MotionSetpoint | None = None
        self.latest_measured_rpm: float | None = None
        self._photo = None
        self._closing = self._fault_popup_shown = self._scan_running = False
        self._scan_results: queue.Queue[tuple[list[str], str | None]] = queue.Queue()
        try:
            self.settings, warning = load_settings(), None
        except AppConfigError as exc:
            self.settings, warning = ControlSettings().validated(), str(exc)
        self._make_variables()
        self._build_ui()
        self._install_traces()
        self._on_backend_selected(); self._on_mode_selected()
        if warning: self.detail_var.set(warning + "；已使用安全默认值。")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(30, self._camera_tick)
        self.root.after(50, self._poll_motor_events)
        self.root.after(50, self._control_tick)
        self.root.after(100, self._refresh_status)

    def _make_variables(self) -> None:
        s = self.settings
        values = {
            "backend": s.backend, "tcp_host": s.tcp_host, "tcp_port": s.tcp_port,
            "camera_source": "0", "operation_mode": s.operation_mode,
            "manual_rpm": 0, "manual_speed": 0.0, "pixels_per_meter": s.pixels_per_meter,
            "rpm_per_mps": s.rpm_per_mps, "position_kp": s.position_kp,
            "camera_sign": f"{s.camera_axis_sign:+d}", "motor_sign": f"{s.motor_axis_sign:+d}",
            "target_offset": s.target_offset_px, "deadband": s.deadband_m,
            "max_speed": s.max_speed_mps, "rpm_limit": s.rpm_limit,
            "rpm_rate": s.max_rpm_rate_per_s, "window_size": s.displacement_window_size,
            "window_time": s.displacement_window_s,
        }
        for name, value in values.items(): setattr(self, f"{name}_var", tk.StringVar(value=str(value)))
        self.advanced_visible = tk.BooleanVar(value=False)
        displays = {
            "state": STATE_LABELS[self.safety.state], "banner": "未连接：virtual 不驱动真实设备。",
            "detail": "请配置后端并连接。", "backend_badge": "", "supervisor": "未启动",
            "offset": "-- px / -- m", "expected_speed": "-- m/s", "raw_rpm": "-- RPM",
            "sent_rpm": "0 RPM", "estimated_speed": "0.000 m/s（指令估算）",
            "feedback": "无设备反馈", "calibration": "未确认",
        }
        for name, value in displays.items(): setattr(self, f"{name}_var", tk.StringVar(value=value))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12); outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=3); outer.columnconfigure(1, weight=2); outer.rowconfigure(2, weight=1)
        ttk.Label(outer, text="swimmer_Tracker", font=("Microsoft YaHei UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(outer, textvariable=self.state_var, font=("Microsoft YaHei UI", 12, "bold")).grid(row=0, column=1, sticky="e")
        self.banner = tk.Label(outer, textvariable=self.banner_var, anchor="w", padx=10, pady=8)
        self.banner.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 10))
        left = ttk.Frame(outer); left.grid(row=2, column=0, sticky="nsew", padx=(0, 12)); left.columnconfigure(0, weight=1); left.rowconfigure(0, weight=1)
        self.video_label = tk.Label(left, text="请连接后打开摄像头", bg="#0f172a", fg="#e2e8f0", font=("Microsoft YaHei UI", 14))
        self.video_label.grid(row=0, column=0, sticky="nsew")
        metrics = ttk.LabelFrame(left, text="分层控制实时状态", padding=8); metrics.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        items = [("目标偏差", self.offset_var), ("期望线速度", self.expected_speed_var), ("换算前 RPM", self.raw_rpm_var),
                 ("实际发送 RPM", self.sent_rpm_var), ("机器人速度", self.estimated_speed_var), ("设备反馈", self.feedback_var)]
        for i, (label, variable) in enumerate(items):
            row, group = divmod(i, 3)
            ttk.Label(metrics, text=label).grid(row=row, column=group * 2, sticky="w", padx=(0, 6), pady=3)
            ttk.Label(metrics, textvariable=variable, font=("Consolas", 10, "bold")).grid(row=row, column=group * 2 + 1, sticky="w", padx=(0, 14), pady=3)
        host = ttk.Frame(outer); host.grid(row=2, column=1, sticky="nsew"); host.columnconfigure(0, weight=1); host.rowconfigure(0, weight=1)
        canvas = tk.Canvas(host, highlightthickness=0); scroll = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set); canvas.grid(row=0, column=0, sticky="nsew"); scroll.grid(row=0, column=1, sticky="ns")
        panel = ttk.Frame(canvas); window = canvas.create_window((0, 0), window=panel, anchor="nw")
        panel.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width)); panel.columnconfigure(0, weight=1)
        connection = ttk.LabelFrame(panel, text="1. 电机与画面连接", padding=10); connection.grid(row=0, column=0, sticky="ew"); connection.columnconfigure(1, weight=1)
        self.backend_badge = tk.Label(connection, textvariable=self.backend_badge_var, padx=6, pady=4); self.backend_badge.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 7))
        self._combo_row(connection, 1, "后端", self.backend_var, ("virtual", "tcp"), self._on_backend_selected)
        self._entry_row(connection, 2, "TCP IP", self.tcp_host_var); self._entry_row(connection, 3, "TCP 端口", self.tcp_port_var)
        ttk.Label(connection, text="摄像头源").grid(row=4, column=0, sticky="w", pady=3)
        self.camera_source_box = ttk.Combobox(connection, textvariable=self.camera_source_var, values=("0",)); self.camera_source_box.grid(row=4, column=1, sticky="ew", padx=(8, 0))
        self.scan_camera_button = ttk.Button(connection, text="扫描", width=6, command=self.scan_camera_sources); self.scan_camera_button.grid(row=4, column=2, padx=(5, 0))
        buttons = ttk.Frame(connection); buttons.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        for column in range(3): buttons.columnconfigure(column, weight=1)
        self.connect_button = ttk.Button(buttons, text="连接", command=self.connect_motor); self.connect_button.grid(row=0, column=0, sticky="ew")
        self.disconnect_button = ttk.Button(buttons, text="断开", command=self.disconnect_motor); self.disconnect_button.grid(row=0, column=1, sticky="ew", padx=5)
        self.open_camera_button = ttk.Button(buttons, text="打开画面", command=self.open_camera); self.open_camera_button.grid(row=0, column=2, sticky="ew")
        ttk.Label(connection, text="监督进程").grid(row=6, column=0, sticky="w", pady=(6, 0)); ttk.Label(connection, textvariable=self.supervisor_var).grid(row=6, column=1, columnspan=2, sticky="e")
        control = ttk.LabelFrame(panel, text="2. 模式与基础参数", padding=10); control.grid(row=1, column=0, sticky="ew", pady=(8, 0)); control.columnconfigure(1, weight=1)
        self._combo_row(control, 0, "运行模式", self.operation_mode_var, tuple(MODE_LABELS), self._on_mode_selected)
        for row, item in enumerate((("手动 RPM", self.manual_rpm_var), ("手动速度 m/s", self.manual_speed_var), ("像素/米", self.pixels_per_meter_var),
                                    ("RPM/(m/s)", self.rpm_per_mps_var), ("位置 P 增益", self.position_kp_var)), 1): self._entry_row(control, row, *item)
        ttk.Label(control, text="标定状态").grid(row=6, column=0, sticky="w"); ttk.Label(control, textvariable=self.calibration_var).grid(row=6, column=1, sticky="e")
        ttk.Button(control, text="应用并确认参数", command=self.confirm_settings).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        advanced = ttk.LabelFrame(panel, text="3. 高级参数", padding=10); advanced.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(advanced, text="展开高级参数", variable=self.advanced_visible, command=self._toggle_advanced).pack(anchor="w")
        self.advanced_frame = ttk.Frame(advanced); self.advanced_frame.columnconfigure(1, weight=1)
        fields = (("相机方向", self.camera_sign_var), ("电机方向", self.motor_sign_var), ("目标偏移 px", self.target_offset_var),
                  ("死区 m", self.deadband_var), ("最大速度 m/s", self.max_speed_var), ("RPM 上限", self.rpm_limit_var),
                  ("RPM变化率/秒", self.rpm_rate_var), ("估算窗口样本", self.window_size_var), ("估算窗口秒", self.window_time_var))
        for row, item in enumerate(fields): self._entry_row(self.advanced_frame, row, *item)
        actions = ttk.LabelFrame(panel, text="4. 操作", padding=10); actions.grid(row=3, column=0, sticky="ew", pady=(8, 0)); actions.columnconfigure(0, weight=1)
        self.select_target_button = ttk.Button(actions, text="框选 CSRT 目标", command=self.select_target)
        self.start_button = ttk.Button(actions, text="确认风险并启动", command=self.start_control)
        self.stop_button = ttk.Button(actions, text="停止电机", command=self.manual_stop)
        self.ack_fault_button = ttk.Button(actions, text="确认故障并复位", command=self.acknowledge_fault)
        for row, button in enumerate((self.select_target_button, self.start_button, self.stop_button, self.ack_fault_button)): button.grid(row=row, column=0, sticky="ew", pady=(0 if row == 0 else 5, 0))
        ttk.Label(panel, textvariable=self.detail_var, wraplength=390, foreground="#475569").grid(row=4, column=0, sticky="ew", pady=(8, 0))

    @staticmethod
    def _entry_row(parent, row, label, variable) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3); ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=3)

    @staticmethod
    def _combo_row(parent, row, label, variable, values, callback) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        box = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly"); box.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=3); box.bind("<<ComboboxSelected>>", callback)

    def _install_traces(self) -> None:
        for variable in (self.pixels_per_meter_var, self.rpm_per_mps_var, self.position_kp_var, self.camera_sign_var, self.motor_sign_var,
                         self.target_offset_var, self.deadband_var, self.max_speed_var, self.rpm_limit_var, self.rpm_rate_var, self.window_size_var, self.window_time_var):
            variable.trace_add("write", self._on_control_parameter_edited)

    def _toggle_advanced(self) -> None:
        self.advanced_frame.pack(fill="x", pady=(7, 0)) if self.advanced_visible.get() else self.advanced_frame.pack_forget()

    def _on_backend_selected(self, _event=None) -> None:
        real = self.backend_var.get() == "tcp"
        self.backend_badge_var.set("真实 TCP｜无设备反馈" if real else "virtual｜不会驱动真实设备")
        self.backend_badge.configure(bg="#fee2e2" if real else "#dbeafe", fg="#b91c1c" if real else "#1d4ed8")

    def _on_mode_selected(self, _event=None) -> None:
        if self.safety.state is AppState.RUNNING: self._trigger_fault("运行中切换了控制模式"); return
        self._reset_control_history(clear_target=False)
        self.detail_var.set(f"已选择：{MODE_LABELS.get(self.operation_mode_var.get(), '未知模式')}。")

    def _on_control_parameter_edited(self, *_args) -> None:
        if self._closing: return
        was_confirmed = self.calibration.confirmed; self.calibration.invalidate(); self.calibration_var.set("未确认")
        if self.safety.state is AppState.RUNNING: self._trigger_fault("运行中修改了控制参数")
        elif was_confirmed: self.detail_var.set("控制参数已修改，请重新确认。")

    def _settings_from_ui(self) -> ControlSettings:
        try:
            mode = self.operation_mode_var.get()
            return replace(self.settings, backend=self.backend_var.get(), tcp_host=self.tcp_host_var.get().strip(), tcp_port=int(self.tcp_port_var.get()),
                operation_mode=mode, follow_mode=mode if mode in FOLLOW_MODES else self.settings.follow_mode,
                pixels_per_meter=float(self.pixels_per_meter_var.get()), rpm_per_mps=float(self.rpm_per_mps_var.get()), position_kp=float(self.position_kp_var.get()),
                camera_axis_sign=int(self.camera_sign_var.get()), motor_axis_sign=int(self.motor_sign_var.get()), target_offset_px=float(self.target_offset_var.get()),
                deadband_m=float(self.deadband_var.get()), max_speed_mps=float(self.max_speed_var.get()), rpm_limit=int(self.rpm_limit_var.get()),
                max_rpm_rate_per_s=float(self.rpm_rate_var.get()), displacement_window_size=int(self.window_size_var.get()), displacement_window_s=float(self.window_time_var.get())).validated()
        except (ValueError, TypeError) as exc: raise SettingsError("参数必须填写有效数字") from exc

    @staticmethod
    def _motion_config(s: ControlSettings) -> MotionControlConfig:
        return MotionControlConfig(mode=s.follow_mode, pixels_per_meter=s.pixels_per_meter, camera_axis_sign=s.camera_axis_sign,
            target_offset_px=s.target_offset_px, position_kp=s.position_kp, deadband_m=s.deadband_m, max_speed_mps=s.max_speed_mps,
            rpm_per_mps=s.rpm_per_mps, motor_axis_sign=s.motor_axis_sign, estimator_window_size=s.displacement_window_size,
            estimator_window_s=s.displacement_window_s, max_offset_fraction=s.max_offset_fraction).validated()

    def confirm_settings(self) -> None:
        if self.safety.state in (AppState.RUNNING, AppState.FAULT): messagebox.showwarning("不能修改", "请先停止并处理故障。"); return
        try: settings = self._settings_from_ui(); self._motion_config(settings)
        except (SettingsError, MotionControlError) as exc: messagebox.showerror("参数无效", str(exc)); return
        if not messagebox.askyesno("确认标定", "确认换算、方向、限幅和控制参数已经核对？"): return
        self.settings = settings; self.calibration.confirm(settings); self.calibration_var.set("已确认")
        self.motion_controller = MotionController(self._motion_config(settings)); self.gateway.configure_rate_limit(settings.max_rpm_rate_per_s)
        try: save_settings(settings)
        except AppConfigError as exc: self.detail_var.set(f"参数已应用但保存失败：{exc}"); return
        self.detail_var.set("参数已确认并保存。")

    def connect_motor(self) -> None:
        if self.gateway.connected: return
        try:
            settings = self._settings_from_ui(); config = BackendConfig(backend=settings.backend, tcp_host=settings.tcp_host, tcp_port=settings.tcp_port).validated()
        except (SettingsError, MotorBackendError) as exc: messagebox.showerror("连接配置无效", str(exc)); return
        if settings.backend == "tcp" and not messagebox.askyesno("真实 TCP 控制确认", "TCP 第一版没有实际转速和驱动故障反馈。\nAPP 无法检测堵转或实际速度偏差。\n\n请确认物理急停和下位机失联停车可用。", icon="warning"): return
        try: self.gateway.connect(config); self.safety.serial_connected()
        except (SupervisorClientError, MotorBackendError, StateTransitionError) as exc: messagebox.showerror("连接失败", str(exc)); return
        self.settings = settings; self.feedback_var.set("无设备反馈" if settings.backend == "tcp" else "等待仿真反馈")
        self.detail_var.set("TCP 已连接并发送 P、T0。" if settings.backend == "tcp" else "virtual 已连接。")

    connect_serial = connect_motor

    def disconnect_motor(self) -> None:
        real = self.settings.backend == "tcp"; self.gateway.close(); self.frame_source.close(); self.target_tracker.clear()
        self.safety.disconnected("用户断开电机"); self._reset_control_history(); self.supervisor_var.set("已关闭")
        self.detail_var.set("已发送停车命令并断开；实际停止未反馈。" if real else "已停车并断开 virtual。")

    disconnect_serial = disconnect_motor

    def scan_camera_sources(self) -> None:
        if self._scan_running: return
        self._scan_running = True
        def worker():
            try: self._scan_results.put((FrameSource.scan(), None))
            except Exception as exc: self._scan_results.put(([], str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _consume_camera_scan_results(self) -> None:
        try: values, error = self._scan_results.get_nowait()
        except queue.Empty: return
        self._scan_running = False
        if error: self.detail_var.set(f"摄像头扫描失败：{error}"); return
        current = self.camera_source_var.get().strip(); merged = list(values)
        if current and current not in merged: merged.append(current)
        self.camera_source_box.configure(values=tuple(merged or ["0"])); self.detail_var.set("可用摄像头：" + (", ".join(values) if values else "未发现"))

    def open_camera(self) -> None:
        if not self.gateway.connected: messagebox.showwarning("尚未连接", "请先连接电机后端。"); return
        try: self.latest_sample = self.frame_source.open(self.camera_source_var.get()); self.target_tracker.clear(); self.safety.camera_opened()
        except (FrameSourceError, StateTransitionError) as exc: messagebox.showerror("摄像头错误", str(exc)); return
        self.detail_var.set("第五层已接收画面，第四层当前原样透传。")

    def select_target(self) -> None:
        if self.latest_sample is None: messagebox.showwarning("没有画面", "请先打开摄像头。"); return
        try:
            observation = self.target_tracker.select(self.latest_sample); settings = self._settings_from_ui()
            self.motion_controller = MotionController(self._motion_config(settings)); self.latest_observation = observation
            self.latest_motion = self.motion_controller.compute(observation, self.gateway.commanded_rpm_estimate); self.safety.target_locked()
        except TargetSelectionCancelled as exc: self.detail_var.set(str(exc)); return
        except (TargetTrackingError, SettingsError, MotionControlError, StateTransitionError) as exc: messagebox.showerror("框选失败", str(exc)); return
        self.detail_var.set("CSRT 目标已锁定，运动控制历史已重置。")

    def start_control(self) -> None:
        try: settings = self._settings_from_ui()
        except SettingsError as exc: messagebox.showerror("参数无效", str(exc)); return
        if not self.gateway.connected: messagebox.showwarning("尚不能启动", "电机后端未连接。"); return
        if not self.calibration.is_confirmed_for(settings): messagebox.showwarning("尚不能启动", "请先应用并确认参数。"); return
        follow = settings.operation_mode in FOLLOW_MODES
        if follow and (not self.frame_source.is_open or not self.target_tracker.locked): messagebox.showwarning("尚不能启动", "视觉模式需要打开摄像头并框选目标。"); return
        if self.frame_source.source and self.frame_source.source.offline_file and settings.backend == "tcp": messagebox.showwarning("禁止启动", "本地视频禁止驱动真实 TCP 电机。"); return
        warning = f"将启动 {MODE_LABELS[settings.operation_mode]}。" + ("\n\n当前无实际转速反馈，确认物理急停可用。" if settings.backend == "tcp" else "")
        if not messagebox.askyesno("启动确认", warning, icon="warning"): return
        try:
            inputs = self._safety_inputs(settings); self.safety.start(inputs) if follow else self.safety.start_constant_speed(inputs)
            self.settings = settings; self.gateway.configure_rate_limit(settings.max_rpm_rate_per_s); self.gateway.start()
        except (StateTransitionError, SupervisorClientError) as exc: self._trigger_fault(f"启动失败：{exc}"); return
        self.detail_var.set("控制已启动；期望目标按设定周期更新。")

    def manual_stop(self) -> None:
        if self.gateway.connected:
            try: self.gateway.stop()
            except SupervisorClientError as exc: self.detail_var.set(f"停车发送失败：{exc}")
        self.safety.manual_stop(); self.frame_source.close(); self.target_tracker.clear(); self._reset_control_history()
        self.detail_var.set("停车命令已发送，实际停止未反馈。" if self.settings.backend == "tcp" else "virtual 已停车。")

    def acknowledge_fault(self) -> None:
        if self.safety.state is not AppState.FAULT: return
        try:
            if self.gateway.connected: self.gateway.reset_fault()
            self.safety.acknowledge_fault()
        except (SupervisorClientError, StateTransitionError) as exc: messagebox.showerror("复位失败", str(exc)); return
        self._fault_popup_shown = False; self._reset_control_history(); self.detail_var.set("故障已确认，电机保持停止。")

    def _camera_tick(self) -> None:
        if self._closing: return
        if self.frame_source.is_open:
            try:
                sample = self.frame_processor.process(self.frame_source.read()); observation = self.target_tracker.update(sample)
                self.latest_sample, self.latest_observation = sample, observation
                if observation is not None and self.motion_controller is not None:
                    self.latest_motion = self.motion_controller.compute(observation, self.gateway.commanded_rpm_estimate); self._show_motion(self.latest_motion)
                    if self.latest_motion.outside_safe_region: raise TrackingLostError("目标偏差超过安全区域")
                self._render_image(self.renderer.render(sample, observation, target_offset_px=self.settings.target_offset_px, max_offset_fraction=self.settings.max_offset_fraction))
            except (FrameSourceError, TrackingLostError, TargetTrackingError, MotionControlError) as exc:
                if self.safety.state is AppState.RUNNING:
                    self._trigger_fault(str(exc))
                else:
                    if not self.target_tracker.locked:
                        try: self.safety.target_cleared()
                        except StateTransitionError: pass
                    self.detail_var.set(str(exc))
        self.root.after(30, self._camera_tick)

    def _show_motion(self, motion: MotionSetpoint) -> None:
        self.offset_var.set(f"{motion.error_px:+.1f} px / {motion.error_m:+.3f} m")
        self.expected_speed_var.set("样本收集中" if motion.expected_speed_mps is None else f"{motion.expected_speed_mps:+.3f} m/s")

    def _control_tick(self) -> None:
        if self._closing: return
        if self.safety.state is AppState.RUNNING:
            reason = self._runtime_fault_reason(time.monotonic())
            if reason: self._trigger_fault(reason)
            else:
                try:
                    s, mode = self.settings, self.settings.operation_mode
                    if mode == "manual_rpm": raw = float(self.manual_rpm_var.get()); command = self.gateway.set_expected_rpm(raw, s.rpm_limit)
                    else:
                        if mode == "manual_speed": speed = float(self.manual_speed_var.get())
                        else:
                            if self.latest_motion is None or not self.latest_motion.ready or self.latest_motion.expected_speed_mps is None: raise MotionControlError("运动控制结果未就绪")
                            speed = self.latest_motion.expected_speed_mps
                        raw, command = self.gateway.set_expected_speed(speed, s.rpm_per_mps, s.motor_axis_sign, s.rpm_limit)
                    self.raw_rpm_var.set(f"{raw:+.1f} RPM"); self.sent_rpm_var.set(f"{command:+d} RPM")
                    estimated_speed = self.gateway.estimated_speed_mps(s.rpm_per_mps, s.motor_axis_sign)
                    self.estimated_speed_var.set(f"{estimated_speed:+.3f} m/s（指令估算）")
                except (ValueError, MotionControlError, SupervisorClientError, MotorBackendError) as exc: self._trigger_fault(f"控制命令失败：{exc}")
        self.root.after(max(10, int(self.settings.command_interval_s * 1000)), self._control_tick)

    def _runtime_fault_reason(self, now: float) -> str | None:
        if not self.gateway.connected: return "运行中 TCP/监督进程断开"
        if not self.calibration.is_confirmed_for(self.settings): return "控制参数确认失效"
        if self.settings.operation_mode in FOLLOW_MODES:
            if not self.frame_source.is_open: return "摄像头断开"
            if not self.target_tracker.locked: return "CSRT 目标丢失"
            if self.latest_observation is None or now - self.latest_observation.timestamp > self.settings.vision_timeout_s: return "目标观测超时"
        return None

    def _safety_inputs(self, s: ControlSettings) -> SafetyInputs:
        follow = s.operation_mode in FOLLOW_MODES; source = self.frame_source.source
        return SafetyInputs(serial_connected=self.gateway.connected, telemetry_fresh=s.backend == "tcp" or self.latest_measured_rpm is not None,
            camera_ready=self.frame_source.is_open if follow else False, target_locked=self.target_tracker.locked if follow else False,
            calibration_confirmed=self.calibration.is_confirmed_for(s), directions_valid=True,
            motion_solution_valid=bool(self.latest_motion is not None and self.latest_motion.ready) if follow else False,
            offline_source=bool(source and source.offline_file), real_backend=s.backend == "tcp")

    def _poll_motor_events(self) -> None:
        if self._closing: return
        while True:
            try: event = self.gateway.events.get_nowait()
            except queue.Empty: break
            if event.kind == "telemetry" and event.telemetry is not None:
                self.latest_measured_rpm = event.telemetry.actual_rpm; self.feedback_var.set(f"{event.telemetry.actual_rpm:+.1f} RPM（仿真测量）")
            elif event.kind == "status": self.supervisor_var.set(event.message or "--")
            elif event.kind == "error": self._trigger_fault(event.message)
            elif event.kind in ("notice", "warning"): self.detail_var.set(event.message)
        self.root.after(50, self._poll_motor_events)

    def _trigger_fault(self, reason: str) -> None:
        first = self.safety.fault(reason)
        if self.gateway.connected:
            try: self.gateway.stop()
            except SupervisorClientError: pass
        self.frame_source.close(); self.target_tracker.clear(); self._reset_control_history(clear_target=False)
        self.detail_var.set(f"故障：{reason}。已请求停车，故障不会自动恢复。")
        if first and not self._fault_popup_shown:
            self._fault_popup_shown = True; messagebox.showerror("控制故障", f"{reason}\n\n已请求停车；TCP 模式无法确认实际停止。")

    def _reset_control_history(self, clear_target: bool = True) -> None:
        if self.motion_controller: self.motion_controller.reset()
        self.gateway.reset_rate_limit(); self.latest_motion = None
        if clear_target: self.latest_observation = None
        self.raw_rpm_var.set("-- RPM"); self.sent_rpm_var.set("0 RPM"); self.expected_speed_var.set("-- m/s")
        self.offset_var.set("-- px / -- m"); self.estimated_speed_var.set("0.000 m/s（指令估算）")

    def _refresh_status(self) -> None:
        if self._closing: return
        self._consume_camera_scan_results(); state = self.safety.state; self.state_var.set(STATE_LABELS[state])
        fg, bg = ({AppState.RUNNING: ("#15803d", "#f0fdf4"), AppState.FAULT: ("#b91c1c", "#fef2f2")}).get(state, ("#1d4ed8", "#eff6ff")); self.banner.configure(fg=fg, bg=bg)
        self.banner_var.set(f"{MODE_LABELS.get(self.settings.operation_mode, '')}运行中｜发送 {self.gateway.commanded_rpm_estimate:+d} RPM" if state is AppState.RUNNING else (f"故障锁定：{self.safety.fault_reason}" if state is AppState.FAULT else STATE_LABELS[state]))
        connected = self.gateway.connected; blocked = state in (AppState.RUNNING, AppState.FAULT)
        self.connect_button.configure(state="disabled" if connected else "normal"); self.disconnect_button.configure(state="normal" if connected else "disabled")
        self.open_camera_button.configure(state="normal" if connected and not blocked else "disabled")
        self.select_target_button.configure(state="normal" if self.frame_source.is_open and state is AppState.CAMERA_READY else "disabled")
        self.start_button.configure(state="normal" if connected and not blocked else "disabled"); self.stop_button.configure(state="normal" if connected else "disabled")
        self.ack_fault_button.configure(state="normal" if state is AppState.FAULT else "disabled"); self.scan_camera_button.configure(state="disabled" if self._scan_running else "normal")
        self.root.after(100, self._refresh_status)

    def _render_image(self, bgr_image) -> None:
        image = Image.fromarray(bgr_image[:, :, ::-1]); image.thumbnail((max(320, self.video_label.winfo_width()), max(240, self.video_label.winfo_height())), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(image); self.video_label.configure(image=self._photo, text="")

    def on_close(self) -> None:
        if self._closing: return
        if self.safety.state is AppState.RUNNING and not messagebox.askyesno("确认退出", "退出将发送停车命令，是否继续？", icon="warning"): return
        self._closing = True; self.gateway.close(); self.frame_source.close(); self.target_tracker.clear(); self.root.destroy()

    def run(self) -> None: self.root.mainloop()


def main() -> None: SwimControlApp().run()


if __name__ == "__main__": main()
