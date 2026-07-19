from __future__ import annotations

from PySide6 import QtCore

from .capabilities import DIRECTIONS, DYNAMIC_COLORS, EFFECTS, STATIC_COLORS
from .constants import AUTOSTART_ENTRY, LANGUAGE_LABELS
from .translations import load_translations
from .ui_helpers import normalize_language_code, set_combo_by_data

class LanguageMixin:
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
                previous_language = self.settings.get("language", "")
                self.settings["language"] = lang
                if not self.save_settings():
                    self.settings["language"] = previous_language
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
            previous_language = self.settings.get("language", "")
            self.settings["language"] = lang
            if not self.save_settings():
                self.settings["language"] = previous_language
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
            for color in STATIC_COLORS:
                self.static_color.addItem(self.tr(f"color.{color}"), color)
            set_combo_by_data(self.static_color, static_value)

            self.color.clear()
            self.color.addItem(self.tr("color.none"), "none")
            for color in DYNAMIC_COLORS:
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

    def on_language_changed(self, _index):
        language = self.language_combo.currentData()
        if not language:
            return
        self.set_language(language, save=True)
