"""Event-driven user daemon for login1 resume and UPower changes."""

from __future__ import annotations

import sys
import time

from PySide6 import QtCore, QtDBus

from .automation_core import AutomationController, required_bus_signals
from .restore_profile import apply_profile
from .storage import (
    active_profile_from_raw_store,
    load_settings,
    read_profile_file,
    switch_active_profile,
)


def log(message: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def load_active_profile():
    return active_profile_from_raw_store(read_profile_file())


class SystemBusAdapter(QtCore.QObject):
    def __init__(self, controller: AutomationController):
        super().__init__()
        self.controller = controller
        self.bus = QtDBus.QDBusConnection.systemBus()

    def connect_signals(self, *, resume_enabled: bool, power_enabled: bool) -> bool:
        if not self.bus.isConnected():
            log("System D-Bus is unavailable")
            return False
        sleep_ok = True
        power_ok = True
        if resume_enabled:
            sleep_ok = self.bus.connect(
                "org.freedesktop.login1",
                "/org/freedesktop/login1",
                "org.freedesktop.login1.Manager",
                "PrepareForSleep",
                self,
                QtCore.SLOT("on_prepare_for_sleep(bool)"),
            )
        if power_enabled:
            power_ok = self.bus.connect(
                "org.freedesktop.UPower",
                "/org/freedesktop/UPower",
                "org.freedesktop.DBus.Properties",
                "PropertiesChanged",
                self,
                QtCore.SLOT(
                    "on_properties_changed(QString,QVariantMap,QStringList)"
                ),
            )
        if resume_enabled and not sleep_ok:
            log("Unable to subscribe to login1 PrepareForSleep")
        if power_enabled and not power_ok:
            log("Unable to subscribe to UPower PropertiesChanged")
        return (resume_enabled or power_enabled) and sleep_ok and power_ok

    def read_initial_power_state(self) -> bool:
        interface = QtDBus.QDBusInterface(
            "org.freedesktop.UPower",
            "/org/freedesktop/UPower",
            "org.freedesktop.UPower",
            self.bus,
        )
        if not interface.isValid():
            log("UPower interface is unavailable")
            return False
        on_battery = interface.property("OnBattery")
        if on_battery is None:
            log("UPower did not expose OnBattery")
            return False
        self.controller.on_power_state(not bool(on_battery))
        return True

    @QtCore.Slot(bool)
    def on_prepare_for_sleep(self, sleeping):
        self.controller.on_prepare_for_sleep(bool(sleeping))

    @QtCore.Slot(str, "QVariantMap", "QStringList")
    def on_properties_changed(self, interface_name, changed, _invalidated):
        if interface_name != "org.freedesktop.UPower" or "OnBattery" not in changed:
            return
        self.controller.on_power_state(not bool(changed["OnBattery"]))


def main() -> int:
    app = QtCore.QCoreApplication([])
    settings = load_settings()
    resume_enabled, power_enabled = required_bus_signals(settings)
    controller = AutomationController(
        settings_loader=load_settings,
        profile_switcher=switch_active_profile,
        active_profile_loader=load_active_profile,
        profile_applier=apply_profile,
        logger=log,
    )
    adapter = SystemBusAdapter(controller)
    if not adapter.connect_signals(
        resume_enabled=resume_enabled,
        power_enabled=power_enabled,
    ):
        return 1
    if power_enabled:
        adapter.read_initial_power_state()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
