import subprocess
import unittest
from unittest import mock

import bootstrap  # noqa: F401

from xmg_backlight import driver


class DriverExecutionTests(unittest.TestCase):
    @mock.patch("xmg_backlight.driver.subprocess.run")
    def test_timeout_is_structured(self, run):
        run.side_effect = subprocess.TimeoutExpired(["tool"], 2)
        self.assertEqual(
            driver._run_unlocked("tool", ["query"], timeout=2),
            (124, "", "Command timed out after 2.0s"),
        )

    @mock.patch("xmg_backlight.driver.resolve_tool", return_value="/tool")
    @mock.patch("xmg_backlight.driver.hardware_lock")
    @mock.patch("xmg_backlight.driver._run_unlocked")
    def test_sequence_stops_at_first_failure(self, run, lock, _resolve):
        lock.return_value.__enter__.return_value = None
        run.side_effect = [(0, "", ""), (7, "", "bad"), (0, "", "")]
        result = driver.run_sequence(
            [["off"], ["effect", "rainbow"], ["brightness", "40"]],
            inter_command_delay=0,
        )
        self.assertEqual(result, (7, "", "bad", 1))
        self.assertEqual(run.call_count, 2)

    @mock.patch("xmg_backlight.driver.resolve_tool", return_value=None)
    def test_missing_bundled_driver_is_not_hidden(self, _resolve):
        rc, _, error = driver.run_cmd(["query"])
        self.assertEqual(rc, 127)
        self.assertIn("bundled", error.lower())
