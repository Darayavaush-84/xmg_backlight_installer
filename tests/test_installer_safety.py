import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bootstrap  # noqa: F401

from installer_lib.artifacts import ArtifactValidationError, load_and_validate_manifest
from installer_lib.ownership import (
    OwnershipError,
    assert_replaceable_file,
    sha256_directory,
    sha256_file,
    verify_owned_directory,
)
from installer_lib.processes import is_managed_gui_process
from installer_lib.transaction import FilesystemTransaction
from installer_lib.udev import (
    existing_rule_contains_device,
    format_udev_rule,
    rule_grants_world_write,
)
import install as installer


class ArtifactManifestTests(unittest.TestCase):
    def test_repository_manifest_and_wheels_validate(self):
        manifest = load_and_validate_manifest(Path("vendor/manifest.json"))
        self.assertEqual(manifest.driver_version, "0.4.post1")
        self.assertEqual(len(manifest.artifacts), 2)

    def test_tampered_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = root / "ite8291r3_ctl-1-py3-none-any.whl"
            wheel.write_bytes(b"tampered")
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "driver_distribution": "ite8291r3-ctl",
                        "driver_version": "1",
                        "artifacts": [{"filename": wheel.name, "sha256": "0" * 64}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ArtifactValidationError):
                load_and_validate_manifest(root / "manifest.json")


class OwnershipTests(unittest.TestCase):
    def test_modified_managed_file_is_not_replaceable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wrapper"
            path.write_text("managed", encoding="utf-8")
            manifest = {"files": {str(path): sha256_file(path)}}
            assert_replaceable_file(path, manifest)
            path.write_text("user modified", encoding="utf-8")
            with self.assertRaises(OwnershipError):
                assert_replaceable_file(path, manifest)

    def test_unrelated_legacy_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wrapper"
            path.write_text("other program", encoding="utf-8")
            with self.assertRaises(OwnershipError):
                assert_replaceable_file(path, {}, legacy_validator=lambda _: False)

    def test_modified_directory_tree_is_not_owned(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "managed"
            path.mkdir()
            install_id = "directory-test"
            (path / ".xmg-backlight-owner.json").write_text(
                json.dumps({"install_id": install_id}), encoding="utf-8"
            )
            payload = path / "payload"
            payload.write_text("original", encoding="utf-8")
            manifest = {
                "install_id": install_id,
                "directories": [str(path)],
                "directory_hashes": {str(path): sha256_directory(path)},
            }
            self.assertTrue(verify_owned_directory(path, manifest))
            payload.write_text("modified", encoding="utf-8")
            self.assertFalse(verify_owned_directory(path, manifest))


class FilesystemTransactionTests(unittest.TestCase):
    def test_exception_rolls_back_directory_and_file_replacements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup_parent = root / "state"
            target_dir = root / "live-dir"
            target_dir.mkdir()
            (target_dir / "value").write_text("old", encoding="utf-8")
            staged_dir = root / "stage-dir"
            staged_dir.mkdir()
            (staged_dir / "value").write_text("new", encoding="utf-8")
            target_file = root / "live-file"
            target_file.write_text("old", encoding="utf-8")
            staged_file = root / "stage-file"
            staged_file.write_text("new", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "abort"):
                with FilesystemTransaction(backup_parent) as transaction:
                    transaction.replace_directory(staged_dir, target_dir)
                    transaction.replace_file(staged_file, target_file, mode=0o600)
                    raise RuntimeError("abort")
            self.assertEqual((target_dir / "value").read_text(), "old")
            self.assertEqual(target_file.read_text(), "old")
            self.assertFalse(list(root.glob(".*.xmg-backlight-backup-*")))
            self.assertFalse(list(root.glob(".*.xmg-backlight-stage-*")))

    def test_exception_rolls_back_directory_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "managed-dir"
            target.mkdir()
            (target / "value").write_text("preserved", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "abort"):
                with FilesystemTransaction(root / "state") as transaction:
                    transaction.remove_directory(target)
                    raise RuntimeError("abort")
            self.assertEqual((target / "value").read_text(), "preserved")


class InstallerCliTests(unittest.TestCase):
    def test_destructive_flags_require_uninstall(self):
        for arguments in (["--purge"], ["--purge-user-data"], ["--all-users"]):
            with self.subTest(arguments=arguments):
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    installer.parse_args(arguments)

    def test_all_users_requires_explicit_user_data_purge(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            installer.parse_args(["--uninstall", "--all-users"])

    def test_update_check_option_is_rejected_for_uninstall(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            installer.parse_args(["--uninstall", "--skip-update-check"])


class UninstallPreflightTests(unittest.TestCase):
    def test_modified_artifact_aborts_before_any_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrapper = root / "xmg-backlight"
            driver_wrapper = root / "ite8291r3-ctl"
            desktop = root / "app.desktop"
            rule = root / "rule.rules"
            share = root / "share"
            venv = root / "venv"
            state = root / "state"
            manifest_path = state / "manifest.json"
            state.mkdir()
            install_id = "test-install"
            for path in (wrapper, driver_wrapper, desktop, rule):
                path.write_text(f"managed:{path.name}", encoding="utf-8")
            for path in (share, venv):
                path.mkdir()
                (path / ".xmg-backlight-owner.json").write_text(
                    json.dumps({"install_id": install_id}), encoding="utf-8"
                )
                (path / "payload").write_text("managed", encoding="utf-8")
            manifest = {
                "schema": 1,
                "install_id": install_id,
                "directories": [str(venv), str(share)],
                "directory_hashes": {
                    str(venv): sha256_directory(venv),
                    str(share): sha256_directory(share),
                },
                "files": {
                    str(path): sha256_file(path)
                    for path in (wrapper, driver_wrapper, desktop, rule)
                },
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            driver_wrapper.write_text("locally modified", encoding="utf-8")

            replacements = {
                "WRAPPER_PATH": wrapper,
                "DRIVER_WRAPPER_PATH": driver_wrapper,
                "DESKTOP_PATH": desktop,
                "UDEV_RULE_PATH": rule,
                "SHARE_DIR": share,
                "VENV_DIR": venv,
                "STATE_DIR": state,
                "MANIFEST_PATH": manifest_path,
            }
            with mock.patch.multiple(installer, **replacements), mock.patch.object(
                installer, "require_supported_root_python"
            ), mock.patch.object(installer, "close_running_gui"), mock.patch.object(
                installer, "ensure_state_directory"
            ):
                with self.assertRaisesRegex(
                    installer.InstallerError, "modified or unowned file"
                ):
                    installer.uninstall(
                        purge=True,
                        purge_user_data=False,
                        all_users=False,
                    )

            self.assertTrue(wrapper.exists())
            self.assertTrue(driver_wrapper.exists())
            self.assertTrue(desktop.exists())
            self.assertTrue(rule.exists())
            self.assertTrue(share.exists())
            self.assertTrue(venv.exists())
            self.assertTrue(manifest_path.exists())


class LegacyAdoptionTests(unittest.TestCase):
    def test_legacy_wrapper_must_match_exact_managed_contents(self):
        content = "# unrelated\n# xmg-backlight-venv -m xmg_backlight.app\n"
        self.assertFalse(installer._legacy_wrapper(content))


class VenvStagingTests(unittest.TestCase):
    def test_generated_scripts_are_relocated_to_final_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = root / "stage"
            (stage / "bin").mkdir(parents=True)
            script = stage / "bin" / "pip"
            script.write_text(f"#!{stage}/bin/python\n", encoding="utf-8")
            script.chmod(0o755)
            (stage / "pyvenv.cfg").write_text(
                f"command = python -m venv {stage}\n", encoding="utf-8"
            )
            final = root / "final-venv"
            with mock.patch.object(installer, "VENV_DIR", final):
                installer._relocate_staged_venv(stage)
            self.assertEqual(
                script.read_text(encoding="utf-8"),
                f"#!{final}/bin/python\n",
            )
            self.assertIn(
                str(final),
                (stage / "pyvenv.cfg").read_text(encoding="utf-8"),
            )

    def test_failed_venv_creation_removes_staging_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(installer, "VENV_DIR", root / "final"), mock.patch.object(
                installer,
                "run",
                side_effect=installer.InstallerError("creation failed"),
            ):
                with self.assertRaises(installer.InstallerError):
                    installer._create_staged_venv(
                        Path("/usr/bin/python3"),
                        "test",
                        SimpleNamespace(artifacts=(), driver_version="test"),
                    )
            self.assertFalse(list(root.glob(".xmg-backlight-venv-stage-*")))

    def test_failed_share_validation_removes_staging_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(installer, "SHARE_DIR", root / "final"), mock.patch.object(
                installer,
                "run",
                side_effect=installer.InstallerError("validation failed"),
            ):
                with self.assertRaises(installer.InstallerError):
                    installer._create_staged_share(Path("/python"), "test")
            self.assertFalse(list(root.glob(".xmg-backlight-share-stage-*")))

    def test_successful_venv_stage_is_runtime_traversable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = SimpleNamespace(artifacts=(), driver_version="test")
            with mock.patch.object(
                installer, "VENV_DIR", root / "final"
            ), mock.patch.object(installer, "run"), mock.patch.object(
                installer, "_relocate_staged_venv"
            ):
                stage = installer._create_staged_venv(
                    Path("/usr/bin/python3"), "test", artifacts
                )
            self.assertEqual(stage.stat().st_mode & 0o777, 0o755)

    def test_successful_share_stage_is_runtime_traversable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_package = root / "source" / "xmg_backlight"
            source_package.mkdir(parents=True)
            (source_package / "__init__.py").write_text(
                "", encoding="utf-8"
            )
            with mock.patch.object(
                installer, "SHARE_DIR", root / "final"
            ), mock.patch.object(
                installer, "SOURCE_PACKAGE", source_package
            ), mock.patch.object(installer, "run"):
                stage = installer._create_staged_share(Path("/python"), "test")
            self.assertEqual(stage.stat().st_mode & 0o777, 0o755)


class ProcessRecognitionTests(unittest.TestCase):
    def test_only_exact_module_interpreter_and_cwd_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            interpreter = root / "python"
            interpreter.write_text("", encoding="utf-8")
            share = root / "share"
            share.mkdir()
            args = [str(interpreter), "-m", "xmg_backlight.app"]
            self.assertTrue(
                is_managed_gui_process(
                    args,
                    executable=str(interpreter),
                    cwd=str(share),
                    venv_python=interpreter,
                    share_dir=share,
                )
            )
            self.assertFalse(
                is_managed_gui_process(
                    [str(interpreter), "app.py"],
                    executable=str(interpreter),
                    cwd=str(share),
                    venv_python=interpreter,
                    share_dir=share,
                )
            )
            self.assertFalse(
                is_managed_gui_process(
                    [str(interpreter), "-c", "pass", "-m", "xmg_backlight.app"],
                    executable=str(interpreter),
                    cwd=str(share),
                    venv_python=interpreter,
                    share_dir=share,
                )
            )

    def test_running_managed_gui_is_terminated_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = Path(tmp) / "share"
            package = share / "xmg_backlight"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "app.py").write_text(
                "import time\nwhile True:\n    time.sleep(1)\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(share)
            process = subprocess.Popen(
                [sys.executable, "-m", "xmg_backlight.app"],
                cwd=share,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                with mock.patch.object(
                    installer, "VENV_PYTHON", Path(sys.executable)
                ), mock.patch.object(installer, "SHARE_DIR", share):
                    deadline = time.monotonic() + 2
                    while not installer._is_running_gui_pid(process.pid):
                        if process.poll() is not None:
                            self.fail("managed GUI fixture exited unexpectedly")
                        if time.monotonic() >= deadline:
                            self.fail("managed GUI fixture was not recognized")
                        time.sleep(0.01)
                    installer.close_running_gui(timeout=2)
                self.assertIsNotNone(process.poll())
                self.assertEqual(process.returncode, -signal.SIGTERM)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)


class UdevSafetyTests(unittest.TestCase):
    def test_vendor_and_product_must_be_on_same_rule(self):
        text = (
            'ATTRS{idVendor}=="048d", ATTRS{idProduct}=="1111"\n'
            'ATTRS{idVendor}=="9999", ATTRS{idProduct}=="6004"\n'
        )
        self.assertFalse(existing_rule_contains_device(text, "048d", "6004"))

    def test_rule_uses_active_session_access_not_world_write(self):
        rule = format_udev_rule("048d", "600b")
        self.assertIn('TAG+="uaccess"', rule)
        self.assertNotIn("0666", rule)

    def test_logical_continuation_is_parsed_as_one_rule(self):
        text = (
            'SUBSYSTEM=="usb", ATTR{idVendor}=="048d", \\\n'
            '  ATTR{idProduct}=="600b", MODE:="0666"\n'
        )
        self.assertTrue(existing_rule_contains_device(text, "048d", "600b"))
        self.assertTrue(rule_grants_world_write(text, "048d", "600b"))
