"""Autostart and systemd user-service helpers."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess

from .constants import (
    APP_DISPLAY_NAME,
    APP_ROOT,
    AUTOSTART_DIR,
    AUTOSTART_ENTRY,
    POWER_MONITOR_SERVICE_NAME,
    POWER_MONITOR_SERVICE_PATH,
    POWER_MONITOR_SCRIPT,
    PYTHON_EXECUTABLE,
    RESTORE_SCRIPT,
    RESUME_SERVICE_NAME,
    RESUME_SERVICE_PATH,
    SYSTEMD_USER_DIR,
)


def module_exec(module_name: str) -> str:
    command = (
        f"cd {shlex.quote(APP_ROOT)} && "
        f"exec {shlex.quote(PYTHON_EXECUTABLE)} -m {shlex.quote(module_name)}"
    )
    return f"/usr/bin/sh -c {shlex.quote(command)}"


def ensure_autostart_dir():
    os.makedirs(AUTOSTART_DIR, exist_ok=True)


def autostart_entry_contents():
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_DISPLAY_NAME}\n"
        f"Exec={module_exec('xmg_backlight.app')}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Comment=Start keyboard backlight manager minimized in system tray.\n"
    )


def is_autostart_enabled():
    return os.path.isfile(AUTOSTART_ENTRY)


def create_autostart_entry():
    ensure_autostart_dir()
    tmp_path = AUTOSTART_ENTRY + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(autostart_entry_contents())
    os.replace(tmp_path, AUTOSTART_ENTRY)


def remove_autostart_entry():
    try:
        os.remove(AUTOSTART_ENTRY)
    except FileNotFoundError:
        pass


def ensure_restore_script_executable():
    try:
        st = os.stat(RESTORE_SCRIPT)
    except FileNotFoundError:
        return
    new_mode = st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    if new_mode != st.st_mode:
        try:
            os.chmod(RESTORE_SCRIPT, new_mode)
        except OSError:
            pass


def ensure_systemd_user_dir():
    os.makedirs(SYSTEMD_USER_DIR, exist_ok=True)


def resume_service_contents():
    exec_cmd = module_exec("xmg_backlight.restore_profile")
    exec_stop_post = f"/usr/bin/sh -c {shlex.quote('sleep 2; ' + exec_cmd)}"
    return (
        "[Unit]\n"
        "Description=Restore keyboard backlight after suspend/resume\n"
        "After=sleep.target suspend.target hibernate.target hybrid-sleep.target\n"
        "StopWhenUnneeded=yes\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        "ExecStart=/usr/bin/true\n"
        f"ExecStopPost={exec_stop_post}\n\n"
        "[Install]\n"
        "WantedBy=sleep.target\n"
        "WantedBy=suspend.target\n"
        "WantedBy=hibernate.target\n"
        "WantedBy=hybrid-sleep.target\n"
    )


def ensure_resume_service_file():
    ensure_systemd_user_dir()
    contents = resume_service_contents()
    tmp_path = RESUME_SERVICE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(contents)
    os.replace(tmp_path, RESUME_SERVICE_PATH)


def remove_resume_service_file():
    try:
        os.remove(RESUME_SERVICE_PATH)
    except FileNotFoundError:
        pass


def power_monitor_service_contents():
    ensure_restore_script_executable()
    exec_cmd = module_exec("xmg_backlight.power_state_monitor")
    return (
        "[Unit]\n"
        "Description=Keyboard backlight power monitor\n"
        "After=graphical-session.target\n"
        "PartOf=graphical-session.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exec_cmd}\n"
        "Restart=on-failure\n"
        "RestartSec=3\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def ensure_power_monitor_service_file():
    ensure_systemd_user_dir()
    contents = power_monitor_service_contents()
    tmp_path = POWER_MONITOR_SERVICE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(contents)
    os.replace(tmp_path, POWER_MONITOR_SERVICE_PATH)


def remove_power_monitor_service_file():
    try:
        os.remove(POWER_MONITOR_SERVICE_PATH)
    except FileNotFoundError:
        pass


def systemctl_user(args):
    cmd = ["systemctl", "--user", *args]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True)
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "systemctl not found"


def is_power_monitor_enabled():
    rc, out, err = systemctl_user(["is-enabled", POWER_MONITOR_SERVICE_NAME])
    if rc == 0:
        return True, "Enabled"
    if rc in (1, 2, 3, 4, 5):
        detail = err or out or "Disabled"
        if detail:
            normalized = detail.lower().replace("-", " ")
            if "not found" in normalized:
                detail = "Disabled"
        return False, detail
    if rc == 127:
        return False, "systemctl not available"
    return False, err or out or f"Status unknown (rc={rc})"


def enable_power_monitor_service():
    ensure_restore_script_executable()
    ensure_power_monitor_service_file()
    rc, _, err = systemctl_user(["daemon-reload"])
    if rc != 0:
        return False, err or "Failed to reload systemd user daemon."
    rc, out, err = systemctl_user(["enable", "--now", POWER_MONITOR_SERVICE_NAME])
    if rc != 0:
        return False, err or out or "Failed to enable power monitor."
    return True, "Power monitor enabled."


def disable_power_monitor_service():
    rc, out, err = systemctl_user(["disable", "--now", POWER_MONITOR_SERVICE_NAME])
    if rc not in (0, 1, 5):
        return False, err or out or "Failed to disable power monitor."
    remove_power_monitor_service_file()
    rc, _, _ = systemctl_user(["daemon-reload"])
    return True, "Power monitor disabled."


def is_resume_service_enabled():
    rc, out, err = systemctl_user(["is-enabled", RESUME_SERVICE_NAME])
    if rc == 0:
        return True, "Enabled"
    if rc in (1, 2, 3, 4, 5):
        detail = err or out or "Disabled"
        if detail:
            normalized = detail.lower().replace("-", " ")
            if "not found" in normalized:
                detail = "Disabled"
        return False, detail
    if rc == 127:
        return False, "systemctl not available"
    return False, err or out or f"Status unknown (rc={rc})"


def enable_resume_service():
    ensure_restore_script_executable()
    ensure_resume_service_file()
    rc, _, err = systemctl_user(["daemon-reload"])
    if rc != 0:
        return False, err or "Failed to reload systemd user daemon."
    rc, out, err = systemctl_user(["enable", RESUME_SERVICE_NAME])
    if rc != 0:
        return False, err or out or "Failed to enable resume service."
    return True, "Resume service enabled."


def disable_resume_service():
    rc, out, err = systemctl_user(["disable", RESUME_SERVICE_NAME])
    if rc not in (0, 1, 5):
        return False, err or out or "Failed to disable resume service."
    remove_resume_service_file()
    rc, _, _ = systemctl_user(["daemon-reload"])
    return True, "Resume service disabled."
