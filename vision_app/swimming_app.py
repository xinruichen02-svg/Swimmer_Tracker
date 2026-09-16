from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# Support both the canonical package launch (`python -m vision_app`) and
# direct execution from an IDE (`python vision_app/swimming_app.py`).  Python
# otherwise puts only the script's directory on sys.path, so the top-level
# `vision_app` package cannot be resolved when this file is run directly.
if __package__ in (None, ""):
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from PIL import Image, ImageTk

from vision_app.app_config import AppConfigError, load_settings, save_settings, load_tcp_host_history, save_tcp_host_history
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
from vision_app.ui_theme import P, F, apply_theme, WaveBar, PulseDot, ArcGauge, metric_card, draw_hud
from vision_app.video_recorder import VideoRecorder, VideoRecorderError


FOLLOW_MODES = {FollowMode.POSITION.value, FollowMode.VELOCITY_ESTIMATE.value}
MODE_LABELS = {
    "manual_rpm": "手动 RPM", "manual_speed": "手动线速度",
    "position_follow": "位置比例跟随", "velocity_estimate_follow": "速度估算跟随",
}
MODE_VALUES = {label: value for value, label in MODE_LABELS.items()}
VISUAL_PROCESSING_LABELS = {
    True: "增强处理",
    False: "不处理（对照）",
}
VISUAL_PROCESSING_VALUES = {label: enabled for enabled, label in VISUAL_PROCESSING_LABELS.items()}
STATE_LABELS = {
    AppState.DISCONNECTED: "未连接", AppState.STOPPED: "已停止",
    AppState.CAMERA_READY: "摄像头就绪", AppState.TARGET_LOCKED: "目标已锁定",
    AppState.RUNNING: "运行中", AppState.FAULT: "故障锁定",
}


class SwimControlApp:
    """GUI composition root; calculations and device I/O stay in their layers."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Swimmer_Tracker")
        self.root.geometry("1440x880")
        self.root.minsize(1100, 720)
        apply_theme(self.root)

        self.gateway = MotorCommandGateway()
        self.motor = self.gateway
        self.frame_source, self.frame_processor = FrameSource(), FrameProcessor()
        self.target_tracker, self.renderer = TargetTracker(), FrameRenderer()
        self.recorder = VideoRecorder()
        self.safety, self.calibration = SafetyController(), CalibrationConfirmation()
        self.motion_controller: MotionController | None = None
        self.latest_raw_sample: FrameSample | None = None
        self.latest_sample: FrameSample | None = None
        self.latest_observation: TargetObservation | None = None
        self._prior_observation: TargetObservation | None = None
        self.latest_motion: MotionSetpoint | None = None
        self.latest_measured_rpm: float | None = None
        self._photo = None
        self._last_rendered_frame = None
        self._closing = self._fault_popup_shown = self._scan_running = False
        self._media_paused = False
        self._analysis_session = False
        self._playback_next_due: float | None = None
        self._scan_results: queue.Queue[tuple[list[str], str | None]] = queue.Queue()
        self._tcp_host_history = load_tcp_host_history()
        try:
            self.settings, warning = load_settings(), None
        except AppConfigError as exc:
            self.settings, warning = ControlSettings().validated(), str(exc)
        self._make_variables()
        self._build_ui()
        self._install_traces()
        self._on_backend_selected(); self._on_mode_selected()
        if warning: self.detail_var.set(warning + "；已使用安全默认值。")
        self._wave.start()
        self._pulse.set_color(P["tx4"], pulse=False)
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
            "operation_mode_display": MODE_LABELS[s.operation_mode],
            "manual_rpm": 0, "manual_speed": 0.0, "pixels_per_meter": s.pixels_per_meter,
            "rpm_per_mps": s.rpm_per_mps, "position_kp": s.position_kp,
            "camera_sign": f"{s.camera_axis_sign:+d}", "motor_sign": f"{s.motor_axis_sign:+d}",
            "target_offset": s.target_offset_px, "deadband": s.deadband_m,
            "max_speed": s.max_speed_mps, "rpm_limit": s.rpm_limit,
            "rpm_rate": s.max_rpm_rate_per_s, "window_size": s.displacement_window_size,
            "window_time": s.displacement_window_s,
            "visual_processing": VISUAL_PROCESSING_LABELS[s.visual_processing_enabled],
            "media_status": "尚未打开画面", "recording": "未录制", "record_path": "",
        }
        for name, value in values.items():
            setattr(self, f"{name}_var", tk.StringVar(value=str(value)))
        self.advanced_visible = tk.BooleanVar(value=False)
        displays = {
            "state": STATE_LABELS[self.safety.state], "banner": "未连接：virtual 不驱动真实设备。",
            "detail": "请配置后端并连接。", "backend_badge": "", "supervisor": "未启动",
            "offset": "-- px / -- m", "expected_speed": "-- m/s", "raw_rpm": "-- RPM",
            "sent_rpm": "0 RPM", "estimated_speed": "0.000 m/s", "feedback": "无设备反馈",
            "calibration": "未确认", "source_kind": "无输入",
        }
        for name, value in displays.items():
            setattr(self, f"{name}_var", tk.StringVar(value=value))

    # ═══════════════════════════════════════════════════════════════
    #  UI — 紧凑一屏布局
    # ═══════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        root_frame = tk.Frame(self.root, bg=P["bg"])
        root_frame.pack(fill="both", expand=True)

        topbar = tk.Frame(root_frame, bg=P["bg2"], height=44)
        topbar.pack(fill="x"); topbar.pack_propagate(False)
        ltb = tk.Frame(topbar, bg=P["bg2"]); ltb.pack(side="left", padx=16, pady=6)
        tk.Label(ltb, text="SWIMMER_TRACKER", bg=P["bg2"], fg=P["cy"], font=F["logo"]).pack(side="left")
        tk.Label(ltb, text="  VISION / ANALYSIS / RECORD", bg=P["bg2"], fg=P["tx3"], font=F["logo2"]).pack(side="left", padx=(4, 0))
        rtb = tk.Frame(topbar, bg=P["bg2"]); rtb.pack(side="right", padx=16, pady=6)
        self._pulse = PulseDot(rtb, size=14); self._pulse.widget.pack(side="right", padx=(8, 0))
        self._state_label = tk.Label(rtb, textvariable=self.state_var, bg=P["bg2"], fg=P["tx2"], font=F["st_big"])
        self._state_label.pack(side="right")

        self._wave = WaveBar(root_frame, height=18, color=P["cy3"], speed=45)
        self._wave.widget.pack(fill="x")

        self.banner = tk.Label(root_frame, textvariable=self.banner_var, anchor="w",
                               padx=14, pady=4, bg=P["cy4"], fg=P["cy2"], font=F["lbl2"])
        self.banner.pack(fill="x")

        body = tk.Frame(root_frame, bg=P["bg"])
        body.pack(fill="both", expand=True, padx=8, pady=(6, 8))
        body.columnconfigure(0, weight=7)
        body.columnconfigure(1, weight=4, minsize=390)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=P["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        # 媒体工作流固定在视频上方：输入、分析和录制互不依赖电机连接。
        media = tk.Frame(left, bg=P["card"], highlightbackground=P["border"], highlightthickness=1)
        media.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        media.columnconfigure(6, weight=1)
        self.upload_video_button = ttk.Button(media, text="＋ 上传视频", style="C.TButton", command=self.upload_video)
        self.upload_video_button.grid(row=0, column=0, padx=(8, 3), pady=7)
        self.analysis_button = ttk.Button(media, text="▶ 开始分析", style="G.TButton", command=self.toggle_analysis)
        self.analysis_button.grid(row=0, column=1, padx=3, pady=7)
        self.record_button = ttk.Button(media, text="● 开始录制", style="R.TButton", command=self.toggle_recording)
        self.record_button.grid(row=0, column=2, padx=3, pady=7)
        self.close_media_button = ttk.Button(media, text="关闭画面", style="X.TButton", command=self.close_media)
        self.close_media_button.grid(row=0, column=3, padx=3, pady=7)
        tk.Label(media, text="视觉", bg=P["card"], fg=P["tx3"], font=F["lbl2"]).grid(
            row=0, column=4, padx=(10, 3), pady=7
        )
        self.visual_processing_box = ttk.Combobox(
            media, textvariable=self.visual_processing_var,
            values=tuple(VISUAL_PROCESSING_VALUES), state="readonly", width=12,
        )
        self.visual_processing_box.grid(row=0, column=5, padx=3, pady=7)
        self.visual_processing_box.bind("<<ComboboxSelected>>", self._on_visual_processing_selected)
        mstatus = tk.Frame(media, bg=P["card"])
        mstatus.grid(row=0, column=6, sticky="e", padx=10)
        tk.Label(mstatus, textvariable=self.source_kind_var, bg=P["card"], fg=P["cy2"], font=F["st_sm"]).pack(anchor="e")
        tk.Label(mstatus, textvariable=self.media_status_var, bg=P["card"], fg=P["tx3"], font=F["lbl2"]).pack(anchor="e")

        vid = tk.Frame(left, bg=P["vid_bg"], highlightbackground=P["vid_glow"], highlightthickness=2)
        vid.grid(row=1, column=0, sticky="nsew")
        vid.rowconfigure(0, weight=1); vid.columnconfigure(0, weight=1)
        self._hud = tk.Canvas(vid, bg=P["vid_bg"], highlightthickness=0)
        self._hud.grid(row=0, column=0, sticky="nsew")
        self.video_label = tk.Label(self._hud, text="SWIMMER_TRACKER", bg=P["vid_bg"], fg=P["tx4"], font=F["hint"])
        self.video_label.place(relx=0.5, rely=0.5, anchor="center")
        self._hud.bind("<Configure>", lambda _e: draw_hud(self._hud))

        dash = tk.Frame(left, bg=P["bg"])
        dash.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        for c in range(5): dash.columnconfigure(c, weight=1)
        for i, (title, variable, accent) in enumerate([
            ("目标偏差", self.offset_var, "cy"),
            ("期望速度", self.expected_speed_var, "bl"),
            ("发送 RPM", self.sent_rpm_var, "gn"),
            ("机器人速度", self.estimated_speed_var, "am"),
        ]):
            metric_card(dash, title, variable, accent).grid(
                row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0)
            )
        self._gauge = ArcGauge(dash, size=96, thickness=6)
        self._gauge.widget.grid(row=0, column=4, sticky="nsew", padx=(4, 0), pady=4)

        # 右侧分页，避免连接、控制和高级参数同时挤在一个窄列中。
        right = tk.Frame(body, bg=P["bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        head = tk.Frame(right, bg=P["card"], highlightbackground=P["border"], highlightthickness=1)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(head, text="CONTROL CONSOLE", bg=P["card"], fg=P["cy"], font=F["sec"]).pack(side="left", padx=10, pady=8)
        self.backend_badge = tk.Label(head, textvariable=self.backend_badge_var,
                                      bg=P["cy4"], fg=P["cy2"], font=F["st_sm"], padx=8, pady=2)
        self.backend_badge.pack(side="right", padx=10, pady=7)

        notebook = ttk.Notebook(right, style="Console.TNotebook")
        self.control_notebook = notebook
        notebook.grid(row=1, column=0, sticky="nsew")
        device_tab = tk.Frame(notebook, bg=P["card"])
        control_tab = tk.Frame(notebook, bg=P["card"])
        advanced_tab = tk.Frame(notebook, bg=P["card"])
        notebook.add(device_tab, text="设备与输入")
        notebook.add(control_tab, text="运动控制")
        notebook.add(advanced_tab, text="高级安全")

        c1 = tk.Frame(device_tab, bg=P["card"]); c1.pack(fill="x", padx=14, pady=14)
        c1.columnconfigure(1, weight=1); c1.columnconfigure(3, weight=1)
        ttk.Label(c1, text="后端", style="D.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        be = ttk.Combobox(c1, textvariable=self.backend_var, values=("virtual", "tcp"), state="readonly", width=10)
        be.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=4); be.bind("<<ComboboxSelected>>", self._on_backend_selected)
        ttk.Label(c1, text="端口", style="D.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=4)
        ttk.Entry(c1, textvariable=self.tcp_port_var, width=9).grid(row=0, column=3, sticky="ew", pady=4)
        ttk.Label(c1, text="控制器 IP", style="D.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=4)
        self.tcp_host_box = ttk.Combobox(c1, textvariable=self.tcp_host_var, values=tuple(self._tcp_host_history))
        self.tcp_host_box.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Label(c1, text="摄像头源", style="D.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=4)
        self.camera_source_box = ttk.Combobox(c1, textvariable=self.camera_source_var, values=("0",))
        self.camera_source_box.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(0, 6), pady=4)
        self.scan_camera_button = ttk.Button(c1, text="扫描", style="Xs.TButton", command=self.scan_camera_sources)
        self.scan_camera_button.grid(row=2, column=3, sticky="ew", pady=4)
        br1 = tk.Frame(device_tab, bg=P["card"]); br1.pack(fill="x", padx=14, pady=(0, 10))
        for c in range(3): br1.columnconfigure(c, weight=1)
        self.connect_button = ttk.Button(br1, text="⚡ 连接电机", style="C.TButton", command=self.connect_motor)
        self.connect_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.disconnect_button = ttk.Button(br1, text="断开", style="X.TButton", command=self.disconnect_motor)
        self.disconnect_button.grid(row=0, column=1, sticky="ew", padx=3)
        self.open_camera_button = ttk.Button(br1, text="📹 打开相机", style="X.TButton", command=self.open_camera)
        self.open_camera_button.grid(row=0, column=2, sticky="ew", padx=(3, 0))
        device_info = tk.Frame(device_tab, bg=P["bg2"])
        device_info.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        tk.Label(device_info, text="监督进程", bg=P["bg2"], fg=P["tx3"], font=F["lbl2"]).pack(anchor="w", padx=10, pady=(9, 2))
        tk.Label(device_info, textvariable=self.supervisor_var, bg=P["bg2"], fg=P["tx"], font=F["v_sm"]).pack(anchor="w", padx=10)
        tk.Label(device_info, textvariable=self.detail_var, wraplength=345, bg=P["bg2"], fg=P["tx2"],
                 font=F["lbl2"], anchor="nw", justify="left").pack(fill="both", expand=True, padx=10, pady=(8, 10))

        basic = tk.Frame(control_tab, bg=P["card"]); basic.pack(fill="x", padx=14, pady=14)
        basic.columnconfigure(1, weight=1); basic.columnconfigure(3, weight=1)
        ttk.Label(basic, text="运行模式", style="D.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        mb = ttk.Combobox(basic, textvariable=self.operation_mode_display_var,
                          values=tuple(MODE_VALUES), state="readonly")
        mb.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4); mb.bind("<<ComboboxSelected>>", self._on_mode_selected)
        for row, items in enumerate([
            ("手动 RPM", self.manual_rpm_var, "速度 m/s", self.manual_speed_var),
            ("像素/米", self.pixels_per_meter_var, "RPM/(m/s)", self.rpm_per_mps_var),
            ("位置 P 增益", self.position_kp_var, None, None),
        ], start=1):
            ttk.Label(basic, text=items[0], style="D.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 6), pady=4)
            ttk.Entry(basic, textvariable=items[1], width=10).grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=4)
            if items[2]:
                ttk.Label(basic, text=items[2], style="D.TLabel").grid(row=row, column=2, sticky="w", padx=(0, 6), pady=4)
                ttk.Entry(basic, textvariable=items[3], width=10).grid(row=row, column=3, sticky="ew", pady=4)
        cal = tk.Frame(control_tab, bg=P["bg2"]); cal.pack(fill="x", padx=14, pady=(0, 10))
        tk.Label(cal, text="标定状态", bg=P["bg2"], fg=P["tx3"], font=F["lbl2"]).pack(side="left", padx=10, pady=9)
        self._cal_lbl = tk.Label(cal, textvariable=self.calibration_var, bg=P["bg2"], fg=P["tx3"], font=F["v_sm"])
        self._cal_lbl.pack(side="right", padx=10, pady=9)
        ttk.Button(control_tab, text="✔ 应用并确认参数", style="G.TButton", command=self.confirm_settings).pack(fill="x", padx=14, pady=(0, 14))

        self.advanced_frame = tk.Frame(advanced_tab, bg=P["card"])
        self.advanced_frame.pack(fill="x", padx=14, pady=14)
        self.advanced_frame.columnconfigure(1, weight=1); self.advanced_frame.columnconfigure(3, weight=1)
        for row, items in enumerate([
            ("相机方向", self.camera_sign_var, "电机方向", self.motor_sign_var),
            ("目标偏移 px", self.target_offset_var, "死区 m", self.deadband_var),
            ("最大速度 m/s", self.max_speed_var, "RPM 上限", self.rpm_limit_var),
            ("RPM 变化率/s", self.rpm_rate_var, "估算窗口 N", self.window_size_var),
            ("估算窗口 s", self.window_time_var, None, None),
        ]):
            ttk.Label(self.advanced_frame, text=items[0], style="D.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 6), pady=4)
            ttk.Entry(self.advanced_frame, textvariable=items[1], width=9).grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=4)
            if items[2]:
                ttk.Label(self.advanced_frame, text=items[2], style="D.TLabel").grid(row=row, column=2, sticky="w", padx=(0, 6), pady=4)
                ttk.Entry(self.advanced_frame, textvariable=items[3], width=9).grid(row=row, column=3, sticky="ew", pady=4)
        tk.Label(advanced_tab, text="真实 TCP 模式必须配备物理急停与失联停车。\n本地视频仅用于分析，不允许驱动真实电机。",
                 bg=P["am3"], fg=P["am2"], font=F["lbl2"], justify="left", anchor="w", padx=10, pady=9).pack(fill="x", padx=14, pady=(0, 14))

        # 操作按钮始终固定在分页面板下方。
        s4 = tk.Frame(right, bg=P["bg"])
        s4.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        s4.columnconfigure(0, weight=1); s4.columnconfigure(1, weight=1)
        self.select_target_button = ttk.Button(s4, text="🎯 框选目标", style="C.TButton", command=self.select_target)
        self.select_target_button.grid(row=0, column=0, sticky="ew", padx=(0, 3), pady=2)
        self.start_button = ttk.Button(s4, text="▶ 启动", style="G.TButton", command=self.start_control)
        self.start_button.grid(row=0, column=1, sticky="ew", padx=(3, 0), pady=2)
        self.stop_button = ttk.Button(s4, text="⏹ 停止", style="R.TButton", command=self.manual_stop)
        self.stop_button.grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=2)
        self.ack_fault_button = ttk.Button(s4, text="⚠ 复位", style="A.TButton", command=self.acknowledge_fault)
        self.ack_fault_button.grid(row=1, column=1, sticky="ew", padx=(3, 0), pady=2)
        rec = tk.Frame(s4, bg=P["bg2"]); rec.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        rec.columnconfigure(1, weight=1)
        self._record_label = tk.Label(rec, textvariable=self.recording_var, bg=P["bg2"], fg=P["tx3"], font=F["st_sm"])
        self._record_label.grid(row=0, column=0, padx=8, pady=6)
        tk.Label(rec, textvariable=self.record_path_var, bg=P["bg2"], fg=P["tx3"], font=F["lbl2"], anchor="e").grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=6)

    # ── 辅助 ──

    def _install_traces(self) -> None:
        for v in (self.pixels_per_meter_var, self.rpm_per_mps_var, self.position_kp_var,
                  self.camera_sign_var, self.motor_sign_var, self.target_offset_var,
                  self.deadband_var, self.max_speed_var, self.rpm_limit_var,
                  self.rpm_rate_var, self.window_size_var, self.window_time_var):
            v.trace_add("write", self._on_control_parameter_edited)

    def _toggle_advanced(self) -> None:
        if self.advanced_visible.get(): self.advanced_frame.pack(fill="both", expand=True, padx=0, pady=(2, 6))
        else: self.advanced_frame.pack_forget()

    def _on_backend_selected(self, _e=None) -> None:
        real = self.backend_var.get() == "tcp"
        if real:
            self.backend_badge_var.set("真实 TCP ｜ 无设备反馈")
            self.backend_badge.configure(bg=P["rd3"], fg=P["rd2"])
        else:
            self.backend_badge_var.set("virtual ｜ 不会驱动真实设备")
            self.backend_badge.configure(bg=P["cy4"], fg=P["cy2"])

    def _on_mode_selected(self, _e=None) -> None:
        if self.safety.state is AppState.RUNNING: self._trigger_fault("运行中切换了控制模式"); return
        if _e is not None:
            self.operation_mode_var.set(MODE_VALUES.get(
                self.operation_mode_display_var.get(), self.operation_mode_var.get()
            ))
        else:
            self.operation_mode_display_var.set(MODE_LABELS.get(
                self.operation_mode_var.get(), self.operation_mode_var.get()
            ))
        self._reset_control_history(clear_target=False)
        self.detail_var.set(f"已选择：{MODE_LABELS.get(self.operation_mode_var.get(), '未知模式')}。")

    def _on_control_parameter_edited(self, *_a) -> None:
        if self._closing: return
        was = self.calibration.confirmed; self.calibration.invalidate(); self.calibration_var.set("未确认")
        if self.safety.state is AppState.RUNNING: self._trigger_fault("运行中修改了控制参数")
        elif was: self.detail_var.set("控制参数已修改，请重新确认。")

    def _visual_processing_enabled(self) -> bool:
        return VISUAL_PROCESSING_VALUES.get(self.visual_processing_var.get(), True)

    def _on_visual_processing_selected(self, _event=None) -> None:
        if self.safety.state in (AppState.RUNNING, AppState.FAULT):
            self.visual_processing_var.set(
                VISUAL_PROCESSING_LABELS[self.settings.visual_processing_enabled]
            )
            messagebox.showinfo("视觉处理", "请先停止控制并处理故障，再切换视觉处理方式。")
            return
        enabled = self._visual_processing_enabled()
        if enabled == self.settings.visual_processing_enabled:
            return
        self.frame_processor.reset()
        self.settings = replace(self.settings, visual_processing_enabled=enabled)
        save_warning = ""
        try:
            save_settings(self.settings)
        except AppConfigError as exc:
            save_warning = f"；但保存失败：{exc}"
        label = VISUAL_PROCESSING_LABELS[enabled]
        if not self.frame_source.is_open:
            self.detail_var.set(f"已选择“{label}”；载入视频后将使用该处理方式{save_warning}。")
            return

        # A tracker must never continue across two differently processed image
        # streams. Keep the current source open, but reset tracking and let the
        # user select the target again on the current raw frame.
        self.target_tracker.clear()
        self.latest_sample = self.latest_raw_sample
        self.latest_observation = self.latest_motion = None
        self._prior_observation = None
        self._reset_control_history(clear_target=True)
        if self.gateway.connected:
            try:
                self.safety.target_cleared()
            except StateTransitionError:
                pass

        source = self.frame_source.source
        if source and source.offline_file:
            self._analysis_session = True
            self._media_paused = True
            self._playback_next_due = None
            self.source_kind_var.set("离线视频 · " + label)
            self.media_status_var.set("处理方式已切换 · 请重新框选目标")
        else:
            self.source_kind_var.set("实时画面 · " + label)
            self.media_status_var.set("采集中 · 请重新框选目标")

        if self.latest_raw_sample is not None:
            rendered = self.renderer.render(
                self.latest_raw_sample,
                None,
                target_offset_px=self.settings.target_offset_px,
                max_offset_fraction=self.settings.max_offset_fraction,
            )
            self._render_image(rendered)
        self.detail_var.set(f"已切换为“{label}”；旧目标已清除，请重新框选{save_warning}。")

    def _settings_from_ui(self) -> ControlSettings:
        try:
            mode = self.operation_mode_var.get()
            return replace(self.settings, backend=self.backend_var.get(),
                tcp_host=self.tcp_host_var.get().strip(), tcp_port=int(self.tcp_port_var.get()),
                operation_mode=mode, follow_mode=mode if mode in FOLLOW_MODES else self.settings.follow_mode,
                pixels_per_meter=float(self.pixels_per_meter_var.get()), rpm_per_mps=float(self.rpm_per_mps_var.get()),
                position_kp=float(self.position_kp_var.get()),
                camera_axis_sign=int(self.camera_sign_var.get()), motor_axis_sign=int(self.motor_sign_var.get()),
                target_offset_px=float(self.target_offset_var.get()), deadband_m=float(self.deadband_var.get()),
                max_speed_mps=float(self.max_speed_var.get()), rpm_limit=int(self.rpm_limit_var.get()),
                max_rpm_rate_per_s=float(self.rpm_rate_var.get()),
                displacement_window_size=int(self.window_size_var.get()),
                displacement_window_s=float(self.window_time_var.get()),
                visual_processing_enabled=self._visual_processing_enabled()).validated()
        except (ValueError, TypeError) as exc: raise SettingsError("参数必须填写有效数字") from exc

    @staticmethod
    def _motion_config(s: ControlSettings) -> MotionControlConfig:
        return MotionControlConfig(mode=s.follow_mode, pixels_per_meter=s.pixels_per_meter,
            camera_axis_sign=s.camera_axis_sign, target_offset_px=s.target_offset_px,
            position_kp=s.position_kp, deadband_m=s.deadband_m, max_speed_mps=s.max_speed_mps,
            rpm_per_mps=s.rpm_per_mps, motor_axis_sign=s.motor_axis_sign,
            estimator_window_size=s.displacement_window_size, estimator_window_s=s.displacement_window_s,
            max_offset_fraction=s.max_offset_fraction).validated()

    def confirm_settings(self) -> None:
        if self.safety.state in (AppState.RUNNING, AppState.FAULT): messagebox.showwarning("不能修改", "请先停止并处理故障。"); return
        try: settings = self._settings_from_ui(); self._motion_config(settings)
        except (SettingsError, MotionControlError) as exc: messagebox.showerror("参数无效", str(exc)); return
        if not messagebox.askyesno("确认标定", "确认换算、方向、限幅和控制参数已经核对？"): return
        self.settings = settings; self.calibration.confirm(settings); self.calibration_var.set("已确认")
        self.motion_controller = MotionController(self._motion_config(settings))
        self.gateway.configure_rate_limit(settings.max_rpm_rate_per_s)
        try: save_settings(settings)
        except AppConfigError as exc: self.detail_var.set(f"参数已应用但保存失败：{exc}"); return
        self.detail_var.set("参数已确认并保存。")

    def _save_tcp_host(self, host: str) -> None:
        host = host.strip()
        if not host: return
        history = [host] + [h for h in self._tcp_host_history if h != host]
        self._tcp_host_history = history[:8]
        save_tcp_host_history(self._tcp_host_history)
        self.tcp_host_box.configure(values=tuple(self._tcp_host_history))

    def connect_motor(self) -> None:
        if self.gateway.connected: return
        try:
            settings = self._settings_from_ui()
            config = BackendConfig(backend=settings.backend, tcp_host=settings.tcp_host, tcp_port=settings.tcp_port).validated()
        except (SettingsError, MotorBackendError) as exc: messagebox.showerror("连接配置无效", str(exc)); return
        if settings.backend == "tcp" and not messagebox.askyesno("真实 TCP 控制确认",
                "TCP 第一版没有实际转速和驱动故障反馈。\nAPP 无法检测堵转或实际速度偏差。\n\n请确认物理急停和下位机失联停车可用。", icon="warning"): return
        try:
            self.gateway.connect(config); self.safety.serial_connected()
            if self.frame_source.is_open:
                self.safety.camera_opened()
                if self.target_tracker.locked:
                    self.safety.target_locked()
        except (SupervisorClientError, MotorBackendError, StateTransitionError) as exc: messagebox.showerror("连接失败", str(exc)); return
        if settings.backend == "tcp": self._save_tcp_host(settings.tcp_host)
        self.settings = settings
        self.feedback_var.set("无设备反馈" if settings.backend == "tcp" else "等待仿真反馈")
        self.detail_var.set("TCP 已连接并发送 P、T0。" if settings.backend == "tcp" else "virtual 已连接。")

    connect_serial = connect_motor

    def disconnect_motor(self) -> None:
        real = self.settings.backend == "tcp"
        self._stop_recording(silent=True)
        self.gateway.close(); self.frame_source.close(); self.target_tracker.clear()
        self._clear_media_display()
        self.safety.disconnected("用户断开电机"); self._reset_control_history()
        self.supervisor_var.set("已关闭")
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
        self.camera_source_box.configure(values=tuple(merged or ["0"]))
        self.detail_var.set("可用摄像头：" + (", ".join(values) if values else "未发现"))

    def upload_video(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择需要分析的视频",
            filetypes=(
                ("视频文件", "*.mp4 *.avi *.mov *.mkv *.m4v *.wmv"),
                ("所有文件", "*.*"),
            ),
        )
        if path:
            self._open_media(path, pause_offline=True)

    def open_camera(self) -> None:
        self._open_media(self.camera_source_var.get(), pause_offline=False)

    def _open_media(self, raw_source: str, *, pause_offline: bool) -> None:
        if self.safety.state in (AppState.RUNNING, AppState.FAULT):
            messagebox.showwarning("当前不可用", "请先停止控制并处理故障。")
            return
        self._stop_recording(silent=True)
        try:
            self.frame_processor.reset()
            sample = self.frame_processor.prepare(self.frame_source.open(raw_source))
            self.target_tracker.clear()
            self.latest_raw_sample = sample
            self.latest_sample, self.latest_observation = sample, None
            self._prior_observation = None
            self.latest_motion = None
            source = self.frame_source.source
            self._analysis_session = bool(source and source.offline_file)
            self._media_paused = self._analysis_session and pause_offline
            self._playback_next_due = None
            if self.gateway.connected:
                self.safety.camera_opened()
        except (FrameSourceError, StateTransitionError) as exc:
            messagebox.showerror("画面错误", str(exc))
            return
        self.camera_source_var.set(raw_source)
        if self._analysis_session:
            self.source_kind_var.set("离线视频 · " + VISUAL_PROCESSING_LABELS[self._visual_processing_enabled()])
            self.media_status_var.set(f"已载入 · {Path(raw_source).name} · 等待框选")
            self.detail_var.set("视频已停在首帧。请框选目标，然后点击“开始分析”。")
        else:
            self.source_kind_var.set("实时画面 · " + VISUAL_PROCESSING_LABELS[self._visual_processing_enabled()])
            self.media_status_var.set(f"采集中 · {raw_source}")
            self.detail_var.set("实时画面已打开，可框选目标或直接录制。")
        rendered = self.renderer.render(
            sample, None,
            target_offset_px=self.settings.target_offset_px,
            max_offset_fraction=self.settings.max_offset_fraction,
        )
        self._render_image(rendered)

    def toggle_analysis(self) -> None:
        source = self.frame_source.source
        if not self.frame_source.is_open or source is None or not source.offline_file:
            messagebox.showinfo("视频分析", "请先点击“上传视频”选择一个本地视频。")
            return
        if not self.target_tracker.locked:
            messagebox.showwarning("尚未框选", "请先在当前帧框选需要分析的目标。")
            return
        self._media_paused = not self._media_paused
        if self._media_paused:
            self._playback_next_due = None
            self.media_status_var.set("分析已暂停")
            self.detail_var.set("视频分析已暂停，可重新框选或恢复分析。")
        else:
            self._playback_next_due = time.monotonic()
            self.media_status_var.set("正在分析目标轨迹")
            self.detail_var.set("离线目标分析进行中；不会驱动真实电机。")

    def toggle_recording(self) -> None:
        if self.recorder.is_recording:
            self._stop_recording()
            return
        if not self.frame_source.is_open or self.latest_sample is None:
            messagebox.showwarning("没有画面", "请先打开相机或上传视频。")
            return
        video_folder = Path.home() / "Videos"
        initial_dir = video_folder if video_folder.is_dir() else Path.home()
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="选择录像保存位置",
            initialdir=str(initial_dir),
            initialfile=f"swimmer_{datetime.now():%Y%m%d_%H%M%S}.mp4",
            defaultextension=".mp4",
            filetypes=(("MP4 视频", "*.mp4"), ("AVI 视频", "*.avi")),
            confirmoverwrite=True,
        )
        if not path:
            return
        try:
            target = self.recorder.start(
                path,
                (self.latest_sample.width, self.latest_sample.height),
                self.frame_source.fps,
            )
        except VideoRecorderError as exc:
            messagebox.showerror("无法开始录制", str(exc))
            return
        self.recording_var.set("● REC  0 帧")
        self._record_label.configure(fg=P["rd2"])
        self.record_path_var.set(target.name)
        if self._last_rendered_frame is not None:
            try:
                self.recorder.write(self._last_rendered_frame)
                self.recording_var.set("● REC  1 帧")
            except VideoRecorderError as exc:
                self._stop_recording(silent=True)
                messagebox.showerror("无法开始录制", str(exc))
                return
        self.detail_var.set(f"正在录制带分析标记的画面：{target}")

    def _stop_recording(self, *, silent: bool = False) -> None:
        result = self.recorder.stop()
        self.recording_var.set("未录制")
        self._record_label.configure(fg=P["tx3"])
        if result is None:
            return
        self.record_path_var.set(result.path.name)
        if not silent:
            self.detail_var.set(f"录像已保存：{result.path}（{result.frame_count} 帧）")

    def close_media(self) -> None:
        if self.safety.state is AppState.RUNNING:
            messagebox.showwarning("正在运行", "请先停止控制，再关闭画面。")
            return
        self._stop_recording()
        self.frame_source.close(); self.target_tracker.clear()
        self.latest_raw_sample = self.latest_sample = None
        self.latest_observation = self.latest_motion = None
        self._prior_observation = None
        if self.gateway.connected:
            try: self.safety.camera_closed()
            except StateTransitionError: pass
        self._clear_media_display()
        self.detail_var.set("画面已关闭。")

    def _clear_media_display(self) -> None:
        self._analysis_session = False
        self._media_paused = False
        self._playback_next_due = None
        self.latest_raw_sample = self.latest_sample = None
        self.latest_observation = self.latest_motion = None
        self._prior_observation = None
        self.source_kind_var.set("无输入")
        self.media_status_var.set("尚未打开画面")
        self._photo = None
        self._last_rendered_frame = None
        self.video_label.configure(image="", text="SWIMMER_TRACKER")
        self.video_label.place(relx=0.5, rely=0.5, anchor="center")

    def select_target(self) -> None:
        selection_sample = self.latest_raw_sample or self.latest_sample
        if selection_sample is None:
            messagebox.showwarning("没有画面", "请先打开相机或上传视频。")
            return
        try:
            bbox = self.target_tracker.select_bbox(selection_sample)
            settings = self._settings_from_ui()
            self.frame_processor.reset()
            tracking_sample = self.frame_processor.process(
                selection_sample, bbox, enhance=self._visual_processing_enabled()
            )
            observation = self.target_tracker.initialize(tracking_sample, bbox)
            self.motion_controller = MotionController(self._motion_config(settings))
            self.latest_sample = tracking_sample
            self.latest_observation = observation
            self._prior_observation = None
            self.latest_motion = self.motion_controller.compute(observation, self.gateway.commanded_rpm_estimate)
            if self.gateway.connected:
                self.safety.target_locked()
        except TargetSelectionCancelled as exc: self.detail_var.set(str(exc)); return
        except (TargetTrackingError, SettingsError, MotionControlError, StateTransitionError) as exc: messagebox.showerror("框选失败", str(exc)); return
        rendered = self.renderer.render(
            tracking_sample, observation,
            target_offset_px=settings.target_offset_px,
            max_offset_fraction=settings.max_offset_fraction,
        )
        self._render_image(rendered)
        processing_label = VISUAL_PROCESSING_LABELS[self._visual_processing_enabled()]
        if self._analysis_session:
            self.detail_var.set(f"目标已锁定，CSRT 已使用“{processing_label}”画面初始化。点击“开始分析”播放视频。")
            self.media_status_var.set(f"目标已选取 · {processing_label} · 等待开始分析")
        else:
            self.detail_var.set(f"CSRT 已使用“{processing_label}”画面初始化，运动控制历史已重置。")

    def start_control(self) -> None:
        try: settings = self._settings_from_ui()
        except SettingsError as exc: messagebox.showerror("参数无效", str(exc)); return
        if not self.gateway.connected: messagebox.showwarning("尚不能启动", "电机后端未连接。"); return
        if not self.calibration.is_confirmed_for(settings): messagebox.showwarning("尚不能启动", "请先应用并确认参数。"); return
        follow = settings.operation_mode in FOLLOW_MODES
        if follow and (not self.frame_source.is_open or not self.target_tracker.locked): messagebox.showwarning("尚不能启动", "视觉模式需要打开摄像头并框选目标。"); return
        if follow and self.frame_source.source and self.frame_source.source.offline_file and self._media_paused:
            messagebox.showwarning("尚不能启动", "离线视频当前已暂停，请先点击“继续分析”。")
            return
        if self.frame_source.source and self.frame_source.source.offline_file and settings.backend == "tcp": messagebox.showwarning("禁止启动", "本地视频禁止驱动真实 TCP 电机。"); return
        warning = f"将启动 {MODE_LABELS[settings.operation_mode]}。" + ("\n\n当前无实际转速反馈，确认物理急停可用。" if settings.backend == "tcp" else "")
        if not messagebox.askyesno("启动确认", warning, icon="warning"): return
        try:
            inputs = self._safety_inputs(settings)
            self.safety.start(inputs) if follow else self.safety.start_constant_speed(inputs)
            self.settings = settings; self.gateway.configure_rate_limit(settings.max_rpm_rate_per_s); self.gateway.start()
        except (StateTransitionError, SupervisorClientError) as exc: self._trigger_fault(f"启动失败：{exc}"); return
        self.detail_var.set("控制已启动；期望目标按设定周期更新。")

    def manual_stop(self) -> None:
        if self.gateway.connected:
            try: self.gateway.stop()
            except SupervisorClientError as exc: self.detail_var.set(f"停车发送失败：{exc}")
        self._stop_recording(silent=True)
        self.safety.manual_stop(); self.frame_source.close(); self.target_tracker.clear()
        self._clear_media_display()
        self._reset_control_history()
        self.detail_var.set("停车命令已发送，实际停止未反馈。" if self.settings.backend == "tcp" else "virtual 已停车。")

    def acknowledge_fault(self) -> None:
        if self.safety.state is not AppState.FAULT: return
        try:
            if self.gateway.connected: self.gateway.reset_fault()
            self.safety.acknowledge_fault()
        except (SupervisorClientError, StateTransitionError) as exc: messagebox.showerror("复位失败", str(exc)); return
        self._fault_popup_shown = False; self._reset_control_history()
        self.detail_var.set("故障已确认，电机保持停止。")

    def _camera_tick(self) -> None:
        if self._closing: return
        delay_ms = 30
        source = self.frame_source.source
        if self.frame_source.is_open and not (source and source.offline_file and self._media_paused):
            try:
                frame_interval = None
                if source and source.offline_file:
                    frame_interval = 1.0 / self.frame_source.fps
                    now = time.monotonic()
                    if self._playback_next_due is None:
                        self._playback_next_due = now
                    late_by = max(0.0, now - self._playback_next_due)
                    requested_skip = min(8, int(late_by / frame_interval))
                    skipped = self.frame_source.skip_frames(requested_skip)
                    self._playback_next_due += skipped * frame_interval
                    if skipped and self.recorder.is_recording and self._last_rendered_frame is not None:
                        for _ in range(skipped):
                            self.recorder.write(self._last_rendered_frame)
                raw_sample = self.frame_processor.prepare(self.frame_source.read())
                self.latest_raw_sample = raw_sample
                processing_bbox = self._predicted_tracking_bbox()
                enabled = self._visual_processing_enabled()
                sample = self.frame_processor.process(
                    raw_sample, processing_bbox, enhance=enabled
                ) if processing_bbox is not None else raw_sample
                self.latest_sample = sample
                observation = self.target_tracker.update(sample)
                self._prior_observation = self.latest_observation
                self.latest_observation = observation
                if observation is not None and self.motion_controller is not None:
                    self.latest_motion = self.motion_controller.compute(observation, self.gateway.commanded_rpm_estimate)
                    self._show_motion(self.latest_motion)
                    if self.latest_motion.outside_safe_region and self.safety.state is AppState.RUNNING:
                        raise TrackingLostError("目标偏差超过安全区域")
                rendered = self.renderer.render(sample, observation,
                    target_offset_px=self.settings.target_offset_px, max_offset_fraction=self.settings.max_offset_fraction)
                if self.recorder.is_recording:
                    self.recorder.write(rendered)
                    self.recording_var.set(f"● REC  {self.recorder.frame_count} 帧")
                self._render_image(rendered)
                if frame_interval is not None:
                    self._playback_next_due += frame_interval
                    remaining = self._playback_next_due - time.monotonic()
                    delay_ms = max(1, int(round(remaining * 1000.0)))
            except FrameSourceError as exc:
                if source and source.offline_file:
                    self._finish_offline_analysis()
                else:
                    if self.safety.state is AppState.RUNNING: self._trigger_fault(str(exc))
                    else:
                        self.frame_source.close(); self.target_tracker.clear()
                        self._stop_recording(silent=True); self._clear_media_display()
                        self.detail_var.set(str(exc))
            except (TrackingLostError, TargetTrackingError, MotionControlError, VideoRecorderError) as exc:
                if self.safety.state is AppState.RUNNING: self._trigger_fault(str(exc))
                else:
                    if not self.target_tracker.locked:
                        try: self.safety.target_cleared()
                        except StateTransitionError: pass
                    if source and source.offline_file:
                        self._media_paused = True
                        self.media_status_var.set("目标丢失 · 分析已暂停")
                    if isinstance(exc, VideoRecorderError):
                        self._stop_recording(silent=True)
                    self.detail_var.set(str(exc))
        self.root.after(delay_ms, self._camera_tick)

    def _finish_offline_analysis(self) -> None:
        result = self.recorder.stop()
        self.frame_source.close(); self.target_tracker.clear()
        self.latest_observation = self.latest_motion = None
        self._prior_observation = None
        self._analysis_session = False; self._media_paused = False
        self._playback_next_due = None
        if self.gateway.connected:
            try: self.safety.camera_closed()
            except StateTransitionError: pass
        self.source_kind_var.set("离线视频")
        self.media_status_var.set("分析完成")
        self.recording_var.set("未录制")
        self._record_label.configure(fg=P["tx3"])
        if result:
            self.record_path_var.set(result.path.name)
            self.detail_var.set(f"视频分析完成，录像已保存：{result.path}（{result.frame_count} 帧）")
        else:
            self.detail_var.set("视频分析完成。可重新上传视频继续分析。")

    def _show_motion(self, motion: MotionSetpoint) -> None:
        self.offset_var.set(f"{motion.error_px:+.1f} px / {motion.error_m:+.3f} m")
        self.expected_speed_var.set("收集中" if motion.expected_speed_mps is None else f"{motion.expected_speed_mps:+.3f} m/s")

    def _predicted_tracking_bbox(self) -> tuple[int, int, int, int] | None:
        """Predict one frame ahead so a moving target stays out of the blurred background."""

        current = self.latest_observation
        previous = self._prior_observation
        if current is None:
            return None
        x, y, width, height = current.bbox
        if previous is None:
            return current.bbox
        px, py, _pw, _ph = previous.bbox
        limit_x, limit_y = max(2, width // 4), max(2, height // 4)
        dx = max(-limit_x, min(limit_x, x - px))
        dy = max(-limit_y, min(limit_y, y - py))
        return x + dx, y + dy, width, height

    def _control_tick(self) -> None:
        if self._closing: return
        if self.safety.state is AppState.RUNNING:
            reason = self._runtime_fault_reason(time.monotonic())
            if reason: self._trigger_fault(reason)
            else:
                try:
                    s, mode = self.settings, self.settings.operation_mode
                    if mode == "manual_rpm":
                        raw = float(self.manual_rpm_var.get())
                        command = self.gateway.set_expected_rpm(raw, s.rpm_limit)
                    else:
                        if mode == "manual_speed": speed = float(self.manual_speed_var.get())
                        else:
                            if self.latest_motion is None or not self.latest_motion.ready or self.latest_motion.expected_speed_mps is None:
                                raise MotionControlError("运动控制结果未就绪")
                            speed = self.latest_motion.expected_speed_mps
                        raw, command = self.gateway.set_expected_speed(speed, s.rpm_per_mps, s.motor_axis_sign, s.rpm_limit)
                    self.raw_rpm_var.set(f"{raw:+.1f} RPM"); self.sent_rpm_var.set(f"{command:+d} RPM")
                    estimated_speed = self.gateway.estimated_speed_mps(s.rpm_per_mps, s.motor_axis_sign)
                    self.estimated_speed_var.set(f"{estimated_speed:+.3f} m/s")
                    gcolor = "gn" if abs(command) < s.rpm_limit * 0.7 else ("am" if abs(command) < s.rpm_limit * 0.9 else "rd")
                    self._gauge.update(f"{command:+d}", float(command), gcolor)
                except (ValueError, MotionControlError, SupervisorClientError, MotorBackendError) as exc:
                    self._trigger_fault(f"控制命令失败：{exc}")
        else:
            self._gauge.update("--", 0, "cy")
        self.root.after(max(10, int(self.settings.command_interval_s * 1000)), self._control_tick)

    def _runtime_fault_reason(self, now: float) -> str | None:
        if not self.gateway.connected: return "运行中 TCP/监督进程断开"
        if not self.calibration.is_confirmed_for(self.settings): return "控制参数确认失效"
        if self.settings.operation_mode in FOLLOW_MODES:
            if not self.frame_source.is_open: return "摄像头断开"
            if not self.target_tracker.locked: return "CSRT 目标丢失"
            if self.latest_observation is None or now - self.latest_observation.timestamp > self.settings.vision_timeout_s:
                return "目标观测超时"
        return None

    def _safety_inputs(self, s: ControlSettings) -> SafetyInputs:
        follow = s.operation_mode in FOLLOW_MODES; source = self.frame_source.source
        return SafetyInputs(serial_connected=self.gateway.connected,
            telemetry_fresh=s.backend == "tcp" or self.latest_measured_rpm is not None,
            camera_ready=self.frame_source.is_open if follow else False,
            target_locked=self.target_tracker.locked if follow else False,
            calibration_confirmed=self.calibration.is_confirmed_for(s), directions_valid=True,
            motion_solution_valid=bool(self.latest_motion is not None and self.latest_motion.ready) if follow else False,
            offline_source=bool(source and source.offline_file), real_backend=s.backend == "tcp")

    def _poll_motor_events(self) -> None:
        if self._closing: return
        while True:
            try: event = self.gateway.events.get_nowait()
            except queue.Empty: break
            if event.kind == "telemetry" and event.telemetry is not None:
                self.latest_measured_rpm = event.telemetry.actual_rpm
                self.feedback_var.set(f"{event.telemetry.actual_rpm:+.1f} RPM")
            elif event.kind == "status": self.supervisor_var.set(event.message or "--")
            elif event.kind == "error": self._trigger_fault(event.message)
            elif event.kind in ("notice", "warning"): self.detail_var.set(event.message)
        self.root.after(50, self._poll_motor_events)

    def _trigger_fault(self, reason: str) -> None:
        first = self.safety.fault(reason)
        if self.gateway.connected:
            try: self.gateway.stop()
            except SupervisorClientError: pass
        self._stop_recording(silent=True)
        self.frame_source.close(); self.target_tracker.clear(); self._clear_media_display()
        self._reset_control_history(clear_target=False)
        self.detail_var.set(f"故障：{reason}。已请求停车，故障不会自动恢复。")
        if first and not self._fault_popup_shown:
            self._fault_popup_shown = True
            messagebox.showerror("控制故障", f"{reason}\n\n已请求停车；TCP 模式无法确认实际停止。")

    def _reset_control_history(self, clear_target: bool = True) -> None:
        if self.motion_controller: self.motion_controller.reset()
        self.gateway.reset_rate_limit(); self.latest_motion = None
        if clear_target:
            self.latest_observation = None
            self._prior_observation = None
        self.raw_rpm_var.set("-- RPM"); self.sent_rpm_var.set("0 RPM")
        self.expected_speed_var.set("-- m/s"); self.offset_var.set("-- px / -- m")
        self.estimated_speed_var.set("0.000 m/s"); self._gauge.update("--", 0, "cy")

    def _refresh_status(self) -> None:
        if self._closing: return
        self._consume_camera_scan_results()
        state = self.safety.state
        source = self.frame_source.source
        offline_open = bool(source and source.offline_file and self.frame_source.is_open)
        self.state_var.set("视频分析" if offline_open and not self.gateway.connected else STATE_LABELS[state])
        if state is AppState.RUNNING:
            self._pulse.set_color(P["cy"], pulse=True); self._state_label.configure(fg=P["cy2"])
            self.banner.configure(bg=P["gn3"], fg=P["gn2"])
        elif state is AppState.FAULT:
            self._pulse.set_color(P["rd"], pulse=True); self._state_label.configure(fg=P["rd2"])
            self.banner.configure(bg=P["rd3"], fg=P["rd2"])
        elif state is AppState.STOPPED:
            self._pulse.set_color(P["gn"], pulse=False); self._state_label.configure(fg=P["gn2"])
            self.banner.configure(bg=P["cy4"], fg=P["cy2"])
        else:
            self._pulse.set_color(P["tx4"], pulse=False); self._state_label.configure(fg=P["tx2"])
            self.banner.configure(bg=P["cy4"], fg=P["cy3"])
        if state is AppState.RUNNING:
            banner_text = f"{MODE_LABELS.get(self.settings.operation_mode, '')} · {self.gateway.commanded_rpm_estimate:+d} RPM"
        elif state is AppState.FAULT:
            banner_text = f"⚠ {self.safety.fault_reason}"
        elif offline_open:
            banner_text = "离线分析模式 · 不会向真实电机发送命令"
        else:
            banner_text = STATE_LABELS[state]
        self.banner_var.set(banner_text)
        connected = self.gateway.connected; blocked = state in (AppState.RUNNING, AppState.FAULT)
        self.connect_button.configure(state="disabled" if connected else "normal")
        self.disconnect_button.configure(state="normal" if connected else "disabled")
        self.open_camera_button.configure(state="disabled" if blocked else "normal")
        self.upload_video_button.configure(state="disabled" if blocked else "normal")
        self.close_media_button.configure(state="normal" if self.frame_source.is_open and not blocked else "disabled")
        self.visual_processing_box.configure(state="disabled" if blocked else "readonly")
        self.select_target_button.configure(state="normal" if self.frame_source.is_open and not blocked else "disabled")
        can_analyze = offline_open and self.target_tracker.locked and not blocked
        self.analysis_button.configure(
            state="normal" if can_analyze else "disabled",
            text="▶ 继续分析" if self._media_paused else "Ⅱ 暂停分析",
        )
        self.record_button.configure(
            state="normal" if (self.frame_source.is_open and not blocked) or self.recorder.is_recording else "disabled",
            text="■ 停止录制" if self.recorder.is_recording else "● 开始录制",
        )
        self.start_button.configure(state="normal" if connected and not blocked else "disabled")
        self.stop_button.configure(state="normal" if connected else "disabled")
        self.ack_fault_button.configure(state="normal" if state is AppState.FAULT else "disabled")
        self.scan_camera_button.configure(state="disabled" if self._scan_running else "normal")
        cal_text = self.calibration_var.get()
        self._cal_lbl.configure(fg=P["gn2"] if "已确认" in cal_text else P["tx3"])
        self.root.after(100, self._refresh_status)

    def _render_image(self, bgr_image) -> None:
        self._last_rendered_frame = bgr_image
        image = Image.fromarray(bgr_image[:, :, ::-1])
        w = max(320, self._hud.winfo_width()); h = max(240, self._hud.winfo_height())
        image.thumbnail((w, h), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(image)
        self.video_label.configure(image=self._photo, text="")
        self.video_label.place(relx=0.5, rely=0.5, anchor="center")

    def on_close(self) -> None:
        if self._closing: return
        if self.safety.state is AppState.RUNNING and not messagebox.askyesno("确认退出", "退出将发送停车命令，是否继续？", icon="warning"): return
        self._closing = True; self._wave.stop(); self._stop_recording(silent=True)
        self.gateway.close(); self.frame_source.close(); self.target_tracker.clear(); self.root.destroy()

    def run(self) -> None: self.root.mainloop()


def main() -> None: SwimControlApp().run()
if __name__ == "__main__": main()
