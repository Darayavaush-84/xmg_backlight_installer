#!/usr/bin/env python3
"""Transactional installer for XMG Backlight Management 2.5.0-rc1."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

sys.dont_write_bytecode = True

from installer_lib.artifacts import (
    ArtifactValidationError,
    load_and_validate_manifest,
)
from installer_lib.ownership import (
    OwnershipError,
    assert_replaceable_directory,
    assert_replaceable_file,
    load_install_manifest,
    sha256_directory,
    sha256_file,
    verify_owned_directory,
    verify_owned_file,
)
from installer_lib.processes import is_managed_gui_process
from installer_lib.transaction import FilesystemTransaction
from installer_lib.udev import format_udev_rule, rule_grants_world_write
from installer_lib.versioning import is_newer_version

APP_NAME = "XMG Backlight Management"
APP_VERSION = "2.5.0-rc1"
GUI_DEPENDENCY = "PySide6==6.11.0"
MINIMUM_PYTHON = (3, 10)
GUI_CLOSE_TIMEOUT_SECONDS = 20.0

VENV_DIR = Path("/usr/local/lib/xmg-backlight-venv")
VENV_PYTHON = VENV_DIR / "bin" / "python"
SHARE_DIR = Path("/usr/share/xmg-backlight")
WRAPPER_PATH = Path("/usr/local/bin/xmg-backlight")
DRIVER_WRAPPER_PATH = Path("/usr/local/bin/ite8291r3-ctl")
DESKTOP_PATH = Path("/usr/share/applications/XMG-Backlight-Management.desktop")
UDEV_RULE_PATH = Path("/etc/udev/rules.d/70-xmg-backlight.rules")
LEGACY_UDEV_RULE_PATH = Path("/etc/udev/rules.d/99-ite8291.rules")
LEGACY_SYSTEM_AUTOSTART = Path(
    "/etc/xdg/autostart/xmg-backlight-restore.desktop"
)

LOG_DIR = Path("/var/log/xmg-backlight")
INSTALLER_LOG_PATH = LOG_DIR / "installer.log"
STATE_DIR = Path("/var/lib/xmg-backlight")
MANIFEST_PATH = STATE_DIR / "install-manifest.json"
LEGACY_STATE_PATH = STATE_DIR / "installer-state.json"

BASE_DIR = Path(__file__).resolve().parent
SOURCE_PACKAGE = BASE_DIR / "source" / "xmg_backlight"
VENDOR_MANIFEST_PATH = BASE_DIR / "vendor" / "manifest.json"
GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/"
    "Darayavaush-84/xmg_backlight_installer/releases/latest"
)

SUPPORTED_DEVICE_IDS = (
    ("048d", "6004"),
    ("048d", "6006"),
    ("048d", "600b"),
    ("048d", "ce00"),
)


class InstallerError(RuntimeError):
    pass


def ensure_state_directory() -> None:
    try:
        directory_info = STATE_DIR.lstat()
    except FileNotFoundError:
        STATE_DIR.mkdir(parents=True, mode=0o755)
        directory_info = STATE_DIR.lstat()
    if (
        not stat.S_ISDIR(directory_info.st_mode)
        or directory_info.st_uid != 0
        or directory_info.st_mode & 0o022
    ):
        raise InstallerError(f"Unsafe installer state directory: {STATE_DIR}")
    if MANIFEST_PATH.exists() or MANIFEST_PATH.is_symlink():
        manifest_info = MANIFEST_PATH.lstat()
        if (
            not stat.S_ISREG(manifest_info.st_mode)
            or manifest_info.st_uid != 0
            or manifest_info.st_mode & 0o022
        ):
            raise InstallerError(f"Unsafe install manifest: {MANIFEST_PATH}")


def ensure_log() -> None:
    try:
        directory_stat = LOG_DIR.lstat()
    except FileNotFoundError:
        LOG_DIR.mkdir(parents=True, mode=0o755)
        directory_stat = LOG_DIR.lstat()
    if (
        not stat.S_ISDIR(directory_stat.st_mode)
        or stat.S_ISLNK(directory_stat.st_mode)
        or directory_stat.st_uid != 0
        or directory_stat.st_mode & 0o022
    ):
        raise OSError(f"Unsafe installer log directory: {LOG_DIR}")
    os.chmod(LOG_DIR, 0o755)
    descriptor = os.open(
        INSTALLER_LOG_PATH,
        os.O_WRONLY
        | os.O_APPEND
        | os.O_CREAT
        | os.O_CLOEXEC
        | os.O_NOFOLLOW,
        0o644,
    )
    try:
        file_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_uid != 0
            or file_stat.st_mode & 0o022
        ):
            raise OSError(f"Unsafe installer log file: {INSTALLER_LOG_PATH}")
        os.fchmod(descriptor, 0o644)
    finally:
        os.close(descriptor)


def log(message: str) -> None:
    line = f"[installer] {message}"
    print(line)
    try:
        ensure_log()
        descriptor = os.open(
            INSTALLER_LOG_PATH,
            os.O_WRONLY | os.O_APPEND | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def run(
    command,
    *,
    check: bool = True,
    timeout: float = 600,
    env: dict | None = None,
):
    process = subprocess.run(
        [str(item) for item in command],
        text=True,
        capture_output=True,
        timeout=timeout,
        env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1", **(env or {})},
    )
    stdout = (process.stdout or "").strip()
    stderr = (process.stderr or "").strip()
    if stdout:
        log(stdout)
    if stderr:
        log(f"stderr: {stderr}")
    if check and process.returncode != 0:
        raise InstallerError(
            f"Command {' '.join(map(str, command))} failed "
            f"with exit code {process.returncode}"
        )
    return process.returncode, stdout, stderr


def require_supported_root_python() -> Path:
    if os.geteuid() != 0:
        raise InstallerError("Run this installer with root privileges (sudo).")
    if sys.version_info < MINIMUM_PYTHON:
        raise InstallerError("Python 3.10 or newer is required.")
    candidates = []
    base_candidate = Path(sys.base_prefix) / "bin" / "python3"
    candidates.append(base_candidate)
    candidates.extend((Path("/usr/bin/python3"), Path("/usr/local/bin/python3")))
    for candidate in candidates:
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        rc, output, _ = run(
            [
                candidate,
                "-c",
                "import sys; print(sys.version_info.major, sys.version_info.minor)",
            ],
            check=False,
            timeout=10,
        )
        if rc != 0:
            continue
        try:
            major, minor = map(int, output.split())
        except ValueError:
            continue
        if (major, minor) >= MINIMUM_PYTHON:
            return candidate
    raise InstallerError(
        "No supported system Python was found. Install Python 3.10+ and venv."
    )


def check_for_update() -> None:
    request = urllib.request.Request(
        GITHUB_LATEST_RELEASE_URL,
        headers={"User-Agent": "xmg-backlight-installer"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except Exception as exc:
        log(f"Update check unavailable: {exc}")
        return
    tag = str(payload.get("tag_name") or "")
    if tag and is_newer_version(tag, APP_VERSION):
        url = payload.get("html_url") or "the project release page"
        raise InstallerError(
            f"A newer release ({tag}) is available at {url}. "
            f"Use --skip-update-check only if you intentionally want {APP_VERSION}."
        )


def _read_proc_link(path: Path) -> str | None:
    try:
        return os.readlink(path)
    except OSError:
        return None


def _is_running_gui_pid(pid: int) -> bool:
    entry = Path("/proc") / str(pid)
    try:
        raw = (entry / "cmdline").read_bytes()
    except OSError:
        return False
    args = [
        item.decode("utf-8", "surrogateescape")
        for item in raw.split(b"\0")
        if item
    ]
    return is_managed_gui_process(
        args,
        executable=_read_proc_link(entry / "exe"),
        cwd=_read_proc_link(entry / "cwd"),
        venv_python=VENV_PYTHON,
        share_dir=SHARE_DIR,
    )


def find_running_gui_pids() -> list[int]:
    return sorted(
        int(entry.name)
        for entry in Path("/proc").iterdir()
        if entry.name.isdigit() and _is_running_gui_pid(int(entry.name))
    )


def _terminate_gui_batch(pids: list[int], *, deadline: float) -> None:
    pending: dict[int, int] = {}
    poller = select.poll()
    try:
        for pid in pids:
            try:
                pidfd = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            except OSError as exc:
                raise InstallerError(
                    f"Cannot safely close {APP_NAME} (PID: {pid}): {exc}"
                ) from exc
            if not _is_running_gui_pid(pid):
                os.close(pidfd)
                continue
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGTERM)
            except ProcessLookupError:
                os.close(pidfd)
                continue
            except OSError as exc:
                os.close(pidfd)
                raise InstallerError(
                    f"Cannot close {APP_NAME} (PID: {pid}): {exc}"
                ) from exc
            pending[pid] = pidfd
            poller.register(pidfd, select.POLLIN)

        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                joined = ", ".join(map(str, sorted(pending)))
                raise InstallerError(
                    f"{APP_NAME} did not close before the installer timeout "
                    f"(PID: {joined})."
                )
            try:
                events = poller.poll(max(1, int(remaining * 1000)))
            except InterruptedError:
                continue
            for pidfd, _event in events:
                poller.unregister(pidfd)
                pid = next(
                    current_pid
                    for current_pid, current_fd in pending.items()
                    if current_fd == pidfd
                )
                os.close(pending.pop(pid))
    finally:
        for pidfd in pending.values():
            os.close(pidfd)


def close_running_gui(*, timeout: float = GUI_CLOSE_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    closed_any = False
    while True:
        pids = find_running_gui_pids()
        if not pids:
            if closed_any:
                log(f"Closed running {APP_NAME} instance.")
            return
        log(
            f"Closing running {APP_NAME} instance "
            f"(PID: {', '.join(map(str, pids))})."
        )
        closed_any = True
        _terminate_gui_batch(pids, deadline=deadline)


def _legacy_wrapper(content: str) -> bool:
    return content == _gui_wrapper_contents()


def _legacy_driver_wrapper(content: str) -> bool:
    return content == _driver_wrapper_contents()


def _legacy_desktop(content: str) -> bool:
    return content == _desktop_contents()


def _legacy_venv(path: Path) -> bool:
    return (
        (path / "pyvenv.cfg").is_file()
        and (path / "bin" / "python").exists()
        and any(path.glob("lib/python*/site-packages/ite8291r3_ctl"))
        and any(path.glob("lib/python*/site-packages/PySide6"))
    )


def _legacy_share(path: Path) -> bool:
    package = path / "xmg_backlight"
    try:
        app_contents = (package / "app.py").read_text(encoding="utf-8")
        constants_contents = (package / "constants.py").read_text(
            encoding="utf-8"
        )
    except OSError:
        return False
    return (
        "class Main(" in app_contents
        and 'APP_DISPLAY_NAME = "XMG Backlight Management"' in constants_contents
    )


def _stage_text(directory: Path, name: str, contents: str) -> Path:
    path = directory / name
    path.write_text(contents, encoding="utf-8")
    return path


def _owner_marker(install_id: str) -> str:
    return json.dumps(
        {"schema": 1, "install_id": install_id, "app_version": APP_VERSION},
        sort_keys=True,
    ) + "\n"


def _relocate_staged_venv(stage: Path) -> None:
    """Rewrite text metadata generated with the temporary venv path."""
    old_prefix = str(stage).encode("utf-8")
    new_prefix = str(VENV_DIR).encode("utf-8")
    candidates = [stage / "pyvenv.cfg"]
    candidates.extend((stage / "bin").iterdir())
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            continue
        contents = path.read_bytes()
        if b"\0" in contents or old_prefix not in contents:
            continue
        mode = path.stat().st_mode
        path.write_bytes(contents.replace(old_prefix, new_prefix))
        os.chmod(path, mode)


def _create_staged_venv(system_python: Path, install_id: str, artifacts):
    VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=".xmg-backlight-venv-stage-", dir=VENV_DIR.parent)
    )
    try:
        run([system_python, "-m", "venv", stage])
        python = stage / "bin" / "python"
        artifact_paths = [item.path for item in artifacts.artifacts]
        run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--no-compile",
                *artifact_paths,
            ]
        )
        run([python, "-m", "pip", "install", "--no-compile", GUI_DEPENDENCY])
        _relocate_staged_venv(stage)
        validation = (
            "import importlib.metadata as m; "
            "import ite8291r3_ctl.ite8291r3 as d; import PySide6; "
            f"assert m.version('ite8291r3-ctl') == '{artifacts.driver_version}'; "
            "assert 0x600B in d.PRODUCT_IDS; "
            "print(m.version('ite8291r3-ctl'), PySide6.__version__)"
        )
        run(
            [python, "-c", validation],
            timeout=30,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
        )
        (stage / ".xmg-backlight-owner.json").write_text(
            _owner_marker(install_id), encoding="utf-8"
        )
        stage.chmod(0o755)
        return stage
    except Exception:
        shutil.rmtree(stage)
        raise


def _create_staged_share(stage_python: Path, install_id: str) -> Path:
    if not SOURCE_PACKAGE.is_dir():
        raise InstallerError(f"Application source not found at {SOURCE_PACKAGE}")
    SHARE_DIR.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=".xmg-backlight-share-stage-", dir=SHARE_DIR.parent)
    )
    try:
        shutil.copytree(
            SOURCE_PACKAGE,
            stage / "xmg_backlight",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        (stage / ".xmg-backlight-owner.json").write_text(
            _owner_marker(install_id), encoding="utf-8"
        )
        run(
            [
                stage_python,
                "-c",
                (
                    "import xmg_backlight.app, xmg_backlight.automation_daemon, "
                    "xmg_backlight.restore_profile; "
                    "print('application imports valid')"
                ),
            ],
            env={
                "PYTHONPATH": str(stage),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            timeout=30,
        )
        stage.chmod(0o755)
        return stage
    except Exception:
        shutil.rmtree(stage)
        raise


def _driver_wrapper_contents() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'exec {VENV_PYTHON} -m ite8291r3_ctl "$@"\n'
    )


def _gui_wrapper_contents() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"cd {SHARE_DIR}\n"
        f'exec {VENV_PYTHON} -m xmg_backlight.app "$@"\n'
    )


def _desktop_contents() -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Manage the XMG keyboard backlight\n"
        f"Exec={WRAPPER_PATH}\n"
        f"TryExec={WRAPPER_PATH}\n"
        "Icon=preferences-desktop-keyboard\n"
        "Terminal=false\n"
        "Categories=Settings;Utility;\n"
    )


def _udev_contents() -> str:
    lines = [
        "# Managed by XMG Backlight; grant the active local session access",
        *(
            format_udev_rule(vendor, product)
            for vendor, product in SUPPORTED_DEVICE_IDS
        ),
    ]
    return "\n".join(lines) + "\n"


def _legacy_system_autostart(content: str) -> bool:
    return (
        "Name=XMG Backlight Restore" in content
        and "xmg_backlight.restore_profile" in content
    )


def _legacy_state(content: str) -> bool:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(data, dict)
        and data.get("venv_dir") == str(VENV_DIR)
        and "installer_version" in data
    )


def _has_trusted_legacy_state() -> bool:
    if not LEGACY_STATE_PATH.is_file() or LEGACY_STATE_PATH.is_symlink():
        return False
    try:
        return _legacy_state(LEGACY_STATE_PATH.read_text(encoding="utf-8"))
    except OSError:
        return False


def _prepare_legacy_udev_cleanup(staging: Path):
    if not LEGACY_UDEV_RULE_PATH.is_file() or LEGACY_UDEV_RULE_PATH.is_symlink():
        return None
    content = LEGACY_UDEV_RULE_PATH.read_text(encoding="utf-8", errors="strict")
    marker = "# Allow non-root access to ITE 8291 keyboards"
    if marker not in content:
        return None
    cleaned = []
    for line in content.splitlines():
        if line.strip() == marker:
            continue
        if (
            'MODE:="0666"' in line
            and 'ATTRS{idVendor}=="048d"' in line
            and any(
                f'ATTRS{{idProduct}}=="{product}"' in line
                for _, product in SUPPORTED_DEVICE_IDS
            )
        ):
            continue
        cleaned.append(line)
    cleaned_text = "\n".join(cleaned).strip()
    if not cleaned_text:
        return ("remove", None)
    return ("replace", _stage_text(staging, "legacy-udev-cleaned", cleaned_text + "\n"))


def _preflight_legacy_udev(*, adopting_legacy: bool) -> None:
    if not LEGACY_UDEV_RULE_PATH.exists() and not LEGACY_UDEV_RULE_PATH.is_symlink():
        return
    if LEGACY_UDEV_RULE_PATH.is_symlink() or not LEGACY_UDEV_RULE_PATH.is_file():
        raise InstallerError(f"Unsafe legacy udev rule path: {LEGACY_UDEV_RULE_PATH}")
    content = LEGACY_UDEV_RULE_PATH.read_text(encoding="utf-8", errors="strict")
    unsafe = any(
        rule_grants_world_write(content, vendor, product)
        for vendor, product in SUPPORTED_DEVICE_IDS
    )
    managed_marker = "# Allow non-root access to ITE 8291 keyboards" in content
    if unsafe and not (adopting_legacy and managed_marker):
        raise InstallerError(
            f"Refusing to leave an unowned world-writable udev rule at "
            f"{LEGACY_UDEV_RULE_PATH}. Remove or secure that rule first."
        )


def install(*, skip_update_check: bool) -> None:
    system_python = require_supported_root_python()
    if not skip_update_check:
        check_for_update()
    ensure_state_directory()
    try:
        artifacts = load_and_validate_manifest(VENDOR_MANIFEST_PATH)
        previous_manifest = load_install_manifest(MANIFEST_PATH)
    except (ArtifactValidationError, OwnershipError) as exc:
        raise InstallerError(str(exc)) from exc

    install_id = previous_manifest.get("install_id") or str(uuid.uuid4())
    adopting_legacy = not previous_manifest and _has_trusted_legacy_state()
    _preflight_legacy_udev(adopting_legacy=adopting_legacy)
    assert_replaceable_directory(
        VENV_DIR,
        previous_manifest,
        legacy_validator=_legacy_venv if adopting_legacy else None,
    )
    assert_replaceable_directory(
        SHARE_DIR,
        previous_manifest,
        legacy_validator=_legacy_share if adopting_legacy else None,
    )
    validators = {
        WRAPPER_PATH: _legacy_wrapper,
        DRIVER_WRAPPER_PATH: _legacy_driver_wrapper,
        DESKTOP_PATH: _legacy_desktop,
    }
    for path, validator in validators.items():
        assert_replaceable_file(
            path,
            previous_manifest,
            legacy_validator=validator if adopting_legacy else None,
        )
    assert_replaceable_file(UDEV_RULE_PATH, previous_manifest)
    if LEGACY_SYSTEM_AUTOSTART.exists() or LEGACY_SYSTEM_AUTOSTART.is_symlink():
        assert_replaceable_file(
            LEGACY_SYSTEM_AUTOSTART,
            {},
            legacy_validator=(
                _legacy_system_autostart if adopting_legacy else None
            ),
        )

    stage_venv = None
    stage_share = None
    file_stage = None
    try:
        stage_venv = _create_staged_venv(system_python, install_id, artifacts)
        stage_share = _create_staged_share(
            stage_venv / "bin" / "python", install_id
        )
        rc, devices, _ = run(
            [
                stage_venv / "bin" / "python",
                "-m",
                "ite8291r3_ctl",
                "query",
                "--devices",
            ],
            check=False,
            timeout=30,
        )
        if rc == 0 and devices:
            log(f"Detected supported device(s):\n{devices}")
        else:
            log("No supported keyboard is currently connected; installation continues.")

        file_stage = Path(tempfile.mkdtemp(prefix=".files-stage-", dir=STATE_DIR))
        staged_files = {
            WRAPPER_PATH: (
                _stage_text(file_stage, "xmg-backlight", _gui_wrapper_contents()),
                0o755,
            ),
            DRIVER_WRAPPER_PATH: (
                _stage_text(
                    file_stage, "ite8291r3-ctl", _driver_wrapper_contents()
                ),
                0o755,
            ),
            DESKTOP_PATH: (
                _stage_text(file_stage, "desktop", _desktop_contents()),
                0o644,
            ),
            UDEV_RULE_PATH: (
                _stage_text(file_stage, "udev", _udev_contents()),
                0o644,
            ),
        }
        file_hashes = {
            str(target): sha256_file(staged)
            for target, (staged, _mode) in staged_files.items()
        }
        manifest_payload = {
            "schema": 1,
            "install_id": install_id,
            "app_version": APP_VERSION,
            "driver_version": artifacts.driver_version,
            "venv_python": str(VENV_PYTHON),
            "directories": [str(VENV_DIR), str(SHARE_DIR)],
            "directory_hashes": {
                str(VENV_DIR): sha256_directory(stage_venv),
                str(SHARE_DIR): sha256_directory(stage_share),
            },
            "files": file_hashes,
            "installed_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            ),
        }
        staged_manifest = _stage_text(
            file_stage,
            "install-manifest.json",
            json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        )
        legacy_udev_action = (
            _prepare_legacy_udev_cleanup(file_stage)
            if adopting_legacy
            else None
        )

        udev_available = bool(shutil.which("udevadm"))
        close_running_gui()
        try:
            with FilesystemTransaction(STATE_DIR) as transaction:
                transaction.replace_directory(stage_venv, VENV_DIR)
                stage_venv = None
                transaction.replace_directory(stage_share, SHARE_DIR)
                stage_share = None
                for target, (staged, mode) in staged_files.items():
                    transaction.replace_file(staged, target, mode=mode)
                if LEGACY_SYSTEM_AUTOSTART.exists():
                    transaction.remove_file(LEGACY_SYSTEM_AUTOSTART)
                if LEGACY_STATE_PATH.exists():
                    if adopting_legacy:
                        transaction.remove_file(LEGACY_STATE_PATH)
                if legacy_udev_action:
                    action, staged = legacy_udev_action
                    if action == "remove":
                        transaction.remove_file(LEGACY_UDEV_RULE_PATH)
                    else:
                        transaction.replace_file(
                            staged, LEGACY_UDEV_RULE_PATH, mode=0o644
                        )
                transaction.replace_file(
                    staged_manifest, MANIFEST_PATH, mode=0o600
                )
                run(
                    [
                        VENV_PYTHON,
                        "-c",
                        (
                            "import ite8291r3_ctl, PySide6, xmg_backlight.app; "
                            "print('committed environment valid')"
                        ),
                    ],
                    env={
                        "PYTHONPATH": str(SHARE_DIR),
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                    timeout=30,
                )
                if udev_available:
                    run(["udevadm", "control", "--reload"], timeout=30)
                    run(["udevadm", "trigger"], timeout=60)
        except Exception:
            # The filesystem transaction has restored the previous rule files;
            # reload them so the kernel view matches the rolled-back filesystem.
            if udev_available:
                run(
                    ["udevadm", "control", "--reload"],
                    check=False,
                    timeout=30,
                )
                run(["udevadm", "trigger"], check=False, timeout=60)
            raise
        log(
            f"Installation completed: app {APP_VERSION}, bundled driver "
            f"{artifacts.driver_version}, dedicated venv {VENV_DIR}."
        )
    finally:
        for path in (stage_venv, stage_share, file_stage):
            if path and path.exists():
                shutil.rmtree(path)


def _safe_user_directory(path: Path, uid: int) -> bool:
    try:
        stat_result = path.lstat()
    except FileNotFoundError:
        return False
    return (
        path.is_dir()
        and not path.is_symlink()
        and stat_result.st_uid == uid
    )


def _select_user_entries(*, purge_data: bool, all_users: bool):
    sudo_user = os.environ.get("SUDO_USER")
    selected = []
    for entry in pwd.getpwall():
        if entry.pw_uid < 1000:
            continue
        if not all_users and entry.pw_name != sudo_user:
            continue
        selected.append(entry)
    if purge_data and not selected:
        raise InstallerError(
            "Cannot identify the invoking desktop user. "
            "Use sudo from that account or pass --all-users explicitly."
        )
    return selected


def _remove_user_integrations(*, selected, purge_data: bool) -> None:
    service_names = (
        "keyboard-backlight-automation.service",
        "keyboard-backlight-resume.service",
        "keyboard-backlight-power-monitor.service",
    )
    for entry in selected:
        home = Path(entry.pw_dir)
        systemd_dir = home / ".config" / "systemd" / "user"
        if _safe_user_directory(systemd_dir, entry.pw_uid):
            for name in service_names:
                path = systemd_dir / name
                if path.is_file() and not path.is_symlink():
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    if "xmg_backlight." in content:
                        path.unlink()
            for target_name in (
                "default.target.wants",
                "sleep.target.wants",
                "suspend.target.wants",
                "hibernate.target.wants",
                "hybrid-sleep.target.wants",
            ):
                target_dir = systemd_dir / target_name
                if not _safe_user_directory(target_dir, entry.pw_uid):
                    continue
                for name in service_names:
                    link = target_dir / name
                    if link.is_symlink():
                        raw_target = Path(os.readlink(link))
                        if not raw_target.is_absolute():
                            raw_target = link.parent / raw_target
                        expected = systemd_dir / name
                        if os.path.normpath(raw_target) == os.path.normpath(expected):
                            link.unlink()
        autostart_dir = home / ".config" / "autostart"
        if _safe_user_directory(autostart_dir, entry.pw_uid):
            path = autostart_dir / "keyboard-backlight-restore.desktop"
            if path.is_file() and not path.is_symlink():
                content = path.read_text(encoding="utf-8", errors="ignore")
                if "xmg_backlight.app" in content:
                    path.unlink()
        if purge_data:
            config = home / ".config" / "backlight-linux"
            if _safe_user_directory(config, entry.pw_uid):
                shutil.rmtree(config)


def _preflight_uninstall(
    manifest: dict, *, purge: bool
) -> tuple[list[Path], list[Path]]:
    allowed_files = {
        WRAPPER_PATH,
        DRIVER_WRAPPER_PATH,
        DESKTOP_PATH,
        UDEV_RULE_PATH,
    }
    allowed_directories = {VENV_DIR, SHARE_DIR}
    manifest_files = {Path(raw_path) for raw_path in manifest.get("files", {})}
    manifest_directories = {
        Path(raw_path) for raw_path in manifest.get("directories", [])
    }
    unexpected = (manifest_files - allowed_files) | (
        manifest_directories - allowed_directories
    )
    if unexpected:
        raise InstallerError(
            "Install manifest contains unexpected paths: "
            + ", ".join(sorted(map(str, unexpected)))
        )

    removable_files = []
    for path in sorted(manifest_files, key=str):
        if not path.exists() and not path.is_symlink():
            continue
        if not verify_owned_file(path, manifest):
            raise InstallerError(f"Refused modified or unowned file: {path}")
        removable_files.append(path)

    removable_directories = []
    inspected_directories = {SHARE_DIR, VENV_DIR}
    for path in sorted(inspected_directories, key=str):
        if not path.exists() and not path.is_symlink():
            continue
        if (
            path not in manifest_directories
            or not verify_owned_directory(path, manifest)
        ):
            raise InstallerError(f"Refused modified or unowned directory: {path}")
        if path == SHARE_DIR or purge:
            removable_directories.append(path)
    return removable_files, removable_directories


def uninstall(*, purge: bool, purge_user_data: bool, all_users: bool) -> None:
    require_supported_root_python()
    ensure_state_directory()
    try:
        manifest = load_install_manifest(MANIFEST_PATH)
    except OwnershipError as exc:
        raise InstallerError(str(exc)) from exc
    if not manifest:
        raise InstallerError(
            f"No compatible ownership manifest exists. Install {APP_VERSION} "
            "first so the legacy installation can be adopted safely."
        )
    removable_files, removable_directories = _preflight_uninstall(
        manifest, purge=purge
    )
    selected_users = _select_user_entries(
        purge_data=purge_user_data,
        all_users=all_users,
    )
    remaining_directories = []
    if not purge and VENV_DIR.exists():
        remaining_directories = [str(VENV_DIR)]

    retained_stage_dir = None
    retained_manifest_stage = None
    if remaining_directories:
        remaining = dict(manifest)
        remaining["directories"] = remaining_directories
        remaining["directory_hashes"] = {
            str(VENV_DIR): manifest["directory_hashes"][str(VENV_DIR)]
        }
        remaining["files"] = {}
        retained_stage_dir = Path(
            tempfile.mkdtemp(prefix=".uninstall-stage-", dir=STATE_DIR)
        )
        retained_manifest_stage = _stage_text(
            retained_stage_dir,
            "install-manifest.json",
            json.dumps(remaining, indent=2, sort_keys=True) + "\n",
        )

    removed_paths = [*removable_files, *removable_directories]
    try:
        close_running_gui()
        with FilesystemTransaction(STATE_DIR) as transaction:
            for path in removable_files:
                transaction.remove_file(path)
            for path in removable_directories:
                transaction.remove_directory(path)
            if retained_manifest_stage is not None:
                transaction.replace_file(
                    retained_manifest_stage, MANIFEST_PATH, mode=0o600
                )
            else:
                transaction.remove_file(MANIFEST_PATH)
    finally:
        if retained_stage_dir and retained_stage_dir.exists():
            shutil.rmtree(retained_stage_dir)

    for path in removed_paths:
        log(f"Removed {path}")
    _remove_user_integrations(
        selected=selected_users,
        purge_data=purge_user_data,
    )
    if shutil.which("udevadm"):
        run(["udevadm", "control", "--reload"], check=False, timeout=30)
        run(["udevadm", "trigger"], check=False, timeout=60)

    if remaining_directories:
        log(f"Dedicated venv retained at {VENV_DIR}")
    log("Uninstallation completed.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Install or uninstall XMG Backlight Management."
    )
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument(
        "--purge",
        action="store_true",
        help="With --uninstall, also remove the dedicated application venv.",
    )
    parser.add_argument(
        "--purge-user-data",
        action="store_true",
        help="With --uninstall, remove profile data for the invoking user.",
    )
    parser.add_argument(
        "--all-users",
        action="store_true",
        help="With --purge-user-data, explicitly include all desktop users.",
    )
    parser.add_argument("--skip-update-check", action="store_true")
    args = parser.parse_args(argv)
    if (args.purge or args.purge_user_data or args.all_users) and not args.uninstall:
        parser.error("--purge, --purge-user-data and --all-users require --uninstall")
    if args.all_users and not args.purge_user_data:
        parser.error("--all-users requires --purge-user-data")
    if args.uninstall and args.skip_update_check:
        parser.error("--skip-update-check is valid only during installation")
    return args


def main() -> None:
    args = parse_args()
    if args.uninstall:
        uninstall(
            purge=args.purge,
            purge_user_data=args.purge_user_data,
            all_users=args.all_users,
        )
    else:
        install(skip_update_check=args.skip_update_check)


if __name__ == "__main__":
    try:
        main()
    except (InstallerError, OwnershipError, ArtifactValidationError) as exc:
        log(f"ERROR: {exc}")
        raise SystemExit(1)
    except subprocess.TimeoutExpired as exc:
        log(f"ERROR: command timed out: {exc.cmd}")
        raise SystemExit(1)
