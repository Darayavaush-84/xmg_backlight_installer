import unittest

import bootstrap  # noqa: F401

from xmg_backlight.automation_core import AutomationController, required_bus_signals


class AutomationControllerTests(unittest.TestCase):
    def test_only_enabled_features_require_bus_subscriptions(self):
        self.assertEqual(
            required_bus_signals(
                {"resume_enabled": True, "power_monitor_enabled": False}
            ),
            (True, False),
        )
        self.assertEqual(
            required_bus_signals(
                {"resume_enabled": False, "power_monitor_enabled": True}
            ),
            (False, True),
        )
    def build(self, settings):
        self.events = []
        self.active = {"brightness": 40}
        self.profiles = {"AC": {"brightness": 40}, "BAT": {"brightness": 10}}

        def switch(name):
            if name not in self.profiles:
                return False
            self.active = self.profiles[name]
            self.events.append(("switch", name))
            return True

        def apply(profile):
            self.events.append(("apply", profile["brightness"]))
            return True, "applied"

        return AutomationController(
            settings_loader=lambda: dict(settings),
            profile_switcher=switch,
            active_profile_loader=lambda: dict(self.active),
            profile_applier=apply,
            logger=lambda message: self.events.append(("log", message)),
        )

    def test_resume_requires_a_paired_prepare_signal(self):
        controller = self.build({"resume_enabled": True})
        self.assertFalse(controller.on_prepare_for_sleep(False))
        controller.on_prepare_for_sleep(True)
        self.assertTrue(controller.on_prepare_for_sleep(False))
        self.assertIn(("apply", 40), self.events)

    def test_disabled_resume_does_not_apply(self):
        controller = self.build({"resume_enabled": False})
        controller.on_prepare_for_sleep(True)
        self.assertFalse(controller.on_prepare_for_sleep(False))
        self.assertFalse(any(event[0] == "apply" for event in self.events))

    def test_first_known_power_state_applies_assigned_profile(self):
        controller = self.build(
            {"power_monitor_enabled": True, "ac_profile": "AC", "battery_profile": "BAT"}
        )
        self.assertTrue(controller.on_power_state(False))
        self.assertEqual(self.events[-1], ("log", "Power state changed to battery: applied"))
        self.assertIn(("switch", "BAT"), self.events)
        self.assertIn(("apply", 10), self.events)

    def test_duplicate_power_signal_is_ignored(self):
        controller = self.build({"power_monitor_enabled": True, "ac_profile": "AC"})
        controller.on_power_state(True)
        before = list(self.events)
        self.assertFalse(controller.on_power_state(True))
        self.assertEqual(self.events, before)

    def test_missing_assignment_does_not_fallback_to_active_profile(self):
        controller = self.build({"power_monitor_enabled": True, "ac_profile": ""})
        self.assertFalse(controller.on_power_state(True))
        self.assertFalse(any(event[0] == "apply" for event in self.events))
