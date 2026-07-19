"""Autostart and unified systemd user-service management."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import tempfile

from .constants import (
    APP_DISPLAY_NAME,
    APP_ROOT,
    AUTOMATION_SERVICE_NAME,
    AUTOMATION_SERVICE_PATH,
    AUTOSTART_ENTRY,
    POWER_MONITOR_SERVICE_NAME,
    POWER_MONITOR_SERVICE_PATH,
    PYTHON_EXECUTABLE,
    RESUME_SERVICE_NAME,
    RESUME_SERVICE_PATH,
)


def module_exec(module_name: str) -> str:
    command = (
        f"cd {shlex.quote(APP_ROOT)} && "
        f"exec {shlex.quote(PYTHON_EXECUTABLE)} -m {shlex.quote(module_name)}"
    )
    return f"/usr/bin/sh -c {shlex.quote(command)}"


def _atomic_text_write(path: str, contents: str) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    directory_info = os.lstat(directory)
    if not stat.S_ISDIR(directory_info.st_mode) or directory_info.st_uid != os.getuid():
        raise OSError(f"Unsafe integration directory: {directory}")
    descriptor, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(contents)
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


def autostart_entry_contents():
    return (
        "# Managed by XMG Backlight\n"
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_DISPLAY_NAME}\n"
        f"Exec={module_exec('xmg_backlight.app')}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Comment=Start keyboard backlight manager minimized in system tray.\n"
    )


def is_autostart_enabled():
    if not os.path.isfile(AUTOSTART_ENTRY):
        return False
    try:
        with open(AUTOSTART_ENTRY, "r", encoding="utf-8") as handle:
            return handle.read() == autostart_entry_contents()
    except OSError:
        return False


def create_autostart_entry():
    contents = autostart_entry_contents()
    _assert_replaceable_user_file(
        AUTOSTART_ENTRY,
        allowed_contents=(contents, contents.split("\n", 1)[1]),
    )
    _atomic_text_write(AUTOSTART_ENTRY, contents)


def remove_autostart_entry():
    contents = autostart_entry_contents()
    _remove_owned_user_file(
        AUTOSTART_ENTRY, allowed_contents=(contents, contents.split("\n", 1)[1])
    )


def automation_service_contents():
    return (
        "# Managed by XMG Backlight\n"
        "[Unit]\n"
        "Description=XMG keyboard backlight automation\n"
        "After=graphical-session.target dbus.service\n"
        "PartOf=graphical-session.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={module_exec('xmg_backlight.automation_daemon')}\n"
        "Restart=on-failure\n"
        "RestartSec=3\n"
        "NoNewPrivileges=yes\n"
        "PrivateTmp=yes\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def ensure_automation_service_file():
    contents = automation_service_contents()
    _assert_replaceable_user_file(
        AUTOMATION_SERVICE_PATH,
        allowed_contents=(contents, contents.split("\n", 1)[1]),
    )
    _atomic_text_write(AUTOMATION_SERVICE_PATH, contents)


def remove_automation_service_file():
    contents = automation_service_contents()
    _remove_owned_user_file(
        AUTOMATION_SERVICE_PATH,
        allowed_contents=(contents, contents.split("\n", 1)[1]),
    )


def _read_regular_user_file(path):
    if not os.path.lexists(path):
        return None
    if os.path.islink(path) or not os.path.isfile(path):
        raise OSError(f"Refusing unsafe integration file: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _assert_replaceable_user_file(
    path, *, allowed_contents=(), legacy_markers=()
):
    contents = _read_regular_user_file(path)
    if contents is None:
        return
    if contents in allowed_contents or any(
        marker in contents for marker in legacy_markers
    ):
        return
    raise OSError(f"Refusing to replace an unowned integration file: {path}")


def _remove_owned_user_file(path, *, allowed_contents=(), legacy_markers=()):
    contents = _read_regular_user_file(path)
    if contents is None:
        return False
    if contents not in allowed_contents and not any(
        marker in contents for marker in legacy_markers
    ):
        raise OSError(f"Refusing to remove an unowned integration file: {path}")
    os.remove(path)
    return True


def systemctl_user(args):
    try:
        process = subprocess.run(
            ["systemctl", "--user", *args],
            text=True,
            capture_output=True,
            timeout=10,
        )
    except FileNotFoundError:
        return 127, "", "systemctl not found"
    except subprocess.TimeoutExpired:
        return 124, "", "systemctl --user timed out"
    return (
        process.returncode,
        (process.stdout or "").strip(),
        (process.stderr or "").strip(),
    )


def automation_service_status():
    rc, out, err = systemctl_user(["is-enabled", AUTOMATION_SERVICE_NAME])
    if rc == 0:
        return True, "Enabled"
    detail = err or out
    if rc == 127:
        return False, "systemctl not available"
    if rc == 124:
        return False, detail
    if detail in {"disabled", "not-found", "No such file or directory"}:
        return False, "Disabled"
    return False, detail or f"Unable to query service status (rc={rc})"


def _remove_legacy_automation_units():
    for name, path in (
        (RESUME_SERVICE_NAME, RESUME_SERVICE_PATH),
        (POWER_MONITOR_SERVICE_NAME, POWER_MONITOR_SERVICE_PATH),
    ):
        if not os.path.lexists(path):
            continue
        _assert_replaceable_user_file(
            path,
            legacy_markers=("xmg_backlight.",),
        )
        rc, out, err = systemctl_user(["disable", "--now", name])
        if rc not in (0, 1, 5):
            raise OSError(err or out or f"Failed to disable legacy unit {name}")
        _remove_owned_user_file(path, legacy_markers=("xmg_backlight.",))


def reconcile_automation_service(settings: dict):
    desired = bool(
        settings.get("resume_enabled", False)
        or settings.get("power_monitor_enabled", False)
    )
    try:
        _remove_legacy_automation_units()
        if desired:
            ensure_automation_service_file()
    except OSError as exc:
        return False, str(exc)
    if desired:
        rc, _, err = systemctl_user(["daemon-reload"])
        if rc != 0:
            return False, err or "Failed to reload the systemd user daemon."
        rc, out, err = systemctl_user(["enable", AUTOMATION_SERVICE_NAME])
        if rc != 0:
            return False, err or out or "Failed to enable automation service."
        rc, out, err = systemctl_user(["restart", AUTOMATION_SERVICE_NAME])
        if rc != 0:
            return False, err or out or "Failed to restart automation service."
        return True, "Automation service enabled."

    if os.path.lexists(AUTOMATION_SERVICE_PATH):
        try:
            contents = automation_service_contents()
            _assert_replaceable_user_file(
                AUTOMATION_SERVICE_PATH,
                allowed_contents=(contents, contents.split("\n", 1)[1]),
            )
        except OSError as exc:
            return False, str(exc)
        rc, out, err = systemctl_user(
            ["disable", "--now", AUTOMATION_SERVICE_NAME]
        )
        if rc not in (0, 1, 5):
            return False, err or out or "Failed to disable automation service."
        try:
            remove_automation_service_file()
        except OSError as exc:
            return False, str(exc)
    rc, _, err = systemctl_user(["daemon-reload"])
    if rc != 0:
        return False, err or "Failed to reload the systemd user daemon."
    return True, "Automation service disabled."
