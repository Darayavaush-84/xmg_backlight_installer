from __future__ import annotations

import json
import os
import subprocess
import time

from PySide6 import QtCore, QtGui, QtWidgets

from .constants import *
from .driver import TOOL, apply_effect_with_fallback, format_cli_error, format_log, run_cmd
from .services import *
from .storage import *
from .translations import detect_system_language, load_translations
from .ui_helpers import build_flag_icon, clamp_int, normalize_language_code, sanitize_choice, set_combo_by_data

class ProfileMixin:
    def save_settings(self):
        try:
            write_settings_file(self.settings)
        except OSError as exc:
            self.log(f"Failed to save settings: {exc}", level="error")

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
