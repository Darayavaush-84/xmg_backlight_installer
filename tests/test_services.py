import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bootstrap  # noqa: F401

from xmg_backlight import services


class ServiceTests(unittest.TestCase):
    def test_automation_unit_is_event_daemon_not_fake_sleep_target(self):
        unit = services.automation_service_contents()
        self.assertIn("xmg_backlight.automation_daemon", unit)
        self.assertIn("WantedBy=default.target", unit)
        self.assertNotIn("sleep.target", unit)
        self.assertNotIn("ExecStopPost", unit)

    def test_reconcile_enables_one_service_for_either_feature(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            services, "AUTOMATION_SERVICE_PATH", str(Path(tmp) / "automation.service")
        ), mock.patch.object(
            services, "RESUME_SERVICE_PATH", str(Path(tmp) / "old-resume.service")
        ), mock.patch.object(
            services, "POWER_MONITOR_SERVICE_PATH", str(Path(tmp) / "old-power.service")
        ), mock.patch.object(services, "systemctl_user") as systemctl:
            systemctl.return_value = (0, "", "")
            ok, _ = services.reconcile_automation_service(
                {"resume_enabled": True, "power_monitor_enabled": False}
            )
            self.assertTrue(ok)
            self.assertTrue(Path(services.AUTOMATION_SERVICE_PATH).is_file())
            self.assertIn(
                mock.call(["enable", services.AUTOMATION_SERVICE_NAME]),
                systemctl.call_args_list,
            )
            self.assertIn(
                mock.call(["restart", services.AUTOMATION_SERVICE_NAME]),
                systemctl.call_args_list,
            )

    def test_unowned_service_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            services, "AUTOMATION_SERVICE_PATH", str(Path(tmp) / "automation.service")
        ), mock.patch.object(
            services, "RESUME_SERVICE_PATH", str(Path(tmp) / "old-resume.service")
        ), mock.patch.object(
            services, "POWER_MONITOR_SERVICE_PATH", str(Path(tmp) / "old-power.service")
        ), mock.patch.object(services, "systemctl_user") as systemctl:
            target = Path(services.AUTOMATION_SERVICE_PATH)
            target.write_text("[Service]\nExecStart=/another/program\n", encoding="utf-8")
            ok, detail = services.reconcile_automation_service(
                {"resume_enabled": True, "power_monitor_enabled": False}
            )
            self.assertFalse(ok)
            self.assertIn("unowned", detail)
            self.assertIn("/another/program", target.read_text(encoding="utf-8"))
            systemctl.assert_not_called()

    def test_operational_status_error_is_not_reported_as_disabled(self):
        with mock.patch.object(
            services,
            "systemctl_user",
            return_value=(1, "", "Failed to connect to bus"),
        ):
            enabled, detail = services.automation_service_status()
        self.assertFalse(enabled)
        self.assertEqual(detail, "Failed to connect to bus")
