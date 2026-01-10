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
from collections import deque
from PySide6 import QtCore, QtWidgets, QtGui

APP_DISPLAY_NAME = "XMG Backlight Management"
APP_VERSION = "1.7.0"
GITHUB_REPO_URL = "https://github.com/Darayavaush-84/xmg_backlight_installer"
NOTIFICATION_TIMEOUT_MS = 1500
ACTIVITY_LOG_MAX_LINES = 100
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
TRANSLATIONS_DIR = os.path.join(BASE_DIR, "translations")
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
    "dark_mode": True,
    "ac_profile": "",
    "battery_profile": "",
    "language": "",
}

LANGUAGE_LABELS = {
    "en": "English",
    "it": "Italiano",
    "de": "Deutsch",
    "es": "Español",
    "fr": "Français",
}

FLAG_ICON_CACHE = {}


def build_flag_icon(code):
    cached = FLAG_ICON_CACHE.get(code)
    if cached is not None:
        return cached

    width, height = 20, 14
    pixmap = QtGui.QPixmap(width, height)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
    rect = QtCore.QRect(0, 0, width, height)

    if code == "it":
        third = width // 3
        middle = width - 2 * third
        painter.fillRect(0, 0, third, height, QtGui.QColor("#009246"))
        painter.fillRect(third, 0, middle, height, QtGui.QColor("#ffffff"))
        painter.fillRect(third + middle, 0, third, height, QtGui.QColor("#ce2b37"))
    elif code == "fr":
        third = width // 3
        middle = width - 2 * third
        painter.fillRect(0, 0, third, height, QtGui.QColor("#0055a4"))
        painter.fillRect(third, 0, middle, height, QtGui.QColor("#ffffff"))
        painter.fillRect(third + middle, 0, third, height, QtGui.QColor("#ef4135"))
    elif code == "de":
        third = height // 3
        middle = height - 2 * third
        painter.fillRect(0, 0, width, third, QtGui.QColor("#000000"))
        painter.fillRect(0, third, width, middle, QtGui.QColor("#dd0000"))
        painter.fillRect(0, third + middle, width, third, QtGui.QColor("#ffce00"))
    elif code == "es":
        band = height // 4
        middle = height - 2 * band
        painter.fillRect(0, 0, width, band, QtGui.QColor("#aa151b"))
        painter.fillRect(0, band, width, middle, QtGui.QColor("#f1bf00"))
        painter.fillRect(0, band + middle, width, band, QtGui.QColor("#aa151b"))
    elif code == "en":
        painter.fillRect(rect, QtGui.QColor("#012169"))
        cross = max(4, height // 3)
        inner = max(2, cross // 2)
        cx = width // 2
        cy = height // 2
        painter.fillRect(cx - cross // 2, 0, cross, height, QtGui.QColor("#ffffff"))
        painter.fillRect(0, cy - cross // 2, width, cross, QtGui.QColor("#ffffff"))
        painter.fillRect(cx - inner // 2, 0, inner, height, QtGui.QColor("#c8102e"))
        painter.fillRect(0, cy - inner // 2, width, inner, QtGui.QColor("#c8102e"))
    else:
        painter.fillRect(rect, QtGui.QColor("#64748b"))

    painter.setPen(QtGui.QPen(QtGui.QColor(148, 163, 184, 160)))
    painter.drawRect(0, 0, width - 1, height - 1)
    painter.end()

    icon = QtGui.QIcon(pixmap)
    FLAG_ICON_CACHE[code] = icon
    return icon


def normalize_language_code(value):
    if not value:
        return ""
    return str(value).split("-")[0].split("_")[0].lower()


def clamp_int(value, minimum, maximum, fallback):
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, ivalue))


def set_combo_by_data(combo, value):
    idx = combo.findData(value)
    if idx >= 0:
        combo.setCurrentIndex(idx)
        return True
    return False


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
    language_value = normalize_language_code(data.get("language", ""))
    if language_value not in LANGUAGE_LABELS:
        language_value = ""
    base["language"] = language_value
    return base


def load_translations(language):
    lang = normalize_language_code(language)
    if not lang:
        return {}
    path = os.path.join(TRANSLATIONS_DIR, f"{lang}.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def detect_system_language():
    try:
        languages = QtCore.QLocale.system().uiLanguages() or []
    except Exception:
        languages = []
    for lang in languages:
        code = normalize_language_code(lang)
        if code in LANGUAGE_LABELS:
            return code
    return "en"


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
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{APP_VERSION}")
        self.resize(980, 500)
        self.activity_log_buffer = deque(maxlen=ACTIVITY_LOG_MAX_LINES)

        QtWidgets.QApplication.setStyle("Fusion")
        QtWidgets.QApplication.setQuitOnLastWindowClosed(False)
        base_icon = QtGui.QIcon.fromTheme("input-keyboard")
        if base_icon.isNull():
            base_icon = self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
        self.setWindowIcon(base_icon)

        self.settings = load_settings()
        self.language = normalize_language_code(self.settings.get("language", ""))
        if not self.language:
            self.language = detect_system_language()
        if self.language not in LANGUAGE_LABELS:
            self.language = "en"
        self.translations = load_translations(self.language)
        self.fallback_translations = load_translations("en")
        self.tray_supported = QtWidgets.QSystemTrayIcon.isSystemTrayAvailable()
        self.is_off = False
        self.last_brightness = 40
        self.last_static_color = "white"
        self._suppress = False
        self._pending_effect_after_brightness = False
        self._ignore_profile_events = False
        self._updating_profile_combo = False
        self._profile_dirty = False
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
        self.hero_subtitle = QtWidgets.QLabel(
            self.tr("hero.subtitle")
        )
        self.hero_subtitle.setWordWrap(True)
        self.hero_subtitle.setObjectName("heroSubtitle")
        hero_text.addWidget(hero_title)
        hero_text.addWidget(self.hero_subtitle)

        hardware_row = QtWidgets.QHBoxLayout()
        hardware_row.setSpacing(8)
        self.hardware_caption = QtWidgets.QLabel(self.tr("hero.hardware"))
        self.hardware_caption.setObjectName("heroCaption")
        self.hardware_label = QtWidgets.QLabel(self.tr("hero.hardware_unknown"))
        self.hardware_label.setWordWrap(True)
        self.hardware_label.setObjectName("hardwareBadge")
        self.hardware_detected = False
        hardware_row.addWidget(self.hardware_caption)
        hardware_row.addWidget(self.hardware_label, 1)
        hero_text.addLayout(hardware_row)

        hero_layout.addLayout(hero_text, 1)

        hero_controls = QtWidgets.QVBoxLayout()
        hero_controls.setSpacing(12)
        hero_controls.addStretch(1)
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addStretch(1)
        self.github_button = QtWidgets.QPushButton(self.tr("buttons.github"))
        self.github_button.setObjectName("pillButton")
        top_row.addWidget(self.github_button)
        hero_controls.addLayout(top_row)
        self.export_logs_button = QtWidgets.QPushButton(self.tr("buttons.export_logs"))
        self.export_logs_button.setObjectName("pillButton")
        hero_controls.addWidget(self.export_logs_button, 0, QtCore.Qt.AlignRight)
        self.log_toggle_button = QtWidgets.QPushButton(self.tr("buttons.show_activity_log"))
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

        self.bright_title = QtWidgets.QLabel(self.tr("brightness.title"))
        self.bright_title.setObjectName("sectionTitle")
        bc_layout.addWidget(self.bright_title)

        self.bright_caption = QtWidgets.QLabel(self.tr("brightness.subtitle"))
        self.bright_caption.setObjectName("sectionSubtitle")
        self.bright_caption.setWordWrap(True)
        bc_layout.addWidget(self.bright_caption)

        gl = QtWidgets.QGridLayout()
        gl.setColumnStretch(1, 1)
        gl.setHorizontalSpacing(16)
        gl.setVerticalSpacing(12)

        self.brightness_value_label = QtWidgets.QLabel(self.tr("brightness.value"))
        gl.addWidget(self.brightness_value_label, 0, 0)
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

        self.btn_power = QtWidgets.QPushButton(self.tr("buttons.turn_on"))
        self.btn_power.setObjectName("powerButton")
        self.btn_power.setMinimumHeight(52)
        bc_layout.addWidget(self.btn_power)

        left_col.addWidget(brightness_card)

        mode_card = QtWidgets.QFrame()
        mode_card.setObjectName("surfaceCard")
        mode_layout = QtWidgets.QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(24, 24, 24, 24)
        mode_layout.setSpacing(18)

        mode_header = QtWidgets.QHBoxLayout()
        self.mode_title = QtWidgets.QLabel(self.tr("effects.title"))
        self.mode_title.setObjectName("sectionTitle")
        mode_header.addWidget(self.mode_title)
        mode_header.addStretch(1)
        self.apply_button = QtWidgets.QPushButton(self.tr("buttons.apply"))
        self.apply_button.setObjectName("applyButton")
        self.apply_button.setEnabled(False)
        mode_header.addWidget(self.apply_button)
        mode_layout.addLayout(mode_header)

        self.mode_caption = QtWidgets.QLabel(self.tr("effects.subtitle"))
        self.mode_caption.setWordWrap(True)
        self.mode_caption.setObjectName("sectionSubtitle")
        mode_layout.addWidget(self.mode_caption)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(16)
        self.mode_label = QtWidgets.QLabel(self.tr("effects.effect"))
        mode_row.addWidget(self.mode_label)
        self.mode = QtWidgets.QComboBox()
        for effect in EFFECTS:
            self.mode.addItem(self.tr(f"effect.{effect}"), effect)
        set_combo_by_data(self.mode, "static")
        mode_row.addWidget(self.mode, 1)

        self.static_label = QtWidgets.QLabel(self.tr("effects.static_color"))
        mode_row.addWidget(self.static_label)
        self.static_color = QtWidgets.QComboBox()
        for color in COLORS:
            self.static_color.addItem(self.tr(f"color.{color}"), color)
        set_combo_by_data(self.static_color, self.last_static_color)
        mode_row.addWidget(self.static_color, 1)
        mode_layout.addLayout(mode_row)

        self.effect_panel = QtWidgets.QWidget()
        epl = QtWidgets.QGridLayout(self.effect_panel)
        epl.setContentsMargins(0, 0, 0, 0)
        epl.setHorizontalSpacing(16)
        epl.setVerticalSpacing(12)

        self.speed_label = QtWidgets.QLabel(self.tr("effects.speed"))
        epl.addWidget(self.speed_label, 0, 0)
        self.speed = QtWidgets.QSpinBox()
        self.speed.setRange(0, 10)
        self.speed.setValue(5)
        self.speed.setButtonSymbols(QtWidgets.QSpinBox.NoButtons)
        epl.addWidget(self.speed, 0, 1)

        self.dynamic_color_label = QtWidgets.QLabel(self.tr("effects.dynamic_color"))
        epl.addWidget(self.dynamic_color_label, 0, 2)
        self.color = QtWidgets.QComboBox()
        self.color.addItem(self.tr("color.none"), "none")
        for color in COLORS:
            self.color.addItem(self.tr(f"color.{color}"), color)
        set_combo_by_data(self.color, "none")
        epl.addWidget(self.color, 0, 3)

        self.reactive = QtWidgets.QCheckBox(self.tr("effects.reactive"))
        epl.addWidget(self.reactive, 1, 1)

        self.direction_label = QtWidgets.QLabel(self.tr("effects.direction"))
        epl.addWidget(self.direction_label, 1, 2)
        self.direction = QtWidgets.QComboBox()
        for direction in DIRECTIONS:
            self.direction.addItem(self.tr(f"direction.{direction}"), direction)
        set_combo_by_data(self.direction, "none")
        epl.addWidget(self.direction, 1, 3)

        mode_layout.addWidget(self.effect_panel)
        right_col.addWidget(mode_card)

        profiles_card = QtWidgets.QFrame()
        profiles_card.setObjectName("surfaceCard")
        profiles_layout = QtWidgets.QVBoxLayout(profiles_card)
        profiles_layout.setContentsMargins(24, 24, 24, 24)
        profiles_layout.setSpacing(16)

        self.profiles_title = QtWidgets.QLabel(self.tr("profiles.title"))
        self.profiles_title.setObjectName("sectionTitle")
        profiles_layout.addWidget(self.profiles_title)

        self.profiles_caption = QtWidgets.QLabel(self.tr("profiles.subtitle"))
        self.profiles_caption.setWordWrap(True)
        self.profiles_caption.setObjectName("sectionSubtitle")
        profiles_layout.addWidget(self.profiles_caption)

        pl = QtWidgets.QGridLayout()
        pl.setColumnStretch(1, 1)
        pl.setHorizontalSpacing(12)
        pl.setVerticalSpacing(10)
        self.active_profile_label = QtWidgets.QLabel(self.tr("profiles.active"))
        pl.addWidget(self.active_profile_label, 0, 0)
        self.profile_combo = QtWidgets.QComboBox()
        pl.addWidget(self.profile_combo, 0, 1, 1, 2)
        self.btn_profile_save = QtWidgets.QPushButton(self.tr("buttons.save"))
        pl.addWidget(self.btn_profile_save, 0, 3)
        self.btn_profile_new = QtWidgets.QPushButton(self.tr("buttons.new"))
        pl.addWidget(self.btn_profile_new, 1, 0)
        self.btn_profile_save_as = QtWidgets.QPushButton(self.tr("buttons.save_as"))
        pl.addWidget(self.btn_profile_save_as, 1, 1)
        self.btn_profile_rename = QtWidgets.QPushButton(self.tr("buttons.rename"))
        pl.addWidget(self.btn_profile_rename, 1, 2)
        self.btn_profile_delete = QtWidgets.QPushButton(self.tr("buttons.delete"))
        pl.addWidget(self.btn_profile_delete, 1, 3)
        profiles_layout.addLayout(pl)

        self.pp_title = QtWidgets.QLabel(self.tr("profiles.power_title"))
        self.pp_title.setObjectName("sectionTitle")
        self.pp_title.setContentsMargins(0, 12, 0, 0)
        profiles_layout.addWidget(self.pp_title)

        power_profiles_row = QtWidgets.QFrame()
        power_profiles_row.setObjectName("helperRow")
        pp_layout = QtWidgets.QGridLayout(power_profiles_row)
        pp_layout.setContentsMargins(12, 10, 12, 10)
        pp_layout.setHorizontalSpacing(12)
        pp_layout.setVerticalSpacing(8)
        pp_layout.setColumnStretch(1, 1)

        self.ac_label = QtWidgets.QLabel(self.tr("profiles.on_ac"))
        pp_layout.addWidget(self.ac_label, 0, 0)
        self.ac_profile_combo = QtWidgets.QComboBox()
        self.ac_profile_combo.setToolTip(self.tr("profiles.on_ac_tooltip"))
        pp_layout.addWidget(self.ac_profile_combo, 0, 1)

        self.battery_label = QtWidgets.QLabel(self.tr("profiles.on_battery"))
        pp_layout.addWidget(self.battery_label, 1, 0)
        self.battery_profile_combo = QtWidgets.QComboBox()
        self.battery_profile_combo.setToolTip(self.tr("profiles.on_battery_tooltip"))
        pp_layout.addWidget(self.battery_profile_combo, 1, 1)

        profiles_layout.addWidget(power_profiles_row)

        left_col.addWidget(profiles_card)

        helper_card = QtWidgets.QFrame()
        helper_card.setObjectName("surfaceCard")
        helper_layout = QtWidgets.QVBoxLayout(helper_card)
        helper_layout.setContentsMargins(24, 24, 24, 24)
        helper_layout.setSpacing(16)

        self.helper_title = QtWidgets.QLabel(self.tr("smart.title"))
        self.helper_title.setObjectName("sectionTitle")
        helper_layout.addWidget(self.helper_title)

        self.helper_intro = QtWidgets.QLabel(
            self.tr("smart.subtitle")
        )
        self.helper_intro.setWordWrap(True)
        self.helper_intro.setObjectName("sectionSubtitle")
        helper_layout.addWidget(self.helper_intro)

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
            flag = QtWidgets.QPushButton(self.tr("status.disabled"))
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
            return flag, detail, label, info, row

        (
            self.autostart_flag,
            self.autostart_status_label,
            self.autostart_label,
            self.autostart_info_button,
            self.autostart_row,
        ) = helper_entry(
            self.tr("smart.autostart_title"),
            self.tr(
                "smart.autostart_tooltip",
                path=AUTOSTART_ENTRY,
            ),
        )

        (
            self.resume_flag,
            self.resume_status_label,
            self.resume_label,
            self.resume_info_button,
            self.resume_row,
        ) = helper_entry(
            self.tr("smart.resume_title"),
            self.tr("smart.resume_tooltip"),
            selectable=True,
        )

        (
            self.power_monitor_flag,
            self.power_monitor_status_label,
            self.power_monitor_label,
            self.power_monitor_info_button,
            self.power_monitor_row,
        ) = helper_entry(
            self.tr("smart.power_monitor_title"),
            self.tr("smart.power_monitor_tooltip"),
            selectable=True,
        )

        settings_row = QtWidgets.QFrame()
        settings_layout = QtWidgets.QHBoxLayout(settings_row)
        settings_layout.setContentsMargins(0, 12, 0, 0)
        settings_layout.setSpacing(12)
        settings_layout.addStretch(1)
        self.language_combo = QtWidgets.QComboBox()
        self.language_combo.setObjectName("languageCombo")
        self.language_combo.setToolTip(self.tr("language.tooltip"))
        self.language_combo.setMinimumWidth(140)
        self.language_combo.setIconSize(QtCore.QSize(20, 14))
        for code, label in LANGUAGE_LABELS.items():
            self.language_combo.addItem(build_flag_icon(code), label, code)
        lang_index = self.language_combo.findData(self.language)
        if lang_index >= 0:
            self.language_combo.setCurrentIndex(lang_index)
        settings_layout.addWidget(self.language_combo)
        self.dark_mode_checkbox = QtWidgets.QCheckBox(self.tr("settings.dark_mode"))
        self.dark_mode_checkbox.setChecked(self.settings.get("dark_mode", False))
        settings_layout.addWidget(self.dark_mode_checkbox)
        self.notifications_checkbox = QtWidgets.QCheckBox(self.tr("settings.notifications"))
        self.notifications_checkbox.setChecked(self.settings.get("show_notifications", True))
        settings_layout.addWidget(self.notifications_checkbox)
        helper_layout.addWidget(settings_row)

        right_col.addWidget(helper_card)
        right_col.addStretch(1)

        surface_layout.addStretch(1)
        self.log_window = QtWidgets.QDialog(self)
        self.log_window.setObjectName("logWindow")
        self.log_window.setWindowTitle(self.tr("log.title"))
        self.log_window.setModal(False)
        self.log_window.setSizeGripEnabled(True)
        self.log_window.setMinimumSize(520, 260)
        log_window_layout = QtWidgets.QVBoxLayout(self.log_window)
        log_window_layout.setContentsMargins(24, 24, 24, 24)
        log_window_layout.setSpacing(12)

        self.log_card = QtWidgets.QFrame()
        self.log_card.setObjectName("surfaceCard")
        log_window_layout.addWidget(self.log_card)

        log_layout = QtWidgets.QVBoxLayout(self.log_card)
        log_layout.setContentsMargins(20, 20, 20, 20)
        log_layout.setSpacing(12)

        log_header = QtWidgets.QHBoxLayout()
        log_header.setSpacing(12)
        self.log_title = QtWidgets.QLabel(self.tr("log.title"))
        self.log_title.setObjectName("sectionTitle")
        log_header.addWidget(self.log_title)
        log_header.addStretch(1)
        self.log_close_button = QtWidgets.QPushButton(self.tr("buttons.close"))
        self.log_close_button.setObjectName("pillButton")
        log_header.addWidget(self.log_close_button)
        log_layout.addLayout(log_header)

        self.console = QtWidgets.QTextEdit()
        self.console.setObjectName("logView")
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
        self.console.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.console.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.console.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        log_layout.addWidget(self.console, 1)

        self.log_window.finished.connect(self.on_log_window_closed)
        self.log_window.hide()

        self.github_button.clicked.connect(self.on_github_clicked)
        self.export_logs_button.clicked.connect(self.on_export_logs_clicked)
        self.log_toggle_button.toggled.connect(self.on_log_toggle_toggled)
        self.log_close_button.clicked.connect(self.on_log_close_clicked)
        self.language_combo.currentIndexChanged.connect(self.on_language_changed)

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
        if self.profile_data:
            self.load_profile_into_controls(self.profile_data)
        self.apply_language()
        self.update_panels()
        self.update_power_button()

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
        self.apply_button.clicked.connect(self.on_apply_clicked)

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

    def _append_activity_log_lines(self, text, level, timestamp):
        if not hasattr(self, "activity_log_buffer"):
            return
        prefix = f"[{timestamp}] [{level}] "
        lines = str(text).splitlines() or [""]
        self.activity_log_buffer.append(prefix + lines[0])
        indent = " " * len(prefix)
        for line in lines[1:]:
            self.activity_log_buffer.append(indent + line)

    def log(self, text, level="info"):
        timestamp = time.strftime("%H:%M:%S")
        self._append_activity_log_lines(text, level, timestamp)
        entry = format_log(f"[{timestamp}] {text}", level)
        self.console.append(entry)
        sb = self.console.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())
        if hasattr(self, "log_window") and self.log_window.isVisible():
            self._fit_log_window()

    def tr(self, key, **kwargs):
        text = self.translations.get(key) or self.fallback_translations.get(key) or key
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, ValueError):
                return text
        return text

    def set_language(self, language, *, save=False):
        lang = normalize_language_code(language)
        if lang not in LANGUAGE_LABELS:
            lang = "en"
        if lang == self.language and self.translations:
            if save:
                self.settings["language"] = lang
                self.save_settings()
            return
        self.language = lang
        self.translations = load_translations(lang)
        self.fallback_translations = load_translations("en")
        if hasattr(self, "language_combo"):
            blocker = QtCore.QSignalBlocker(self.language_combo)
            try:
                idx = self.language_combo.findData(lang)
                if idx >= 0:
                    self.language_combo.setCurrentIndex(idx)
            finally:
                del blocker
        if save:
            self.settings["language"] = lang
            self.save_settings()
        self.apply_language()

    def refresh_effect_combos(self):
        mode_value = self.mode.currentData() or "static"
        static_value = self.static_color.currentData() or self.last_static_color
        color_value = self.color.currentData() or "none"
        direction_value = self.direction.currentData() or "none"

        mode_blocker = QtCore.QSignalBlocker(self.mode)
        static_blocker = QtCore.QSignalBlocker(self.static_color)
        color_blocker = QtCore.QSignalBlocker(self.color)
        direction_blocker = QtCore.QSignalBlocker(self.direction)
        try:
            self.mode.clear()
            for effect in EFFECTS:
                self.mode.addItem(self.tr(f"effect.{effect}"), effect)
            set_combo_by_data(self.mode, mode_value)

            self.static_color.clear()
            for color in COLORS:
                self.static_color.addItem(self.tr(f"color.{color}"), color)
            set_combo_by_data(self.static_color, static_value)

            self.color.clear()
            self.color.addItem(self.tr("color.none"), "none")
            for color in COLORS:
                self.color.addItem(self.tr(f"color.{color}"), color)
            set_combo_by_data(self.color, color_value)

            self.direction.clear()
            for direction in DIRECTIONS:
                self.direction.addItem(self.tr(f"direction.{direction}"), direction)
            set_combo_by_data(self.direction, direction_value)
        finally:
            del mode_blocker
            del static_blocker
            del color_blocker
            del direction_blocker

    def apply_language(self):
        self.hero_subtitle.setText(self.tr("hero.subtitle"))
        self.hardware_caption.setText(self.tr("hero.hardware"))
        if not getattr(self, "hardware_detected", False):
            self.hardware_label.setText(self.tr("hero.hardware_unknown"))
        self.github_button.setText(self.tr("buttons.github"))
        self.export_logs_button.setText(self.tr("buttons.export_logs"))
        self.log_toggle_button.setText(
            self.tr("buttons.hide_activity_log")
            if self.log_toggle_button.isChecked()
            else self.tr("buttons.show_activity_log")
        )
        self.language_combo.setToolTip(self.tr("language.tooltip"))

        self.bright_title.setText(self.tr("brightness.title"))
        self.bright_caption.setText(self.tr("brightness.subtitle"))
        self.brightness_value_label.setText(self.tr("brightness.value"))

        self.apply_button.setText(self.tr("buttons.apply"))
        self.mode_title.setText(self.tr("effects.title"))
        self.mode_caption.setText(self.tr("effects.subtitle"))
        self.mode_label.setText(self.tr("effects.effect"))
        self.static_label.setText(self.tr("effects.static_color"))
        self.speed_label.setText(self.tr("effects.speed"))
        self.dynamic_color_label.setText(self.tr("effects.dynamic_color"))
        self.reactive.setText(self.tr("effects.reactive"))
        self.direction_label.setText(self.tr("effects.direction"))
        self.refresh_effect_combos()

        self.profiles_title.setText(self.tr("profiles.title"))
        self.profiles_caption.setText(self.tr("profiles.subtitle"))
        self.active_profile_label.setText(self.tr("profiles.active"))
        self.btn_profile_new.setText(self.tr("buttons.new"))
        self.btn_profile_save_as.setText(self.tr("buttons.save_as"))
        self.btn_profile_rename.setText(self.tr("buttons.rename"))
        self.btn_profile_delete.setText(self.tr("buttons.delete"))
        self.pp_title.setText(self.tr("profiles.power_title"))
        self.ac_label.setText(self.tr("profiles.on_ac"))
        self.battery_label.setText(self.tr("profiles.on_battery"))
        self.ac_profile_combo.setToolTip(self.tr("profiles.on_ac_tooltip"))
        self.battery_profile_combo.setToolTip(self.tr("profiles.on_battery_tooltip"))

        self.helper_title.setText(self.tr("smart.title"))
        self.helper_intro.setText(self.tr("smart.subtitle"))
        autostart_tooltip = self.tr(
            "smart.autostart_tooltip",
            path=AUTOSTART_ENTRY,
        )
        for widget in (
            self.autostart_row,
            self.autostart_label,
            self.autostart_info_button,
            self.autostart_flag,
            self.autostart_status_label,
        ):
            widget.setToolTip(autostart_tooltip)
            widget.setToolTipDuration(0)
        self.autostart_label.setText(self.tr("smart.autostart_title"))

        resume_tooltip = self.tr("smart.resume_tooltip")
        for widget in (
            self.resume_row,
            self.resume_label,
            self.resume_info_button,
            self.resume_flag,
            self.resume_status_label,
        ):
            widget.setToolTip(resume_tooltip)
            widget.setToolTipDuration(0)
        self.resume_label.setText(self.tr("smart.resume_title"))

        power_tooltip = self.tr("smart.power_monitor_tooltip")
        for widget in (
            self.power_monitor_row,
            self.power_monitor_label,
            self.power_monitor_info_button,
            self.power_monitor_flag,
            self.power_monitor_status_label,
        ):
            widget.setToolTip(power_tooltip)
            widget.setToolTipDuration(0)
        self.power_monitor_label.setText(self.tr("smart.power_monitor_title"))

        self.dark_mode_checkbox.setText(self.tr("settings.dark_mode"))
        self.notifications_checkbox.setText(self.tr("settings.notifications"))

        self.log_window.setWindowTitle(self.tr("log.title"))
        self.log_title.setText(self.tr("log.title"))
        self.log_close_button.setText(self.tr("buttons.close"))

        if hasattr(self, "tray_show_action"):
            self.tray_show_action.setText(self.tr("tray.show_window"))
        if hasattr(self, "tray_turn_on_action"):
            self.tray_turn_on_action.setText(self.tr("tray.turn_on"))
        if hasattr(self, "tray_turn_off_action"):
            self.tray_turn_off_action.setText(self.tr("tray.turn_off"))
        if hasattr(self, "tray_quit_action"):
            self.tray_quit_action.setText(self.tr("tray.quit"))
        if hasattr(self, "tray_profiles_menu"):
            self.tray_profiles_menu.setTitle(self.tr("tray.profiles"))

        self.update_profile_save_state()
        self.refresh_autostart_flag()
        self.refresh_resume_controls()
        self.refresh_power_monitor_controls()
        self.refresh_power_profile_combos()
        self.update_panels()
        self.update_power_button()

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
            self.tray_show_action = menu.addAction(self.tr("tray.show_window"))
            self.tray_show_action.triggered.connect(self.show_window_from_tray)
            menu.addSeparator()
            self.tray_turn_on_action = menu.addAction(self.tr("tray.turn_on"))
            self.tray_turn_on_action.triggered.connect(self.on_tray_turn_on)
            self.tray_turn_off_action = menu.addAction(self.tr("tray.turn_off"))
            self.tray_turn_off_action.triggered.connect(self.on_tray_turn_off)
            menu.addSeparator()
            self.tray_profiles_menu = menu.addMenu(self.tr("tray.profiles"))
            self.rebuild_tray_profiles_menu()
            menu.addSeparator()
            self.tray_quit_action = menu.addAction(self.tr("tray.quit"))
            self.tray_quit_action.triggered.connect(self.on_tray_quit)
            self.tray_icon.setContextMenu(menu)
            self.tray_icon.activated.connect(self.on_tray_activated)
        if self.tray_icon:
            self.tray_icon.show()
        if self.settings.get("start_in_tray", False) and self.tray_icon:
            self.hide()
            self.notify(APP_DISPLAY_NAME, self.tr("notify.minimized_to_tray"))

    def on_log_toggle_toggled(self, checked):
        if not hasattr(self, "log_window"):
            return
        if checked:
            self.log_window.show()
            self.log_window.raise_()
            self.log_window.activateWindow()
            self._fit_log_window()
        else:
            self.log_window.hide()
        if hasattr(self, "log_toggle_button"):
            self.log_toggle_button.setText(
                self.tr("buttons.hide_activity_log")
                if checked
                else self.tr("buttons.show_activity_log")
            )

    def on_language_changed(self, _index):
        language = self.language_combo.currentData()
        if not language:
            return
        self.set_language(language, save=True)

    def on_log_close_clicked(self):
        if hasattr(self, "log_window"):
            self.log_window.close()

    def on_log_window_closed(self, _result=None):
        if not hasattr(self, "log_toggle_button"):
            return
        blocker = QtCore.QSignalBlocker(self.log_toggle_button)
        try:
            self.log_toggle_button.setChecked(False)
            self.log_toggle_button.setText(self.tr("buttons.show_activity_log"))
        finally:
            del blocker

    def _fit_log_window(self):
        if not hasattr(self, "log_window") or not self.log_window.isVisible():
            return
        screen = self.log_window.screen()
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        outer_margin = 48
        max_width = min(900, max(520, available.width() - outer_margin))
        target_width = max_width
        window_layout = self.log_window.layout()
        window_margins = window_layout.contentsMargins() if window_layout else QtCore.QMargins()
        card_layout = self.log_card.layout() if hasattr(self, "log_card") else None
        card_margins = card_layout.contentsMargins() if card_layout else QtCore.QMargins()
        header_height = 0
        if card_layout and card_layout.count() > 0:
            header_item = card_layout.itemAt(0)
            if header_item:
                header_height = header_item.sizeHint().height()

        text_width = (
            target_width
            - window_margins.left() - window_margins.right()
            - card_margins.left() - card_margins.right()
        )
        if text_width < 320:
            text_width = 320
        self.console.setFixedWidth(text_width)
        self.console.document().setTextWidth(self.console.viewport().width())
        self.console.document().adjustSize()

        max_height = available.height() - outer_margin
        max_text_height = (
            max_height
            - window_margins.top() - window_margins.bottom()
            - card_margins.top() - card_margins.bottom()
            - header_height
        )
        if max_text_height < 120:
            max_text_height = 120
        self._trim_log_to_fit(max_text_height)
        self.console.document().adjustSize()
        doc_height = int(self.console.document().size().height())
        text_height = min(doc_height, max_text_height)
        self.console.setFixedHeight(max(80, text_height + 4))

        target_height = (
            window_margins.top() + window_margins.bottom()
            + card_margins.top() + card_margins.bottom()
            + header_height + text_height + 4
        )
        if target_height < 260:
            target_height = 260
        if target_height > max_height:
            target_height = max_height

        self.log_window.resize(target_width, target_height)
        self._clamp_log_window_to_screen(available)

    def _trim_log_to_fit(self, max_text_height):
        doc = self.console.document()
        doc.setTextWidth(self.console.viewport().width())
        doc.adjustSize()
        if doc.size().height() <= max_text_height:
            return
        while doc.size().height() > max_text_height and doc.blockCount() > 1:
            cursor = QtGui.QTextCursor(doc)
            cursor.movePosition(QtGui.QTextCursor.Start)
            cursor.movePosition(QtGui.QTextCursor.NextBlock, QtGui.QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            cursor.deleteChar()
            doc.setTextWidth(self.console.viewport().width())
            doc.adjustSize()

    def _clamp_log_window_to_screen(self, available):
        frame = self.log_window.frameGeometry()
        new_frame = QtCore.QRect(frame)
        if new_frame.left() < available.left():
            new_frame.moveLeft(available.left())
        if new_frame.top() < available.top():
            new_frame.moveTop(available.top())
        if new_frame.right() > available.right():
            new_frame.moveRight(available.right())
        if new_frame.bottom() > available.bottom():
            new_frame.moveBottom(available.bottom())
        if new_frame != frame:
            self.log_window.move(new_frame.topLeft())

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
            self.tr("dialogs.export_logs.title"),
            os.path.expanduser(f"~/{default_name}"),
            self.tr("dialogs.export_logs.filter")
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

                # 6. Activity log
                if hasattr(self, "activity_log_buffer") and self.activity_log_buffer:
                    log_text = "\n".join(self.activity_log_buffer) + "\n"
                    zf.writestr("activity-log.txt", log_text)

                # 7. System info
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
                self,
                self.tr("dialogs.export_logs.complete_title"),
                self.tr("dialogs.export_logs.complete_message", path=file_path),
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("dialogs.export_logs.failed_title"),
                self.tr("dialogs.export_logs.failed_message", error=str(e)),
            )

    def show_window_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def on_tray_turn_on(self):
        self.on_power_on()
        self.notify(APP_DISPLAY_NAME, self.tr("notify.backlight_on"))

    def on_tray_turn_off(self):
        self.on_power_off()
        self.notify(APP_DISPLAY_NAME, self.tr("notify.backlight_off"))

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
            self.notify(APP_DISPLAY_NAME, self.tr("notify.profile_reapplied", name=name))
            return
        if not self.switch_active_profile(name, triggered_by_user=True):
            self.rebuild_tray_profiles_menu()
            return
        self.rebuild_tray_profiles_menu()
        self.notify(APP_DISPLAY_NAME, self.tr("notify.profile_applied", name=name))

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
                reverted = self.revert_unsaved_preview(
                    self.tr("status.preview_discarded_hide")
                )
                self.hide()
                if reverted:
                    self.notify(
                        APP_DISPLAY_NAME,
                        self.tr("notify.preview_discarded"),
                    )

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
        suffix = ", ".join(parts) if parts else self.tr("log.unknown_state")
        self.log(self.tr("log.synced_device_state", details=suffix))

    def closeEvent(self, event):
        reverted = self.revert_unsaved_preview(
            self.tr("status.preview_discarded_close")
        )
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
                message = self.tr("notify.tray_hint")
                if reverted:
                    message = self.tr("notify.tray_hint_preview")
                self.notify(APP_DISPLAY_NAME, message)
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
        none_label = self.tr("profiles.none_option")
        profile_names = list(self.profile_store["profiles"].keys())

        ac_blocker = QtCore.QSignalBlocker(self.ac_profile_combo)
        battery_blocker = QtCore.QSignalBlocker(self.battery_profile_combo)
        try:
            self.ac_profile_combo.clear()
            self.battery_profile_combo.clear()
            self.ac_profile_combo.addItem(none_label, "")
            self.battery_profile_combo.addItem(none_label, "")
            for name in profile_names:
                self.ac_profile_combo.addItem(name, name)
                self.battery_profile_combo.addItem(name, name)

            ac_profile = self.settings.get("ac_profile", "")
            battery_profile = self.settings.get("battery_profile", "")

            ac_idx = self.ac_profile_combo.findData(ac_profile) if ac_profile else 0
            if ac_idx < 0:
                ac_idx = 0
            self.ac_profile_combo.setCurrentIndex(ac_idx)

            battery_idx = self.battery_profile_combo.findData(battery_profile) if battery_profile else 0
            if battery_idx < 0:
                battery_idx = 0
            self.battery_profile_combo.setCurrentIndex(battery_idx)
        finally:
            del ac_blocker
            del battery_blocker

    def on_ac_profile_changed(self, text):
        value = self.ac_profile_combo.currentData() or ""
        if self.settings.get("ac_profile") == value:
            return
        self.settings["ac_profile"] = value
        self.save_settings()
        self.set_status(
            self.tr("status.ac_profile_set", profile=self.ac_profile_combo.currentText())
        )

    def on_battery_profile_changed(self, text):
        value = self.battery_profile_combo.currentData() or ""
        if self.settings.get("battery_profile") == value:
            return
        self.settings["battery_profile"] = value
        self.save_settings()
        self.set_status(
            self.tr(
                "status.battery_profile_set",
                profile=self.battery_profile_combo.currentText(),
            )
        )

    def set_status(self, t, level="info"):
        self.log(t, level=level)

    def run_cli(self, args, **kwargs):
        return run_cmd(args, log_cb=self.log, **kwargs)

    def detect_device(self):
        rc, out, err = self.run_cli(["query", "--devices"])
        if rc == 0:
            self.hardware_detected = True
            msg = (out or "").strip() or self.tr("status.device_detected")
            self.hardware_label.setText(msg)
            self.set_status(msg)
            self.sync_initial_state()
        else:
            self.hardware_detected = False
            self.hardware_label.setText(self.tr("hero.hardware_unknown"))
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
        #logWindow {
            background-color: #eef2f7;
            background-image: radial-gradient(circle at 15% 15%, rgba(59, 130, 246, 0.12), transparent 55%);
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
        QPushButton#applyButton {
            padding: 8px 22px;
            border-radius: 16px;
            border: 2px solid #94a3b8;
            background-color: #ffffff;
            font-weight: 600;
            color: #1f2933;
        }
        QPushButton#applyButton:enabled {
            border: 2px solid #16a34a;
            color: #ffffff;
            background-color: #16a34a;
        }
        QPushButton#applyButton:disabled {
            background-color: #f1f5f9;
            color: #94a3b8;
            border: 2px solid #cbd5e1;
        }
        """
        dark = """
        #MainView {
            background-color: #0f172a;
        }
        #logWindow {
            background-color: #0b1220;
            background-image: radial-gradient(circle at 15% 15%, rgba(59, 130, 246, 0.18), transparent 55%);
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
        QPushButton#applyButton {
            padding: 8px 22px;
            border-radius: 16px;
            border: 2px solid #64748b;
            background-color: #1e293b;
            font-weight: 600;
            color: #e2e8f0;
        }
        QPushButton#applyButton:enabled {
            border: 2px solid #16a34a;
            color: #ffffff;
            background-color: #16a34a;
        }
        QPushButton#applyButton:disabled {
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
            self._style_combobox_views("#1e293b", "#e2e8f0")
        else:
            self.setStyleSheet(base)
            self._style_combobox_views("#ffffff", "#1f2933")
        if hasattr(self, "log_window"):
            self.log_window.setStyleSheet(self.styleSheet())
            if self.log_window.isVisible():
                self._fit_log_window()

    def _style_combobox_views(self, bg_color, text_color):
        """Style all ComboBox dropdown views to remove white borders."""
        comboboxes = [
            self.mode, self.static_color, self.color, self.direction,
            self.profile_combo, self.ac_profile_combo, self.battery_profile_combo,
            self.language_combo,
        ]
        for combo in comboboxes:
            view = combo.view()
            if view:
                view.setFrameShape(QtWidgets.QFrame.NoFrame)
                view.setStyleSheet(f"background-color: {bg_color}; color: {text_color}; border: none;")
                parent = view.parentWidget()
                if parent:
                    parent.setStyleSheet(f"background-color: {bg_color}; border: 1px solid rgba(148, 163, 184, 0.3);")

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
            if not set_combo_by_data(self.mode, mode_value):
                set_combo_by_data(self.mode, "static")

            static_value = sanitize_choice(
                data.get("static_color"), COLORS, self.last_static_color
            )
            if not set_combo_by_data(self.static_color, static_value):
                set_combo_by_data(self.static_color, self.last_static_color)
            self.last_static_color = static_value

            self.speed.setValue(clamp_int(data.get("speed"), 0, 10, self.speed.value()))

            color_value = data.get("color") or "none"
            if color_value != "none" and color_value not in COLORS:
                color_value = "none"
            set_combo_by_data(self.color, color_value)

            reactive_value = bool(data.get("reactive"))
            self.reactive.setChecked(reactive_value)

            direction_value = sanitize_choice(
                data.get("direction"), DIRECTIONS, (self.direction.currentData() or "none")
            )
            if reactive_value:
                direction_value = "none"
            set_combo_by_data(self.direction, direction_value)
        finally:
            del blockers

        self.update_panels()
        self.set_profile_dirty(False)

    def update_profile_save_state(self):
        if not hasattr(self, "btn_profile_save"):
            return
        label = (
            self.tr("buttons.save_dirty")
            if self._profile_dirty
            else self.tr("buttons.save")
        )
        self.btn_profile_save.setText(label)
        if hasattr(self, "apply_button"):
            self.apply_button.setEnabled(self._profile_dirty)

    def set_profile_dirty(self, dirty):
        dirty = bool(dirty)
        if self._profile_dirty == dirty:
            return
        self._profile_dirty = dirty
        self.update_profile_save_state()

    def refresh_profile_dirty_state(self):
        if not self.profile_data:
            self.set_profile_dirty(False)
            return
        current = self.capture_profile_state()
        self.set_profile_dirty(current != self.profile_data)

    def confirm_profile_switch(self, target_name):
        self.refresh_profile_dirty_state()
        if not self._profile_dirty:
            return True
        message = QtWidgets.QMessageBox(self)
        message.setWindowTitle(self.tr("dialogs.profile.unsaved_title"))
        message.setIcon(QtWidgets.QMessageBox.Warning)
        message.setText(
            self.tr(
                "dialogs.profile.unsaved_message",
                active=self.active_profile_name,
                target=target_name,
            )
        )
        message.setInformativeText(
            self.tr("dialogs.profile.unsaved_detail")
        )
        message.setStandardButtons(
            QtWidgets.QMessageBox.Save
            | QtWidgets.QMessageBox.Discard
            | QtWidgets.QMessageBox.Cancel
        )
        message.setDefaultButton(QtWidgets.QMessageBox.Save)
        choice = message.exec()
        if choice == QtWidgets.QMessageBox.Save:
            self.persist_profile()
            self.set_status(
                self.tr("status.profile_saved", name=self.active_profile_name)
            )
            return True
        if choice == QtWidgets.QMessageBox.Discard:
            return True
        return False

    def revert_unsaved_preview(self, reason=None):
        self.refresh_profile_dirty_state()
        if not self._profile_dirty:
            return False
        if not self.profile_data:
            return False
        self.apply_timer.stop()
        self.brightness_timer.stop()
        saved_state = dict(self.profile_data)
        self.load_profile_into_controls(saved_state)
        brightness = clamp_int(
            saved_state.get("brightness"), 0, 50, self.last_brightness
        )
        if brightness <= 0:
            self.is_off = True
            self.run_cli(["off"], log_cmd=False, log_stdout=False, log_stderr=False)
        else:
            self.is_off = False
            self.apply_current_mode()
        self.update_power_button()
        if reason:
            self.set_status(reason)
        return True

    def capture_profile_state(self):
        mode_value = sanitize_choice(self.mode.currentData(), EFFECTS, "static")
        static_value = sanitize_choice(
            self.static_color.currentData(), COLORS, self.last_static_color
        )
        self.last_static_color = static_value

        color_value = self.color.currentData() or "none"
        if color_value != "none" and color_value not in COLORS:
            color_value = "none"

        direction_value = self.direction.currentData()
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
        self.set_profile_dirty(False)

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
            self.set_status(
                self.tr("status.profile_save_failed", error=str(exc)),
                level="error",
            )
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
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("dialogs.profile.invalid_title"),
                self.tr("dialogs.profile.invalid_message"),
            )
            return None
        return name

    def on_profile_save_clicked(self):
        self.persist_profile()
        self.set_status(self.tr("status.profile_saved", name=self.active_profile_name))

    def on_apply_clicked(self):
        self.apply_timer.stop()
        self.brightness_timer.stop()
        self.persist_profile()
        if not self.is_off:
            self.apply_current_mode()
        self.set_status(self.tr("status.profile_updated", name=self.active_profile_name))

    def on_profile_new_clicked(self):
        name = self.prompt_profile_name(
            self.tr("dialogs.profile.new_title"),
            self.tr("dialogs.profile.name_label"),
        )
        if not name:
            return
        if name in self.profile_store["profiles"]:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("dialogs.profile.name_in_use_title"),
                self.tr("dialogs.profile.name_in_use_message"),
            )
            return
        self.profile_store["profiles"][name] = dict(DEFAULT_PROFILE_STATE)
        self.active_profile_name = name
        self.profile_store["active"] = name
        self.profile_data = dict(DEFAULT_PROFILE_STATE)
        self.save_profile_store()
        self.refresh_profile_combo()
        self.load_profile_into_controls(self.profile_data)
        self.set_status(self.tr("status.profile_created", name=name))

    def on_profile_save_as_clicked(self):
        name = self.prompt_profile_name(
            self.tr("dialogs.profile.save_title"),
            self.tr("dialogs.profile.name_label"),
            self.active_profile_name,
        )
        if not name:
            return
        if name in self.profile_store["profiles"] and name != self.active_profile_name:
            reply = QtWidgets.QMessageBox.question(
                self,
                self.tr("dialogs.profile.overwrite_title"),
                self.tr("dialogs.profile.overwrite_message", name=name),
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self.active_profile_name = name
        state = self.capture_profile_state()
        self.update_active_profile_state(state)
        self.save_profile_store()
        self.refresh_profile_combo()
        self.set_profile_dirty(False)
        self.set_status(self.tr("status.profile_saved", name=name))

    def on_profile_rename_clicked(self):
        new_name = self.prompt_profile_name(
            self.tr("dialogs.profile.rename_title"),
            self.tr("dialogs.profile.rename_label"),
            self.active_profile_name,
        )
        if not new_name or new_name == self.active_profile_name:
            return
        if new_name in self.profile_store["profiles"]:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("dialogs.profile.name_in_use_title"),
                self.tr("dialogs.profile.rename_in_use_message"),
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
        self.set_status(self.tr("status.profile_renamed", name=new_name))

    def on_profile_delete_clicked(self):
        if len(self.profile_store["profiles"]) <= 1:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("dialogs.profile.cannot_delete_title"),
                self.tr("dialogs.profile.cannot_delete_message"),
            )
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            self.tr("dialogs.profile.delete_title"),
            self.tr("dialogs.profile.delete_message", name=self.active_profile_name),
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
        self.set_status(
            self.tr("status.profile_active", name=self.active_profile_name)
        )
        if not self.is_off:
            self.apply_current_mode()

    def switch_active_profile(self, name, triggered_by_user=False):
        if name not in self.profile_store["profiles"]:
            self.set_status(self.tr("status.profile_not_found", name=name), level="error")
            self.refresh_profile_combo()
            return False
        if triggered_by_user and not self.confirm_profile_switch(name):
            self.refresh_profile_combo()
            return False
        self.active_profile_name = name
        self.profile_store["active"] = name
        self.profile_data = dict(self.profile_store["profiles"][name])
        self.save_profile_store()
        self.refresh_profile_combo()
        self.load_profile_into_controls(self.profile_data)
        self.set_status(self.tr("status.profile_loaded", name=name))
        if triggered_by_user and not self.is_off:
            self.apply_current_mode()
        return True

    def refresh_autostart_flag(self, detail_text=None):
        state = is_autostart_enabled()
        self.autostart_enabled = state
        status_label = (
            self.tr("status.enabled") if state else self.tr("status.disabled")
        )
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
                self.set_status(self.tr("status.autostart_removed"))
            else:
                ensure_restore_script_executable()
                create_autostart_entry()
                self.settings["start_in_tray"] = True
                self.save_settings()
                self.set_status(
                    self.tr("status.autostart_created", path=AUTOSTART_ENTRY)
                )
        except OSError as exc:
            error = self.tr("status.autostart_error", error=str(exc))
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
                self.resume_flag.setText(
                    self.tr("status.enabled")
                    if status_enabled
                    else self.tr("status.disabled")
                )
                disabled = status_text == "systemctl not available"
                self.resume_flag.setEnabled(not disabled)
                if disabled:
                    self.resume_flag.setToolTip(
                        self.tr("status.systemctl_unavailable")
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
                self.power_monitor_flag.setText(
                    self.tr("status.enabled")
                    if status_enabled
                    else self.tr("status.disabled")
                )
                disabled = status_text == "systemctl not available"
                self.power_monitor_flag.setEnabled(not disabled)
                if disabled:
                    self.power_monitor_flag.setToolTip(
                        self.tr("status.systemctl_unavailable_monitor")
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
            self.tr(
                "status.restoring_profile",
                name=self.active_profile_name,
                path=PROFILE_PATH,
            )
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
            self.set_status(self.tr("status.profiles_reloaded"))
        except (OSError, json.JSONDecodeError) as exc:
            self.set_status(
                self.tr("status.profiles_reload_failed", error=str(exc)),
                level="error",
            )

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
                self.set_status(self.tr("status.profiles_updated"))
            except (OSError, json.JSONDecodeError) as exc:
                self.set_status(
                    self.tr("status.profiles_reload_failed", error=str(exc)),
                    level="error",
                )

    def update_panels(self):
        is_static = (self.mode.currentData() == "static")
        self.static_label.setVisible(is_static)
        self.static_color.setVisible(is_static)
        self.effect_panel.setVisible(not is_static)
        self.direction.setEnabled(not self.reactive.isChecked())
        if self.reactive.isChecked():
            set_combo_by_data(self.direction, "none")

    def update_power_button(self):
        if not hasattr(self, "btn_power"):
            return
        label = self.tr("buttons.turn_on") if self.is_off else self.tr("buttons.turn_off")
        self.btn_power.setText(label)
        self.btn_power.setProperty("powerState", "off" if self.is_off else "on")
        self.btn_power.style().unpolish(self.btn_power)
        self.btn_power.style().polish(self.btn_power)

    def on_reactive_toggled(self, checked):
        self.direction.setEnabled(not checked)
        if checked:
            set_combo_by_data(self.direction, "none")

    def on_mode_changed(self):
        self.update_panels()
        self.schedule_apply()

    def on_brightness_changed(self, v):
        if self._suppress:
            return
        v = int(v)
        was_off = self.is_off
        self.last_brightness = v
        self.refresh_profile_dirty_state()
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
            self.set_status(self.tr("status.backlight_off"))
            self.update_power_button()
        else:
            self.set_status(format_cli_error(rc, out, err))

    def on_power_toggle(self):
        if self.is_off:
            self.on_power_on()
        else:
            self.on_power_off()

    def schedule_apply(self):
        self.refresh_profile_dirty_state()
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
            self.set_status(self.tr("status.brightness_set", value=v))
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
        color_value = self.static_color.currentData() or self.static_color.currentText()
        display_color = self.static_color.currentText()
        self.last_static_color = color_value
        rc, out, err = self.hard_reset_then(
            ["monocolor", "-b", str(v), "--name", color_value]
        )
        if rc == 0:
            self.set_status(
                self.tr(
                    "status.static_applied",
                    brightness=v,
                    color=display_color,
                )
            )
        else:
            self.set_status(
                self.tr(
                    "status.error_generic",
                    code=rc,
                    message=(err or out or self.tr("status.unknown_error")),
                ),
                level="error",
            )

    def build_effect_args(self):
        v = int(self.b_spin.value())
        eff = self.mode.currentData() or "static"
        args = ["effect", "-b", str(v)]

        if self.speed.value() != 5:
            args += ["-s", str(self.speed.value())]

        col = self.color.currentData() or "none"
        if col != "none":
            args += ["-c", col]

        if self.reactive.isChecked():
            args.append("-r")
        else:
            d = self.direction.currentData() or "none"
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
            self.set_status(
                self.tr("status.effect_applied", details=used_str)
            )
        else:
            self.set_status(
                self.tr(
                    "status.error_generic",
                    code=rc,
                    message=(err or out or self.tr("status.unknown_error")),
                ),
                level="error",
            )

    def apply_current_mode(self):
        if self.is_off:
            return
        if self.mode.currentData() == "static":
            self.apply_static()
        else:
            self.apply_effect()


def main():
    app = QtWidgets.QApplication([])

    lock_handle = acquire_single_instance_lock()
    if lock_handle is None:
        language = detect_system_language()
        translations = load_translations(language)
        fallback = load_translations("en")

        def tr(key, **kwargs):
            text = translations.get(key) or fallback.get(key) or key
            if kwargs:
                try:
                    return text.format(**kwargs)
                except (KeyError, ValueError):
                    return text
            return text

        QtWidgets.QMessageBox.warning(
            None,
            APP_DISPLAY_NAME,
            tr("dialogs.app_already_running"),
        )
        sys.exit(0)

    w = Main()
    if not (w.settings.get("start_in_tray", False) and w.tray_supported and w.tray_icon):
        w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
