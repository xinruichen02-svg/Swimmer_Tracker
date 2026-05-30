from __future__ import annotations

import csv
import math
import time
from collections import deque
from pathlib import Path

import cv2
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import filedialog, messagebox, ttk


def create_tracker():
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    raise RuntimeError("CSRT tracker is not available in this OpenCV build.")


def center_of(bbox):
    x, y, w, h = bbox
    return x + w / 2.0, y + h / 2.0


class SwimApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Swim Speed Visualizer")
        self.root.geometry("1360x860")
        self.root.minsize(1120, 760)
        self.root.configure(bg="#edf2f7")

        self.source_var = tk.StringVar(value="0")
        self.scale_var = tk.StringVar(value="120")
        self.axis_var = tk.StringVar(value="xy")
        self.window_var = tk.StringVar(value="5")
        self.status_var = tk.StringVar(value="Ready. Open a camera or video first.")

        self.speed_var = tk.StringVar(value="0.00 m/s")
        self.pixel_speed_var = tk.StringVar(value="0.00 px/s")
        self.center_speed_var = tk.StringVar(value="0.00 m/s")
        self.offset_var = tk.StringVar(value="0.0 px / 0.0 px")
        self.delta_var = tk.StringVar(value="0.0 px / 0.0 px")
        self.elapsed_var = tk.StringVar(value="0.00 s")

        self.cap = None
        self.tracker = None
        self.last_frame = None
        self.photo = None
        self.job = None

        self.pixels_per_meter = 120.0
        self.measure_axis = "xy"
        self.smooth_window = 5
        self.speed_buffer = deque(maxlen=self.smooth_window)
        self.center_speed_buffer = deque(maxlen=self.smooth_window)
        self.history = deque(maxlen=240)
        self.path_points = deque(maxlen=80)

        self.prev_cx = 0.0
        self.prev_cy = 0.0
        self.prev_time = 0.0
        self.prev_offset_x = 0.0
        self.prev_offset_y = 0.0
        self.start_time = 0.0

        self._build_ui()
        self.chart.bind("<Configure>", lambda _event: self.draw_chart())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")

        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=4)
        outer.columnconfigure(1, weight=2)
        outer.rowconfigure(1, weight=1)

        title = ttk.Label(
            outer,
            text="Swim Speed Visualizer",
            font=("Segoe UI", 18, "bold"),
            background="#edf2f7",
        )
        title.grid(row=0, column=0, columnspan=2, sticky="w")

        subtitle = ttk.Label(
            outer,
            text="Live video, speed metrics, and history curves in one simple desktop tool.",
            background="#edf2f7",
            foreground="#475569",
        )
        subtitle.grid(row=0, column=0, columnspan=2, sticky="w", pady=(34, 10))

        left = ttk.Frame(outer)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=5)
        left.rowconfigure(1, weight=2)

        video_box = ttk.Frame(left, padding=10)
        video_box.grid(row=0, column=0, sticky="nsew")
        video_box.columnconfigure(0, weight=1)
        video_box.rowconfigure(0, weight=1)
        self.video_label = tk.Label(
            video_box,
            text="Live video will appear here",
            bg="#0f172a",
            fg="#e2e8f0",
            font=("Segoe UI", 14),
        )
        self.video_label.grid(row=0, column=0, sticky="nsew")

        chart_box = ttk.Frame(left, padding=10)
        chart_box.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        chart_box.columnconfigure(0, weight=1)
        chart_box.rowconfigure(0, weight=1)
        self.chart = tk.Canvas(chart_box, bg="#ffffff", highlightthickness=0)
        self.chart.grid(row=0, column=0, sticky="nsew")

        right = ttk.Frame(outer)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        source_box = ttk.LabelFrame(right, text="Source", padding=12)
        source_box.grid(row=0, column=0, sticky="ew")
        source_box.columnconfigure(0, weight=1)
        ttk.Label(source_box, text="Camera index or video path").grid(row=0, column=0, sticky="w")
        ttk.Entry(source_box, textvariable=self.source_var).grid(row=1, column=0, sticky="ew", pady=(6, 8))
        ttk.Button(source_box, text="Choose Video File", command=self.browse_file).grid(row=2, column=0, sticky="ew")

        params_box = ttk.LabelFrame(right, text="Settings", padding=12)
        params_box.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        params_box.columnconfigure(1, weight=1)
        ttk.Label(params_box, text="Pixels per meter").grid(row=0, column=0, sticky="w")
        ttk.Entry(params_box, textvariable=self.scale_var).grid(row=0, column=1, sticky="ew", padx=(10, 0))
        ttk.Label(params_box, text="Measure axis").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Combobox(params_box, textvariable=self.axis_var, values=("x", "y", "xy"), state="readonly").grid(
            row=1, column=1, sticky="ew", padx=(10, 0), pady=(10, 0)
        )
        ttk.Label(params_box, text="Smooth window").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(params_box, textvariable=self.window_var).grid(
            row=2, column=1, sticky="ew", padx=(10, 0), pady=(10, 0)
        )
        ttk.Button(params_box, text="Apply Settings", command=self.apply_settings).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0)
        )

        action_box = ttk.LabelFrame(right, text="Actions", padding=12)
        action_box.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        action_box.columnconfigure(0, weight=1)
        ttk.Button(action_box, text="Open Video", command=self.start_source).grid(row=0, column=0, sticky="ew")
        ttk.Button(action_box, text="Select Target", command=self.select_target).grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(action_box, text="Reset Tracking", command=self.reset_tracking).grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(action_box, text="Export CSV", command=self.export_csv).grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(action_box, text="Stop Video", command=self.stop_source).grid(row=4, column=0, sticky="ew", pady=(8, 0))

        metric_box = ttk.LabelFrame(right, text="Metrics", padding=12)
        metric_box.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        metric_box.columnconfigure(1, weight=1)
        rows = [
            ("Speed", self.speed_var),
            ("Pixel Speed", self.pixel_speed_var),
            ("Center Speed", self.center_speed_var),
            ("Target Offset", self.offset_var),
            ("Frame Delta", self.delta_var),
            ("Elapsed", self.elapsed_var),
        ]
        for row, (label, var) in enumerate(rows):
            ttk.Label(metric_box, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Label(metric_box, textvariable=var, font=("Segoe UI", 11, "bold")).grid(
                row=row, column=1, sticky="e", pady=4
            )

        status = ttk.Label(outer, textvariable=self.status_var, background="#edf2f7", foreground="#0f172a")
        status.grid(row=2, column=0, columnspan=2, sticky="w", pady=(14, 0))

    def browse_file(self):
        path = filedialog.askopenfilename(
            title="Choose Video File",
            filetypes=[("Video Files", "*.mp4 *.avi *.mov *.mkv"), ("All Files", "*.*")],
        )
        if path:
            self.source_var.set(path)

    def apply_settings(self):
        source = self.source_var.get().strip() or "0"
        if source.lstrip("-").isdigit():
            self.source_value = int(source)
        else:
            path = Path(source)
            if not path.exists():
                messagebox.showerror("Input Error", "The video file does not exist.")
                return False
            self.source_value = str(path)

        try:
            self.pixels_per_meter = float(self.scale_var.get())
            self.smooth_window = int(self.window_var.get())
        except ValueError:
            messagebox.showerror("Input Error", "Pixels per meter and smooth window must be numeric.")
            return False

        if self.pixels_per_meter <= 0 or self.smooth_window <= 0:
            messagebox.showerror("Input Error", "Pixels per meter and smooth window must be greater than zero.")
            return False

        self.measure_axis = self.axis_var.get().strip() or "xy"
        if self.measure_axis not in {"x", "y", "xy"}:
            messagebox.showerror("Input Error", "Measure axis must be x, y, or xy.")
            return False

        self.speed_buffer = deque(list(self.speed_buffer)[-self.smooth_window:], maxlen=self.smooth_window)
        self.center_speed_buffer = deque(list(self.center_speed_buffer)[-self.smooth_window:], maxlen=self.smooth_window)
        self.status_var.set("Settings applied.")
        return True

    def start_source(self):
        if not self.apply_settings():
            return

        self.stop_source(clear_placeholder=False)
        self.cap = cv2.VideoCapture(self.source_value)
        if not self.cap.isOpened():
            self.cap = None
            self.status_var.set("Could not open the selected video source.")
            messagebox.showerror("Open Failed", "Could not open the selected camera or video file.")
            return

        ok, frame = self.cap.read()
        if not ok:
            self.stop_source(clear_placeholder=False)
            self.status_var.set("First frame read failed.")
            messagebox.showerror("Open Failed", "Connected to the source but could not read the first frame.")
            return

        self.last_frame = frame
        self.tracker = None
        self.path_points.clear()
        self.history.clear()
        self.refresh_metrics()
        self.draw_chart()
        self.render_frame(self.process_frame(frame.copy()))
        self.status_var.set("Video opened. Click 'Select Target' to begin tracking.")
        self.job = self.root.after(30, self.update_loop)

    def stop_source(self, clear_placeholder=True):
        if self.job:
            self.root.after_cancel(self.job)
            self.job = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.tracker = None
        self.last_frame = None
        if clear_placeholder:
            self.video_label.configure(image="", text="Video stopped. Open a source to continue.")
            self.photo = None
        self.status_var.set("Video stopped.")

    def select_target(self):
        if self.last_frame is None:
            messagebox.showinfo("Hint", "Open a camera or video file first.")
            return

        frame = self.last_frame.copy()
        bbox = cv2.selectROI("Select Target", frame, fromCenter=False, showCrosshair=True)
        cv2.destroyWindow("Select Target")
        if bbox == (0, 0, 0, 0):
            self.status_var.set("Target selection cancelled.")
            return

        self.tracker = create_tracker()
        init_result = self.tracker.init(frame, tuple(int(v) for v in bbox))
        if init_result is False:
            self.tracker = None
            messagebox.showerror("Init Failed", "Tracker initialization failed. Please try again.")
            return

        self.prev_cx, self.prev_cy = center_of(tuple(int(v) for v in bbox))
        self.prev_time = time.time()
        self.start_time = self.prev_time
        self.prev_offset_x = 0.0
        self.prev_offset_y = 0.0
        self.speed_buffer.clear()
        self.center_speed_buffer.clear()
        self.history.clear()
        self.path_points.clear()
        self.path_points.append((int(self.prev_cx), int(self.prev_cy)))
        self.status_var.set("Target locked. Tracking is running.")

    def reset_tracking(self):
        self.tracker = None
        self.speed_buffer.clear()
        self.center_speed_buffer.clear()
        self.history.clear()
        self.path_points.clear()
        self.refresh_metrics()
        self.draw_chart()
        self.status_var.set("Tracking reset. Select a target again.")
        if self.last_frame is not None:
            self.render_frame(self.process_frame(self.last_frame.copy()))

    def export_csv(self):
        if not self.history:
            messagebox.showinfo("Hint", "There is no tracking data to export yet.")
            return

        save_dir = Path.cwd() / "save"
        save_dir.mkdir(parents=True, exist_ok=True)
        default_name = time.strftime("swimming_metrics_%Y%m%d_%H%M%S.csv")
        save_path = filedialog.asksaveasfilename(
            title="Export CSV",
            defaultextension=".csv",
            initialdir=save_dir,
            initialfile=default_name,
            filetypes=[("CSV Files", "*.csv")],
        )
        if not save_path:
            return

        with Path(save_path).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["elapsed_s", "speed_m_s", "center_speed_m_s", "dx_px", "dy_px", "offset_x_px", "offset_y_px"])
            for row in self.history:
                writer.writerow(row)
        self.status_var.set(f"CSV exported to {save_path}")

    def update_loop(self):
        if self.cap is None:
            return

        ok, frame = self.cap.read()
        if not ok:
            self.job = None
            self.status_var.set("Video ended or frame read failed.")
            return

        self.last_frame = frame
        annotated = self.process_frame(frame.copy())
        self.render_frame(annotated)
        self.job = self.root.after(30, self.update_loop)

    def process_frame(self, frame):
        tracking_frame = frame.copy()
        height, width = frame.shape[:2]
        center_x = width // 2
        center_y = height // 2
        cv2.line(frame, (0, center_y), (width, center_y), (235, 235, 235), 1)
        cv2.line(frame, (center_x, 0), (center_x, height), (235, 235, 235), 1)
        cv2.rectangle(frame, (0, 0), (width, 34), (26, 36, 46), -1)

        if self.tracker is None:
            cv2.putText(frame, "Select a target to start tracking", (14, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1)
            return frame

        now = time.time()
        dt = max(now - self.prev_time, 1e-6)
        ok, bbox = self.tracker.update(tracking_frame)
        if not ok:
            self.prev_time = now
            self.status_var.set("Tracking lost. Please select the target again.")
            cv2.putText(frame, "Tracking lost", (14, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1)
            cv2.putText(frame, "Tracking lost", (18, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 85, 255), 2)
            return frame

        x, y, w, h = [int(v) for v in bbox]
        cx, cy = center_of((x, y, w, h))
        dx = cx - self.prev_cx
        dy = cy - self.prev_cy
        if self.measure_axis == "x":
            disp = dx
        elif self.measure_axis == "y":
            disp = dy
        else:
            disp = math.hypot(dx, dy)

        speed_px = disp / dt
        speed_m = (disp / self.pixels_per_meter) / dt
        self.speed_buffer.append(speed_m)
        smooth_speed = sum(self.speed_buffer) / len(self.speed_buffer)

        offset_x = cx - center_x
        offset_y = cy - center_y
        center_disp = math.hypot(offset_x - self.prev_offset_x, offset_y - self.prev_offset_y)
        center_speed = (center_disp / self.pixels_per_meter) / dt
        self.center_speed_buffer.append(center_speed)
        smooth_center_speed = sum(self.center_speed_buffer) / len(self.center_speed_buffer)

        elapsed = now - self.start_time
        self.history.append(
            (
                f"{elapsed:.3f}",
                f"{smooth_speed:.5f}",
                f"{smooth_center_speed:.5f}",
                f"{dx:.3f}",
                f"{dy:.3f}",
                f"{offset_x:.3f}",
                f"{offset_y:.3f}",
            )
        )
        self.path_points.append((int(cx), int(cy)))

        points = list(self.path_points)
        for index in range(1, len(points)):
            cv2.line(frame, points[index - 1], points[index], (14, 113, 255), 1 + index // 20)

        cv2.rectangle(frame, (x, y), (x + w, y + h), (30, 207, 149), 2)
        cv2.circle(frame, (int(cx), int(cy)), 5, (35, 78, 255), -1)
        cv2.putText(frame, "Tracking stable", (14, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1)
        cv2.putText(frame, f"Speed {smooth_speed:+.2f} m/s", (18, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, f"Offset {offset_x:+.1f}px / {offset_y:+.1f}px", (18, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.63, (255, 255, 255), 2)

        self.prev_cx = cx
        self.prev_cy = cy
        self.prev_time = now
        self.prev_offset_x = offset_x
        self.prev_offset_y = offset_y
        self.refresh_metrics(smooth_speed, speed_px, smooth_center_speed, offset_x, offset_y, dx, dy, elapsed)
        self.draw_chart()
        self.status_var.set("Tracking stable.")
        return frame

    def refresh_metrics(self, speed=0.0, px_speed=0.0, center_speed=0.0, offx=0.0, offy=0.0, dx=0.0, dy=0.0, elapsed=0.0):
        self.speed_var.set(f"{speed:+.2f} m/s")
        self.pixel_speed_var.set(f"{px_speed:+.2f} px/s")
        self.center_speed_var.set(f"{center_speed:+.2f} m/s")
        self.offset_var.set(f"{offx:+.1f}px / {offy:+.1f}px")
        self.delta_var.set(f"{dx:+.1f}px / {dy:+.1f}px")
        self.elapsed_var.set(f"{elapsed:.2f} s")

    def draw_chart(self):
        self.chart.delete("all")
        width = max(self.chart.winfo_width(), 320)
        height = max(self.chart.winfo_height(), 180)
        left, top, right, bottom = 42, 16, width - 14, height - 32

        self.chart.create_rectangle(left, top, right, bottom, outline="#cbd5e1")
        self.chart.create_text(left, 4, text="Speed history", anchor="nw", fill="#0f172a", font=("Segoe UI", 10, "bold"))

        if not self.history:
            self.chart.create_text(width / 2, height / 2, text="History will appear after tracking starts", fill="#64748b")
            return

        times = [float(item[0]) for item in self.history]
        speeds = [float(item[1]) for item in self.history]
        center_speeds = [float(item[2]) for item in self.history]
        values = speeds + center_speeds
        min_v = min(values)
        max_v = max(values)
        if abs(max_v - min_v) < 1e-6:
            min_v -= 1.0
            max_v += 1.0

        span_x = max(times[-1], 1.0)
        span_y = max_v - min_v
        plot_w = max(right - left, 1)
        plot_h = max(bottom - top, 1)

        for index in range(5):
            y = top + index * plot_h / 4
            self.chart.create_line(left, y, right, y, fill="#e2e8f0")

        def to_points(series):
            points = []
            for x_value, y_value in zip(times, series):
                x = left + x_value / span_x * plot_w
                y = bottom - (y_value - min_v) / span_y * plot_h
                points.extend([x, y])
            return points

        speed_points = to_points(speeds)
        center_points = to_points(center_speeds)
        if len(speed_points) >= 4:
            self.chart.create_line(*speed_points, fill="#2563eb", width=2, smooth=True)
        if len(center_points) >= 4:
            self.chart.create_line(*center_points, fill="#059669", width=2, dash=(6, 3), smooth=True)

        self.chart.create_text(left, bottom + 12, text="0 s", anchor="nw", fill="#475569")
        self.chart.create_text(right, bottom + 12, text=f"{times[-1]:.1f} s", anchor="ne", fill="#475569")
        self.chart.create_text(left, top - 2, text=f"{max_v:.2f}", anchor="sw", fill="#475569")
        self.chart.create_text(left, bottom + 2, text=f"{min_v:.2f}", anchor="nw", fill="#475569")
        self.chart.create_line(right - 130, top + 8, right - 105, top + 8, fill="#2563eb", width=2)
        self.chart.create_text(right - 98, top + 8, text="Body speed", anchor="w", fill="#2563eb")
        self.chart.create_line(right - 130, top + 26, right - 105, top + 26, fill="#059669", width=2, dash=(6, 3))
        self.chart.create_text(right - 98, top + 26, text="Center speed", anchor="w", fill="#059669")

    def render_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        target_w = max(self.video_label.winfo_width(), 960)
        target_h = max(self.video_label.winfo_height(), 540)
        image.thumbnail((target_w, target_h))
        self.photo = ImageTk.PhotoImage(image)
        self.video_label.configure(image=self.photo, text="")

    def on_close(self):
        if self.job:
            self.root.after_cancel(self.job)
            self.job = None
        if self.cap is not None:
            self.cap.release()
        cv2.destroyAllWindows()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    SwimApp().run()


if __name__ == "__main__":
    main()
