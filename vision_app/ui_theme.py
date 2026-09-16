from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

try:
    import tkinter.font as tkfont
except ImportError:
    tkfont = None


# ═══════════════════════════════════════════════════════════════
#  调色板
# ═══════════════════════════════════════════════════════════════
P: dict[str, str] = {
    "bg":           "#04080F",
    "bg2":          "#0A1120",
    "card":         "#0D1929",
    "card_hi":      "#112240",
    "border":       "#1B2B4A",
    "border_dim":   "#132040",
    "field":        "#080E1C",
    "field_b":      "#1A2D50",
    "vid_bg":       "#020508",
    "vid_glow":     "#0C4A5E",
    "tx":           "#E2E8F0",
    "tx2":          "#8899B0",
    "tx3":          "#4A5E7A",
    "tx4":          "#2E3E56",
    "cy":           "#06D6A0",
    "cy2":          "#0EF5BA",
    "cy3":          "#048866",
    "cy4":          "#022E20",
    "gn":           "#10B981",
    "gn2":          "#34D399",
    "gn3":          "#05392B",
    "rd":           "#F43F5E",
    "rd2":          "#FB7185",
    "rd3":          "#5C1A28",
    "am":           "#F59E0B",
    "am2":          "#FBBF24",
    "am3":          "#5C3D08",
    "bl":           "#3B82F6",
    "bl2":          "#60A5FA",
    "bl3":          "#1A3566",
}

F: dict[str, "tkfont.Font"] = {}


def _mk_fonts(root: tk.Tk) -> dict[str, "tkfont.Font"]:
    cn, mo, ui = "Microsoft YaHei UI", "Consolas", "Segoe UI"
    return {n: tkfont.Font(root=root, font=f) for n, f in {
        "logo":      (cn, 24, "bold"),   "logo2":  (ui, 9),
        "st_big":    (cn, 14, "bold"),   "st_sm":  (ui, 8, "bold"),
        "sec":       (ui, 9, "bold"),    "lbl":    (cn, 9),
        "lbl2":      (cn, 8),            "fld":    (cn, 10),
        "btn":       (cn, 9, "bold"),    "btn2":   (ui, 8, "bold"),
        "v_lg":      (mo, 20, "bold"),   "v_md":   (mo, 13, "bold"),
        "v_sm":      (mo, 10, "bold"),   "hint":   (cn, 12),
        "g_lbl":     (ui, 7),            "g_val":  (mo, 12, "bold"),
        "g_tick":    (mo, 7),
    }.items()}


def _btn(s: ttk.Style, n: str, *, bg: str, fg: str, pr: str) -> None:
    s.configure(n, background=bg, foreground=fg, font=F["btn"],
                borderwidth=0, focusthickness=0, focuscolor=bg, padding=(14, 7))
    s.map(n, background=[("disabled", P["field"]), ("pressed", pr), ("active", pr)],
          foreground=[("disabled", P["tx4"])])


def apply_theme(root: tk.Tk) -> None:
    if not F: F.update(_mk_fonts(root))
    root.configure(bg=P["bg"])
    s = ttk.Style(root)
    try: s.theme_use("clam")
    except tk.TclError: pass

    s.configure(".", background=P["bg"], foreground=P["tx"], font=F["lbl"], borderwidth=0)
    s.configure("TFrame", background=P["bg"])
    s.configure("TLabelframe", background=P["card"], bordercolor=P["border"],
                relief="solid", borderwidth=1, labelmargins=(10, 0, 10, 4))
    s.configure("TLabelframe.Label", background=P["bg"], foreground=P["cy"],
                font=F["sec"], padding=(6, 1))
    s.configure("TLabel", background=P["card"], foreground=P["tx"], font=F["lbl"])
    s.configure("D.TLabel", background=P["card"], foreground=P["tx2"], font=F["lbl2"])
    s.configure("F.TLabel", background=P["bg"], foreground=P["tx3"], font=F["lbl2"])
    s.configure("TEntry", fieldbackground=P["field"], foreground=P["tx"],
                insertcolor=P["cy"], bordercolor=P["field_b"],
                lightcolor=P["field"], darkcolor=P["field"], padding=(8, 5))
    s.map("TEntry", bordercolor=[("focus", P["cy"])],
          lightcolor=[("focus", P["cy"])],
          fieldbackground=[("disabled", P["field"]), ("readonly", P["field"])])
    s.configure("TCombobox", fieldbackground=P["field"], background=P["field"],
                foreground=P["tx"], arrowcolor=P["cy3"],
                bordercolor=P["field_b"], lightcolor=P["field"],
                darkcolor=P["field"], padding=(8, 5))
    s.map("TCombobox", fieldbackground=[("readonly", P["field"])],
          foreground=[("readonly", P["tx"])], bordercolor=[("focus", P["cy"])])
    root.option_add("*TCombobox*Listbox.background", P["card"])
    root.option_add("*TCombobox*Listbox.foreground", P["tx"])
    root.option_add("*TCombobox*Listbox.selectBackground", P["cy4"])
    root.option_add("*TCombobox*Listbox.selectForeground", P["cy2"])
    root.option_add("*TCombobox*Listbox.font", F["fld"])

    _btn(s, "C.TButton",  bg=P["cy4"],  fg=P["cy2"], pr=P["cy3"])
    _btn(s, "G.TButton",  bg=P["gn3"],  fg=P["gn2"], pr="#0A7B5E")
    _btn(s, "R.TButton",  bg=P["rd3"],  fg=P["rd2"], pr="#991B1B")
    _btn(s, "A.TButton",  bg=P["am3"],  fg=P["am2"], pr="#92400E")
    _btn(s, "X.TButton",  bg=P["bg2"],  fg=P["tx2"], pr=P["card"])
    for n, bg, fg, pr in [("Cs.TButton", P["cy4"], P["cy2"], P["cy3"]),
                           ("Xs.TButton", P["bg2"], P["tx2"], P["card"])]:
        s.configure(n, background=bg, foreground=fg, font=F["btn2"],
                    borderwidth=0, focusthickness=0, focuscolor=bg, padding=(8, 4))
        s.map(n, background=[("disabled", P["field"]), ("pressed", pr), ("active", pr)],
              foreground=[("disabled", P["tx4"])])
    s.configure("TCheckbutton", background=P["card"], foreground=P["tx2"],
                font=F["lbl2"], focuscolor=P["card"])
    s.map("TCheckbutton", background=[("active", P["card"])], foreground=[("active", P["tx"])])
    s.configure("Console.TNotebook", background=P["bg"], borderwidth=0,
                tabmargins=(0, 0, 0, 6))
    s.configure("Console.TNotebook.Tab", background=P["bg2"], foreground=P["tx3"],
                font=F["btn"], padding=(16, 8), borderwidth=0)
    s.map("Console.TNotebook.Tab",
          background=[("selected", P["card"]), ("active", P["card_hi"])],
          foreground=[("selected", P["cy2"]), ("active", P["tx2"])])
    s.configure("Vertical.TScrollbar", background=P["card"], troughcolor=P["bg"],
                bordercolor=P["bg"], arrowcolor=P["tx3"], relief="flat", width=6)
    s.map("Vertical.TScrollbar", background=[("active", P["border"])])


# ═══════════════════════════════════════════════════════════════
#  动画水波纹装饰条
# ═══════════════════════════════════════════════════════════════

class WaveBar:
    """在 Canvas 上绘制动态水波纹装饰，用 after() 驱动。"""
    def __init__(self, parent, height: int = 32, color: str = P["cy3"],
                 speed: int = 40) -> None:
        self.canvas = tk.Canvas(parent, height=height, bg=P["bg"], highlightthickness=0)
        self._h = height
        self._color = color
        self._phase = 0.0
        self._speed = speed
        self._0_ids: list[int] = []
        self._running = False

    @property
    def widget(self) -> tk.Canvas:
        return self.canvas

    def start(self) -> None:
        if self._running: return
        self._running = True
        self._tick()

    def stop(self) -> None:
        self._running = False

    def _tick(self) -> None:
        if not self._running: return
        c = self.canvas
        c.delete("wave")
        w = c.winfo_width()
        if w < 20:
            self.canvas.after(self._speed, self._tick)
            return
        # 两层波纹，不同振幅和频率
        for amp, freq, y_off, alpha_color in [
            (5, 0.035, 0.55, self._color),
            (3, 0.055, 0.65, P["cy4"]),
        ]:
            pts = []
            for x in range(0, w + 4, 4):
                y = self._h * y_off + amp * math.sin(freq * x + self._phase * (1.2 if y_off > 0.6 else 1.0))
                pts.extend([x, y])
            if len(pts) >= 4:
                c.create_line(pts, fill=alpha_color, width=2, smooth=True, tags="wave")
        self._phase += 0.15
        self.canvas.after(self._speed, self._tick)


# ═══════════════════════════════════════════════════════════════
#  脉冲状态指示灯
# ═══════════════════════════════════════════════════════════════

class PulseDot:
    """带呼吸动画的状态圆点。"""
    def __init__(self, parent, size: int = 12) -> None:
        self.canvas = tk.Canvas(parent, width=size, height=size,
                                bg=P["card"], highlightthickness=0)
        self._size = size
        self._r = size // 2 - 1
        cx, cy = size // 2, size // 2
        self._dot = self.canvas.create_oval(cx - self._r, cy - self._r,
                                             cx + self._r, cy + self._r,
                                             fill=P["tx4"], outline="")
        self._glow = self.canvas.create_oval(cx - self._r - 2, cy - self._r - 2,
                                              cx + self._r + 2, cy + self._r + 2,
                                              fill="", outline="", width=0)
        self._phase = 0.0
        self._running = False
        self._color = P["tx4"]

    @property
    def widget(self) -> tk.Canvas:
        return self.canvas

    def set_color(self, color: str, pulse: bool = True) -> None:
        self._color = color
        self.canvas.itemconfigure(self._dot, fill=color)
        if pulse and not self._running:
            self._running = True
            self._tick()
        elif not pulse:
            self._running = False
            self.canvas.itemconfigure(self._glow, outline="", width=0)

    def _tick(self) -> None:
        if not self._running: return
        # 微妙的光晕脉冲
        alpha = 0.3 + 0.3 * math.sin(self._phase)
        cx, cy = self._size // 2, self._size // 2
        gr = self._r + 2 + int(2 * alpha)
        self.canvas.itemconfigure(self._glow, outline=self._color, width=max(1, int(2 * alpha)))
        self.canvas.coords(self._glow, cx - gr, cy - gr, cx + gr, cy + gr)
        self._phase += 0.12
        self.canvas.after(50, self._tick)


# ═══════════════════════════════════════════════════════════════
#  圆弧转速表（带刻度线）
# ═══════════════════════════════════════════════════════════════

class ArcGauge:
    """专业仪表盘风格转速表：背景弧 + 刻度线 + 前景弧 + 中心数值。"""
    def __init__(self, parent, size: int = 110, thickness: int = 7,
                 max_rpm: int = 2047) -> None:
        self._max = max_rpm
        self.canvas = tk.Canvas(parent, width=size, height=size,
                                bg=P["card"], highlightthickness=0)
        cx, cy = size / 2, size / 2
        r = size / 2 - thickness - 4
        self._cx, self._cy, self._r = cx, cy, r
        self._start = 225
        self._extent = -270
        self._thick = thickness

        # 刻度线
        n_ticks = 27
        for i in range(n_ticks + 1):
            angle_deg = self._start + self._extent * i / n_ticks
            angle_rad = math.radians(angle_deg)
            is_major = (i % 9 == 0)
            tick_len = 6 if is_major else 3
            x1 = cx + (r + 2) * math.cos(angle_rad)
            y1 = cy - (r + 2) * math.sin(angle_rad)
            x2 = cx + (r + 2 + tick_len) * math.cos(angle_rad)
            y2 = cy - (r + 2 + tick_len) * math.sin(angle_rad)
            self.canvas.create_line(x1, y1, x2, y2,
                                    fill=P["tx3"] if is_major else P["tx4"],
                                    width=1)

        # 刻度标签（0, 1/3, 2/3, max）
        for frac, label in [(0, "0"), (0.33, f"{int(max_rpm*0.33)}"),
                             (0.66, f"{int(max_rpm*0.66)}"), (1.0, str(max_rpm))]:
            angle_deg = self._start + self._extent * frac
            angle_rad = math.radians(angle_deg)
            lx = cx + (r + 14) * math.cos(angle_rad)
            ly = cy - (r + 14) * math.sin(angle_rad)
            self.canvas.create_text(lx, ly, text=label, fill=P["tx3"],
                                    font=F["g_tick"], anchor="center")

        # 背景弧
        self.canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                               start=self._start, extent=self._extent,
                               outline=P["border"], width=thickness, style="arc")
        # 前景弧
        self._fg = self.canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                                          start=self._start, extent=0,
                                          outline=P["cy"], width=thickness, style="arc")
        # 中心数值
        self._val = self.canvas.create_text(cx, cy, text="--", fill=P["tx"],
                                            font=F["g_val"], anchor="center")
        self.canvas.create_text(cx, cy + 14, text="RPM", fill=P["tx3"],
                                font=F["g_lbl"], anchor="center")

    @property
    def widget(self) -> tk.Canvas:
        return self.canvas

    def update(self, text: str, rpm: float, color: str = "cy") -> None:
        frac = max(0.0, min(1.0, abs(rpm) / max(1, self._max)))
        c = {"cy": P["cy"], "gn": P["gn"], "rd": P["rd"], "am": P["am"]}.get(color, P["cy"])
        self.canvas.itemconfigure(self._fg, extent=self._extent * frac, outline=c)
        self.canvas.itemconfigure(self._val, text=text)


# ═══════════════════════════════════════════════════════════════
#  指标卡片
# ═══════════════════════════════════════════════════════════════

def metric_card(parent, title: str, var, accent: str = "cy") -> tk.Frame:
    ac = {"cy": P["cy"], "gn": P["gn"], "rd": P["rd"],
          "am": P["am"], "bl": P["bl"]}.get(accent, P["cy"])
    outer = tk.Frame(parent, bg=P["card"], highlightbackground=P["border_dim"],
                     highlightthickness=1)
    bar = tk.Frame(outer, bg=ac, width=3)
    bar.pack(side="left", fill="y", pady=5)
    bar.pack_propagate(False)
    inner = tk.Frame(outer, bg=P["card"])
    inner.pack(side="left", fill="both", expand=True, padx=(10, 12), pady=(7, 7))
    tk.Label(inner, text=title, bg=P["card"], fg=P["tx3"],
             font=F["lbl2"], anchor="w").pack(fill="x")
    tk.Label(inner, textvariable=var, bg=P["card"], fg=P["tx"],
             font=F["v_lg"], anchor="w").pack(fill="x", pady=(2, 0))
    return outer


# ═══════════════════════════════════════════════════════════════
#  HUD 视频叠加绘制
# ═══════════════════════════════════════════════════════════════

def draw_hud(canvas: tk.Canvas) -> None:
    """在视频 Canvas 上绘制专业取景器 HUD。"""
    canvas.delete("hud")
    w, h = canvas.winfo_width(), canvas.winfo_height()
    if w < 80 or h < 80: return
    # 四角 L 形
    L = 30
    for x0, y0, dx, dy in [(2, 2, 1, 1), (w - 2, 2, -1, 1),
                            (2, h - 2, 1, -1), (w - 2, h - 2, -1, -1)]:
        canvas.create_line(x0, y0, x0 + dx * L, y0, fill=P["vid_glow"], width=2, tags="hud")
        canvas.create_line(x0, y0, x0, y0 + dy * L, fill=P["vid_glow"], width=2, tags="hud")
    # 中心十字
    cx, cy = w // 2, h // 2
    for length, color in [(18, P["cy3"]), (8, P["cy"])]:
        canvas.create_line(cx - length, cy, cx - 4, cy, fill=color, width=1, tags="hud")
        canvas.create_line(cx + 4, cy, cx + length, cy, fill=color, width=1, tags="hud")
        canvas.create_line(cx, cy - length, cx, cy - 4, fill=color, width=1, tags="hud")
        canvas.create_line(cx, cy + 4, cx, cy + length, fill=color, width=1, tags="hud")
    # 中心小圆
    canvas.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, outline=P["cy3"], width=1, tags="hud")
    # 底部信息条
    canvas.create_rectangle(0, h - 22, w, h, fill=P["bg"], stipple="gray50", outline="", tags="hud")
    canvas.create_text(10, h - 11, text="SWIMMER_TRACKER", fill=P["cy3"],
                       font=F["g_lbl"], anchor="w", tags="hud")
    canvas.create_text(w - 10, h - 11, text="CSRT ACTIVE", fill=P["tx3"],
                       font=F["g_lbl"], anchor="e", tags="hud")
    # 安全区竖线提示
    safe_x = int(w * 0.45)
    for sx in [cx - safe_x, cx + safe_x]:
        if 30 < sx < w - 30:
            canvas.create_line(sx, 30, sx, h - 30, fill=P["rd3"], width=1,
                               dash=(4, 8), tags="hud")
