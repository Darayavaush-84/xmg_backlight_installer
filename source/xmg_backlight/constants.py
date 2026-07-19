"""Shared constants and paths for XMG Backlight Management."""

from __future__ import annotations

import os
import shutil
import sys

APP_DISPLAY_NAME = "XMG Backlight Management"
APP_VERSION = "2.5.0-rc1"
GITHUB_REPO_URL = "https://github.com/Darayavaush-84/xmg_backlight_installer"
NOTIFICATION_TIMEOUT_MS = 1500
ACTIVITY_LOG_MAX_LINES = 100

DRIVER_WRAPPER_PATH = "/usr/local/bin/ite8291r3-ctl"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(BASE_DIR)
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "backlight-linux")
STATE_PATH = os.path.join(CONFIG_DIR, "state.json")
# Read only during the one-time migration to the unified state document.
PROFILE_PATH = os.path.join(CONFIG_DIR, "profile.json")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
LOCK_FILE_PATH = os.path.join(CONFIG_DIR, "app.lock")
TRANSLATIONS_DIR = os.path.join(BASE_DIR, "translations")
INSTALLER_LOG_PATH = "/var/log/xmg-backlight/installer.log"
AUTOSTART_DIR = os.path.join(os.path.expanduser("~"), ".config", "autostart")
AUTOSTART_ENTRY = os.path.join(AUTOSTART_DIR, "keyboard-backlight-restore.desktop")
SYSTEMD_USER_DIR = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")
RESUME_SERVICE_NAME = "keyboard-backlight-resume.service"
RESUME_SERVICE_PATH = os.path.join(SYSTEMD_USER_DIR, RESUME_SERVICE_NAME)
POWER_MONITOR_SERVICE_NAME = "keyboard-backlight-power-monitor.service"
POWER_MONITOR_SERVICE_PATH = os.path.join(SYSTEMD_USER_DIR, POWER_MONITOR_SERVICE_NAME)
AUTOMATION_SERVICE_NAME = "keyboard-backlight-automation.service"
AUTOMATION_SERVICE_PATH = os.path.join(SYSTEMD_USER_DIR, AUTOMATION_SERVICE_NAME)
PYTHON_EXECUTABLE = sys.executable or shutil.which("python3") or "/usr/bin/python3"

DEFAULT_PROFILE_NAME = "Default"
DEFAULT_PROFILE_STATE = {
    "brightness": 40,
    "mode": "static",
    "static_color": "white",
    "speed": 5,
    "color": "none",
    "direction": "none",
    "reactive": False,
}
DEFAULT_SETTINGS = {
    "start_in_tray": False,
    "show_notifications": True,
    "dark_mode": True,
    "ac_profile": "",
    "battery_profile": "",
    "language": "",
    "resume_enabled": False,
    "power_monitor_enabled": False,
}
LANGUAGE_LABELS = {
    "en": "English",
    "it": "Italiano",
    "de": "Deutsch",
    "es": "Español",
    "fr": "Français",
}
