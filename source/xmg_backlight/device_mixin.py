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

class DeviceMixin:
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
