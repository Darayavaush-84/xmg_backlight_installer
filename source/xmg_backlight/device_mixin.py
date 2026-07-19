from __future__ import annotations

import time

from PySide6 import QtCore

from .async_tasks import submit_task
from .commands import parse_keyboard_state
from .driver import format_cli_error, run_cmd

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
        self.run_hardware_task(
            lambda: run_cmd(
                ["query", "--brightness", "--state"],
                log_cmd=False,
                log_stdout=False,
                log_stderr=False,
            ),
            self._on_state_sync_completed,
            task_key="sync",
            supersede=True,
        )

    def _on_state_sync_completed(self, result):
        rc, out, err = result
        if rc != 0:
            message = format_cli_error(rc, out, err)
            self.set_status(message, level="error")
            return

        parsed = parse_keyboard_state(out)
        brightness = parsed.brightness
        state = parsed.power

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

    def run_hardware_task(
        self,
        function,
        completed,
        *,
        task_key=None,
        supersede=False,
    ):
        if self._hardware_shutdown:
            return None
        generation = self._hardware_generations.get(task_key, 0)
        if task_key is not None and supersede:
            generation += 1
            self._hardware_generations[task_key] = generation
            for pending in tuple(self._hardware_tasks):
                if pending.task_key == task_key:
                    pending.cancel_if_pending()

        def is_current():
            return (
                not self._hardware_shutdown
                and (
                    task_key is None
                    or self._hardware_generations.get(task_key, 0) == generation
                )
            )

        def completed_if_current(result):
            if is_current():
                completed(result)

        def failed(message):
            if is_current():
                self.set_status(message, level="error")

        task = submit_task(
            self.hardware_pool,
            function,
            completed_if_current,
            failed,
            task_key=task_key,
            auto_start=False,
        )
        self._hardware_tasks.add(task)
        task.signals.finished.connect(
            lambda current=task: self._hardware_tasks.discard(current)
        )
        self.hardware_pool.start(task)
        return task

    def shutdown_hardware_tasks(self):
        if self._hardware_shutdown:
            return
        self._hardware_shutdown = True
        for task in tuple(self._hardware_tasks):
            task.cancel_if_pending()
        self.hardware_pool.waitForDone(15000)
        self._hardware_tasks.clear()

    def detect_device(self):
        self.log("$ query --devices", level="cmd")
        self.run_hardware_task(
            lambda: run_cmd(["query", "--devices"]),
            self._on_device_detection_completed,
            task_key="detect",
            supersede=True,
        )

    def _on_device_detection_completed(self, result):
        rc, out, err = result
        if rc == 0 and (out or "").strip():
            self.hardware_detected = True
            msg = (out or "").strip() or self.tr("status.device_detected")
            self.hardware_label.setText(msg)
            self.set_status(msg)
            self.sync_initial_state()
        else:
            self.hardware_detected = False
            self.hardware_label.setText(self.tr("hero.hardware_unknown"))
            if rc == 0:
                self.set_status(self.tr("hero.hardware_unknown"))
            else:
                self.set_status(format_cli_error(rc, out, err))

    def sync_initial_state(self):
        self.sync_state_from_device()
