from __future__ import annotations

import sys
from collections import deque

from PySide6 import QtCore, QtGui, QtWidgets

from .activity_log_mixin import ActivityLogMixin
from .automation_mixin import AutomationMixin
from .constants import *
from .device_mixin import DeviceMixin
from .effects_mixin import EffectsMixin
from .export_mixin import ExportMixin
from .language_mixin import LanguageMixin
from .profile_mixin import ProfileMixin
from .services import ensure_restore_script_executable, is_autostart_enabled, is_power_monitor_enabled, is_resume_service_enabled
from .storage import acquire_single_instance_lock, load_profile_store, load_settings
from .theme_mixin import ThemeMixin
from .translations import detect_system_language, load_translations
from .tray_mixin import TrayMixin
from .ui_helpers import build_flag_icon, clamp_int, normalize_language_code, sanitize_choice, set_combo_by_data

class Main(LanguageMixin, ActivityLogMixin, ExportMixin, TrayMixin, DeviceMixin, ThemeMixin, ProfileMixin, AutomationMixin, EffectsMixin, QtWidgets.QWidget):
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
