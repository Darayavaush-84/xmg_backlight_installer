#!/usr/bin/env python3
import atexit
import fcntl
import html
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import time
from PySide6 import QtCore, QtWidgets, QtGui

APP_DISPLAY_NAME = "XMG Backlight Management"
APP_VERSION = "1.3.1"
GITHUB_REPO_URL = "https://github.com/Darayavaush-84/xmg_backlight_installer"
NOTIFICATION_TIMEOUT_MS = 1500
TOOL_ENV_VAR = "ITE8291R3_CTL"
TOOL_CANDIDATES = [
    os.environ.get(TOOL_ENV_VAR),
    "/usr/local/bin/ite8291r3-ctl",
    "ite8291r3-ctl",
]


def _resolve_tool():
    for candidate in TOOL_CANDIDATES:
        if not candidate:
            continue
        path = candidate
        if not os.path.isabs(candidate):
            resolved = shutil.which(candidate)
            if not resolved:
                continue
            path = resolved
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    return None


def _tool_hint():
    candidates = [c for c in TOOL_CANDIDATES if c]
    return ", ".join(candidates) if candidates else "ite8291r3-ctl"


TOOL = _resolve_tool()

MISSING_TOOL_MESSAGE = (
    f"CLI tool not found. Install 'ite8291r3-ctl' or set ${TOOL_ENV_VAR}."
)


EFFECTS = [
    "static",
    "breathing", "wave", "random", "rainbow",
    "ripple", "marquee", "raindrop", "aurora", "fireworks",
]
COLORS = ["white", "red", "orange", "yellow", "green", "blue", "teal", "purple", "random"]
DIRECTIONS = ["none", "right", "left", "up", "down"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "backlight-linux")
PROFILE_PATH = os.path.join(CONFIG_DIR, "profile.json")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
LOCK_FILE_PATH = os.path.join(CONFIG_DIR, "app.lock")
RESTORE_SCRIPT = os.path.join(BASE_DIR, "restore_profile.py")
POWER_MONITOR_SCRIPT = os.path.join(BASE_DIR, "power_state_monitor.py")
RESUME_LOG_PATH = "/var/log/xmg-backlight/restore.log"
INSTALLER_LOG_PATH = "/var/log/xmg-backlight/installer.log"
AUTOSTART_DIR = os.path.join(os.path.expanduser("~"), ".config", "autostart")
AUTOSTART_ENTRY = os.path.join(AUTOSTART_DIR, "keyboard-backlight-restore.desktop")
SYSTEMD_USER_DIR = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")
RESUME_SERVICE_NAME = "keyboard-backlight-resume.service"
RESUME_SERVICE_PATH = os.path.join(SYSTEMD_USER_DIR, RESUME_SERVICE_NAME)
POWER_MONITOR_SERVICE_NAME = "keyboard-backlight-power-monitor.service"
POWER_MONITOR_SERVICE_PATH = os.path.join(
    SYSTEMD_USER_DIR, POWER_MONITOR_SERVICE_NAME
)
POWER_SUPPLY_DIR = "/sys/class/power_supply"
MAINS_TYPES = {"mains", "ac", "usb"}
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
    "dark_mode": False,
    "ac_profile": "",
    "battery_profile": "",
}


def clamp_int(value, minimum, maximum, fallback):
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, ivalue))


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def acquire_single_instance_lock():
    """Try to acquire an exclusive lock. Returns the file handle if successful, None otherwise."""
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
    """Release the lock file and remove it."""
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


def sanitize_choice(value, options, fallback):
    return value if value in options else fallback


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


def ensure_autostart_dir():
    os.makedirs(AUTOSTART_DIR, exist_ok=True)


def autostart_entry_contents():
    gui_script = os.path.join(BASE_DIR, "keyboard_backlight.py")
    exec_cmd = f"{shlex.quote(PYTHON_EXECUTABLE)} {shlex.quote(gui_script)}"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_DISPLAY_NAME}\n"
        f"Exec={exec_cmd}\n"
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
    exec_cmd = f"{shlex.quote(PYTHON_EXECUTABLE)} {shlex.quote(RESTORE_SCRIPT)}"
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
    exec_cmd = f"{shlex.quote(PYTHON_EXECUTABLE)} {shlex.quote(POWER_MONITOR_SCRIPT)}"
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
    rc, out, err = systemctl_user(["enable", "--now", RESUME_SERVICE_NAME])
    if rc != 0:
        return False, err or out or "Failed to enable resume service."
    return True, "Resume service enabled."


def disable_resume_service():
    rc, out, err = systemctl_user(["disable", "--now", RESUME_SERVICE_NAME])
    if rc not in (0, 1, 5):
        return False, err or out or "Failed to disable resume service."
    remove_resume_service_file()
    rc, _, _ = systemctl_user(["daemon-reload"])
    return True, "Resume service disabled."


LOG_COLORS = {
    "info": "#e5e7eb",
    "cmd": "#7dd3fc",
    "stdout": "#c7f9cc",
    "stderr": "#fca5a5",
    "error": "#f87171",
}


def format_log(text, level="info"):
    color = LOG_COLORS.get(level, LOG_COLORS["info"])
    safe = html.escape(text)
    return f'<span style="color:{color}">{safe}</span>'


def run_cmd(args, log_cb=None, *, log_cmd=True, log_stdout=True, log_stderr=True):
    cmd_display = " ".join(shlex.quote(str(a)) for a in args)
    if log_cb and log_cmd:
        log_cb(f"$ {cmd_display}", level="cmd")

    if not TOOL:
        msg = f"{MISSING_TOOL_MESSAGE} (candidati: {_tool_hint()})"
        if log_cb:
            log_cb(msg, level="error")
        return 127, "", msg

    try:
        p = subprocess.run([TOOL, *args], text=True, capture_output=True)
        stdout = (p.stdout or "").strip()
        stderr = (p.stderr or "").strip()
        if stdout and log_cb and log_stdout:
            log_cb(stdout, level="stdout")
        if stderr and log_cb and log_stderr:
            log_cb(stderr, level="stderr")
        return p.returncode, stdout, stderr
    except FileNotFoundError:
        msg = f"{MISSING_TOOL_MESSAGE} (candidati: {_tool_hint()})"
        if log_cb:
            log_cb(msg, level="error")
        return 127, "", msg


def format_cli_error(rc, out, err):
    text = (err or out or "").strip()
    lower = text.lower()

    if rc == 127 or "cli tool non trovato" in lower or "cli tool not found" in lower:
        return f"{MISSING_TOOL_MESSAGE} Searched: {_tool_hint()}."

    if "libusb_error_access" in lower or "permission denied" in lower:
        return (
            "Insufficient permissions to access the keyboard. "
            "Run as root or create a udev rule."
        )

    if "device handle could not be acquired" in lower or "no such device" in lower:
        return "Keyboard not detected. Check the USB connection and try again."

    if text:
        return f"Error ({rc}): {text}"

    return f"Error ({rc}): unknown"


def drop_flag(args, flag):
    out = []
    i = 0
    while i < len(args):
        if args[i] == flag:
            if flag in ("-s", "-b", "-c", "-d") and i + 1 < len(args):
                i += 2
                continue
            i += 1
            continue
        out.append(args[i])
        i += 1
    return out


def apply_effect_with_fallback(args, runner=run_cmd):
    rc, out, err = runner(args)
    if rc == 0:
        return rc, out, err, args

    msg = (err or out or "").lower()
    if "attr is not needed by effect" not in msg:
        return rc, out, err, args

    candidates = [
        ("direction", "-d"),
        ("reactive", "-r"),
        ("color", "-c"),
        ("speed", "-s"),
        ("brightness", "-b"),
    ]

    tried = set()
    current = list(args)

    for _ in range(6):
        m = (err or out or "").lower()
        changed = False
        for key, flag in candidates:
            if key in m and flag not in tried:
                tried.add(flag)
                current = drop_flag(current, flag)
                rc, out, err = runner(current)
                changed = True
                if rc == 0:
                    return rc, out, err, current
                break
        if not changed:
            break

    return rc, out, err, current


class Main(QtWidgets.QWidget):
    def __init__(self, *, enable_tray=True):
        super().__init__()
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.resize(980, 500)

        QtWidgets.QApplication.setStyle("Fusion")
        QtWidgets.QApplication.setQuitOnLastWindowClosed(False)
        base_icon = QtGui.QIcon.fromTheme("input-keyboard")
        if base_icon.isNull():
            base_icon = self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
        self.setWindowIcon(base_icon)

        self.settings = load_settings()
        self.tray_supported = QtWidgets.QSystemTrayIcon.isSystemTrayAvailable()
        self.is_off = False
        self.last_brightness = 40
        self.last_static_color = "white"
        self._suppress = False
        self._pending_effect_after_brightness = False
        self._ignore_profile_events = False
        self._updating_profile_combo = False
        ensure_restore_script_executable()
        self.profile_store = load_profile_store()
        self.active_profile_name = self.profile_store["active"]
        self.profile_data = dict(self.profile_store["profiles"][self.active_profile_name])
        self.autostart_enabled = is_autostart_enabled()
        if self.autostart_enabled and not self.settings.get("start_in_tray", False):
            self.settings["start_in_tray"] = True
            self.save_settings()
        self.resume_enabled = False
        self.resume_status = "Unknown"
        status_enabled, status_text = is_resume_service_enabled()
        self.resume_enabled = status_enabled
        self.resume_status = status_text
        self.power_monitor_enabled, self.power_monitor_status = is_power_monitor_enabled()
        self.profile_watcher = QtCore.QFileSystemWatcher(self)
        self.profile_watcher.fileChanged.connect(self.on_profile_file_changed)
        self.profile_watcher.directoryChanged.connect(self.on_profile_directory_changed)
        self.watch_profile_paths()
        if self.profile_data:
            self.last_brightness = clamp_int(
                self.profile_data.get("brightness"), 0, 50, self.last_brightness
            )
            self.last_static_color = sanitize_choice(
                self.profile_data.get("static_color"), COLORS, self.last_static_color
            )

        self.setObjectName("MainView")
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        surface = QtWidgets.QFrame()
        surface.setObjectName("AppSurface")
        surface_layout = QtWidgets.QVBoxLayout(surface)
        surface_layout.setContentsMargins(28, 28, 28, 28)
        surface_layout.setSpacing(22)
        root.addWidget(surface)

        hero_card = QtWidgets.QFrame()
        hero_card.setObjectName("heroCard")
        hero_layout = QtWidgets.QHBoxLayout(hero_card)
        hero_layout.setContentsMargins(32, 28, 32, 28)
        hero_layout.setSpacing(24)

        hero_text = QtWidgets.QVBoxLayout()
        hero_text.setSpacing(6)
        hero_title = QtWidgets.QLabel(APP_DISPLAY_NAME)
        hero_title.setObjectName("heroTitle")
        hero_subtitle = QtWidgets.QLabel(
            "Light up your keyboard with curated profiles and thoughtful automations."
        )
        hero_subtitle.setWordWrap(True)
        hero_subtitle.setObjectName("heroSubtitle")
        hero_text.addWidget(hero_title)
        hero_text.addWidget(hero_subtitle)

        hardware_row = QtWidgets.QHBoxLayout()
        hardware_row.setSpacing(8)
        hardware_caption = QtWidgets.QLabel("Hardware")
        hardware_caption.setObjectName("heroCaption")
        self.hardware_label = QtWidgets.QLabel("Hardware: unknown")
        self.hardware_label.setWordWrap(True)
        self.hardware_label.setObjectName("hardwareBadge")
        hardware_row.addWidget(hardware_caption)
        hardware_row.addWidget(self.hardware_label, 1)
        hero_text.addLayout(hardware_row)

        hero_layout.addLayout(hero_text, 1)

        hero_controls = QtWidgets.QVBoxLayout()
        hero_controls.setSpacing(12)
        hero_controls.addStretch(1)
        self.github_button = QtWidgets.QPushButton("GitHub")
        self.github_button.setObjectName("pillButton")
        hero_controls.addWidget(self.github_button, 0, QtCore.Qt.AlignRight)
        self.export_logs_button = QtWidgets.QPushButton("Export logs")
        self.export_logs_button.setObjectName("pillButton")
        hero_controls.addWidget(self.export_logs_button, 0, QtCore.Qt.AlignRight)
        self.log_toggle_button = QtWidgets.QPushButton("Show activity log")
        self.log_toggle_button.setCheckable(True)
        self.log_toggle_button.setObjectName("pillButton")
        hero_controls.addWidget(self.log_toggle_button, 0, QtCore.Qt.AlignRight)
        hero_layout.addLayout(hero_controls)

        surface_layout.addWidget(hero_card)

        content_layout = QtWidgets.QHBoxLayout()
        content_layout.setSpacing(20)
        content_layout.setContentsMargins(0, 0, 0, 0)
        surface_layout.addLayout(content_layout)

        left_col = QtWidgets.QVBoxLayout()
        left_col.setSpacing(20)
        content_layout.addLayout(left_col, 1)
        right_col = QtWidgets.QVBoxLayout()
        right_col.setSpacing(20)
        content_layout.addLayout(right_col, 1)

        brightness_card = QtWidgets.QFrame()
        brightness_card.setObjectName("surfaceCard")
        bc_layout = QtWidgets.QVBoxLayout(brightness_card)
        bc_layout.setContentsMargins(24, 24, 24, 24)
        bc_layout.setSpacing(18)

        bright_title = QtWidgets.QLabel("Brightness & power")
        bright_title.setObjectName("sectionTitle")
        bc_layout.addWidget(bright_title)

        bright_caption = QtWidgets.QLabel("Control intensity (0–50) and toggle the keyboard instantly.")
        bright_caption.setObjectName("sectionSubtitle")
        bright_caption.setWordWrap(True)
        bc_layout.addWidget(bright_caption)

        gl = QtWidgets.QGridLayout()
        gl.setColumnStretch(1, 1)
        gl.setHorizontalSpacing(16)
        gl.setVerticalSpacing(12)

        gl.addWidget(QtWidgets.QLabel("Value"), 0, 0)
        self.b_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.b_slider.setRange(0, 50)
        self.b_slider.setValue(self.last_brightness)
        gl.addWidget(self.b_slider, 0, 1)

        self.b_spin = QtWidgets.QSpinBox()
        self.b_spin.setRange(0, 50)
        self.b_spin.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        self.b_spin.setFixedWidth(80)
        self.b_spin.setValue(self.last_brightness)
        gl.addWidget(self.b_spin, 0, 2)
        bc_layout.addLayout(gl)

        self.btn_power = QtWidgets.QPushButton("Turn on")
        self.btn_power.setObjectName("powerButton")
        self.btn_power.setMinimumHeight(52)
        bc_layout.addWidget(self.btn_power)

        left_col.addWidget(brightness_card)

        mode_card = QtWidgets.QFrame()
        mode_card.setObjectName("surfaceCard")
        mode_layout = QtWidgets.QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(24, 24, 24, 24)
        mode_layout.setSpacing(18)

        mode_title = QtWidgets.QLabel("Effects & colors")
        mode_title.setObjectName("sectionTitle")
        mode_layout.addWidget(mode_title)

        mode_caption = QtWidgets.QLabel("Pick static hues or animated scenes with direction and reactivity.")
        mode_caption.setWordWrap(True)
        mode_caption.setObjectName("sectionSubtitle")
        mode_layout.addWidget(mode_caption)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(16)
        mode_row.addWidget(QtWidgets.QLabel("Effect"))
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(EFFECTS)
        self.mode.setCurrentText("static")
        mode_row.addWidget(self.mode, 1)

        self.static_label = QtWidgets.QLabel("Static color")
        mode_row.addWidget(self.static_label)
        self.static_color = QtWidgets.QComboBox()
        self.static_color.addItems(COLORS)
        self.static_color.setCurrentText(self.last_static_color)
        mode_row.addWidget(self.static_color, 1)
        mode_layout.addLayout(mode_row)

        self.effect_panel = QtWidgets.QWidget()
        epl = QtWidgets.QGridLayout(self.effect_panel)
        epl.setContentsMargins(0, 0, 0, 0)
        epl.setHorizontalSpacing(16)
        epl.setVerticalSpacing(12)

        epl.addWidget(QtWidgets.QLabel("Speed (0–10)"), 0, 0)
        self.speed = QtWidgets.QSpinBox()
        self.speed.setRange(0, 10)
        self.speed.setValue(5)
        self.speed.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        epl.addWidget(self.speed, 0, 1)

        epl.addWidget(QtWidgets.QLabel("Dynamic color"), 0, 2)
        self.color = QtWidgets.QComboBox()
        self.color.addItems(["none"] + COLORS)
        self.color.setCurrentText("none")
        epl.addWidget(self.color, 0, 3)

        self.reactive = QtWidgets.QCheckBox("Reactive mode (-r)")
        epl.addWidget(self.reactive, 1, 1)

        epl.addWidget(QtWidgets.QLabel("Direction"), 1, 2)
        self.direction = QtWidgets.QComboBox()
        self.direction.addItems(DIRECTIONS)
        self.direction.setCurrentText("none")
        epl.addWidget(self.direction, 1, 3)

        mode_layout.addWidget(self.effect_panel)
        right_col.addWidget(mode_card)

        profiles_card = QtWidgets.QFrame()
        profiles_card.setObjectName("surfaceCard")
        profiles_layout = QtWidgets.QVBoxLayout(profiles_card)
        profiles_layout.setContentsMargins(24, 24, 24, 24)
        profiles_layout.setSpacing(16)

        profiles_title = QtWidgets.QLabel("Quick profiles")
        profiles_title.setObjectName("sectionTitle")
        profiles_layout.addWidget(profiles_title)

        profiles_caption = QtWidgets.QLabel("Save your presets and recall them in one click.")
        profiles_caption.setWordWrap(True)
        profiles_caption.setObjectName("sectionSubtitle")
        profiles_layout.addWidget(profiles_caption)

        pl = QtWidgets.QGridLayout()
        pl.setColumnStretch(1, 1)
        pl.setHorizontalSpacing(12)
        pl.setVerticalSpacing(10)
        pl.addWidget(QtWidgets.QLabel("Active profile"), 0, 0)
        self.profile_combo = QtWidgets.QComboBox()
        pl.addWidget(self.profile_combo, 0, 1, 1, 2)
        self.btn_profile_save = QtWidgets.QPushButton("Save")
        pl.addWidget(self.btn_profile_save, 0, 3)
        self.btn_profile_new = QtWidgets.QPushButton("New…")
        pl.addWidget(self.btn_profile_new, 1, 0)
        self.btn_profile_save_as = QtWidgets.QPushButton("Save as…")
        pl.addWidget(self.btn_profile_save_as, 1, 1)
        self.btn_profile_rename = QtWidgets.QPushButton("Rename…")
        pl.addWidget(self.btn_profile_rename, 1, 2)
        self.btn_profile_delete = QtWidgets.QPushButton("Delete")
        pl.addWidget(self.btn_profile_delete, 1, 3)
        profiles_layout.addLayout(pl)

        left_col.addWidget(profiles_card)

        helper_card = QtWidgets.QFrame()
        helper_card.setObjectName("surfaceCard")
        helper_layout = QtWidgets.QVBoxLayout(helper_card)
        helper_layout.setContentsMargins(24, 24, 24, 24)
        helper_layout.setSpacing(16)

        helper_title = QtWidgets.QLabel("Smart automations")
        helper_title.setObjectName("sectionTitle")
        helper_layout.addWidget(helper_title)

        helper_intro = QtWidgets.QLabel(
            "Enable background services to restore your colors on login, resume or power-source changes."
        )
        helper_intro.setWordWrap(True)
        helper_intro.setObjectName("sectionSubtitle")
        helper_layout.addWidget(helper_intro)

        helper_list = QtWidgets.QVBoxLayout()
        helper_list.setSpacing(10)
        helper_layout.addLayout(helper_list)

        def helper_entry(title, tooltip, *, selectable=False):
            row = QtWidgets.QFrame()
            row.setObjectName("helperRow")
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(12)
            info = QtWidgets.QToolButton()
            info.setText("?")
            info.setObjectName("helperInfoButton")
            info.setCursor(QtCore.Qt.PointingHandCursor)
            info.setAutoRaise(True)
            info.setFixedSize(24, 24)
            label = QtWidgets.QLabel(title)
            label.setObjectName("helperLabel")
            flag = QtWidgets.QPushButton("Disabled")
            flag.setCheckable(True)
            flag.setCursor(QtCore.Qt.PointingHandCursor)
            flag.setObjectName("helperFlag")
            row_layout.addWidget(info)
            row_layout.addWidget(label)
            row_layout.addStretch(1)
            row_layout.addWidget(flag)

            detail = QtWidgets.QLabel()
            detail.setWordWrap(True)
            detail.setObjectName("helperDetail")
            detail.setVisible(False)
            if selectable:
                detail.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            detail.setContentsMargins(36, 0, 0, 0)

            widgets = (row, label, info, flag, detail)
            for widget in widgets:
                widget.setToolTip(tooltip)
                widget.setToolTipDuration(0)

            helper_list.addWidget(row)
            helper_list.addWidget(detail)
            return flag, detail

        self.autostart_flag, self.autostart_status_label = helper_entry(
            "Autostart on login",
            (
                "Restore the saved keyboard profile when your desktop session begins.\n"
                f"Desktop entry path: {AUTOSTART_ENTRY}"
            ),
        )

        self.resume_flag, self.resume_status_label = helper_entry(
            "Resume restore",
            "Reapply the profile immediately after suspend, hibernate or hybrid sleep.",
            selectable=True,
        )

        self.power_monitor_flag, self.power_monitor_status_label = helper_entry(
            "Power monitor",
            "Listen for AC/battery switches and reapply the profile when the source changes.",
            selectable=True,
        )

        power_profiles_row = QtWidgets.QFrame()
        power_profiles_row.setObjectName("helperRow")
        pp_layout = QtWidgets.QGridLayout(power_profiles_row)
        pp_layout.setContentsMargins(12, 10, 12, 10)
        pp_layout.setHorizontalSpacing(12)
        pp_layout.setVerticalSpacing(8)

        pp_label = QtWidgets.QLabel("Power-based profiles")
        pp_label.setObjectName("helperLabel")
        pp_layout.addWidget(pp_label, 0, 0, 1, 2)

        ac_label = QtWidgets.QLabel("On AC:")
        pp_layout.addWidget(ac_label, 1, 0)
        self.ac_profile_combo = QtWidgets.QComboBox()
        self.ac_profile_combo.setToolTip("Profile to apply when connected to AC power")
        pp_layout.addWidget(self.ac_profile_combo, 1, 1)

        battery_label = QtWidgets.QLabel("On Battery:")
        pp_layout.addWidget(battery_label, 2, 0)
        self.battery_profile_combo = QtWidgets.QComboBox()
        self.battery_profile_combo.setToolTip("Profile to apply when running on battery")
        pp_layout.addWidget(self.battery_profile_combo, 2, 1)

        helper_list.addWidget(power_profiles_row)

        settings_row = QtWidgets.QFrame()
        settings_layout = QtWidgets.QHBoxLayout(settings_row)
        settings_layout.setContentsMargins(0, 12, 0, 0)
        settings_layout.setSpacing(12)
        settings_layout.addStretch(1)
        self.dark_mode_checkbox = QtWidgets.QCheckBox("Dark Mode")
        self.dark_mode_checkbox.setChecked(self.settings.get("dark_mode", False))
        settings_layout.addWidget(self.dark_mode_checkbox)
        self.notifications_checkbox = QtWidgets.QCheckBox("Show notifications")
        self.notifications_checkbox.setChecked(self.settings.get("show_notifications", True))
        settings_layout.addWidget(self.notifications_checkbox)
        helper_layout.addWidget(settings_row)

        right_col.addWidget(helper_card)
        right_col.addStretch(1)

        self.console_box = QtWidgets.QFrame()
        self.console_box.setObjectName("surfaceCard")
        console_layout = QtWidgets.QVBoxLayout(self.console_box)
        console_layout.setContentsMargins(24, 24, 24, 24)
        console_layout.setSpacing(12)

        console_header = QtWidgets.QHBoxLayout()
        console_header.setSpacing(12)
        console_title = QtWidgets.QLabel("Activity log")
        console_title.setObjectName("sectionTitle")
        console_header.addWidget(console_title)
        console_header.addStretch(1)
        console_layout.addLayout(console_header)

        self.console = QtWidgets.QTextEdit()
        self.console.setObjectName("logView")
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        console_layout.addWidget(self.console, 1)

        self.console_box.setVisible(False)

        surface_layout.addWidget(self.console_box)
        surface_layout.addStretch(1)

        self.github_button.clicked.connect(self.on_github_clicked)
        self.export_logs_button.clicked.connect(self.on_export_logs_clicked)
        self.log_toggle_button.toggled.connect(self.on_log_toggle_toggled)

        self.apply_timer = QtCore.QTimer(self)
        self.apply_timer.setSingleShot(True)
        self.apply_timer.setInterval(180)
        self.apply_timer.timeout.connect(self.apply_current_mode)

        self.brightness_timer = QtCore.QTimer(self)
        self.brightness_timer.setSingleShot(True)
        self.brightness_timer.setInterval(240)
        self.brightness_timer.timeout.connect(self.apply_brightness_only)

        self.detect_device()
        self.apply_styles()
        self.update_panels()
        self.update_power_button()
        if self.profile_data:
            self.load_profile_into_controls(self.profile_data)

        self.b_slider.valueChanged.connect(self.b_spin.setValue)
        self.b_spin.valueChanged.connect(self.b_slider.setValue)

        self.b_spin.valueChanged.connect(self.on_brightness_changed)
        self.btn_power.clicked.connect(self.on_power_toggle)

        self.mode.currentIndexChanged.connect(self.on_mode_changed)

        self.static_color.currentIndexChanged.connect(self.schedule_apply)

        self.speed.valueChanged.connect(self.schedule_apply)
        self.color.currentIndexChanged.connect(self.schedule_apply)
        self.direction.currentIndexChanged.connect(self.schedule_apply)
        self.reactive.toggled.connect(self.on_reactive_toggled)
        self.reactive.toggled.connect(self.schedule_apply)

        self.profile_combo.currentTextChanged.connect(self.on_profile_combo_changed)
        self.btn_profile_new.clicked.connect(self.on_profile_new_clicked)
        self.btn_profile_save.clicked.connect(self.on_profile_save_clicked)
        self.btn_profile_save_as.clicked.connect(self.on_profile_save_as_clicked)
        self.btn_profile_rename.clicked.connect(self.on_profile_rename_clicked)
        self.btn_profile_delete.clicked.connect(self.on_profile_delete_clicked)

        self.autostart_flag.toggled.connect(self.on_autostart_flag_changed)
        self.resume_flag.toggled.connect(self.on_resume_flag_changed)
        self.power_monitor_flag.toggled.connect(self.on_power_monitor_flag_changed)
        self.notifications_checkbox.toggled.connect(self.on_notifications_toggled)
        self.dark_mode_checkbox.toggled.connect(self.on_dark_mode_toggled)
        self.ac_profile_combo.currentTextChanged.connect(self.on_ac_profile_changed)
        self.battery_profile_combo.currentTextChanged.connect(self.on_battery_profile_changed)
        self.refresh_autostart_flag()
        self.refresh_resume_controls()
        self.refresh_power_monitor_controls()
        self.refresh_profile_combo()
        self.refresh_power_profile_combos()

        if self.profile_data:
            self.restore_profile_after_startup()

        self.tray_icon = None
        self._tray_close_hint_shown = False
        self._quitting = False
        self._last_sync_ts = 0.0
        self.setup_tray_icon(enable_tray=enable_tray)

    def log(self, text, level="info"):
        timestamp = time.strftime("%H:%M:%S")
        entry = format_log(f"[{timestamp}] {text}", level)
        self.console.append(entry)
        sb = self.console.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def save_settings(self):
        try:
            write_settings_file(self.settings)
        except OSError as exc:
            self.log(f"Failed to save settings: {exc}", level="error")

    def notify(self, title, message, *, icon=QtWidgets.QSystemTrayIcon.Information):
        if not self.settings.get("show_notifications", True):
            return
        if self.tray_icon and self.tray_icon.isSystemTrayAvailable():
            self.tray_icon.showMessage(title, message, icon, NOTIFICATION_TIMEOUT_MS)

    def setup_tray_icon(self, enable_tray=True):
        if not enable_tray:
            return
        if not self.tray_supported:
            return
        if self.tray_icon is None:
            self.tray_icon = QtWidgets.QSystemTrayIcon(self.windowIcon(), self)
            menu = QtWidgets.QMenu(self)
            menu.aboutToShow.connect(self.on_tray_menu_about_to_show)
            show_action = menu.addAction("Show window")
            show_action.triggered.connect(self.show_window_from_tray)
            menu.addSeparator()
            turn_on_action = menu.addAction("Turn on")
            turn_on_action.triggered.connect(self.on_tray_turn_on)
            turn_off_action = menu.addAction("Turn off")
            turn_off_action.triggered.connect(self.on_tray_turn_off)
            menu.addSeparator()
            self.tray_profiles_menu = menu.addMenu("Profiles")
            self.rebuild_tray_profiles_menu()
            menu.addSeparator()
            quit_action = menu.addAction("Quit")
            quit_action.triggered.connect(self.on_tray_quit)
            self.tray_icon.setContextMenu(menu)
            self.tray_icon.activated.connect(self.on_tray_activated)
        if self.tray_icon:
            self.tray_icon.show()
        if self.settings.get("start_in_tray", False) and self.tray_icon:
            self.hide()
            self.notify(APP_DISPLAY_NAME, "Minimized to tray.")

    def on_log_toggle_toggled(self, checked):
        if not hasattr(self, "console_box"):
            return
        self.console_box.setVisible(checked)
        if hasattr(self, "log_toggle_button"):
            self.log_toggle_button.setText(
                "Hide activity log" if checked else "Show activity log"
            )

    def on_github_clicked(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(GITHUB_REPO_URL))

    def on_export_logs_clicked(self):
        import zipfile
        import tempfile
        from datetime import datetime
        
        # Ask user where to save the ZIP
        default_name = f"xmg-backlight-logs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Logs",
            os.path.expanduser(f"~/{default_name}"),
            "ZIP files (*.zip)"
        )
        if not file_path:
            return
        
        try:
            with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 1. Resume hook log
                if os.path.exists(RESUME_LOG_PATH):
                    try:
                        zf.write(RESUME_LOG_PATH, "resume-hook.log")
                    except Exception:
                        pass

                # 2. Installer log
                if os.path.exists(INSTALLER_LOG_PATH):
                    try:
                        zf.write(INSTALLER_LOG_PATH, "installer.log")
                    except Exception:
                        pass
                
                # 3. Power monitor journal
                try:
                    result = subprocess.run(
                        ["journalctl", "--user", "-u", "keyboard-backlight-power-monitor", 
                         "--since", "24 hours ago", "--no-pager"],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.stdout.strip():
                        zf.writestr("power-monitor.log", result.stdout)
                except Exception:
                    pass
                
                # 4. Resume service journal
                try:
                    result = subprocess.run(
                        ["journalctl", "--user", "-u", "keyboard-backlight-resume.service",
                         "--since", "24 hours ago", "--no-pager"],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.stdout.strip():
                        zf.writestr("resume-service.log", result.stdout)
                except Exception:
                    pass
                
                # 5. User config files
                if os.path.isdir(CONFIG_DIR):
                    for config_file in ["settings.json", "profile.json"]:
                        config_path = os.path.join(CONFIG_DIR, config_file)
                        if os.path.isfile(config_path):
                            zf.write(config_path, f"config/{config_file}")
                
                # 6. System info
                system_info = []
                system_info.append(f"Export date: {datetime.now().isoformat()}")
                system_info.append(f"App version: {APP_VERSION}")
                try:
                    result = subprocess.run(["uname", "-a"], capture_output=True, text=True, timeout=5)
                    system_info.append(f"System: {result.stdout.strip()}")
                except Exception:
                    pass
                try:
                    result = subprocess.run(["ite8291r3-ctl", "--version"], capture_output=True, text=True, timeout=5)
                    system_info.append(f"Driver: {result.stdout.strip() or result.stderr.strip()}")
                except Exception:
                    system_info.append("Driver: not found")
                zf.writestr("system-info.txt", "\n".join(system_info))
            
            QtWidgets.QMessageBox.information(
                self, "Export Complete",
                f"Logs exported successfully to:\n{file_path}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Export Failed",
                f"Failed to export logs:\n{str(e)}"
            )

    def show_window_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def on_tray_turn_on(self):
        self.on_power_on()
        self.notify(APP_DISPLAY_NAME, "Backlight turned on.")

    def on_tray_turn_off(self):
        self.on_power_off()
        self.notify(APP_DISPLAY_NAME, "Backlight turned off.")

    def rebuild_tray_profiles_menu(self):
        if not hasattr(self, "tray_profiles_menu"):
            return
        self.tray_profiles_menu.clear()
        for name in self.profile_store["profiles"].keys():
            action = self.tray_profiles_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == self.active_profile_name)
            action.triggered.connect(lambda checked, n=name: self.on_tray_profile_selected(n))

    def on_tray_profile_selected(self, name):
        if name == self.active_profile_name:
            self.restore_profile_after_startup()
            self.notify(APP_DISPLAY_NAME, f"Profile '{name}' reapplied.")
            return
        self.switch_active_profile(name, triggered_by_user=True)
        self.rebuild_tray_profiles_menu()
        self.notify(APP_DISPLAY_NAME, f"Profile '{name}' applied.")

    def on_tray_quit(self):
        self._quitting = True
        if self.tray_icon:
            self.tray_icon.hide()
        QtWidgets.QApplication.instance().quit()

    def on_tray_menu_about_to_show(self):
        self.sync_state_from_device()

    def on_tray_activated(self, reason):
        if reason in (
            QtWidgets.QSystemTrayIcon.Trigger,
            QtWidgets.QSystemTrayIcon.Context,
            QtWidgets.QSystemTrayIcon.DoubleClick,
        ):
            self.sync_state_from_device()
        if reason in (
            QtWidgets.QSystemTrayIcon.Trigger,
            QtWidgets.QSystemTrayIcon.DoubleClick,
        ):
            if self.isHidden():
                self.show_window_from_tray()
            else:
                self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self.request_state_sync()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.WindowActivate:
            self.request_state_sync()

    def request_state_sync(self, min_interval=0.5):
        now = time.monotonic()
        if (now - self._last_sync_ts) < min_interval:
            return
        self._last_sync_ts = now
        self.sync_state_from_device()

    def sync_state_from_device(self):
        rc, out, err = self.run_cli(
            ["query", "--brightness", "--state"],
            log_cmd=False,
            log_stdout=False,
            log_stderr=False,
        )
        if rc != 0:
            message = format_cli_error(rc, out, err)
            self.set_status(message)
            return

        brightness = None
        state = None
        for line in (out or "").splitlines():
            line = line.strip()
            if not line:
                continue
            lower = line.lower()
            if lower in ("on", "off"):
                state = lower
            else:
                try:
                    brightness = int(line)
                except ValueError:
                    continue

        if brightness is not None:
            prev_suppress = self._suppress
            self._suppress = True
            try:
                self.last_brightness = brightness
                self.b_spin.setValue(brightness)
            finally:
                self._suppress = prev_suppress

        if state == "off" or (brightness is not None and brightness == 0):
            self.is_off = True
        elif state == "on":
            self.is_off = False
        self.update_power_button()
        parts = []
        if state:
            parts.append(f"state={state}")
        if brightness is not None:
            parts.append(f"brightness={brightness}")
        suffix = ", ".join(parts) if parts else "unknown state"
        self.log(f"Synced device state: {suffix}")

    def closeEvent(self, event):
        if self._quitting:
            return super().closeEvent(event)
        if (
            self.settings.get("start_in_tray", False)
            and self.tray_icon
            and self.tray_supported
        ):
            event.ignore()
            self.hide()
            if not self._tray_close_hint_shown:
                self.notify(APP_DISPLAY_NAME, "Still running in tray. Quit from tray menu.")
                self._tray_close_hint_shown = True
            return
        return super().closeEvent(event)

    def on_notifications_toggled(self, checked):
        checked = bool(checked)
        if self.settings.get("show_notifications") == checked:
            return
        self.settings["show_notifications"] = checked
        self.save_settings()

    def on_dark_mode_toggled(self, checked):
        checked = bool(checked)
        if self.settings.get("dark_mode") == checked:
            return
        self.settings["dark_mode"] = checked
        self.save_settings()
        self.apply_styles()

    def refresh_power_profile_combos(self):
        if not hasattr(self, "ac_profile_combo") or not hasattr(self, "battery_profile_combo"):
            return
        profile_names = ["(none)"] + list(self.profile_store["profiles"].keys())

        ac_blocker = QtCore.QSignalBlocker(self.ac_profile_combo)
        battery_blocker = QtCore.QSignalBlocker(self.battery_profile_combo)
        try:
            self.ac_profile_combo.clear()
            self.battery_profile_combo.clear()
            self.ac_profile_combo.addItems(profile_names)
            self.battery_profile_combo.addItems(profile_names)

            ac_profile = self.settings.get("ac_profile", "")
            battery_profile = self.settings.get("battery_profile", "")

            ac_idx = self.ac_profile_combo.findText(ac_profile) if ac_profile else 0
            if ac_idx < 0:
                ac_idx = 0
            self.ac_profile_combo.setCurrentIndex(ac_idx)

            battery_idx = self.battery_profile_combo.findText(battery_profile) if battery_profile else 0
            if battery_idx < 0:
                battery_idx = 0
            self.battery_profile_combo.setCurrentIndex(battery_idx)
        finally:
            del ac_blocker
            del battery_blocker

    def on_ac_profile_changed(self, text):
        value = "" if text == "(none)" else text
        if self.settings.get("ac_profile") == value:
            return
        self.settings["ac_profile"] = value
        self.save_settings()
        self.set_status(f"AC profile set to: {text}")

    def on_battery_profile_changed(self, text):
        value = "" if text == "(none)" else text
        if self.settings.get("battery_profile") == value:
            return
        self.settings["battery_profile"] = value
        self.save_settings()
        self.set_status(f"Battery profile set to: {text}")

    def set_status(self, t, level="info"):
        self.log(t, level=level)

    def run_cli(self, args, **kwargs):
        return run_cmd(args, log_cb=self.log, **kwargs)

    def detect_device(self):
        rc, out, err = self.run_cli(["query", "--devices"])
        if rc == 0:
            msg = (out or "").strip() or "Device detected."
            self.hardware_label.setText(msg)
            self.set_status(msg)
            self.sync_initial_state()
        else:
            self.hardware_label.setText("Hardware: unknown")
            self.set_status(format_cli_error(rc, out, err))

    def sync_initial_state(self):
        rc, out, err = self.run_cli(["query", "--brightness", "--state"])
        if rc != 0:
            self.set_status(format_cli_error(rc, out, err))
            return

        brightness = None
        state = None
        for line in (out or "").splitlines():
            line = line.strip()
            if not line:
                continue
            lower = line.lower()
            if lower in ("on", "off"):
                state = lower
            else:
                try:
                    brightness = int(line)
                except ValueError:
                    continue

        if brightness is not None:
            self.last_brightness = brightness
            self._suppress = True
            self.b_spin.setValue(brightness)
            self._suppress = False

        if state == "off" or (brightness is not None and brightness == 0):
            self.is_off = True
        elif state == "on":
            self.is_off = False
        self.update_power_button()

    def apply_styles(self):
        base = """
        #MainView {
            background-color: #f6f8fb;
        }
        #AppSurface {
            background-color: transparent;
        }
        QLabel, QCheckBox, QToolButton {
            color: #1f2933;
            font-size: 13px;
        }
        #heroTitle {
            font-size: 28px;
            font-weight: 700;
            color: #0f172a;
        }
        #heroSubtitle {
            font-size: 14px;
            color: #52606d;
        }
        #heroCard {
            background-color: #ffffff;
            border-radius: 20px;
            border: 1px solid rgba(15, 33, 55, 0.08);
            background-image: radial-gradient(circle at 15% 20%, rgba(79, 209, 197, 0.25), transparent 60%),
                              radial-gradient(circle at 85% 10%, rgba(99, 102, 241, 0.2), transparent 45%);
        }
        #heroCaption {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #738095;
        }
        #hardwareBadge {
            padding: 6px 12px;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.12);
            color: #1d4ed8;
            font-weight: 600;
        }
        #pillButton {
            padding: 9px 18px;
            border-radius: 999px;
            font-weight: 600;
            border: 1px solid rgba(148,163,184,0.45);
            color: #0f172a;
            background-color: #ffffff;
        }
        #pillButton:checked {
            background-color: #3b82f6;
            border: none;
            color: #ffffff;
        }
        #surfaceCard {
            background-color: #ffffff;
            border-radius: 20px;
            border: 1px solid rgba(15, 23, 42, 0.05);
        }
        #sectionTitle {
            font-size: 17px;
            font-weight: 600;
            color: #111827;
        }
        #sectionSubtitle {
            font-size: 13px;
            color: #5f6b7a;
        }
        QComboBox, QSpinBox, QTextEdit {
            padding: 8px 12px;
            border-radius: 12px;
            border: 1px solid rgba(148, 163, 184, 0.4);
            background-color: #f9fafc;
            color: #1f2933;
        }
        QComboBox::drop-down {
            border: none;
        }
        QSlider::groove:horizontal {
            height: 6px;
            border-radius: 3px;
            background: rgba(148, 163, 184, 0.35);
        }
        QSlider::handle:horizontal {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #34d399, stop:1 #60a5fa);
            border: 2px solid #22c55e;
            border-radius: 10px;
            width: 20px;
            margin: -7px 0;
        }
        QSlider::sub-page:horizontal {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #38bdf8, stop:1 #a855f7);
            border-radius: 3px;
        }
        QPushButton {
            padding: 11px 18px;
            border-radius: 12px;
            font-weight: 600;
            border: 1px solid rgba(37, 99, 235, 0.15);
            background: #ffffff;
            color: #1f2933;
        }
        QPushButton:hover {
            border-color: rgba(37, 99, 235, 0.4);
        }
        QPushButton:pressed {
            background: #e2e8f0;
        }
        QPushButton:disabled {
            border: 1px solid rgba(148, 163, 184, 0.3);
            background: #f1f5f9;
            color: rgba(57, 77, 96, 0.6);
        }
        QPushButton:focus {
            outline: 0;
            border-color: rgba(99, 102, 241, 0.8);
        }
        #powerButton {
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 0.02em;
            border: none;
            color: #ffffff;
        }
        #powerButton[powerState="off"] {
            background-color: #16a34a;
        }
        #powerButton[powerState="on"] {
            background-color: #dc2626;
        }
        QTextEdit {
            min-height: 160px;
        }
        #logView {
            background-color: #0b1120;
            color: #e2e8f0;
            border: 1px solid rgba(15, 23, 42, 0.6);
        }
        #helperRow {
            background-color: #f9fafc;
            border-radius: 14px;
            border: 1px solid rgba(148, 163, 184, 0.35);
        }
        #helperInfoButton {
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.3);
            color: #0f172a;
            font-weight: 700;
        }
        #helperLabel {
            font-weight: 600;
            color: #1f2933;
        }
        #helperFlag {
            font-weight: 600;
        }
        #helperDetail {
            color: #4b5563;
            font-size: 12px;
        }
        QCheckBox::indicator {
            width: 20px;
            height: 20px;
        }
        QCheckBox::indicator:unchecked {
            border-radius: 6px;
            border: 1px solid rgba(148, 163, 184, 0.7);
            background-color: #ffffff;
        }
        QCheckBox::indicator:checked {
            border-radius: 6px;
            border: none;
            background-color: #3b82f6;
        }
        QPushButton#helperFlag {
            padding: 8px 22px;
            border-radius: 16px;
            border: 2px solid #94a3b8;
            background-color: #ffffff;
            font-weight: 600;
            color: #1f2933;
        }
        QPushButton#helperFlag:checked {
            border: 2px solid #16a34a;
            color: #ffffff;
            background-color: #16a34a;
        }
        QPushButton#helperFlag:disabled {
            background-color: #f1f5f9;
            color: #94a3b8;
            border: 2px solid #cbd5e1;
        }
        """
        dark = """
        #MainView {
            background-color: #0f172a;
        }
        #AppSurface {
            background-color: transparent;
        }
        QLabel, QCheckBox, QToolButton {
            color: #e2e8f0;
            font-size: 13px;
        }
        #heroTitle {
            font-size: 28px;
            font-weight: 700;
            color: #f1f5f9;
        }
        #heroSubtitle {
            font-size: 14px;
            color: #94a3b8;
        }
        #heroCard {
            background-color: #1e293b;
            border-radius: 20px;
            border: 1px solid rgba(148, 163, 184, 0.15);
            background-image: radial-gradient(circle at 15% 20%, rgba(79, 209, 197, 0.15), transparent 60%),
                              radial-gradient(circle at 85% 10%, rgba(99, 102, 241, 0.12), transparent 45%);
        }
        #heroCaption {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #64748b;
        }
        #hardwareBadge {
            padding: 6px 12px;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.2);
            color: #60a5fa;
            font-weight: 600;
        }
        #pillButton {
            padding: 9px 18px;
            border-radius: 999px;
            font-weight: 600;
            border: 1px solid rgba(148,163,184,0.3);
            color: #e2e8f0;
            background-color: #1e293b;
        }
        #pillButton:checked {
            background-color: #3b82f6;
            border: none;
            color: #ffffff;
        }
        #surfaceCard {
            background-color: #1e293b;
            border-radius: 20px;
            border: 1px solid rgba(148, 163, 184, 0.1);
        }
        #sectionTitle {
            font-size: 17px;
            font-weight: 700;
            color: #f1f5f9;
        }
        #sectionSubtitle {
            font-size: 13px;
            color: #94a3b8;
        }
        QComboBox {
            padding: 10px 14px;
            border-radius: 10px;
            border: 1px solid rgba(148, 163, 184, 0.3);
            background-color: #0f172a;
            color: #e2e8f0;
            font-size: 13px;
        }
        QComboBox:hover {
            border-color: rgba(99, 102, 241, 0.5);
        }
        QComboBox::drop-down {
            border: none;
        }
        QComboBox QAbstractItemView {
            background-color: #1e293b;
            color: #e2e8f0;
            border: 1px solid rgba(148, 163, 184, 0.3);
            selection-background-color: #3b82f6;
            selection-color: #ffffff;
        }
        QSlider::groove:horizontal {
            height: 6px;
            border-radius: 3px;
            background: rgba(148, 163, 184, 0.25);
        }
        QSlider::handle:horizontal {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #34d399, stop:1 #60a5fa);
            border: 2px solid #22c55e;
            border-radius: 10px;
            width: 20px;
            margin: -7px 0;
        }
        QSlider::sub-page:horizontal {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #38bdf8, stop:1 #a855f7);
            border-radius: 3px;
        }
        QSpinBox {
            padding: 10px 14px;
            border-radius: 10px;
            border: 1px solid rgba(148, 163, 184, 0.3);
            background-color: #0f172a;
            color: #e2e8f0;
            font-size: 13px;
        }
        QPushButton {
            padding: 11px 18px;
            border-radius: 12px;
            font-weight: 600;
            border: 1px solid rgba(148, 163, 184, 0.3);
            background: #1e293b;
            color: #e2e8f0;
        }
        QPushButton:hover {
            border-color: rgba(99, 102, 241, 0.5);
        }
        QPushButton:pressed {
            background: #334155;
            color: #e2e8f0;
        }
        QPushButton:disabled {
            border: 1px solid rgba(148, 163, 184, 0.2);
            background: #1e293b;
            color: rgba(148, 163, 184, 0.5);
        }
        QPushButton:focus {
            outline: 0;
            border-color: rgba(99, 102, 241, 0.8);
        }
        #powerButton {
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 0.02em;
            border: none;
            color: #ffffff;
        }
        #powerButton[powerState="off"] {
            background-color: #16a34a;
        }
        #powerButton[powerState="on"] {
            background-color: #dc2626;
        }
        QTextEdit {
            min-height: 160px;
        }
        #logView {
            background-color: #020617;
            color: #e2e8f0;
            border: 1px solid rgba(148, 163, 184, 0.2);
        }
        #helperRow {
            background-color: #0f172a;
            border-radius: 14px;
            border: 1px solid rgba(148, 163, 184, 0.2);
        }
        #helperInfoButton {
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.2);
            color: #e2e8f0;
            font-weight: 700;
        }
        #helperLabel {
            font-weight: 600;
            color: #e2e8f0;
        }
        #helperFlag {
            font-weight: 600;
        }
        #helperDetail {
            color: #94a3b8;
            font-size: 12px;
        }
        QCheckBox::indicator {
            width: 20px;
            height: 20px;
        }
        QCheckBox::indicator:unchecked {
            border-radius: 6px;
            border: 1px solid rgba(148, 163, 184, 0.5);
            background-color: #1e293b;
        }
        QCheckBox::indicator:checked {
            border-radius: 6px;
            border: none;
            background-color: #3b82f6;
        }
        QPushButton#helperFlag {
            padding: 8px 22px;
            border-radius: 16px;
            border: 2px solid #64748b;
            background-color: #1e293b;
            font-weight: 600;
            color: #e2e8f0;
        }
        QPushButton#helperFlag:checked {
            border: 2px solid #16a34a;
            color: #ffffff;
            background-color: #16a34a;
        }
        QPushButton#helperFlag:disabled {
            background-color: #1e293b;
            color: #64748b;
            border: 2px solid #334155;
        }
        QMessageBox {
            background-color: #1e293b;
            color: #e2e8f0;
        }
        QMessageBox QLabel {
            color: #e2e8f0;
        }
        QMessageBox QPushButton {
            min-width: 80px;
            padding: 8px 16px;
        }
        QInputDialog {
            background-color: #1e293b;
            color: #e2e8f0;
        }
        QInputDialog QLabel {
            color: #e2e8f0;
        }
        QInputDialog QLineEdit {
            padding: 10px 14px;
            border-radius: 10px;
            border: 1px solid rgba(148, 163, 184, 0.3);
            background-color: #0f172a;
            color: #e2e8f0;
            font-size: 13px;
        }
        """
        if self.settings.get("dark_mode", False):
            self.setStyleSheet(dark)
        else:
            self.setStyleSheet(base)

    def load_profile_into_controls(self, data):
        if not data:
            return

        brightness = clamp_int(data.get("brightness"), 0, 50, self.last_brightness)
        prev_suppress = self._suppress
        self._suppress = True
        try:
            self.last_brightness = brightness
            self.b_spin.setValue(brightness)
        finally:
            self._suppress = prev_suppress

        blockers = [
            QtCore.QSignalBlocker(self.mode),
            QtCore.QSignalBlocker(self.static_color),
            QtCore.QSignalBlocker(self.speed),
            QtCore.QSignalBlocker(self.color),
            QtCore.QSignalBlocker(self.direction),
            QtCore.QSignalBlocker(self.reactive),
        ]
        try:
            mode_value = sanitize_choice(data.get("mode"), EFFECTS, "static")
            self.mode.setCurrentText(mode_value)

            static_value = sanitize_choice(
                data.get("static_color"), COLORS, self.last_static_color
            )
            self.static_color.setCurrentText(static_value)
            self.last_static_color = static_value

            self.speed.setValue(clamp_int(data.get("speed"), 0, 10, self.speed.value()))

            color_value = data.get("color") or "none"
            if color_value != "none" and color_value not in COLORS:
                color_value = "none"
            self.color.setCurrentText(color_value)

            reactive_value = bool(data.get("reactive"))
            self.reactive.setChecked(reactive_value)

            direction_value = sanitize_choice(
                data.get("direction"), DIRECTIONS, self.direction.currentText()
            )
            if reactive_value:
                direction_value = "none"
            self.direction.setCurrentText(direction_value)
        finally:
            del blockers

        self.update_panels()

    def capture_profile_state(self):
        mode_value = sanitize_choice(self.mode.currentText(), EFFECTS, "static")
        static_value = sanitize_choice(
            self.static_color.currentText(), COLORS, self.last_static_color
        )
        self.last_static_color = static_value

        color_value = self.color.currentText() or "none"
        if color_value != "none" and color_value not in COLORS:
            color_value = "none"

        direction_value = self.direction.currentText()
        if direction_value not in DIRECTIONS:
            direction_value = "none"

        reactive_value = bool(self.reactive.isChecked())
        if reactive_value:
            direction_value = "none"

        return {
            "brightness": int(self.b_spin.value()),
            "mode": mode_value,
            "static_color": static_value,
            "speed": clamp_int(self.speed.value(), 0, 10, 5),
            "color": color_value,
            "direction": direction_value,
            "reactive": reactive_value,
        }

    def persist_profile(self):
        state = self.capture_profile_state()
        self.update_active_profile_state(state)
        self.save_profile_store()

    def update_active_profile_state(self, state):
        self.profile_store["profiles"][self.active_profile_name] = dict(state)
        self.profile_store["active"] = self.active_profile_name
        self.profile_data = dict(state)

    def save_profile_store(self):
        try:
            self._ignore_profile_events = True
            write_profile_store(self.profile_store)
            self.watch_profile_paths()
        except OSError as exc:
            self.set_status(f"Failed to save profile: {exc}", level="error")
        finally:
            self._ignore_profile_events = False

    def refresh_profile_combo(self):
        if not hasattr(self, "profile_combo"):
            return
        blocker = QtCore.QSignalBlocker(self.profile_combo)
        self._updating_profile_combo = True
        try:
            self.profile_combo.clear()
            for name in self.profile_store["profiles"].keys():
                self.profile_combo.addItem(name)
            idx = self.profile_combo.findText(self.active_profile_name)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        finally:
            self._updating_profile_combo = False
            del blocker
        self.rebuild_tray_profiles_menu()
        self.refresh_power_profile_combos()

    def on_profile_combo_changed(self, name):
        if self._updating_profile_combo or not name:
            return
        if name == self.active_profile_name:
            return
        self.switch_active_profile(name, triggered_by_user=True)

    def prompt_profile_name(self, title, label, initial=""):
        text, ok = QtWidgets.QInputDialog.getText(self, title, label, text=initial)
        if not ok:
            return None
        name = text.strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Invalid name", "Profile name cannot be empty.")
            return None
        return name

    def on_profile_save_clicked(self):
        self.persist_profile()
        self.set_status(f"Profile '{self.active_profile_name}' saved.")

    def on_profile_new_clicked(self):
        name = self.prompt_profile_name("New profile", "Profile name:")
        if not name:
            return
        if name in self.profile_store["profiles"]:
            QtWidgets.QMessageBox.warning(
                self, "Name in use", "A profile with that name already exists."
            )
            return
        self.profile_store["profiles"][name] = dict(DEFAULT_PROFILE_STATE)
        self.active_profile_name = name
        self.profile_store["active"] = name
        self.profile_data = dict(DEFAULT_PROFILE_STATE)
        self.save_profile_store()
        self.refresh_profile_combo()
        self.load_profile_into_controls(self.profile_data)
        self.set_status(f"New profile '{name}' created.")

    def on_profile_save_as_clicked(self):
        name = self.prompt_profile_name("Save profile", "Profile name:", self.active_profile_name)
        if not name:
            return
        if name in self.profile_store["profiles"] and name != self.active_profile_name:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Overwrite profile",
                f"Profile '{name}' already exists. Overwrite?",
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self.active_profile_name = name
        state = self.capture_profile_state()
        self.update_active_profile_state(state)
        self.save_profile_store()
        self.refresh_profile_combo()
        self.set_status(f"Profile '{name}' saved.")

    def on_profile_rename_clicked(self):
        new_name = self.prompt_profile_name(
            "Rename profile", "New name:", self.active_profile_name
        )
        if not new_name or new_name == self.active_profile_name:
            return
        if new_name in self.profile_store["profiles"]:
            QtWidgets.QMessageBox.warning(
                self, "Name in use", "Another profile already has that name."
            )
            return
        self.profile_store["profiles"][new_name] = self.profile_store["profiles"].pop(
            self.active_profile_name
        )
        self.active_profile_name = new_name
        self.profile_store["active"] = new_name
        self.profile_data = dict(self.profile_store["profiles"][new_name])
        self.save_profile_store()
        self.refresh_profile_combo()
        self.set_status(f"Profile renamed to '{new_name}'.")

    def on_profile_delete_clicked(self):
        if len(self.profile_store["profiles"]) <= 1:
            QtWidgets.QMessageBox.warning(
                self, "Cannot delete", "At least one profile must remain."
            )
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete profile",
            f"Delete profile '{self.active_profile_name}'?",
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        del self.profile_store["profiles"][self.active_profile_name]
        self.active_profile_name = next(iter(self.profile_store["profiles"].keys()))
        self.profile_store["active"] = self.active_profile_name
        self.profile_data = dict(self.profile_store["profiles"][self.active_profile_name])
        self.save_profile_store()
        self.refresh_profile_combo()
        self.load_profile_into_controls(self.profile_data)
        self.set_status(f"Profile '{self.active_profile_name}' is now active.")
        if not self.is_off:
            self.apply_current_mode()

    def switch_active_profile(self, name, triggered_by_user=False):
        if name not in self.profile_store["profiles"]:
            self.set_status(f"Profile '{name}' not found.", level="error")
            self.refresh_profile_combo()
            return
        previous_state = self.capture_profile_state()
        self.profile_store["profiles"][self.active_profile_name] = previous_state
        self.active_profile_name = name
        self.profile_store["active"] = name
        self.profile_data = dict(self.profile_store["profiles"][name])
        self.save_profile_store()
        self.refresh_profile_combo()
        self.load_profile_into_controls(self.profile_data)
        self.set_status(f"Profile '{name}' loaded.")
        if triggered_by_user and not self.is_off:
            self.apply_current_mode()

    def refresh_autostart_flag(self, detail_text=None):
        state = is_autostart_enabled()
        self.autostart_enabled = state
        status_label = "Enabled" if state else "Disabled"
        if hasattr(self, "autostart_status_label"):
            if detail_text:
                self.autostart_status_label.setText(detail_text)
                self.autostart_status_label.setVisible(True)
            else:
                self.autostart_status_label.clear()
                self.autostart_status_label.setVisible(False)
        if hasattr(self, "autostart_flag"):
            blocker = QtCore.QSignalBlocker(self.autostart_flag)
            try:
                self.autostart_flag.setChecked(state)
                self.autostart_flag.setText(status_label)
            finally:
                del blocker

    def on_autostart_flag_changed(self, value):
        desired = bool(value)
        if desired == self.autostart_enabled:
            return
        try:
            if self.autostart_enabled:
                remove_autostart_entry()
                self.settings["start_in_tray"] = False
                self.save_settings()
                self.set_status("Autostart entry removed.")
            else:
                ensure_restore_script_executable()
                create_autostart_entry()
                self.settings["start_in_tray"] = True
                self.save_settings()
                self.set_status(f"Autostart entry created at {AUTOSTART_ENTRY}.")
        except OSError as exc:
            error = f"Autostart error: {exc}"
            self.set_status(error, level="error")
            blocker = QtCore.QSignalBlocker(self.autostart_flag)
            try:
                self.autostart_flag.setChecked(self.autostart_enabled)
            finally:
                del blocker
            self.refresh_autostart_flag(detail_text=error)
            return
        self.refresh_autostart_flag()

    def refresh_resume_controls(self):
        status_enabled, status_text = is_resume_service_enabled()
        self.resume_enabled = status_enabled
        self.resume_status = status_text
        if hasattr(self, "resume_status_label"):
            detail_text = (
                status_text
                if status_text and status_text not in ("Enabled", "Disabled")
                else ""
            )
            self.resume_status_label.setText(detail_text)
            self.resume_status_label.setVisible(bool(detail_text))
        if hasattr(self, "resume_flag"):
            blocker = QtCore.QSignalBlocker(self.resume_flag)
            try:
                self.resume_flag.setChecked(status_enabled)
                self.resume_flag.setText("Enabled" if status_enabled else "Disabled")
                disabled = status_text == "systemctl not available"
                self.resume_flag.setEnabled(not disabled)
                if disabled:
                    self.resume_flag.setToolTip(
                        "systemctl non disponibile: installa systemd o abilita manualmente."
                    )
                else:
                    self.resume_flag.setToolTip("")
            finally:
                del blocker

    def on_resume_flag_changed(self, value):
        desired = bool(value)
        if desired == self.resume_enabled:
            return
        if self.resume_status == "systemctl not available":
            blocker = QtCore.QSignalBlocker(self.resume_flag)
            try:
                self.resume_flag.setChecked(self.resume_enabled)
            finally:
                del blocker
            return
        if desired:
            ok, message = enable_resume_service()
        else:
            ok, message = disable_resume_service()
        if ok:
            self.set_status(message)
        else:
            self.set_status(message, level="error")
            blocker = QtCore.QSignalBlocker(self.resume_flag)
            try:
                self.resume_flag.setChecked(self.resume_enabled)
            finally:
                del blocker
            return
        self.refresh_resume_controls()

    def refresh_power_monitor_controls(self):
        status_enabled, status_text = is_power_monitor_enabled()
        self.power_monitor_enabled = status_enabled
        self.power_monitor_status = status_text
        if hasattr(self, "power_monitor_status_label"):
            detail_text = (
                status_text
                if status_text and status_text not in ("Enabled", "Disabled")
                else ""
            )
            self.power_monitor_status_label.setText(detail_text)
            self.power_monitor_status_label.setVisible(bool(detail_text))
        if hasattr(self, "power_monitor_flag"):
            blocker = QtCore.QSignalBlocker(self.power_monitor_flag)
            try:
                self.power_monitor_flag.setChecked(status_enabled)
                self.power_monitor_flag.setText("Enabled" if status_enabled else "Disabled")
                disabled = status_text == "systemctl not available"
                self.power_monitor_flag.setEnabled(not disabled)
                if disabled:
                    self.power_monitor_flag.setToolTip(
                        "systemctl non disponibile: installa systemd per usare il monitor."
                    )
                else:
                    self.power_monitor_flag.setToolTip("")
            finally:
                del blocker

    def on_power_monitor_flag_changed(self, value):
        desired = bool(value)
        if desired == self.power_monitor_enabled:
            return
        if self.power_monitor_status == "systemctl not available":
            blocker = QtCore.QSignalBlocker(self.power_monitor_flag)
            try:
                self.power_monitor_flag.setChecked(self.power_monitor_enabled)
            finally:
                del blocker
            return
        if desired:
            ok, message = enable_power_monitor_service()
        else:
            ok, message = disable_power_monitor_service()
        if ok:
            self.set_status(message)
        else:
            self.set_status(message, level="error")
            blocker = QtCore.QSignalBlocker(self.power_monitor_flag)
            try:
                self.power_monitor_flag.setChecked(self.power_monitor_enabled)
            finally:
                del blocker
            return
        self.refresh_power_monitor_controls()

    def restore_profile_after_startup(self):
        if not self.profile_data:
            return
        brightness = clamp_int(
            self.profile_data.get("brightness"), 0, 50, self.last_brightness
        )
        if brightness <= 0:
            return
        self.set_status(
            f"Restoring saved profile '{self.active_profile_name}' from {PROFILE_PATH}."
        )
        self.is_off = False
        self.apply_current_mode()

    def watch_profile_paths(self):
        files = list(self.profile_watcher.files())
        for path in files:
            self.profile_watcher.removePath(path)
        dirs = list(self.profile_watcher.directories())
        for path in dirs:
            self.profile_watcher.removePath(path)

        ensure_config_dir()
        targets = []
        if os.path.isdir(CONFIG_DIR):
            targets.append(CONFIG_DIR)
        if os.path.isfile(PROFILE_PATH):
            targets.append(PROFILE_PATH)

        for target in targets:
            self.profile_watcher.addPath(target)

    def reload_profile_store_from_disk(self, announce=True):
        self.profile_store = load_profile_store()
        self.active_profile_name = self.profile_store["active"]
        self.profile_data = dict(self.profile_store["profiles"][self.active_profile_name])
        self.refresh_profile_combo()
        if announce:
            self.load_profile_into_controls(self.profile_data)

    def on_profile_file_changed(self, path):
        if path != PROFILE_PATH:
            return
        if self._ignore_profile_events:
            self.watch_profile_paths()
            return
        self.watch_profile_paths()
        try:
            self.reload_profile_store_from_disk(announce=True)
            self.set_status("Profiles reloaded from disk.")
        except (OSError, json.JSONDecodeError) as exc:
            self.set_status(f"Failed to reload profiles: {exc}", level="error")

    def on_profile_directory_changed(self, path):
        if path != CONFIG_DIR:
            return
        if self._ignore_profile_events:
            self.watch_profile_paths()
            return
        self.watch_profile_paths()
        if os.path.isfile(PROFILE_PATH):
            try:
                self.reload_profile_store_from_disk(announce=True)
                self.set_status("Profiles updated after directory change.")
            except (OSError, json.JSONDecodeError) as exc:
                self.set_status(f"Failed to reload profiles: {exc}", level="error")

    def update_panels(self):
        is_static = (self.mode.currentText() == "static")
        self.static_label.setVisible(is_static)
        self.static_color.setVisible(is_static)
        self.effect_panel.setVisible(not is_static)
        self.direction.setEnabled(not self.reactive.isChecked())
        if self.reactive.isChecked():
            self.direction.setCurrentText("none")

    def update_power_button(self):
        if not hasattr(self, "btn_power"):
            return
        label = "Turn on" if self.is_off else "Turn off"
        self.btn_power.setText(label)
        self.btn_power.setProperty("powerState", "off" if self.is_off else "on")
        self.btn_power.style().unpolish(self.btn_power)
        self.btn_power.style().polish(self.btn_power)

    def on_reactive_toggled(self, checked):
        self.direction.setEnabled(not checked)
        if checked:
            self.direction.setCurrentText("none")

    def on_mode_changed(self):
        self.update_panels()
        if not self.is_off:
            self.schedule_apply()

    def on_brightness_changed(self, v):
        if self._suppress:
            return
        v = int(v)
        was_off = self.is_off
        self.last_brightness = v
        if v <= 0:
            self.brightness_timer.stop()
            self.on_power_off()
            return
        self.is_off = False
        if was_off:
            self._pending_effect_after_brightness = True
        self.brightness_timer.start()

    def on_power_on(self):
        self.is_off = False
        v = self.last_brightness if self.last_brightness > 0 else 40
        self._suppress = True
        self.b_spin.setValue(v)
        self._suppress = False
        self.apply_current_mode()
        self.update_power_button()

    def on_power_off(self):
        rc, out, err = self.run_cli(["off"])
        self.is_off = True
        if rc == 0:
            self.set_status("Backlight off")
            self.persist_profile()
            self.update_power_button()
        else:
            self.set_status(format_cli_error(rc, out, err))

    def on_power_toggle(self):
        if self.is_off:
            self.on_power_on()
        else:
            self.on_power_off()

    def schedule_apply(self):
        if self.is_off:
            return
        self.apply_timer.start()

    def apply_brightness_only(self):
        if self.is_off:
            return
        v = int(self.b_spin.value())
        rc, out, err = self.run_cli(
            ["brightness", str(v)],
            log_cmd=False,
            log_stdout=False,
            log_stderr=False,
        )
        if rc == 0:
            self.set_status(f"Brightness set to {v}.")
            self.persist_profile()
            if self._pending_effect_after_brightness:
                self._pending_effect_after_brightness = False
                self.apply_current_mode()
        else:
            self.set_status(format_cli_error(rc, out, err))

    def hard_reset_then(self, args):
        self.run_cli(["off"])
        time.sleep(0.06)
        return self.run_cli(args)

    def apply_static(self):
        v = int(self.b_spin.value())
        c = self.static_color.currentText()
        self.last_static_color = c
        rc, out, err = self.hard_reset_then(["monocolor", "-b", str(v), "--name", c])
        if rc == 0:
            self.set_status(f"Static applied: brightness {v}, color {c}")
            self.persist_profile()
        else:
            self.set_status(f"Error ({rc}): {err or out or 'unknown'}")

    def build_effect_args(self):
        v = int(self.b_spin.value())
        eff = self.mode.currentText()
        args = ["effect", "-b", str(v)]

        if self.speed.value() != 5:
            args += ["-s", str(self.speed.value())]

        col = self.color.currentText()
        if col != "none":
            args += ["-c", col]

        if self.reactive.isChecked():
            args.append("-r")
        else:
            d = self.direction.currentText()
            if d != "none":
                args += ["-d", d]

        args.append(eff)
        return args

    def apply_effect(self):
        args = self.build_effect_args()
        rc, out, err, used = apply_effect_with_fallback(
            args, runner=lambda a: self.run_cli(a)
        )
        if rc == 0:
            used_str = " ".join(used[1:])
            self.set_status(f"Effect applied: {used_str}")
            self.persist_profile()
        else:
            self.set_status(f"Error ({rc}): {err or out or 'unknown'}")

    def apply_current_mode(self):
        if self.is_off:
            return
        if self.mode.currentText() == "static":
            self.apply_static()
        else:
            self.apply_effect()


def main():
    app = QtWidgets.QApplication([])

    lock_handle = acquire_single_instance_lock()
    if lock_handle is None:
        QtWidgets.QMessageBox.warning(
            None,
            APP_DISPLAY_NAME,
            "Application is already running.\n\nCheck the system tray for the running instance.",
        )
        sys.exit(0)

    w = Main()
    if not (w.settings.get("start_in_tray", False) and w.tray_supported and w.tray_icon):
        w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
