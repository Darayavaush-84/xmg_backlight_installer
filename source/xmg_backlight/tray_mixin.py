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

class TrayMixin:
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
