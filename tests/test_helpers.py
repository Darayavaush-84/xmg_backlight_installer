import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

from installer_lib.udev import format_udev_rule, parse_device_id_lines
from installer_lib.versioning import (
    extract_app_version_from_text,
    is_newer_version,
    parse_version,
)
from xmg_backlight.restore_profile import build_commands


class VersioningTests(unittest.TestCase):
    def test_extracts_app_version(self):
        self.assertEqual(
            extract_app_version_from_text('APP_VERSION = "2.1.0"'),
            "2.1.0",
        )

    def test_compares_versions(self):
        self.assertEqual(parse_version("v2.1.0"), (2, 1, 0))
        self.assertTrue(is_newer_version("v2.1.1", "2.1.0"))
        self.assertFalse(is_newer_version("v2.1.0", "2.1.0"))


class UdevTests(unittest.TestCase):
    def test_parses_driver_device_output(self):
        result = parse_device_id_lines(
            [
                "048d:6004 bus 1 addr 2 rev 0.03 product "
                "'ITE Device(8291)' manufacturer 'ITE Tech. Inc.'"
            ]
        )
        self.assertEqual(result.ids, [("048d", "6004")])
        self.assertEqual(result.unmatched, [])

    def test_formats_udev_rule(self):
        self.assertEqual(
            format_udev_rule("048d", "6004"),
            'SUBSYSTEMS=="usb", ATTRS{idVendor}=="048d", '
            'ATTRS{idProduct}=="6004", MODE:="0666"',
        )


class RestoreProfileTests(unittest.TestCase):
    def test_builds_static_restore_commands(self):
        self.assertEqual(
            build_commands(
                {"brightness": 40, "mode": "static", "static_color": "white"}
            ),
            [["off"], ["monocolor", "-b", "40", "--name", "white"], ["brightness", "40"]],
        )


if __name__ == "__main__":
    unittest.main()
