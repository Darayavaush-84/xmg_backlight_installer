import unittest

import bootstrap  # noqa: F401

import install as installer
from installer_lib.versioning import is_newer_version, parse_version


class VersioningTests(unittest.TestCase):
    def test_release_version_and_comparison(self):
        self.assertEqual(installer.APP_VERSION, "2.5.0-rc1")
        self.assertEqual(parse_version("v2.5.0"), (2, 5, 0))
        self.assertTrue(is_newer_version("2.5.1", "2.5.0"))
        self.assertFalse(is_newer_version("2.5.0", "2.5.0"))
        self.assertEqual(parse_version("2.invalid.1"), ())

    def test_final_release_is_newer_than_release_candidate(self):
        self.assertTrue(is_newer_version("v2.5.0", "2.5.0-rc1"))
        self.assertTrue(is_newer_version("2.5.0-rc2", "2.5.0-rc1"))
        self.assertFalse(is_newer_version("2.5.0-rc1", "2.5.0"))
        self.assertFalse(is_newer_version("2.5.0-rc1", "2.5.0-rc1"))
