from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from priceradar.notifier import NotificationConfig


@dataclass
class Settings:
    database_path: Path


def load_settings(*, db_path_override: Path | None = None) -> Settings:
    db_path_env = os.environ.get("PRICERADAR_DB_PATH")
    db_path = (
        Path(db_path_env) if db_path_env else (db_path_override or Path("data/priceradar.duckdb"))
    )
    db_path = db_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(database_path=db_path)


_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def load_notification_config(config_path: Path) -> NotificationConfig:
    if not config_path.exists():
        return NotificationConfig(enabled=False, channels=[])

    loaded = cast(object, yaml.safe_load(config_path.read_text(encoding="utf-8")))
    root = cast(dict[str, Any], loaded if isinstance(loaded, dict) else {})
    notifications = cast(dict[str, Any], root.get("notifications", {}))

    channels = notifications.get("channels", [])
    if not isinstance(channels, list):
        channels = []

    return NotificationConfig(
        enabled=bool(notifications.get("enabled", False)),
        channels=[str(channel) for channel in channels],
        email_settings=_resolve_env_refs(cast(dict[str, Any], notifications.get("email", {}))),
        webhook_url=str(_resolve_env_refs(notifications.get("webhook_url", ""))),
        telegram_config=_resolve_env_refs(cast(dict[str, Any], notifications.get("telegram", {}))),
        rules=_resolve_env_refs(cast(dict[str, Any], notifications.get("rules", {}))),
    )


def _resolve_env_refs(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda match: os.environ.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [_resolve_env_refs(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _resolve_env_refs(item) for key, item in value.items()}
    return value
