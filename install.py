#!/usr/bin/env python3
"""XMG Backlight Management installer (tested on Fedora).

This script installs the ite8291r3-ctl CLI via pip, deploys the GUI
("XMG Backlight Management") system-wide and registers a desktop entry
visible to all users. Run it on a Fedora system (where it has been tested)
with sudo/root privileges.
"""

from __future__ import annotations

import argparse
import filecmp
import importlib.util
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Iterable, Tuple

APP_NAME = "XMG Backlight Management"
DRIVER_PACKAGE = "ite8291r3-ctl"
GUI_DEPENDENCY = "PySide6"
GUI_SCRIPT_NAME = "keyboard_backlight.py"
GUI_CLOSE_TIMEOUT_SEC = 4.0
PYTHON_EXECUTABLE = sys.executable or "/usr/bin/python3"
SHARE_DIR = Path("/usr/share/xmg-backlight")
WRAPPER_PATH = Path("/usr/local/bin/xmg-backlight")
DESKTOP_PATH = Path("/usr/share/applications/XMG-Backlight-Management.desktop")
AUTOSTART_PATH = Path("/etc/xdg/autostart/xmg-backlight-restore.desktop")
SYSTEM_SLEEP_HOOK_PATH = Path("/etc/systemd/system-sleep/xmg-backlight-restore")
RESUME_HELPER_PATH = Path("/usr/local/lib/xmg-backlight-resume-hook.sh")
SYSTEMD_SERVICE_DROPINS = [
    ("systemd-suspend.service", "suspend"),
    ("systemd-hibernate.service", "hibernate"),
    ("systemd-hybrid-sleep.service", "hybrid-sleep"),
    ("systemd-suspend-then-hibernate.service", "suspend-then-hibernate"),
]
DROPIN_FILENAME = "xmg-backlight-restore.conf"
FEDORA_NOTICE = (
    "This installer has been tested on Fedora. Other distributions have not "
    "been validated and may require manual adjustments."
)
GITHUB_REPO = "Darayavaush-84/xmg_backlight_installer"
GITHUB_LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
UPDATE_CHECK_TIMEOUT_SEC = 10
UPDATE_SKIP_ENV = "XMG_BACKLIGHT_SKIP_UPDATE"
LOG_DIR = Path("/var/log/xmg-backlight")
LOG_FILE_PATH = LOG_DIR / "restore.log"
INSTALLER_LOG_PATH = LOG_DIR / "installer.log"
UDEV_RULE_PATH = Path("/etc/udev/rules.d/99-ite8291.rules")

BASE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = (BASE_DIR / "source").resolve()
FILES_TO_DEPLOY = [
    "keyboard_backlight.py",
    "restore_profile.py",
    "power_state_monitor.py",
]
DIRS_TO_DEPLOY: list[str] = ["translations"]
DRIVER_INSTALLED_THIS_RUN = False
_INSTALLER_LOG_READY = False


class InstallerError(RuntimeError):
    """Raised when installation fails."""


def log(msg: str) -> None:
    line = f"[installer] {msg}"
    print(line)
    append_installer_log(line)


def ensure_installer_log_path() -> bool:
    global _INSTALLER_LOG_READY
    if _INSTALLER_LOG_READY:
        return True
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(LOG_DIR, 0o755)
        if not INSTALLER_LOG_PATH.exists():
            INSTALLER_LOG_PATH.touch()
        os.chmod(INSTALLER_LOG_PATH, 0o644)
    except OSError:
        return False
    _INSTALLER_LOG_READY = True
    return True


def append_installer_log(line: str) -> None:
    if not ensure_installer_log_path():
        return
    try:
        with open(INSTALLER_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line)
            if not line.endswith("\n"):
                handle.write("\n")
    except OSError:
        pass


def require_root() -> None:
    if os.geteuid() != 0:
        raise InstallerError("This installer must be executed with root privileges (sudo).")


def run(cmd: Iterable[str], check: bool = True) -> Tuple[int, str, str]:
    proc = subprocess.run(
        list(cmd),
        text=True,
        capture_output=True,
        env=dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1"),
    )
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if stdout:
        log(stdout)
    if stderr:
        log(f"stderr: {stderr}")
    if check and proc.returncode != 0:
        raise InstallerError(f"Command {' '.join(cmd)} failed with exit code {proc.returncode}")
    return proc.returncode, stdout, stderr


def read_local_app_version() -> str | None:
    version_path = SOURCE_DIR / GUI_SCRIPT_NAME
    try:
        content = version_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in content.splitlines():
        if "APP_VERSION" not in line:
            continue
        match = re.search(r"APP_VERSION\s*=\s*[\"']([^\"']+)[\"']", line)
        if match:
            return match.group(1).strip()
    return None


def parse_version(value: str) -> tuple[int, ...]:
    if not value:
        return tuple()
    trimmed = value.strip()
    if trimmed.lower().startswith("v"):
        trimmed = trimmed[1:]
    trimmed = trimmed.split("+", 1)[0].split("-", 1)[0]
    parts = []
    for part in trimmed.split("."):
        match = re.match(r"([0-9]+)", part)
        if match:
            parts.append(int(match.group(1)))
    return tuple(parts)


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_parts = parse_version(candidate)
    current_parts = parse_version(current)
    if not candidate_parts or not current_parts:
        return False
    max_len = max(len(candidate_parts), len(current_parts))
    candidate_parts += (0,) * (max_len - len(candidate_parts))
    current_parts += (0,) * (max_len - len(current_parts))
    return candidate_parts > current_parts


def fetch_latest_release() -> tuple[str, str, str]:
    request = urllib.request.Request(
        GITHUB_LATEST_RELEASE_URL,
        headers={"User-Agent": "xmg-backlight-installer"},
    )
    with urllib.request.urlopen(request, timeout=UPDATE_CHECK_TIMEOUT_SEC) as response:
        payload = json.load(response)
    tag = str(payload.get("tag_name") or "").strip()
    tar_url = str(payload.get("tarball_url") or "").strip()
    html_url = str(payload.get("html_url") or "").strip()
    return tag, tar_url, html_url


def safe_extract_tar(archive_path: Path, dest_dir: Path) -> None:
    dest_root = dest_dir.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            member_path = (dest_root / member.name).resolve()
            if not str(member_path).startswith(str(dest_root) + os.sep):
                raise InstallerError("Unsafe path detected in release archive.")
        archive.extractall(dest_root)


def find_release_root(dest_dir: Path) -> Path:
    for entry in dest_dir.iterdir():
        if entry.is_dir() and (entry / "install.py").is_file():
            return entry
    raise InstallerError("Downloaded release archive did not contain install.py.")


def check_for_update_and_handoff(original_args: list[str]) -> None:
    if os.environ.get(UPDATE_SKIP_ENV):
        log(f"Update check skipped ({UPDATE_SKIP_ENV}=1).")
        return
    current_version = read_local_app_version()
    if not current_version:
        log("Update check skipped: unable to read local version.")
        return
    log(f"Checking for updates (current {current_version})...")
    try:
        tag, tar_url, html_url = fetch_latest_release()
    except Exception as exc:
        log(f"Update check skipped: {exc}")
        return
    if not tag or not tar_url:
        log("Update check skipped: latest release metadata incomplete.")
        return
    if not is_newer_version(tag, current_version):
        log(f"Installer is up to date (version {current_version}).")
        return
    log(f"A newer release is available: {tag} (current {current_version}).")
    if html_url:
        log(f"Release page: {html_url}")
    answer = input("Download and run the updated installer now? [Y/n]: ").strip().lower()
    if answer not in ("", "y", "yes"):
        log("Continuing with the current installer.")
        return
    try:
        with tempfile.TemporaryDirectory(prefix="xmg-backlight-install-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            archive_path = tmp_path / "release.tar.gz"
            log("Downloading updated installer from GitHub...")
            request = urllib.request.Request(
                tar_url,
                headers={"User-Agent": "xmg-backlight-installer"},
            )
            with urllib.request.urlopen(request, timeout=UPDATE_CHECK_TIMEOUT_SEC) as response:
                with open(archive_path, "wb") as handle:
                    shutil.copyfileobj(response, handle)
            safe_extract_tar(archive_path, tmp_path)
            release_root = find_release_root(tmp_path)
            installer_path = release_root / "install.py"
            log(f"Starting updated installer from {installer_path}")
            env = dict(os.environ)
            env[UPDATE_SKIP_ENV] = "1"
            cmd = [PYTHON_EXECUTABLE, str(installer_path), "--skip-update-check", *original_args]
            rc = subprocess.call(cmd, env=env)
            if rc != 0:
                raise InstallerError(f"Updated installer exited with status {rc}.")
            sys.exit(0)
    except InstallerError as exc:
        log(f"Update failed: {exc}. Continuing with the current installer.")


def iter_process_args() -> Iterable[Tuple[int, list[str]]]:
    proc_dir = Path("/proc")
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            data = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if not data:
            continue
        parts = [part.decode("utf-8", "ignore") for part in data.split(b"\0") if part]
        if not parts:
            continue
        yield int(entry.name), parts


def find_gui_pids() -> list[int]:
    pids: list[int] = []
    for pid, args in iter_process_args():
        if any(Path(arg).name == GUI_SCRIPT_NAME for arg in args):
            pids.append(pid)
    return pids


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_running_gui_processes() -> None:
    log("Checking for running GUI instance(s)...")
    pids = find_gui_pids()
    if not pids:
        log("No running GUI instances detected.")
        return
    pid_list = ", ".join(str(pid) for pid in pids)
    log(
        "Detected running GUI instance(s) "
        f"({pid_list}). Closing them to continue."
    )
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            log(f"Failed to stop GUI process {pid}: {exc}")
    deadline = time.monotonic() + GUI_CLOSE_TIMEOUT_SEC
    remaining = []
    while time.monotonic() < deadline:
        remaining = [pid for pid in pids if is_pid_alive(pid)]
        if not remaining:
            break
        time.sleep(0.2)
    if remaining:
        pid_list = ", ".join(str(pid) for pid in remaining)
        log(f"GUI still running ({pid_list}); sending SIGKILL.")
        for pid in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue
            except PermissionError as exc:
                log(f"Failed to kill GUI process {pid}: {exc}")
        time.sleep(0.2)
        remaining = [pid for pid in remaining if is_pid_alive(pid)]
    if remaining:
        pid_list = ", ".join(str(pid) for pid in remaining)
        log(f"GUI still running ({pid_list}); continuing anyway.")
    else:
        log("GUI processes stopped.")


def pip_show(package: str) -> bool:
    rc, _, _ = run([sys.executable, "-m", "pip", "show", package], check=False)
    return rc == 0


def pip_version(package: str) -> str | None:
    rc, stdout, _ = run([sys.executable, "-m", "pip", "show", package], check=False)
    if rc != 0:
        return None
    for line in stdout.splitlines():
        if line.lower().startswith("version:"):
            return line.split(":", 1)[1].strip() or None
    return None


def describe_component(component: str, state: str, action: str) -> None:
    message = f"{component}: {state}"
    if action:
        message += f" | Action: {action}"
    log(message)


def install_pip_package(package: str) -> bool:
    log(f"Installing pip package: {package}")
    rc, _, _ = run([sys.executable, "-m", "pip", "install", package], check=False)
    if rc != 0:
        raise InstallerError(f"Failed to install pip package {package} (exit code {rc}).")
    return True


def detect_driver() -> None:
    driver_in_path = shutil.which("ite8291r3-ctl") is not None
    version = pip_version(DRIVER_PACKAGE)
    if version:
        describe_component(
            "Driver (ite8291r3-ctl)",
            f"installed via pip (version {version})",
            "skipping install",
        )
        return
    if driver_in_path:
        describe_component(
            "Driver (ite8291r3-ctl)",
            "binary found in PATH but package version unknown",
            "skipping install",
        )
        return
    describe_component(
        "Driver (ite8291r3-ctl)",
        "not detected",
        "pip install will install it now",
    )
    if install_pip_package(DRIVER_PACKAGE):
        global DRIVER_INSTALLED_THIS_RUN
        DRIVER_INSTALLED_THIS_RUN = True


def extract_device_ids(lines: list[str]) -> list[tuple[str, str]]:
    ids: list[tuple[str, str]] = []
    for line in lines:
        match = re.search(
            r"product\s+([0-9a-fA-F]{4}).*manufacturer\s+([0-9a-fA-F]{4})",
            line,
        )
        if not match:
            continue
        product = match.group(1).lower().zfill(4)
        vendor = match.group(2).lower().zfill(4)
        ids.append((vendor, product))
    deduped = list(dict.fromkeys(ids))
    return deduped


def probe_keyboard_hardware() -> list[tuple[str, str]]:
    cli_path = shutil.which("ite8291r3-ctl")
    if not cli_path:
        log("Hardware probe skipped: ite8291r3-ctl binary not found in PATH.")
        return []
    log("Checking for compatible keyboards...")
    rc, stdout, stderr = run([cli_path, "query", "--devices"], check=False)
    if rc != 0:
        log(
            "Warning: unable to query devices (ite8291r3-ctl exited with a non-zero status). "
            "Continuing installation."
        )
        if stderr:
            log(f"ite8291r3-ctl stderr: {stderr}")
        return []
    devices = [line.strip() for line in stdout.splitlines() if line.strip()]
    device_ids = extract_device_ids(devices)
    if devices:
        log(f"Detected {len(devices)} compatible keyboard device(s).")
        return device_ids
    answer = input(
        "No supported keyboard was detected. Continue installation anyway? [y/N]: "
    ).strip()
    if answer.lower() not in ("y", "yes"):
        if DRIVER_INSTALLED_THIS_RUN:
            log("Removing ite8291r3-ctl because installation was aborted.")
            run([sys.executable, "-m", "pip", "uninstall", "-y", DRIVER_PACKAGE], check=False)
        raise InstallerError("Installation aborted: no compatible keyboard detected.")
    log("User opted to continue without a detected keyboard.")
    return []


def ensure_udev_rule(device_ids: list[tuple[str, str]]) -> None:
    if not device_ids:
        log("Skipping udev rule setup: no device IDs detected.")
        return
    vendor, product = device_ids[0]
    if len(device_ids) > 1:
        log(
            "Multiple keyboard devices detected; using the first one "
            f"({vendor}:{product}) for the udev rule."
        )
    log(f"Detected keyboard device ID for udev: vendor={vendor} product={product}")

    existing_text = ""
    if UDEV_RULE_PATH.exists():
        try:
            existing_text = UDEV_RULE_PATH.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            log(f"Unable to read {UDEV_RULE_PATH}: {exc}")
            return
        if (
            f'ATTRS{{idVendor}}=="{vendor}"' in existing_text
            and f'ATTRS{{idProduct}}=="{product}"' in existing_text
        ):
            log(f"Udev rule already present for {vendor}:{product}.")
            return
        answer = input(
            f"A udev rule file already exists at {UDEV_RULE_PATH}. Append a new rule? [Y/n]: "
        ).strip().lower()
        if answer not in ("", "y", "yes"):
            log("Skipping udev rule creation.")
            return

    rule_line = (
        'SUBSYSTEMS=="usb", '
        f'ATTRS{{idVendor}}=="{vendor}", '
        f'ATTRS{{idProduct}}=="{product}", '
        'MODE:="0666"'
    )

    try:
        UDEV_RULE_PATH.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if existing_text else "w"
        with open(UDEV_RULE_PATH, mode, encoding="utf-8") as handle:
            if existing_text and not existing_text.endswith("\n"):
                handle.write("\n")
            if not existing_text:
                handle.write("# Allow non-root access to ITE 8291 keyboards\n")
            handle.write(rule_line)
            handle.write("\n")
        os.chmod(UDEV_RULE_PATH, 0o644)
    except OSError as exc:
        log(f"Failed to write udev rule: {exc}")
        return

    run(["udevadm", "control", "--reload"], check=False)
    run(["udevadm", "trigger"], check=False)
    log("Udev rule installed. You may need to unplug/replug or reboot.")


def detect_gui_installation() -> None:
    if SHARE_DIR.exists():
        describe_component(
            "GUI payload",
            f"found at {SHARE_DIR}",
            "files will be replaced with the bundled version",
        )
    else:
        describe_component(
            "GUI payload",
            "not present in /usr/share",
            "will be installed fresh",
        )
    if WRAPPER_PATH.exists():
        describe_component(
            "Launcher wrapper",
            f"existing script at {WRAPPER_PATH}",
            "will be overwritten",
        )
    else:
        describe_component(
            "Launcher wrapper",
            "missing",
            "new script will be created",
        )
    if DESKTOP_PATH.exists():
        describe_component(
            "Desktop entry",
            f"existing file at {DESKTOP_PATH}",
            "will be updated",
        )
    else:
        describe_component(
            "Desktop entry",
            "not found in /usr/share/applications",
            "will be created",
        )


def ensure_runtime_dependency() -> None:
    version = pip_version(GUI_DEPENDENCY)
    if version:
        describe_component(
            f"GUI dependency ({GUI_DEPENDENCY})",
            f"installed via pip (version {version})",
            "skipping install",
        )
        return
    if importlib.util.find_spec(GUI_DEPENDENCY) is not None:
        describe_component(
            f"GUI dependency ({GUI_DEPENDENCY})",
            "available in the current Python environment",
            "skipping install",
        )
        return
    describe_component(
        f"GUI dependency ({GUI_DEPENDENCY})",
        "not detected",
        "pip install will install it now",
    )
    install_pip_package(GUI_DEPENDENCY)


def deploy_files() -> None:
    if not SOURCE_DIR.is_dir():
        raise InstallerError(f"Source directory not found at {SOURCE_DIR}")
    log(f"Deploying files to {SHARE_DIR}")
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    for relative in FILES_TO_DEPLOY:
        src = SOURCE_DIR / relative
        dst = SHARE_DIR / relative
        if not src.is_file():
            raise InstallerError(f"Missing source file: {src}")
        copy_needed = True
        if dst.exists():
            try:
                if filecmp.cmp(src, dst, shallow=False):
                    copy_needed = False
                    log(f"Unchanged file detected, keeping existing {dst}")
                else:
                    log(f"Updating {dst} (content differs)")
            except OSError as exc:
                log(f"Could not compare {src} and {dst}: {exc}. Forcing copy.")
        if copy_needed:
            shutil.copy2(src, dst)
            log(f"Copied {src} -> {dst}")
        mark_executable(dst)
    for relative in DIRS_TO_DEPLOY:
        src_dir = SOURCE_DIR / relative
        dst_dir = SHARE_DIR / relative
        if not src_dir.is_dir():
            raise InstallerError(f"Missing source directory: {src_dir}")
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.copytree(src_dir, dst_dir)
        log(f"Copied directory {src_dir} -> {dst_dir}")


def mark_executable(path: Path) -> None:
    if not path.exists():
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def create_wrapper() -> None:
    log(f"Creating launcher wrapper at {WRAPPER_PATH}")
    WRAPPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"exec {PYTHON_EXECUTABLE} {SHARE_DIR}/keyboard_backlight.py \"$@\"\n"
    )
    WRAPPER_PATH.write_text(script, encoding="utf-8")
    mark_executable(WRAPPER_PATH)


def create_desktop_entry() -> None:
    log(f"Creating desktop entry at {DESKTOP_PATH}")
    DESKTOP_PATH.parent.mkdir(parents=True, exist_ok=True)
    desktop = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Manage the XMG keyboard backlight\n"
        f"Exec={WRAPPER_PATH}\n"
        "Icon=preferences-desktop-keyboard\n"
        "Terminal=false\n"
        "Categories=Settings;Utility;\n"
    )
    DESKTOP_PATH.write_text(desktop, encoding="utf-8")


def create_restore_autostart_entry() -> None:
    log(f"Creating optional restore launcher at {AUTOSTART_PATH}")
    AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
    exec_cmd = f"{PYTHON_EXECUTABLE} {SHARE_DIR}/restore_profile.py"
    entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=XMG Backlight Restore\n"
        "Comment=Restore the last keyboard backlight profile\n"
        f"Exec={exec_cmd}\n"
        "X-GNOME-Autostart-enabled=false\n"
    )
    AUTOSTART_PATH.write_text(entry, encoding="utf-8")


def reload_systemd_daemon() -> None:
    log("Reloading systemd manager configuration")
    run(["systemctl", "daemon-reload"], check=False)


def remove_user_data(remove_profiles: bool) -> None:
    """Remove user systemd services/autostart entries, optionally profiles, for all users.

    Args:
        remove_profiles: If True, also remove user profiles and settings.
    """
    import pwd
    removed_any = False
    
    for entry in pwd.getpwall():
        if entry.pw_uid < 1000:
            continue  # Skip system users
        
        home = Path(entry.pw_dir)
        
        if remove_profiles:
            # Remove config directory (~/.config/backlight-linux/)
            config_dir = home / ".config" / "backlight-linux"
            if config_dir.exists():
                shutil.rmtree(config_dir)
                log(f"Removed user config: {config_dir}")
                removed_any = True
        
        # Remove systemd user services (~/.config/systemd/user/keyboard-backlight-*.service)
        systemd_user_dir = home / ".config" / "systemd" / "user"
        if systemd_user_dir.exists():
            for service_file in systemd_user_dir.glob("keyboard-backlight-*.service"):
                service_file.unlink()
                log(f"Removed user service: {service_file}")
                removed_any = True
            
            # Remove symlinks in target.wants directories
            for target_dir in systemd_user_dir.glob("*.target.wants"):
                for symlink in target_dir.glob("keyboard-backlight-*"):
                    if symlink.is_symlink() or symlink.exists():
                        symlink.unlink()
                        log(f"Removed service symlink: {symlink}")
                        removed_any = True
                # Remove empty target.wants directories
                if target_dir.exists() and not any(target_dir.iterdir()):
                    target_dir.rmdir()
                    log(f"Removed empty directory: {target_dir}")
        
        # Remove autostart entries (~/.config/autostart/keyboard-backlight-*.desktop)
        autostart_dir = home / ".config" / "autostart"
        if autostart_dir.exists():
            for desktop_file in autostart_dir.glob("keyboard-backlight-*.desktop"):
                desktop_file.unlink()
                log(f"Removed autostart entry: {desktop_file}")
                removed_any = True
            # Also remove xmg-backlight.desktop if present
            xmg_autostart = autostart_dir / "xmg-backlight.desktop"
            if xmg_autostart.exists():
                xmg_autostart.unlink()
                log(f"Removed autostart entry: {xmg_autostart}")
                removed_any = True
    
    if not removed_any:
        if remove_profiles:
            log("No user data found to remove.")
        else:
            log("No user services or autostart entries found to remove.")


def uninstall(purge: bool = False, purge_user_data: bool = False) -> None:
    """Remove all installed files and configurations.
    
    Args:
        purge: If True, also remove pip packages (ite8291r3-ctl, PySide6).
        purge_user_data: If True, also remove user profiles and settings.
    """
    log("Starting uninstallation...")
    
    # Remove systemd drop-ins
    for service, _ in SYSTEMD_SERVICE_DROPINS:
        dropin_dir = Path("/etc/systemd/system") / f"{service}.d"
        dropin_path = dropin_dir / DROPIN_FILENAME
        if dropin_path.exists():
            dropin_path.unlink()
            log(f"Removed {dropin_path}")
        if dropin_dir.exists() and not any(dropin_dir.iterdir()):
            dropin_dir.rmdir()
            log(f"Removed empty directory {dropin_dir}")
    
    # Remove files
    paths_to_remove = [
        RESUME_HELPER_PATH,
        SYSTEM_SLEEP_HOOK_PATH,
        AUTOSTART_PATH,
        DESKTOP_PATH,
        WRAPPER_PATH,
        LOG_FILE_PATH,
    ]
    for path in paths_to_remove:
        if path.exists():
            path.unlink()
            log(f"Removed {path}")
    
    # Remove share directory
    if SHARE_DIR.exists():
        shutil.rmtree(SHARE_DIR)
        log(f"Removed {SHARE_DIR}")
    if LOG_DIR.exists() and LOG_DIR.is_dir() and not any(LOG_DIR.iterdir()):
        LOG_DIR.rmdir()
        log(f"Removed empty directory {LOG_DIR}")
    
    # Reload systemd
    reload_systemd_daemon()
    
    # Optionally remove pip packages
    if purge:
        log("Removing pip packages (--purge specified)...")
        for pkg in ["ite8291r3-ctl", "PySide6", "PySide6_Addons", "PySide6_Essentials", "shiboken6"]:
            rc, _, _ = run(
                [sys.executable, "-m", "pip", "uninstall", "-y", pkg],
                check=False,
            )
            if rc == 0:
                log(f"Removed pip package: {pkg}")
            else:
                log(f"Could not remove {pkg} (may not be installed or requires different pip)")
    
    log(
        "Removing user profiles, services, and autostart entries..."
        if purge_user_data
        else "Removing user services and autostart entries..."
    )
    remove_user_data(remove_profiles=purge_user_data)
    
    log("Uninstallation completed.")
    if not purge:
        log("Note: pip packages (ite8291r3-ctl, PySide6) were NOT removed.")
    if not purge_user_data:
        log("Note: User profiles (~/.config/backlight-linux/) were NOT removed.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="XMG Backlight Management installer/uninstaller."
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove all installed files and configurations.",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Used with --uninstall: also remove pip packages (ite8291r3-ctl, PySide6).",
    )
    parser.add_argument(
        "--purge-user-data",
        action="store_true",
        help="Used with --uninstall: also remove user profiles and settings.",
    )
    parser.add_argument(
        "--skip-update-check",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    original_args = [arg for arg in sys.argv[1:] if arg != "--skip-update-check"]

    log(FEDORA_NOTICE)
    require_root()
    if not args.uninstall and not args.skip_update_check:
        check_for_update_and_handoff(original_args)
    stop_running_gui_processes()

    if args.uninstall:
        purge = args.purge
        purge_user_data = getattr(args, 'purge_user_data', False)
        
        # Interactive mode if no flags provided
        if not purge and not purge_user_data:
            print("\nUninstall options:")
            print("  1) Remove software and system files only")
            print("  2) Remove everything (software, pip packages, and user profiles)")
            print("")
            choice = input("Choose an option [1/2] (default: 1): ").strip()
            if choice == "2":
                purge = True
                purge_user_data = True
                log("Full uninstall selected.")
            else:
                log("Partial uninstall selected (software only).")
        
        uninstall(purge=purge, purge_user_data=purge_user_data)
        return

    detect_driver()
    device_ids = probe_keyboard_hardware()
    ensure_udev_rule(device_ids)
    ensure_runtime_dependency()
    detect_gui_installation()
    deploy_files()
    create_wrapper()
    create_desktop_entry()
    create_restore_autostart_entry()
    reload_systemd_daemon()
    log("Installation completed successfully.")
    log(
        "Launch 'XMG Backlight Management' from the application menu, then enable "
        "per-user automation from within the GUI."
    )


if __name__ == "__main__":
    try:
        main()
    except InstallerError as exc:
        log(f"ERROR: {exc}")
        sys.exit(1)
    except Exception as exc:  # pragma: no cover
        log(f"Unexpected error: {exc}")
        sys.exit(1)
