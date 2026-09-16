from __future__ import annotations

import json
import os
from dataclasses import asdict, fields
from pathlib import Path

from vision_app.settings import ControlSettings, SettingsError


class AppConfigError(RuntimeError):
    pass


def default_config_path() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home())
    return base / "SwimmerTracker" / "settings.json"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_settings(path: Path | None = None) -> ControlSettings:
    target = path or default_config_path()
    if not target.exists():
        return ControlSettings().validated()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise AppConfigError("配置文件顶层必须是对象")
        # Never migrate an old real backend into the new TCP backend implicitly.
        if payload.get("backend") in ("arduino_serial", "python_can"):
            payload["backend"] = "virtual"
        payload["control_mode"] = "driver_pid"
        allowed = {field.name for field in fields(ControlSettings)}
        settings = ControlSettings(
            **{key: value for key, value in payload.items() if key in allowed}
        )
        return settings.validated()
    except (
        OSError,
        json.JSONDecodeError,
        TypeError,
        SettingsError,
        AppConfigError,
    ) as exc:
        raise AppConfigError(f"无法读取配置 {target}: {exc}") from exc


def save_settings(settings: ControlSettings, path: Path | None = None) -> Path:
    settings.validated()
    target = path or default_config_path()
    temporary = target.with_suffix(".tmp")
    try:
        _ensure_parent(target)
        temporary.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    except OSError as exc:
        raise AppConfigError(f"无法保存配置 {target}: {exc}") from exc
    return target


# ── TCP IP 历史记录 ──────────────────────────────────────────────
# 独立于 ControlSettings 存放，避免改 frozen dataclass 的字段定义。
_MAX_HISTORY = 8
_DEFAULT_HOSTS = ["192.168.1.177"]


def _history_path(settings_path: Path | None = None) -> Path:
    base = settings_path or default_config_path()
    return base.parent / "tcp_host_history.json"


def load_tcp_host_history(settings_path: Path | None = None) -> list[str]:
    """Load saved TCP host list; always includes the default address."""
    target = _history_path(settings_path)
    if not target.exists():
        return list(_DEFAULT_HOSTS)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return list(_DEFAULT_HOSTS)
        hosts = [str(item).strip() for item in payload if isinstance(item, str) and item.strip()]
        if _DEFAULT_HOSTS[0] not in hosts:
            hosts = list(_DEFAULT_HOSTS) + hosts
        return hosts[:_MAX_HISTORY]
    except (OSError, json.JSONDecodeError):
        return list(_DEFAULT_HOSTS)


def save_tcp_host_history(hosts: list[str], settings_path: Path | None = None) -> None:
    """Persist the most-recently-used TCP host list (deduplicated, newest first)."""
    seen: set[str] = set()
    unique: list[str] = []
    for h in hosts:
        h = h.strip()
        if h and h not in seen:
            seen.add(h)
            unique.append(h)
    if _DEFAULT_HOSTS[0] not in seen:
        unique.append(_DEFAULT_HOSTS[0])
    target = _history_path(settings_path)
    try:
        _ensure_parent(target)
        target.write_text(
            json.dumps(unique[:_MAX_HISTORY], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass  # 非关键：保存失败不阻塞主流程
