"""Monitor AC/battery transitions and reapply keyboard profile."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from typing import List, Optional

from .constants import APP_ROOT, MAINS_TYPES, POWER_SUPPLY_DIR, PYTHON_EXECUTABLE
from .storage import read_settings_file, switch_active_profile

POLL_INTERVAL_SECONDS = 3
REDISCOVER_INTERVAL = 20


def log(msg: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def discover_mains_online_paths() -> List[str]:
    if not os.path.isdir(POWER_SUPPLY_DIR):
        return []
    paths: List[str] = []
    for entry in os.listdir(POWER_SUPPLY_DIR):
        entry_path = os.path.join(POWER_SUPPLY_DIR, entry)
        type_path = os.path.join(entry_path, "type")
        online_path = os.path.join(entry_path, "online")
        try:
            with open(type_path, "r", encoding="utf-8") as handle:
                power_type = handle.read().strip().lower()
        except OSError:
            continue
        if power_type not in MAINS_TYPES:
            continue
        if os.path.isfile(online_path):
            paths.append(online_path)
    return sorted(set(paths))


def read_online_value(path: str) -> Optional[bool]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip() == "1"
    except OSError:
        return None


def restore_profile(reason: str, power_state: Optional[bool] = None) -> None:
    if power_state is not None:
        settings = read_settings_file()
        target_profile = ""
        if power_state:
            target_profile = settings.get("ac_profile", "")
        else:
            target_profile = settings.get("battery_profile", "")

        if target_profile:
            log(f"Switching to {'AC' if power_state else 'battery'} profile: {target_profile}")
            try:
                switched = switch_active_profile(target_profile)
            except OSError as exc:
                log(f"Failed to switch profile to '{target_profile}': {exc}")
                switched = False
            if switched:
                log(f"Active profile switched to '{target_profile}'")
            else:
                log(f"Cannot switch profile to '{target_profile}', keeping current profile")

    cmd = [PYTHON_EXECUTABLE, "-m", "xmg_backlight.restore_profile"]
    log(f"{reason}: running {' '.join(shlex.quote(part) for part in cmd)}")
    proc = subprocess.run(cmd, text=True, capture_output=True, cwd=APP_ROOT)
    if proc.stdout:
        print(proc.stdout.strip(), flush=True)
    if proc.stderr:
        print(proc.stderr.strip(), file=sys.stderr, flush=True)
    if proc.returncode != 0:
        log(f"restore_profile exited with code {proc.returncode}")


def compute_power_state(paths: List[str]) -> Optional[bool]:
    if not paths:
        return None
    any_offline = False
    for path in paths:
        value = read_online_value(path)
        if value is True:
            return True
        if value is False:
            any_offline = True
    if any_offline:
        return False
    return None


def monitor_loop() -> int:
    iteration = 0
    paths = discover_mains_online_paths()
    last_state = compute_power_state(paths)
    if last_state is None:
        log("Unable to determine initial power state.")
    else:
        log(f"Initial power state: {'AC' if last_state else 'battery'}")
        restore_profile("Initial power state", power_state=last_state)

    while True:
        iteration += 1
        if iteration % REDISCOVER_INTERVAL == 0:
            paths = discover_mains_online_paths()

        state = compute_power_state(paths)
        if state is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        if last_state is None:
            last_state = state
        elif state != last_state:
            label = "AC" if state else "battery"
            log(f"Power source changed: now on {label}.")
            restore_profile("Power source change", power_state=state)
            last_state = state

        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> int:
    try:
        monitor_loop()
    except KeyboardInterrupt:
        log("Monitor interrupted.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
