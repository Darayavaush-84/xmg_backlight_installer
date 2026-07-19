"""Locked, atomic persistence for settings and profiles."""

from __future__ import annotations

import atexit
import fcntl
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from copy import deepcopy

from .capabilities import DIRECTIONS, DYNAMIC_COLORS, EFFECTS, STATIC_COLORS
from .constants import (
    CONFIG_DIR,
    DEFAULT_PROFILE_NAME,
    DEFAULT_PROFILE_STATE,
    DEFAULT_SETTINGS,
    LANGUAGE_LABELS,
    LOCK_FILE_PATH,
    PROFILE_PATH,
    SETTINGS_PATH,
    STATE_PATH,
)
from .validation import clamp_int, normalize_language_code, sanitize_choice


STATE_SCHEMA = 1


class StorageFormatError(ValueError):
    """Raised when a persisted document is malformed or unsafe."""


class ProfileConflictError(RuntimeError):
    """Raised when a stale profile snapshot would overwrite a newer revision."""


def ensure_config_dir() -> None:
    try:
        info = os.lstat(CONFIG_DIR)
    except FileNotFoundError:
        os.makedirs(CONFIG_DIR, mode=0o700)
        info = os.lstat(CONFIG_DIR)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise StorageFormatError(f"Unsafe configuration directory: {CONFIG_DIR}")
    os.chmod(CONFIG_DIR, 0o700)


@contextmanager
def _document_lock(path: str, *, exclusive: bool):
    ensure_config_dir()
    lock_path = f"{path}.lock"
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    os.fchmod(descriptor, 0o600)
    lock_file = os.fdopen(descriptor, "a+", encoding="utf-8")
    try:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
        )
        yield
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def _read_json_unlocked(path: str) -> dict:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise StorageFormatError(f"Cannot safely open {path}: {exc}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise StorageFormatError(f"Unsafe persisted document: {path}")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise StorageFormatError(f"Malformed JSON in {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(data, dict):
        raise StorageFormatError(f"Expected a JSON object in {path}")
    return data


def _write_json_unlocked(path: str, data: dict) -> None:
    ensure_config_dir()
    directory = os.path.dirname(path)
    prefix = f".{os.path.basename(path)}."
    descriptor, tmp_path = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def acquire_single_instance_lock():
    """Acquire the stable application lock without unlinking it."""
    ensure_config_dir()
    descriptor = os.open(
        LOCK_FILE_PATH,
        os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    os.fchmod(descriptor, 0o600)
    lock_file = os.fdopen(descriptor, "r+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    atexit.register(release_single_instance_lock, lock_file)
    return lock_file


def release_single_instance_lock(lock_file) -> None:
    if lock_file is None or lock_file.closed:
        return
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def sanitize_settings(data):
    base = dict(DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return base
    for key in (
        "start_in_tray",
        "show_notifications",
        "dark_mode",
        "resume_enabled",
        "power_monitor_enabled",
    ):
        value = data.get(key)
        if isinstance(value, bool):
            base[key] = value
    base["ac_profile"] = str(data.get("ac_profile", base["ac_profile"]) or "")
    base["battery_profile"] = str(
        data.get("battery_profile", base["battery_profile"]) or ""
    )
    language_value = normalize_language_code(data.get("language", ""))
    base["language"] = language_value if language_value in LANGUAGE_LABELS else ""
    return base


def sanitize_profile_state(data):
    base = dict(DEFAULT_PROFILE_STATE)
    if not isinstance(data, dict):
        return base
    base["brightness"] = clamp_int(data.get("brightness"), 0, 50, base["brightness"])
    base["mode"] = sanitize_choice(data.get("mode"), EFFECTS, base["mode"])
    base["static_color"] = sanitize_choice(
        data.get("static_color"), STATIC_COLORS, base["static_color"]
    )
    base["speed"] = clamp_int(data.get("speed"), 0, 10, base["speed"])
    color_value = data.get("color") or "none"
    if color_value != "none":
        color_value = sanitize_choice(color_value, DYNAMIC_COLORS, "none")
    base["color"] = color_value
    direction_value = sanitize_choice(data.get("direction"), DIRECTIONS, "none")
    if data.get("reactive"):
        direction_value = "none"
    base["direction"] = direction_value
    base["reactive"] = bool(data.get("reactive"))
    return base


def profile_store_from_raw(raw: dict) -> dict:
    store = {"revision": 0, "active": DEFAULT_PROFILE_NAME, "profiles": {}}
    if raw and "profiles" in raw and isinstance(raw.get("profiles"), dict):
        for raw_name, profile_data in raw["profiles"].items():
            name = str(raw_name).strip()
            if not name or len(name) > 128:
                continue
            store["profiles"][name] = sanitize_profile_state(profile_data)
        if not store["profiles"]:
            store["profiles"][DEFAULT_PROFILE_NAME] = dict(DEFAULT_PROFILE_STATE)
        active = str(raw.get("active") or "")
        store["active"] = (
            active if active in store["profiles"] else next(iter(store["profiles"]))
        )
        store["revision"] = clamp_int(raw.get("revision"), 0, 2**63 - 1, 0)
    elif raw:
        store["profiles"][DEFAULT_PROFILE_NAME] = sanitize_profile_state(raw)
    else:
        store["profiles"][DEFAULT_PROFILE_NAME] = dict(DEFAULT_PROFILE_STATE)
    return store


def _state_payload(settings: dict, profile_store: dict) -> dict:
    return {
        "schema": STATE_SCHEMA,
        "settings": sanitize_settings(settings),
        "profile_store": profile_store_from_raw(profile_store),
    }


def _read_state_unlocked() -> dict:
    raw = _read_json_unlocked(STATE_PATH)
    if not raw:
        if os.path.lexists(STATE_PATH):
            raise StorageFormatError(f"Malformed application state in {STATE_PATH}")
        return {}
    if raw.get("schema") != STATE_SCHEMA:
        raise StorageFormatError(f"Unsupported state schema in {STATE_PATH}")
    settings = raw.get("settings")
    profile_store = raw.get("profile_store")
    if not isinstance(settings, dict) or not isinstance(profile_store, dict):
        raise StorageFormatError(f"Malformed application state in {STATE_PATH}")
    profiles = profile_store.get("profiles")
    active = profile_store.get("active")
    revision = profile_store.get("revision")
    if (
        not isinstance(profiles, dict)
        or not profiles
        or not isinstance(active, str)
        or active not in profiles
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 0
    ):
        raise StorageFormatError(f"Malformed profile store in {STATE_PATH}")
    return _state_payload(settings, profile_store)


def _migrated_or_default_state_unlocked() -> dict:
    settings = _read_json_unlocked(SETTINGS_PATH)
    profile_store = profile_store_from_raw(_read_json_unlocked(PROFILE_PATH))
    return _state_payload(settings, profile_store)


def ensure_app_state() -> dict:
    """Create or migrate the single atomic application state document."""
    with _document_lock(STATE_PATH, exclusive=True):
        state = _read_state_unlocked()
        if state:
            return state
        state = _migrated_or_default_state_unlocked()
        _write_json_unlocked(STATE_PATH, state)
        for legacy_path in (SETTINGS_PATH, PROFILE_PATH):
            try:
                os.unlink(legacy_path)
            except FileNotFoundError:
                pass
        return state


def _load_state() -> dict:
    ensure_app_state()
    with _document_lock(STATE_PATH, exclusive=False):
        return _read_state_unlocked()


def read_settings_file() -> dict:
    return dict(_load_state()["settings"])


def write_settings_file(data) -> dict:
    payload = sanitize_settings(data)
    with _document_lock(STATE_PATH, exclusive=True):
        state = _read_state_unlocked() or _migrated_or_default_state_unlocked()
        state["settings"] = payload
        _write_json_unlocked(STATE_PATH, state)
    return payload


def load_settings() -> dict:
    return read_settings_file()


def read_profile_file() -> dict:
    return deepcopy(_load_state()["profile_store"])


def write_profile_file(data, *, expected_revision: int | None = None):
    with _document_lock(STATE_PATH, exclusive=True):
        state = _read_state_unlocked() or _migrated_or_default_state_unlocked()
        current = state["profile_store"]
        current_revision = clamp_int(current.get("revision"), 0, 2**63 - 1, 0)
        if expected_revision is not None and expected_revision != current_revision:
            raise ProfileConflictError(
                f"Profile revision changed from {expected_revision} to {current_revision}"
            )
        payload = profile_store_from_raw(deepcopy(data))
        payload["revision"] = current_revision + 1
        state["profile_store"] = payload
        _write_json_unlocked(STATE_PATH, state)
        return payload


def load_profile_store() -> dict:
    return read_profile_file()


def ensure_profile_store() -> dict:
    return read_profile_file()


def write_profile_store(store, *, expected_revision: int | None = None):
    if expected_revision is None:
        expected_revision = clamp_int(store.get("revision"), 0, 2**63 - 1, 0)
    return write_profile_file(store, expected_revision=expected_revision)


def write_profile_and_settings(
    profile_store: dict,
    settings: dict,
    *,
    expected_profile_revision: int,
) -> tuple[dict, dict]:
    """Commit related profile and settings changes in one atomic replace."""
    with _document_lock(STATE_PATH, exclusive=True):
        state = _read_state_unlocked() or _migrated_or_default_state_unlocked()
        current_revision = clamp_int(
            state["profile_store"].get("revision"), 0, 2**63 - 1, 0
        )
        if current_revision != expected_profile_revision:
            raise ProfileConflictError(
                f"Profile revision changed from {expected_profile_revision} "
                f"to {current_revision}"
            )
        persisted_store = profile_store_from_raw(deepcopy(profile_store))
        persisted_store["revision"] = current_revision + 1
        persisted_settings = sanitize_settings(settings)
        state["profile_store"] = persisted_store
        state["settings"] = persisted_settings
        _write_json_unlocked(STATE_PATH, state)
        return persisted_store, persisted_settings


def active_profile_from_raw_store(store):
    if not store:
        return None
    normalized = profile_store_from_raw(store)
    return normalized["profiles"][normalized["active"]]


def switch_active_profile(profile_name: str) -> bool:
    with _document_lock(STATE_PATH, exclusive=True):
        state = _read_state_unlocked() or _migrated_or_default_state_unlocked()
        store = state["profile_store"]
        if profile_name not in store["profiles"]:
            return False
        if store["active"] == profile_name:
            return True
        store["active"] = profile_name
        store["revision"] = clamp_int(
            store.get("revision"), 0, 2**63 - 1, 0
        ) + 1
        _write_json_unlocked(STATE_PATH, state)
        return True
