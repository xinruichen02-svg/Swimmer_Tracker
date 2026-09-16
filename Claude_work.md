# Swimmer_Tracker 前端重构文档

> 本文档供后续 AI 或开发者理解本次前端重构的范围、设计决策和修改约定，便于在此基础上继续迭代。

## 变更概览

| 文件 | 变更类型 | 说明 |
| --- | --- | --- |
| `vision_app/ui_theme.py` | **新增** | 深色运动控制台主题系统：调色板、字体、ttk Style 全局配置、`metric_tile()` 指标卡片组件 |
| `vision_app/app_config.py` | 扩展 | 新增 `load_tcp_host_history()` / `save_tcp_host_history()`，IP 历史独立存于 `tcp_host_history.json` |
| `vision_app/swimming_app.py` | **重写 GUI** | `_build_ui()` 全部重建、`_on_backend_selected()` / `_refresh_status()` 接入主题色、新增 `_save_tcp_host()` |
| 其余 `.py` 文件 | **未修改** | 控制逻辑、安全状态机、监督进程、TCP 后端、CAN 协议、跟踪器、测试均保持原样 |

## 设计系统：`ui_theme.py`

### 调色板 `PALETTE`

所有颜色集中在 `PALETTE` 字典中，`swimming_app.py` 不硬编码任何色值。改颜色只需改这一处。

| 键 | 用途 | 色值 |
| --- | --- | --- |
| `bg` | 窗口最底层 | `#0B1020` 深海军蓝 |
| `card` | 卡片/面板内部 | `#131D33` |
| `card_border` | 卡片描边 | `#223052` |
| `field` / `field_border` | 输入框内槽与描边 | `#0E1730` / `#26355C` |
| `video_bg` | 视频区底色 | `#050912` |
| `accent` | 品牌青色（按钮、强调） | `#22D3EE` |
| `success` / `danger` / `warning` / `info` | 状态语义色 | 绿 / 红 / 黄 / 蓝 |
| `*_soft` | 对应语义色的深底版（用于徽章、横幅背景） |  |
| `*_fg` / `*_text_on` | 对应语义色上的前景色 |  |

### 字体 `FONTS`

`apply_theme()` 调用后填充，键名：`title` / `subtitle` / `tag` / `state` / `section` / `label` / `field` / `button` / `value` / `placeholder`。

西文等宽用 Consolas，中文用 Microsoft YaHei UI，标签用 Segoe UI。

### ttk Style 名称

| Style | 用途 |
| --- | --- |
| `Card.TLabelframe` / `Card.TLabelframe.Label` | 分区卡片，青色标题悬浮在边框上 |
| `Field.TLabel` | 参数名标签（灰色次要文字） |
| `Header.TLabel` / `Subtitle.TLabel` | 顶栏大标题 / 副标题 |
| `Value.TLabel` | 指标区数值 |
| `Primary.TButton` | 主操作（青色） |
| `Success.TButton` | 启动 / 确认（绿色） |
| `Danger.TButton` | 停止 / 断开（红色） |
| `Warning.TButton` | 故障复位（黄底黄字） |
| `Secondary.TButton` | 辅助操作（深蓝灰） |

### 辅助组件

`metric_tile(parent, title, textvariable) -> tk.Frame`：返回一个带描边的指标卡，内含小号灰色标题 + 大号等宽数值。

## IP 历史记录

- **存储位置**：与 `settings.json` 同目录下的 `tcp_host_history.json`，格式为字符串数组。
- **最大条数**：8（`app_config._MAX_HISTORY`）。
- **默认值**：始终包含 `192.168.1.177`，不会被删除。
- **触发时机**：`connect_motor()` 连接 TCP 成功后调用 `_save_tcp_host()`，把当前 IP 推到最前、去重、持久化、刷新 Combobox 的 `values`。
- **GUI 控件**：`tcp_host_box`（`ttk.Combobox`，可编辑），用户可从历史选也可手动输入新 IP。
- **`ControlSettings.tcp_host` 字段**：未变，仍是 `str`，默认 `192.168.1.177`。

## 修改约定

1. **颜色只改 `PALETTE`**，不要在 `swimming_app.py` 或其他文件里直接写 `#RRGGBB`。
2. **新增 ttk Style 先在 `ui_theme.py` 注册**，然后通过 `style="XXX.TButton"` 引用。
3. **测试兼容性**：`test_gui_smoke.py` 断言了 `backend_badge_var.get()` 含 `"virtual"`、`open_camera_button` 的 `state`、`camera_source_box` 的 `values` 元组——这三个控件的变量名和语义必须保留。
4. **`_build_ui()` 中创建的所有带 `self.xxx` 引用的控件**（按钮、标签、输入框等）被 `_refresh_status()` / `_on_backend_selected()` 等方法在运行时 configure，不要改名字或移除。
5. **IP 历史与 `ControlSettings` 解耦**：不要把 `tcp_host_history` 字段加到 frozen dataclass 里，它通过 `app_config` 的独立函数管理。

## 布局结构速查

```
root (bg)
├── outer (padding=16, 2列: 左3 右2)
│   ├── row 0: header
│   │   ├── SWIMMER_TRACKER (title, accent) + 副标题
│   │   └── state_chip (右侧状态胶囊)
│   ├── row 1: banner (全宽状态条)
│   ├── row 2: 左列 (画面 + 指标) ｜ 右列 (控制面板)
│   │   ├── 左列
│   │   │   ├── video_frame (深黑底, 带描边)
│   │   │   └── metrics_row (2行×3列指标卡)
│   │   └── 右列 (Canvas + Scrollbar)
│   │       └── panel
│   │           ├── ① 电机与画面连接 (Card)
│   │           ├── ② 模式与基础参数 (Card)
│   │           ├── ③ 高级参数 (Card, 可折叠)
│   │           ├── ④ 操作 (Card)
│   │           └── detail (底部详情文字)
```

## 验证方法

```powershell
# 运行现有单元测试（GUI 冒烟测试需有 DISPLAY）
py -m unittest discover -s vision_app/tests -v

# 手动启动 APP，检查：
# 1. 深色主题是否正确渲染
# 2. TCP IP 下拉框是否可编辑、是否包含 192.168.1.177
# 3. 选择 tcp 后端 → 徽章变红、选择 virtual → 徽章变蓝
# 4. 连接 TCP 后 IP 被保存，重启 APP 后历史仍在
# 5. 各按钮颜色：连接=青、启动=绿、停止=红、复位=黄
# 6. 实时指标卡显示正常（偏差/速度/RPM）
py vision_app\swimming_gui.py
```

## 已知限制

- tkinter 的 clam 主题对部分控件（如 Combobox 下拉列表）的样式控制有限，通过 `option_add` 设置了下拉列表颜色，但在某些 Linux 桌面下可能不完全生效。
- Windows 上 emoji 字符（📡、📹 等）依赖系统字体回退，极少数旧系统可能显示方框——不影响功能。
- IP 历史保存是非关键的（`save_tcp_host_history` 内部 catch OSError），保存失败不阻塞主流程。
