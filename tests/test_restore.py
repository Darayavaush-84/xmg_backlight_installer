import unittest
from unittest import mock

import bootstrap  # noqa: F401

from xmg_backlight import restore_profile


class RestoreTests(unittest.TestCase):
    @mock.patch("xmg_backlight.restore_profile.run_cmd")
    @mock.patch("xmg_backlight.restore_profile.run_sequence")
    def test_zero_brightness_off_is_verified_as_success(self, sequence, command):
        sequence.return_value = (0, "", "", None)
        command.return_value = (0, "0\noff", "")
        success, message = restore_profile.apply_profile({"brightness": 0})
        self.assertTrue(success)
        self.assertIn("verified", message)
        sequence.assert_called_once_with([["off"]])

    @mock.patch("xmg_backlight.restore_profile.run_cmd")
    @mock.patch("xmg_backlight.restore_profile.run_sequence")
    def test_verification_mismatch_fails_without_retry(self, sequence, command):
        sequence.return_value = (0, "", "", None)
        command.return_value = (0, "20\non", "")
        success, message = restore_profile.apply_profile({"brightness": 40})
        self.assertFalse(success)
        self.assertIn("mismatch", message)
        self.assertEqual(sequence.call_count, 1)
