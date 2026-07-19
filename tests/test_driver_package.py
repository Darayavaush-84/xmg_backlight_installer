import json
import subprocess
import sys
import tempfile
import unittest
import venv
import zipfile
from pathlib import Path

import bootstrap  # noqa: F401


class BundledDriverTests(unittest.TestCase):
    def test_wheel_contains_only_driver_package(self):
        manifest = json.loads(Path("vendor/manifest.json").read_text())
        driver_name = next(
            row["filename"]
            for row in manifest["artifacts"]
            if row["filename"].startswith("ite8291r3_ctl-")
        )
        with zipfile.ZipFile(Path("vendor") / driver_name) as archive:
            names = archive.namelist()
        self.assertTrue(any(name.startswith("ite8291r3_ctl/") for name in names))
        self.assertFalse(any(name.startswith("xmg_backlight/") for name in names))
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))

    def test_source_declares_600b_revision_0003(self):
        script = r'''
import sys, types
usb = types.ModuleType("usb")
usb.core = types.ModuleType("usb.core")
usb.util = types.ModuleType("usb.util")
sys.modules["usb"] = usb
sys.modules["usb.core"] = usb.core
sys.modules["usb.util"] = usb.util
from ite8291r3_ctl.ite8291r3 import SUPPORTED_DEVICES, is_supported_revision
assert SUPPORTED_DEVICES[(0x048D, 0x600B)] == frozenset({0x0003})
assert is_supported_revision(0x048D, 0x600B, 0x0003)
assert not is_supported_revision(0x048D, 0x600B, 0x0004)
assert not is_supported_revision(0x048D, 0xFFFF, 0x0003)
'''
        environment = dict(__import__("os").environ)
        environment["PYTHONPATH"] = "driver/src"
        subprocess.run([sys.executable, "-c", script], env=environment, check=True)

    def test_driver_cli_rejects_invalid_rgb_before_hardware_access(self):
        script = r'''
import runpy, sys, types
usb = types.ModuleType("usb")
usb.core = types.ModuleType("usb.core")
usb.util = types.ModuleType("usb.util")
sys.modules["usb"] = usb
sys.modules["usb.core"] = usb.core
sys.modules["usb.util"] = usb.util
sys.argv = ["ite8291r3-ctl", "monocolor", "--rgb", "256,-1,20"]
runpy.run_module("ite8291r3_ctl", run_name="__main__")
'''
        environment = dict(__import__("os").environ)
        environment["PYTHONPATH"] = "driver/src"
        process = subprocess.run(
            [sys.executable, "-c", script],
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("between 0 and 255", process.stderr)

    def test_headless_core_does_not_import_qt(self):
        script = r'''
import sys
import xmg_backlight.commands
import xmg_backlight.storage
import xmg_backlight.automation_core
assert not any(name.startswith("PySide6") for name in sys.modules)
'''
        environment = dict(__import__("os").environ)
        environment["PYTHONPATH"] = "source"
        subprocess.run([sys.executable, "-c", script], env=environment, check=True)

    def test_bundled_wheels_install_offline_in_clean_venv(self):
        manifest = json.loads(Path("vendor/manifest.json").read_text())
        wheels = [str(Path("vendor") / row["filename"]) for row in manifest["artifacts"]]
        with tempfile.TemporaryDirectory() as tmp:
            venv.EnvBuilder(with_pip=True).create(tmp)
            python = Path(tmp) / "bin" / "python"
            subprocess.run(
                [python, "-m", "pip", "install", "--no-index", "--no-deps", *wheels],
                check=True,
                capture_output=True,
                text=True,
            )
            output = subprocess.run(
                [python, "-m", "ite8291r3_ctl", "--version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertIn("0.4.post1", output)
            subprocess.run(
                [
                    python,
                    "-c",
                    (
                        "from ite8291r3_ctl.ite8291r3 import is_supported_revision; "
                        "assert is_supported_revision(0x048D, 0x600B, 0x0003); "
                        "assert not is_supported_revision(0x048D, 0x600B, 0x0004)"
                    ),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
