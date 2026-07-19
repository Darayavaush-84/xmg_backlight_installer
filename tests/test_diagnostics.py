import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import bootstrap  # noqa: F401

from xmg_backlight import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_archive_is_atomic_and_records_collection_errors(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            diagnostics, "_capture", return_value=(None, "journal unavailable")
        ), mock.patch.object(diagnostics, "resolve_tool", return_value=None):
            root = Path(tmp)
            config = root / "config"
            config.mkdir()
            (config / "state.json").write_text("{}", encoding="utf-8")
            destination = root / "report.zip"
            report = diagnostics.create_diagnostics_archive(
                str(destination),
                activity_lines=["one", "two"],
                config_dir=str(config),
                installer_log_path=str(root / "missing.log"),
            )
            self.assertTrue(destination.is_file())
            self.assertTrue(report["errors"])
            self.assertFalse(list(root.glob(".report.zip.*.tmp")))
            with zipfile.ZipFile(destination) as archive:
                names = set(archive.namelist())
                self.assertIn("collection-report.json", names)
                self.assertIn("config/state.json", names)
                collection = json.loads(archive.read("collection-report.json"))
                self.assertTrue(collection["errors"])
