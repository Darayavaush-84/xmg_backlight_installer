#!/usr/bin/env python3
"""Monitor AC/battery transitions and reapply keyboard profile."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from typing import List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESTORE_SCRIPT = os.path.join(BASE_DIR, "restore_profile.py")
PYTHON_EXECUTABLE = sys.executable or shutil.which("python3") or "/usr/bin/python3"
POWER_SUPPLY_DIR = "/sys/class/power_supply"
MAINS_TYPES = {"mains", "ac", "usb"}
POLL_INTERVAL_SECONDS = 3
REDISCOVER_INTERVAL = 20  # iterations


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


def ensure_restore_script_executable() -> None:
    try:
        st = os.stat(RESTORE_SCRIPT)
    except FileNotFoundError:
        return
    new_mode = st.st_mode | 0o111
    if new_mode != st.st_mode:
        try:
            os.chmod(RESTORE_SCRIPT, new_mode)
        except OSError:
            pass


def restore_profile(reason: str) -> None:
    ensure_restore_script_executable()
    if not os.path.isfile(RESTORE_SCRIPT):
        log(f"restore_profile.py non trovato ({RESTORE_SCRIPT}).")
        return
    cmd = [PYTHON_EXECUTABLE, RESTORE_SCRIPT]
    log(f"{reason}: eseguo {' '.join(shlex.quote(part) for part in cmd)}")
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout.strip(), flush=True)
    if proc.stderr:
        print(proc.stderr.strip(), file=sys.stderr, flush=True)
    if proc.returncode != 0:
        log(f"restore_profile.py uscita con codice {proc.returncode}")


def compute_power_state(paths: List[str]) -> Optional[bool]:
    if not paths:
        return None
    any_online = False
    any_offline = False
    for path in paths:
        value = read_online_value(path)
        if value is True:
            any_online = True
            break
        if value is False:
            any_offline = True
    if any_online:
        return True
    if any_offline:
        return False
    return None


def monitor_loop() -> int:
    iteration = 0
    paths = discover_mains_online_paths()
    last_state = compute_power_state(paths)
    if last_state is None:
        log("Impossibile determinare lo stato di alimentazione iniziale.")
    else:
        log(f"Stato iniziale: {'rete' if last_state else 'batteria'}")

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
            label = "rete" if state else "batteria"
            log(f"Cambio alimentazione: ora su {label}.")
            restore_profile("Cambio alimentazione")
            last_state = state

        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> int:
    try:
        monitor_loop()
    except KeyboardInterrupt:
        log("Monitor interrotto.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
