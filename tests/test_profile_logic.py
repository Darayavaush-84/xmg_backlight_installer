import unittest

import bootstrap  # noqa: F401

from xmg_backlight.profile_logic import (
    ProfileDomainError,
    delete_profile,
    rename_profile,
    validate_profile_name,
)


class ProfileLogicTests(unittest.TestCase):
    def setUp(self):
        self.store = {
            "revision": 4,
            "active": "Default",
            "profiles": {"Default": {"brightness": 40}, "Low": {"brightness": 10}},
        }
        self.settings = {"ac_profile": "Default", "battery_profile": "Low"}

    def test_rename_preserves_power_references(self):
        store, settings = rename_profile(self.store, self.settings, "Default", "Bright")
        self.assertEqual(store["active"], "Bright")
        self.assertEqual(settings["ac_profile"], "Bright")
        self.assertNotIn("Default", store["profiles"])

    def test_delete_clears_dangling_reference(self):
        store, settings = delete_profile(self.store, self.settings, "Low")
        self.assertEqual(settings["battery_profile"], "")
        self.assertNotIn("Low", store["profiles"])

    def test_cannot_delete_last_profile(self):
        one = {"active": "Only", "profiles": {"Only": {}}}
        with self.assertRaises(ProfileDomainError):
            delete_profile(one, {}, "Only")

    def test_profile_name_length_is_bounded(self):
        with self.assertRaises(ProfileDomainError):
            validate_profile_name("x" * 129)
