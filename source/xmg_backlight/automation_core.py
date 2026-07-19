"""Pure event handling for resume and power-profile automation."""

from __future__ import annotations

from collections.abc import Callable


def required_bus_signals(settings: dict) -> tuple[bool, bool]:
    """Return whether login1 and UPower subscriptions are required."""
    return (
        bool(settings.get("resume_enabled", False)),
        bool(settings.get("power_monitor_enabled", False)),
    )


class AutomationController:
    def __init__(
        self,
        *,
        settings_loader: Callable[[], dict],
        profile_switcher: Callable[[str], bool],
        active_profile_loader: Callable[[], dict | None],
        profile_applier: Callable[[dict], tuple[bool, str]],
        logger: Callable[[str], None],
    ):
        self._settings_loader = settings_loader
        self._profile_switcher = profile_switcher
        self._active_profile_loader = active_profile_loader
        self._profile_applier = profile_applier
        self._logger = logger
        self._sleep_pending = False
        self._last_on_ac: bool | None = None

    def _apply_active(self, reason: str) -> bool:
        profile = self._active_profile_loader()
        if not profile:
            self._logger(f"{reason}: no active profile is available")
            return False
        success, detail = self._profile_applier(profile)
        self._logger(f"{reason}: {detail}")
        return success

    def on_prepare_for_sleep(self, sleeping: bool) -> bool:
        settings = self._settings_loader()
        if sleeping:
            self._sleep_pending = True
            self._logger("System is preparing to sleep")
            return False
        if not self._sleep_pending:
            return False
        self._sleep_pending = False
        if not settings.get("resume_enabled", False):
            self._logger("Resume event ignored because resume automation is disabled")
            return False
        return self._apply_active("Resume from sleep")

    def on_power_state(self, on_ac: bool) -> bool:
        on_ac = bool(on_ac)
        changed = self._last_on_ac is None or self._last_on_ac != on_ac
        self._last_on_ac = on_ac
        if not changed:
            return False
        settings = self._settings_loader()
        if not settings.get("power_monitor_enabled", False):
            self._logger("Power event ignored because power automation is disabled")
            return False
        key = "ac_profile" if on_ac else "battery_profile"
        target = settings.get(key, "")
        state_name = "AC" if on_ac else "battery"
        if not target:
            self._logger(f"{state_name}: no profile is assigned")
            return False
        if not self._profile_switcher(target):
            self._logger(f"{state_name}: assigned profile '{target}' does not exist")
            return False
        return self._apply_active(f"Power state changed to {state_name}")
