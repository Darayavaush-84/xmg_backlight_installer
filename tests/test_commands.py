import unittest

import bootstrap  # noqa: F401

from xmg_backlight.capabilities import EFFECT_CAPABILITIES
from xmg_backlight.commands import (
    KeyboardState,
    build_profile_commands,
    parse_keyboard_state,
    state_matches_desired,
)


class CommandConstructionTests(unittest.TestCase):
    def test_zero_brightness_builds_only_off(self):
        self.assertEqual(build_profile_commands({"brightness": 0}), [["off"]])

    def test_static_random_is_rejected_deterministically(self):
        commands = build_profile_commands(
            {"brightness": 40, "mode": "static", "static_color": "random"}
        )
        self.assertEqual(
            commands,
            [["off"], ["monocolor", "-b", "40", "--name", "white"], ["brightness", "40"]],
        )

    def test_each_effect_contains_only_supported_flags(self):
        profile = {
            "brightness": 33,
            "speed": 8,
            "color": "red",
            "direction": "left",
            "reactive": True,
        }
        for mode, capability in EFFECT_CAPABILITIES.items():
            with self.subTest(mode=mode):
                profile["mode"] = mode
                command = build_profile_commands(profile)[1]
                self.assertEqual(command[-1], mode)
                self.assertEqual("-s" in command, capability.speed)
                self.assertEqual("-c" in command, capability.color)
                self.assertEqual("-r" in command, capability.reactive)
                self.assertEqual(
                    "-d" in command,
                    capability.direction and not capability.reactive,
                )

    def test_wave_uses_direction_and_never_color_or_reactive(self):
        command = build_profile_commands(
            {
                "brightness": 20,
                "mode": "wave",
                "speed": 7,
                "color": "red",
                "direction": "left",
                "reactive": True,
            }
        )[1]
        self.assertIn("-d", command)
        self.assertNotIn("-c", command)
        self.assertNotIn("-r", command)


class StateVerificationTests(unittest.TestCase):
    def test_parses_cli_state(self):
        self.assertEqual(
            parse_keyboard_state("40\non\n"),
            KeyboardState(brightness=40, power="on"),
        )

    def test_off_is_success_for_zero_profile(self):
        self.assertTrue(state_matches_desired(KeyboardState(0, "off"), 0))
        self.assertTrue(state_matches_desired(KeyboardState(40, "off"), 0))
        self.assertFalse(state_matches_desired(KeyboardState(0, "on"), 0))

    def test_on_requires_exact_brightness(self):
        self.assertTrue(state_matches_desired(KeyboardState(40, "on"), 40))
        self.assertFalse(state_matches_desired(KeyboardState(20, "on"), 40))
        self.assertFalse(state_matches_desired(KeyboardState(40, "off"), 40))
