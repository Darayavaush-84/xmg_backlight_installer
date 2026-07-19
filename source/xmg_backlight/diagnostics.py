"""Atomic, explicit diagnostic archive creation."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import tempfile
import zipfile
from datetime import datetime

from .constants import (
    APP_VERSION,
    AUTOMATION_SERVICE_NAME,
    CONFIG_DIR,
    INSTALLER_LOG_PATH,
)
from .driver import resolve_tool


def _capture(command: list[str], timeout: float = 10.0) -> tuple[str | None, str | None]:
    try:
        process = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    output = (process.stdout or "").strip()
    error = (process.stderr or "").strip()
    if process.returncode != 0:
        return output or None, error or f"exit code {process.returncode}"
    return output, None


def create_diagnostics_archive(
    destination: str,
    *,
    activity_lines=(),
    config_dir: str = CONFIG_DIR,
    installer_log_path: str = INSTALLER_LOG_PATH,
) -> dict:
    destination = os.path.abspath(destination)
    parent = os.path.dirname(destination)
    os.makedirs(parent, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(destination)}.", suffix=".tmp", dir=parent
    )
    os.close(descriptor)
    included: list[str] = []
    errors: list[str] = []
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            if os.path.isfile(installer_log_path):
                try:
                    archive.write(installer_log_path, "installer.log")
                    included.append("installer.log")
                except OSError as exc:
                    errors.append(f"installer.log: {exc}")

            journal, journal_error = _capture(
                [
                    "journalctl",
                    "--user",
                    "-u",
                    AUTOMATION_SERVICE_NAME,
                    "--since",
                    "24 hours ago",
                    "--no-pager",
                ]
            )
            if journal:
                archive.writestr("automation-service.log", journal + "\n")
                included.append("automation-service.log")
            if journal_error:
                errors.append(f"automation-service.log: {journal_error}")

            for filename in ("state.json",):
                source = os.path.join(config_dir, filename)
                if os.path.isfile(source):
                    try:
                        archive.write(source, f"config/{filename}")
                        included.append(f"config/{filename}")
                    except OSError as exc:
                        errors.append(f"config/{filename}: {exc}")

            lines = list(activity_lines)
            if lines:
                archive.writestr("activity-log.txt", "\n".join(lines) + "\n")
                included.append("activity-log.txt")

            system_info = [
                f"Export date: {datetime.now().isoformat()}",
                f"App version: {APP_VERSION}",
                f"System: {platform.platform()}",
            ]
            tool = resolve_tool()
            if tool:
                version, version_error = _capture([tool, "--version"], timeout=5)
                if version:
                    system_info.append(f"Driver: {version}")
                if version_error:
                    errors.append(f"driver version: {version_error}")
            else:
                errors.append("driver version: bundled CLI not found")
            archive.writestr("system-info.txt", "\n".join(system_info) + "\n")
            included.append("system-info.txt")
            archive.writestr(
                "collection-report.json",
                json.dumps({"included": included, "errors": errors}, indent=2) + "\n",
            )
        os.chmod(temporary, 0o600)
        descriptor = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, destination)
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return {"included": included, "errors": errors}
