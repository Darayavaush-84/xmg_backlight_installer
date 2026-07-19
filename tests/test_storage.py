import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bootstrap  # noqa: F401

from xmg_backlight import storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = {
            "CONFIG_DIR": str(root),
            "STATE_PATH": str(root / "state.json"),
            "PROFILE_PATH": str(root / "profile.json"),
            "SETTINGS_PATH": str(root / "settings.json"),
            "LOCK_FILE_PATH": str(root / "app.lock"),
        }
        self.patch = mock.patch.multiple(storage, **self.paths)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_atomic_profile_write_has_private_permissions_and_revision(self):
        store = storage.load_profile_store()
        persisted = storage.write_profile_store(store, expected_revision=0)
        path = Path(self.paths["STATE_PATH"])
        self.assertEqual(persisted["revision"], 1)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertFalse(list(path.parent.glob(".state.json.*.tmp")))

    def test_stale_writer_is_rejected_without_losing_newer_data(self):
        initial = storage.write_profile_store(storage.load_profile_store(), expected_revision=0)
        newer = dict(initial)
        newer["profiles"] = dict(initial["profiles"])
        newer["profiles"]["Second"] = dict(storage.DEFAULT_PROFILE_STATE)
        storage.write_profile_store(newer, expected_revision=1)
        with self.assertRaises(storage.ProfileConflictError):
            storage.write_profile_store(initial, expected_revision=1)
        self.assertIn("Second", storage.load_profile_store()["profiles"])

    def test_switch_changes_only_active_profile(self):
        store = storage.load_profile_store()
        store["profiles"]["Battery"] = {**storage.DEFAULT_PROFILE_STATE, "brightness": 10}
        storage.write_profile_store(store, expected_revision=0)
        self.assertTrue(storage.switch_active_profile("Battery"))
        loaded = storage.load_profile_store()
        self.assertEqual(loaded["active"], "Battery")
        self.assertEqual(loaded["profiles"]["Battery"]["brightness"], 10)

    def test_malformed_json_is_not_silently_replaced(self):
        Path(self.paths["STATE_PATH"]).write_text("{broken", encoding="utf-8")
        with self.assertRaises(storage.StorageFormatError):
            storage.load_profile_store()

    def test_malformed_profile_structure_is_not_sanitized_away(self):
        Path(self.paths["STATE_PATH"]).write_text(
            json.dumps(
                {
                    "schema": 1,
                    "settings": {},
                    "profile_store": {
                        "revision": 1,
                        "active": "Missing",
                        "profiles": {},
                    },
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(storage.StorageFormatError):
            storage.load_profile_store()

    def test_legacy_documents_migrate_once_to_unified_state(self):
        Path(self.paths["SETTINGS_PATH"]).write_text(
            json.dumps({"ac_profile": "Battery"}), encoding="utf-8"
        )
        Path(self.paths["PROFILE_PATH"]).write_text(
            json.dumps(
                {
                    "active": "Battery",
                    "profiles": {
                        "Battery": {
                            **storage.DEFAULT_PROFILE_STATE,
                            "brightness": 12,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        state = storage.ensure_app_state()
        self.assertEqual(state["settings"]["ac_profile"], "Battery")
        self.assertEqual(
            state["profile_store"]["profiles"]["Battery"]["brightness"], 12
        )
        self.assertTrue(Path(self.paths["STATE_PATH"]).is_file())
        self.assertFalse(Path(self.paths["SETTINGS_PATH"]).exists())
        self.assertFalse(Path(self.paths["PROFILE_PATH"]).exists())

    def test_profile_and_power_references_commit_together(self):
        store = storage.ensure_profile_store()
        store["profiles"]["Travel"] = dict(storage.DEFAULT_PROFILE_STATE)
        settings = storage.load_settings()
        settings["ac_profile"] = "Travel"
        persisted_store, persisted_settings = storage.write_profile_and_settings(
            store,
            settings,
            expected_profile_revision=0,
        )
        self.assertIn("Travel", persisted_store["profiles"])
        self.assertEqual(persisted_settings["ac_profile"], "Travel")
        raw = json.loads(Path(self.paths["STATE_PATH"]).read_text(encoding="utf-8"))
        self.assertIn("Travel", raw["profile_store"]["profiles"])
        self.assertEqual(raw["settings"]["ac_profile"], "Travel")

    def test_string_booleans_are_not_treated_as_true(self):
        settings = storage.sanitize_settings(
            {"start_in_tray": "false", "show_notifications": "false"}
        )
        self.assertFalse(settings["start_in_tray"])
        self.assertTrue(settings["show_notifications"])

    def test_single_instance_lock_is_stable_and_not_unlinked(self):
        first = storage.acquire_single_instance_lock()
        self.assertIsNotNone(first)
        self.assertIsNone(storage.acquire_single_instance_lock())
        storage.release_single_instance_lock(first)
        self.assertTrue(Path(self.paths["LOCK_FILE_PATH"]).exists())
