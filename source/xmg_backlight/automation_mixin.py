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

class AutomationMixin:
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
