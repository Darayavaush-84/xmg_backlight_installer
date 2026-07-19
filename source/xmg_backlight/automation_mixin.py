from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .constants import AUTOSTART_ENTRY
from .restore_profile import apply_profile
from .services import (
    automation_service_status,
    create_autostart_entry,
    is_autostart_enabled,
    reconcile_automation_service,
    remove_autostart_entry,
)
from .storage import StorageFormatError, write_settings_file


class AutomationMixin:
    def refresh_autostart_flag(self, detail_text=None):
        state = is_autostart_enabled()
        self.autostart_enabled = state
        if hasattr(self, "autostart_status_label"):
            self.autostart_status_label.setText(detail_text or "")
            self.autostart_status_label.setVisible(bool(detail_text))
        if hasattr(self, "autostart_flag"):
            blocker = QtCore.QSignalBlocker(self.autostart_flag)
            try:
                self.autostart_flag.setChecked(state)
                self.autostart_flag.setText(
                    self.tr("status.enabled") if state else self.tr("status.disabled")
                )
            finally:
                del blocker

    def on_autostart_flag_changed(self, value):
        desired = bool(value)
        if desired == self.autostart_enabled:
            return
        previous_settings = dict(self.settings)
        try:
            if desired:
                create_autostart_entry()
                self.settings["start_in_tray"] = True
                message = self.tr("status.autostart_created", path=AUTOSTART_ENTRY)
            else:
                remove_autostart_entry()
                self.settings["start_in_tray"] = False
                message = self.tr("status.autostart_removed")
            write_settings_file(self.settings)
        except (OSError, StorageFormatError) as exc:
            rollback_errors = []
            try:
                if previous_settings.get("start_in_tray", False):
                    create_autostart_entry()
                else:
                    remove_autostart_entry()
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
            self.settings = previous_settings
            error = self.tr("status.autostart_error", error=str(exc))
            if rollback_errors:
                error += " " + "; ".join(rollback_errors)
            self.set_status(error, level="error")
            self.refresh_autostart_flag(detail_text=error)
            return
        self.set_status(message)
        QtWidgets.QApplication.setQuitOnLastWindowClosed(
            not (desired and self.tray_supported)
        )
        self.refresh_autostart_flag()

    def _refresh_automation_flag(self, key, flag, status_label):
        desired = bool(self.settings.get(key, False))
        service_enabled, service_status = automation_service_status()
        active_desired = bool(
            self.settings.get("resume_enabled", False)
            or self.settings.get("power_monitor_enabled", False)
        )
        detail = ""
        if active_desired and self._automation_reconcile_error:
            detail = self._automation_reconcile_error
        elif active_desired and not service_enabled:
            detail = service_status
        if status_label is not None:
            status_label.setText(detail)
            status_label.setVisible(bool(detail))
        blocker = QtCore.QSignalBlocker(flag)
        try:
            flag.setChecked(desired)
            flag.setText(
                self.tr("status.enabled") if desired else self.tr("status.disabled")
            )
            unavailable = service_status == "systemctl not available"
            flag.setEnabled(not unavailable)
        finally:
            del blocker
        return service_enabled, service_status

    def refresh_resume_controls(self):
        self.resume_enabled = bool(self.settings.get("resume_enabled", False))
        service_enabled, status = self._refresh_automation_flag(
            "resume_enabled",
            self.resume_flag,
            self.resume_status_label,
        )
        self.resume_status = status

    def refresh_power_monitor_controls(self):
        self.power_monitor_enabled = bool(
            self.settings.get("power_monitor_enabled", False)
        )
        service_enabled, status = self._refresh_automation_flag(
            "power_monitor_enabled",
            self.power_monitor_flag,
            self.power_monitor_status_label,
        )
        self.power_monitor_status = status

    def _set_automation_preference(self, key, desired):
        desired = bool(desired)
        if bool(self.settings.get(key, False)) == desired:
            return True
        previous = dict(self.settings)
        candidate = dict(self.settings)
        candidate[key] = desired
        try:
            write_settings_file(candidate)
            ok, message = reconcile_automation_service(candidate)
            if not ok:
                raise OSError(message)
        except (OSError, StorageFormatError) as exc:
            rollback_errors = []
            try:
                write_settings_file(previous)
            except (OSError, StorageFormatError) as rollback_exc:
                rollback_errors.append(str(rollback_exc))
            rollback_ok, rollback_message = reconcile_automation_service(previous)
            if not rollback_ok:
                rollback_errors.append(rollback_message)
            self.settings = previous
            message = str(exc)
            if rollback_errors:
                message += "; rollback failed: " + "; ".join(rollback_errors)
            self.set_status(message, level="error")
            self._automation_reconcile_error = message
            return False
        self.settings = candidate
        self._automation_reconcile_error = ""
        self.set_status(message)
        return True

    def on_resume_flag_changed(self, value):
        self._set_automation_preference("resume_enabled", value)
        self.refresh_resume_controls()
        self.refresh_power_monitor_controls()

    def on_power_monitor_flag_changed(self, value):
        self._set_automation_preference("power_monitor_enabled", value)
        self.refresh_resume_controls()
        self.refresh_power_monitor_controls()

    def restore_profile_after_startup(self, completion=None):
        if not self.profile_data:
            return
        self.set_status(
            self.tr(
                "status.restoring_profile",
                name=self.active_profile_name,
                path=self.profile_store.get("active", ""),
            )
        )
        profile = dict(self.profile_data)

        def completed(result):
            success, message = result
            if success:
                self.is_off = int(profile.get("brightness", 40)) <= 0
                self.update_power_button()
            self.set_status(message, level="info" if success else "error")
            if completion:
                completion(success)

        self.run_hardware_task(
            lambda: apply_profile(profile),
            completed,
            task_key="write",
            supersede=True,
        )
