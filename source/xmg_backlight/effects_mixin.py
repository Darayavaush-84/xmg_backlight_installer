from __future__ import annotations

from .capabilities import capability_for
from .commands import build_profile_commands
from .driver import format_cli_error, run_cmd, run_sequence
from .ui_helpers import set_combo_by_data

class EffectsMixin:
    def update_panels(self):
        is_static = (self.mode.currentData() == "static")
        self.static_label.setVisible(is_static)
        self.static_color.setVisible(is_static)
        self.effect_panel.setVisible(not is_static)
        capability = capability_for(self.mode.currentData() or "static")
        self.speed.setEnabled(capability.speed)
        self.color.setEnabled(capability.color)
        self.reactive.setEnabled(capability.reactive)
        self.direction.setEnabled(
            capability.direction and not self.reactive.isChecked()
        )
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
        self.last_brightness = v
        self.refresh_profile_dirty_state()
        if v <= 0:
            self.brightness_timer.stop()
            self.on_power_off()
            return
        self.brightness_timer.start()

    def on_power_on(self, on_success=None):
        v = self.last_brightness if self.last_brightness > 0 else 40
        self._suppress = True
        self.b_spin.setValue(v)
        self._suppress = False
        def completed():
            self.is_off = False
            self.update_power_button()
            if on_success:
                on_success()

        self.apply_current_mode(allow_when_off=True, on_success=completed)

    def on_power_off(self, on_success=None):
        self.log("$ off", level="cmd")

        def completed(result):
            rc, out, err = result
            if rc == 0:
                self.is_off = True
                self.set_status(self.tr("status.backlight_off"))
                self.update_power_button()
                if on_success:
                    on_success()
            else:
                self.set_status(format_cli_error(rc, out, err), level="error")

        self.run_hardware_task(
            lambda: run_cmd(["off"]),
            completed,
            task_key="write",
            supersede=True,
        )

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
            self.on_power_on()
            return
        v = int(self.b_spin.value())
        def completed(result):
            rc, out, err = result
            if rc == 0:
                self.set_status(self.tr("status.brightness_set", value=v))
            else:
                self.set_status(format_cli_error(rc, out, err), level="error")

        self.run_hardware_task(
            lambda: run_cmd(
                ["brightness", str(v)],
                log_cmd=False,
                log_stdout=False,
                log_stderr=False,
            ),
            completed,
            task_key="write",
            supersede=True,
        )

    def hard_reset_then(self, args, completed):
        self.log("$ off / " + " ".join(args), level="cmd")
        self.run_hardware_task(
            lambda: run_sequence([["off"], args]),
            completed,
            task_key="write",
            supersede=True,
        )

    def apply_static(self, on_success=None):
        v = int(self.b_spin.value())
        color_value = self.static_color.currentData() or self.static_color.currentText()
        display_color = self.static_color.currentText()
        self.last_static_color = color_value
        args = ["monocolor", "-b", str(v), "--name", color_value]

        def completed(result):
            rc, out, err, _failed_index = result
            if rc == 0:
                self.set_status(
                    self.tr(
                        "status.static_applied",
                        brightness=v,
                        color=display_color,
                    )
                )
                if on_success:
                    on_success()
            else:
                self.set_status(
                    self.tr(
                        "status.error_generic",
                        code=rc,
                        message=(err or out or self.tr("status.unknown_error")),
                    ),
                    level="error",
                )

        self.hard_reset_then(args, completed)

    def build_effect_args(self):
        commands = build_profile_commands(self.capture_profile_state())
        return commands[1]

    def apply_effect(self, on_success=None):
        args = self.build_effect_args()
        def completed(result):
            rc, out, err, _failed_index = result
            if rc == 0:
                used_str = " ".join(args[1:])
                self.set_status(
                    self.tr("status.effect_applied", details=used_str)
                )
                if on_success:
                    on_success()
            else:
                self.set_status(
                    self.tr(
                        "status.error_generic",
                        code=rc,
                        message=(err or out or self.tr("status.unknown_error")),
                    ),
                    level="error",
                )

        self.hard_reset_then(args, completed)

    def apply_current_mode(self, *, allow_when_off=False, on_success=None):
        if self.is_off and not allow_when_off:
            return
        if self.mode.currentData() == "static":
            self.apply_static(on_success=on_success)
        else:
            self.apply_effect(on_success=on_success)
