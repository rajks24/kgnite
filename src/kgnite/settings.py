from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_WORKSPACE_DIR = "/Users/rajeshsingh/myprojects/kaggle"
DEFAULT_SETTINGS: dict[str, Any] = {
    "workspace_dir": DEFAULT_WORKSPACE_DIR,
    "competitions_dir": "competitions",
    "projects_dir": "projects",
    "kaggle_username": "rajinh",
    "default_dataset_license": "CC0-1.0",
}
SETTING_KEYS = frozenset(DEFAULT_SETTINGS)


def settings_path() -> Path:
    override = os.environ.get("KGNITE_SETTINGS_PATH")
    return (
        Path(override).expanduser()
        if override
        else Path.home() / ".config" / "kgnite" / "settings.json"
    )


def load_settings() -> dict[str, Any]:
    path = settings_path()
    values = dict(DEFAULT_SETTINGS)
    if path.is_file():
        content = path.read_text().strip()
        loaded = json.loads(content) if content else {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Settings must contain a JSON object: {path}")
        values.update({key: value for key, value in loaded.items() if key in SETTING_KEYS})
    values["settings_file"] = str(path)
    values["workspace_dir"] = str(Path(values["workspace_dir"]).expanduser().resolve())
    return values


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    unknown = set(updates) - SETTING_KEYS
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
    current = load_settings()
    current.pop("settings_file", None)
    current.update({key: value for key, value in updates.items() if value is not None})
    workspace = Path(str(current["workspace_dir"])).expanduser().resolve()
    current["workspace_dir"] = str(workspace)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n")
    (workspace / str(current["competitions_dir"])).mkdir(parents=True, exist_ok=True)
    (workspace / str(current["projects_dir"])).mkdir(parents=True, exist_ok=True)
    return load_settings()


def workspace_subdir(kind: str, name: str) -> Path:
    settings = load_settings()
    key = "competitions_dir" if kind == "competition" else "projects_dir"
    return Path(settings["workspace_dir"]) / str(settings[key]) / name
