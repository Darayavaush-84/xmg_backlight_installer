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
import os
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Iterable, Tuple

APP_NAME = "XMG Backlight Management"
DRIVER_PACKAGE = "ite8291r3-ctl"
GUI_DEPENDENCY = "PySide6"
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
LOG_MAX_SIZE_BYTES = 512 * 1024  # 512 KB
LOG_FILE_PATH = Path("/tmp/xmg-backlight-resume.log")

BASE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = (BASE_DIR / "source").resolve()
FILES_TO_DEPLOY = [
    "keyboard_backlight.py",
    "restore_profile.py",
    "power_state_monitor.py",
]
DIRS_TO_DEPLOY: list[str] = []
DRIVER_INSTALLED_THIS_RUN = False


class InstallerError(RuntimeError):
    """Raised when installation fails."""


def log(msg: str) -> None:
    print(f"[installer] {msg}")


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
    log(f"Installing/upgrading pip package: {package}")
    rc, _, _ = run([sys.executable, "-m", "pip", "install", "--upgrade", package], check=False)
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
            "pip install --upgrade to refresh if needed",
        )
    elif driver_in_path:
        describe_component(
            "Driver (ite8291r3-ctl)",
            "binary found in PATH but package version unknown",
            "pip install --upgrade to sync with latest release",
        )
    else:
        describe_component(
            "Driver (ite8291r3-ctl)",
            "not detected",
            "pip install will install it now",
        )
    if install_pip_package(DRIVER_PACKAGE):
        global DRIVER_INSTALLED_THIS_RUN
        DRIVER_INSTALLED_THIS_RUN = True


def probe_keyboard_hardware() -> None:
    cli_path = shutil.which("ite8291r3-ctl")
    if not cli_path:
        log("Hardware probe skipped: ite8291r3-ctl binary not found in PATH.")
        return
    log("Checking for compatible keyboards...")
    rc, stdout, stderr = run([cli_path, "query", "--devices"], check=False)
    if rc != 0:
        log(
            "Warning: unable to query devices (ite8291r3-ctl exited with a non-zero status). "
            "Continuing installation."
        )
        if stderr:
            log(f"ite8291r3-ctl stderr: {stderr}")
        return
    devices = [line.strip() for line in stdout.splitlines() if line.strip()]
    if devices:
        log(f"Detected {len(devices)} compatible keyboard device(s).")
        return
    answer = input(
        "No supported keyboard was detected. Continue installation anyway? [y/N]: "
    ).strip()
    if answer.lower() not in ("y", "yes"):
        if DRIVER_INSTALLED_THIS_RUN:
            log("Removing ite8291r3-ctl because installation was aborted.")
            run([sys.executable, "-m", "pip", "uninstall", "-y", DRIVER_PACKAGE], check=False)
        raise InstallerError("Installation aborted: no compatible keyboard detected.")
    log("User opted to continue without a detected keyboard.")


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
            "pip install --upgrade to refresh if needed",
        )
    else:
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
        f"exec python3 {SHARE_DIR}/keyboard_backlight.py \"$@\"\n"
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
    exec_cmd = f"python3 {SHARE_DIR}/restore_profile.py"
    entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=XMG Backlight Restore\n"
        "Comment=Restore the last keyboard backlight profile\n"
        f"Exec={exec_cmd}\n"
        "X-GNOME-Autostart-enabled=false\n"
    )
    AUTOSTART_PATH.write_text(entry, encoding="utf-8")


def create_system_sleep_hook() -> None:
    log(f"Creating system-sleep hook at {SYSTEM_SLEEP_HOOK_PATH}")
    SYSTEM_SLEEP_HOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    script = textwrap.dedent(
        f"""\
        #!/usr/bin/env sh
        set -eu
        LOGFILE="/tmp/xmg-backlight-resume.log"
        LOG_MAX_SIZE={LOG_MAX_SIZE_BYTES}
        phase="${{1:-}}"
        operation="${{2:-unknown}}"
        timestamp="$(date)"

        # Log rotation: truncate if exceeds max size
        if [ -f "$LOGFILE" ]; then
          log_size=$(stat -c%s "$LOGFILE" 2>/dev/null || echo 0)
          if [ "$log_size" -gt "$LOG_MAX_SIZE" ]; then
            tail -c "$((LOG_MAX_SIZE / 2))" "$LOGFILE" > "$LOGFILE.tmp" 2>/dev/null && mv "$LOGFILE.tmp" "$LOGFILE" || true
            printf "%s: log rotated (was %s bytes)\\n" "$(date)" "$log_size" >> "$LOGFILE"
          fi
        fi

        printf "%s: hook called with phase=%s op=%s\\n" "$timestamp" "$phase" "$operation" >> "$LOGFILE"
        if [ "$phase" != "post" ]; then
          exit 0
        fi
        sleep 5
        printf "%s: starting restore for users\\n" "$(date)" >> "$LOGFILE"
        if command -v loginctl >/dev/null 2>&1; then
          users=$(loginctl list-sessions --no-legend 2>/dev/null | awk '{{print $3}}' | sort -u)
        else
          users=""
        fi
        printf "%s: found users: %s\\n" "$(date)" "$users" >> "$LOGFILE"
        for u in $users; do
          [ "$u" = "root" ] && continue
          printf "%s: restoring for user %s\\n" "$(date)" "$u" >> "$LOGFILE"
          if command -v runuser >/dev/null 2>&1; then
            runuser -u "$u" -- /usr/bin/python3 {SHARE_DIR}/restore_profile.py >> "$LOGFILE" 2>&1 || printf "%s: restore failed for %s\\n" "$(date)" "$u" >> "$LOGFILE"
          else
            su - "$u" -c "/usr/bin/python3 {SHARE_DIR}/restore_profile.py" >> "$LOGFILE" 2>&1 || printf "%s: restore failed for %s\\n" "$(date)" "$u" >> "$LOGFILE"
          fi
        done
        printf "%s: hook finished\\n" "$(date)" >> "$LOGFILE"
        """
    )
    SYSTEM_SLEEP_HOOK_PATH.write_text(script, encoding="utf-8")
    mark_executable(SYSTEM_SLEEP_HOOK_PATH)


def create_systemd_resume_dropins() -> None:
    log(f"Creating resume helper script at {RESUME_HELPER_PATH}")
    RESUME_HELPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    helper_script = textwrap.dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        operation="${1:-suspend}"
        HOOK="/etc/systemd/system-sleep/xmg-backlight-restore"
        LOG_TAG="xmg-backlight-hook"
        if [ ! -x "$HOOK" ]; then
          if command -v logger >/dev/null 2>&1; then
            logger -t "$LOG_TAG" "restore hook missing at $HOOK"
          fi
          exit 0
        fi
        "$HOOK" post "$operation" || {
          if command -v logger >/dev/null 2>&1; then
            logger -t "$LOG_TAG" "restore hook failed for $operation"
          fi
          exit 0
        }
        """
    )
    RESUME_HELPER_PATH.write_text(helper_script, encoding="utf-8")
    mark_executable(RESUME_HELPER_PATH)

    for service, operation in SYSTEMD_SERVICE_DROPINS:
        dropin_dir = Path("/etc/systemd/system") / f"{service}.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)
        dropin_path = dropin_dir / DROPIN_FILENAME
        dropin_content = (
            "[Service]\n"
            f"ExecStartPost={RESUME_HELPER_PATH} {operation}\n"
        )
        dropin_path.write_text(dropin_content, encoding="utf-8")
        log(f"Configured resume drop-in for {service} (operation={operation})")


def reload_systemd_daemon() -> None:
    log("Reloading systemd manager configuration")
    run(["systemctl", "daemon-reload"], check=False)


def uninstall() -> None:
    """Remove all installed files and configurations."""
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
    ]
    for path in paths_to_remove:
        if path.exists():
            path.unlink()
            log(f"Removed {path}")
    
    # Remove share directory
    if SHARE_DIR.exists():
        shutil.rmtree(SHARE_DIR)
        log(f"Removed {SHARE_DIR}")
    
    # Reload systemd
    reload_systemd_daemon()
    
    log("Uninstallation completed.")
    log("Note: pip packages (ite8291r3-ctl, PySide6) were NOT removed.")
    log("To remove them manually: pip uninstall ite8291r3-ctl PySide6")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="XMG Backlight Management installer/uninstaller."
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove all installed files and configurations.",
    )
    args = parser.parse_args()

    log(FEDORA_NOTICE)
    require_root()

    if args.uninstall:
        uninstall()
        return

    detect_driver()
    probe_keyboard_hardware()
    ensure_runtime_dependency()
    detect_gui_installation()
    deploy_files()
    create_wrapper()
    create_desktop_entry()
    create_restore_autostart_entry()
    create_system_sleep_hook()
    create_systemd_resume_dropins()
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
