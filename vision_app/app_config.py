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


def load_settings(path: Path | None = None) -> ControlSettings:
    target = path or default_config_path()
    if not target.exists():
        return ControlSettings().validated()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise AppConfigError("配置文件顶层必须是对象")
        allowed = {field.name for field in fields(ControlSettings)}
        settings = ControlSettings(**{key: value for key, value in payload.items() if key in allowed})
        return settings.validated()
    except (OSError, json.JSONDecodeError, TypeError, SettingsError, AppConfigError) as exc:
        raise AppConfigError(f"无法读取配置 {target}: {exc}") from exc


def save_settings(settings: ControlSettings, path: Path | None = None) -> Path:
    settings.validated()
    target = path or default_config_path()
    temporary = target.with_suffix(".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    except OSError as exc:
        raise AppConfigError(f"无法保存配置 {target}: {exc}") from exc
    return target

