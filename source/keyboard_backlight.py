#!/usr/bin/env python3
import html
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import time
from PySide6 import QtCore, QtWidgets

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
RESTORE_SCRIPT = os.path.join(BASE_DIR, "restore_profile.py")
POWER_MONITOR_SCRIPT = os.path.join(BASE_DIR, "power_state_monitor.py")
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


def clamp_int(value, minimum, maximum, fallback):
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, ivalue))


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


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
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp_path, PROFILE_PATH)


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
    exec_path = shlex.quote(RESTORE_SCRIPT)
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Keyboard Backlight Restore\n"
        f"Exec={exec_path}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Comment=Restore the last keyboard backlight profile on login.\n"
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("XMG Backlight Management")
        self.resize(720, 520)

        QtWidgets.QApplication.setStyle("Fusion")

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

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        header_card = QtWidgets.QFrame()
        header_card.setObjectName("hardwareCard")
        header_layout = QtWidgets.QHBoxLayout(header_card)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(12)

        hardware_title = QtWidgets.QLabel("Detected hardware")
        hardware_title.setObjectName("hardwareTitle")
        header_layout.addWidget(hardware_title)

        self.hardware_label = QtWidgets.QLabel("Hardware: unknown")
        self.hardware_label.setWordWrap(True)
        self.hardware_label.setObjectName("hardwareValue")
        header_layout.addWidget(self.hardware_label, 1)

        self.log_toggle_button = QtWidgets.QPushButton("Show log")
        self.log_toggle_button.setCheckable(True)
        header_layout.addWidget(self.log_toggle_button)

        root.addWidget(header_card)

        self.console_box = QtWidgets.QGroupBox("Activity log")
        cl = QtWidgets.QVBoxLayout(self.console_box)
        cl.setContentsMargins(8, 12, 8, 8)

        self.console = QtWidgets.QTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        cl.addWidget(self.console, 1)

        self.console_box.setVisible(False)
        root.addWidget(self.console_box)
        self.log_toggle_button.toggled.connect(self.on_log_toggle_toggled)

        global_box = QtWidgets.QGroupBox("Brightness & power")
        gl = QtWidgets.QGridLayout(global_box)
        gl.setColumnStretch(1, 1)

        gl.addWidget(QtWidgets.QLabel("Brightness (0–50)"), 0, 0)

        self.b_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.b_slider.setRange(0, 50)
        self.b_slider.setValue(self.last_brightness)
        gl.addWidget(self.b_slider, 0, 1)

        self.b_spin = QtWidgets.QSpinBox()
        self.b_spin.setRange(0, 50)
        self.b_spin.setValue(self.last_brightness)
        gl.addWidget(self.b_spin, 0, 2)

        self.btn_power = QtWidgets.QPushButton()
        gl.addWidget(self.btn_power, 1, 0, 1, 3)

        root.addWidget(global_box)

        mode_box = QtWidgets.QGroupBox("Mode")
        ml = QtWidgets.QGridLayout(mode_box)
        ml.setColumnStretch(1, 1)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(12)

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

        mode_row.addStretch(1)
        ml.addLayout(mode_row, 0, 0, 1, 4)

        self.effect_panel = QtWidgets.QWidget()
        epl = QtWidgets.QGridLayout(self.effect_panel)
        epl.setContentsMargins(0, 0, 0, 0)
        epl.setHorizontalSpacing(10)
        epl.setVerticalSpacing(8)

        epl.addWidget(QtWidgets.QLabel("Speed (0–10)"), 0, 0)
        self.speed = QtWidgets.QSpinBox()
        self.speed.setRange(0, 10)
        self.speed.setValue(5)
        epl.addWidget(self.speed, 0, 1)

        epl.addWidget(QtWidgets.QLabel("Color"), 0, 2)
        self.color = QtWidgets.QComboBox()
        self.color.addItems(["none"] + COLORS)
        self.color.setCurrentText("none")
        epl.addWidget(self.color, 0, 3)

        self.reactive = QtWidgets.QCheckBox("Reactive (-r)")
        epl.addWidget(self.reactive, 1, 1)

        self.direction = QtWidgets.QComboBox()
        self.direction.addItems(DIRECTIONS)
        self.direction.setCurrentText("none")
        epl.addWidget(self.direction, 1, 3)

        ml.addWidget(self.effect_panel, 1, 0, 1, 4)

        root.addWidget(mode_box)

        profiles_box = QtWidgets.QGroupBox("Profiles")
        pl = QtWidgets.QGridLayout(profiles_box)
        pl.setColumnStretch(1, 1)
        pl.addWidget(QtWidgets.QLabel("Profile"), 0, 0)
        self.profile_combo = QtWidgets.QComboBox()
        pl.addWidget(self.profile_combo, 0, 1, 1, 2)
        self.btn_profile_save = QtWidgets.QPushButton("Save")
        pl.addWidget(self.btn_profile_save, 0, 3)
        self.btn_profile_save_as = QtWidgets.QPushButton("Save as…")
        pl.addWidget(self.btn_profile_save_as, 1, 1)
        self.btn_profile_rename = QtWidgets.QPushButton("Rename…")
        pl.addWidget(self.btn_profile_rename, 1, 2)
        self.btn_profile_delete = QtWidgets.QPushButton("Delete")
        pl.addWidget(self.btn_profile_delete, 1, 3)
        root.addWidget(profiles_box)

        helper_box = QtWidgets.QGroupBox("Automation helpers")
        hl = QtWidgets.QVBoxLayout(helper_box)
        hl.setContentsMargins(10, 10, 10, 10)
        helper_intro_text = (
            "Automate profile restore at login, after resume and on power-source changes without keeping the GUI open."
        )
        helper_label = QtWidgets.QLabel(helper_intro_text)
        helper_label.setWordWrap(True)
        hl.addWidget(helper_label)

        def helper_entry(title, tooltip, *, selectable=False):
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            info = QtWidgets.QToolButton()
            info.setText("?")
            info.setObjectName("helperInfoButton")
            info.setCursor(QtCore.Qt.PointingHandCursor)
            info.setAutoRaise(True)
            info.setFixedSize(22, 22)
            label = QtWidgets.QLabel(title)
            flag = QtWidgets.QCheckBox("Disabled")
            flag.setObjectName("helperFlag")
            row_layout.addWidget(info)
            row_layout.addWidget(label)
            row_layout.addSpacing(6)
            row_layout.addWidget(flag)
            row_layout.addStretch(1)

            detail = QtWidgets.QLabel()
            detail.setWordWrap(True)
            detail.setObjectName("helperDetail")
            detail.setVisible(False)
            if selectable:
                detail.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            detail.setContentsMargins(28, 0, 0, 0)

            widgets = (row, label, info, flag, detail)
            for widget in widgets:
                widget.setToolTip(tooltip)
                widget.setToolTipDuration(0)

            hl.addWidget(row)
            hl.addWidget(detail)
            return flag, detail

        self.autostart_flag, self.autostart_status_label = helper_entry(
            "Autostart (login)",
            (
                "Restores the saved keyboard profile when your desktop session starts.\n"
                f"Desktop entry path: {AUTOSTART_ENTRY}"
            ),
        )

        self.resume_flag, self.resume_status_label = helper_entry(
            "Resume restore",
            "Reapplies the current keyboard profile immediately after suspend, hibernate or hybrid sleep.",
            selectable=True,
        )

        self.power_monitor_flag, self.power_monitor_status_label = helper_entry(
            "Power monitor",
            "Listens for AC/battery changes and reapplies the profile when the power source switches.",
            selectable=True,
        )

        root.addWidget(helper_box)

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
        self.btn_profile_save.clicked.connect(self.on_profile_save_clicked)
        self.btn_profile_save_as.clicked.connect(self.on_profile_save_as_clicked)
        self.btn_profile_rename.clicked.connect(self.on_profile_rename_clicked)
        self.btn_profile_delete.clicked.connect(self.on_profile_delete_clicked)

        self.autostart_flag.stateChanged.connect(self.on_autostart_flag_changed)
        self.resume_flag.stateChanged.connect(self.on_resume_flag_changed)
        self.power_monitor_flag.stateChanged.connect(self.on_power_monitor_flag_changed)
        self.refresh_autostart_flag()
        self.refresh_resume_controls()
        self.refresh_power_monitor_controls()
        self.refresh_profile_combo()

        if self.profile_data:
            self.restore_profile_after_startup()

    def log(self, text, level="info"):
        timestamp = time.strftime("%H:%M:%S")
        entry = format_log(f"[{timestamp}] {text}", level)
        self.console.append(entry)
        sb = self.console.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def on_log_toggle_toggled(self, checked):
        if not hasattr(self, "console_box"):
            return
        self.console_box.setVisible(checked)
        if hasattr(self, "log_toggle_button"):
            self.log_toggle_button.setText("Hide log" if checked else "Show log")

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
        QWidget { font-size: 13px; }
        QGroupBox { font-weight: 600; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QComboBox, QSpinBox { padding: 4px 8px; }
        QTextEdit { background-color: #0f172a; color: #f8fafc; border-radius: 8px; }
        QPushButton {
            padding: 7px 12px;
            border-radius: 8px;
            font-weight: 600;
            background-color: #2563eb;
            color: #f8fafc;
            border: none;
        }
        QPushButton:hover { background-color: #1d4ed8; }
        QPushButton:pressed { background-color: #1e40af; }
        QPushButton:disabled { background-color: #94a3b8; color: #e2e8f0; }
        """
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
                self.set_status("Autostart entry removed.")
            else:
                ensure_restore_script_executable()
                create_autostart_entry()
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
        label_text = status_text if status_text else ("Enabled" if status_enabled else "Disabled")
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
        label_text = status_text if status_text else ("Enabled" if status_enabled else "Disabled")
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
        self.watch_profile_paths()
        if self._ignore_profile_events:
            return
        self.reload_profile_store_from_disk(announce=True)
        self.set_status("Profiles reloaded from disk.")

    def on_profile_directory_changed(self, path):
        if path != CONFIG_DIR:
            return
        self.watch_profile_paths()
        if self._ignore_profile_events:
            return
        if os.path.isfile(PROFILE_PATH):
            self.reload_profile_store_from_disk(announce=True)
            self.set_status("Profiles updated after directory change.")

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


app = QtWidgets.QApplication([])
w = Main()
w.show()
app.exec()
