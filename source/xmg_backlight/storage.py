"""Settings and profile storage helpers."""

from __future__ import annotations

import json
import os
import atexit
import fcntl

from .constants import (
    COLORS,
    CONFIG_DIR,
    DEFAULT_PROFILE_NAME,
    DEFAULT_PROFILE_STATE,
    DEFAULT_SETTINGS,
    DIRECTIONS,
    EFFECTS,
    LANGUAGE_LABELS,
    LOCK_FILE_PATH,
    PROFILE_PATH,
    SETTINGS_PATH,
)
from .ui_helpers import clamp_int, normalize_language_code, sanitize_choice


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def acquire_single_instance_lock():
    """Try to acquire an exclusive lock. Returns the file handle if successful."""
    ensure_config_dir()
    try:
        lock_file = open(LOCK_FILE_PATH, "w", encoding="utf-8")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        atexit.register(release_single_instance_lock, lock_file)
        return lock_file
    except (IOError, OSError):
        return None


def release_single_instance_lock(lock_file):
    if lock_file is None:
        return
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
    except (IOError, OSError):
        pass
    try:
        os.remove(LOCK_FILE_PATH)
    except (IOError, OSError):
        pass


def read_settings_file():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_settings_file(data):
    ensure_config_dir()
    tmp_path = SETTINGS_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp_path, SETTINGS_PATH)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def sanitize_settings(data):
    base = dict(DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return base
    base["start_in_tray"] = bool(data.get("start_in_tray", base["start_in_tray"]))
    base["show_notifications"] = bool(
        data.get("show_notifications", base["show_notifications"])
    )
    base["dark_mode"] = bool(data.get("dark_mode", base["dark_mode"]))
    base["ac_profile"] = str(data.get("ac_profile", base["ac_profile"]) or "")
    base["battery_profile"] = str(data.get("battery_profile", base["battery_profile"]) or "")
    language_value = normalize_language_code(data.get("language", ""))
    if language_value not in LANGUAGE_LABELS:
        language_value = ""
    base["language"] = language_value
    return base


def load_settings():
    raw = read_settings_file()
    return sanitize_settings(raw)


def read_profile_file():
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_profile_file(data):
    ensure_config_dir()
    tmp_path = PROFILE_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp_path, PROFILE_PATH)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def sanitize_profile_state(data):
    base = dict(DEFAULT_PROFILE_STATE)
    if not isinstance(data, dict):
        return base
    base["brightness"] = clamp_int(data.get("brightness"), 0, 50, base["brightness"])
    base["mode"] = sanitize_choice(data.get("mode"), EFFECTS, base["mode"])
    base["static_color"] = sanitize_choice(
        data.get("static_color"), COLORS, base["static_color"]
    )
    base["speed"] = clamp_int(data.get("speed"), 0, 10, base["speed"])
    color_value = data.get("color") or "none"
    if color_value != "none" and color_value not in COLORS:
        color_value = "none"
    base["color"] = color_value
    direction_value = sanitize_choice(
        data.get("direction"), DIRECTIONS, base["direction"]
    )
    if data.get("reactive"):
        direction_value = "none"
    base["direction"] = direction_value
    base["reactive"] = bool(data.get("reactive"))
    return base


def load_profile_store():
    raw = read_profile_file()
    store = {"active": DEFAULT_PROFILE_NAME, "profiles": {}}
    if raw and "profiles" in raw and isinstance(raw.get("profiles"), dict):
        for name, pdata in raw["profiles"].items():
            store["profiles"][str(name)] = sanitize_profile_state(pdata)
        if not store["profiles"]:
            store["profiles"][DEFAULT_PROFILE_NAME] = dict(DEFAULT_PROFILE_STATE)
        active = raw.get("active")
        if not active or active not in store["profiles"]:
            active = next(iter(store["profiles"]))
        store["active"] = active
    elif raw:
        store["profiles"][DEFAULT_PROFILE_NAME] = sanitize_profile_state(raw)
        store["active"] = DEFAULT_PROFILE_NAME
    else:
        store["profiles"][DEFAULT_PROFILE_NAME] = dict(DEFAULT_PROFILE_STATE)
    return store


def write_profile_store(store):
    write_profile_file(store)


def active_profile_from_raw_store(store):
    if not store:
        return None
    active_name = store.get("active", DEFAULT_PROFILE_NAME)
    profiles = store.get("profiles", {})
    if isinstance(profiles, dict) and active_name in profiles:
        return profiles[active_name]
    if isinstance(profiles, dict) and profiles:
        return next(iter(profiles.values()))
    return store


def switch_active_profile(profile_name: str) -> bool:
    store = read_profile_file()
    if not store or "profiles" not in store:
        return False
    if profile_name not in store.get("profiles", {}):
        return False
    store["active"] = profile_name
    write_profile_file(store)
    return True
