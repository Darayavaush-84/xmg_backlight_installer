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

class EffectsMixin:
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
