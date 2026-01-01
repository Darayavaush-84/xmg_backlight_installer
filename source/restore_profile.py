#!/usr/bin/env python3
"""Restore keyboard backlight profile saved by the GUI."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from typing import List

TOOL_ENV_VAR = "ITE8291R3_CTL"
TOOL_CANDIDATES = [
    os.environ.get(TOOL_ENV_VAR),
    "/usr/local/bin/ite8291r3-ctl",
    "ite8291r3-ctl",
]

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "backlight-linux")
PROFILE_PATH = os.path.join(CONFIG_DIR, "profile.json")


def clamp(value, minimum, maximum, fallback):
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, ivalue))


def resolve_tool():
    for candidate in TOOL_CANDIDATES:
        if not candidate:
            continue
        path = candidate
        if not os.path.isabs(candidate):
            resolved = shutil.which(candidate)
            if not resolved:
                continue
            path = resolved
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    return None


def read_profile():
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def sanitize_choice(value, options, fallback):
    return value if value in options else fallback


def build_commands(profile):
    brightness = clamp(profile.get("brightness"), 0, 50, 40)
    if brightness <= 0:
        return [["off"]]

    commands = [["off"]]

    mode = profile.get("mode", "static")
    if mode == "static":
        color = profile.get("static_color") or "white"
        commands.append(["monocolor", "-b", str(brightness), "--name", color])
        commands.append(["brightness", str(brightness)])
        return commands

    # Effects
    args: List[str] = ["effect", "-b", str(brightness)]

    speed = clamp(profile.get("speed"), 0, 10, 5)
    if speed != 5:
        args += ["-s", str(speed)]

    color = profile.get("color") or "none"
    if color != "none":
        args += ["-c", color]

    if profile.get("reactive"):
        args.append("-r")
    else:
        direction = profile.get("direction") or "none"
        if direction != "none":
            args += ["-d", direction]

    args.append(mode)
    commands.append(args)
    commands.append(["brightness", str(brightness)])
    return commands


def run_cli(tool, args):
    cmd = [tool, *args]
    print("$", " ".join(shlex.quote(part) for part in cmd))
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode


def query_keyboard_state(tool):
    cmd = [tool, "query", "--brightness", "--state"]
    result = subprocess.run(cmd, text=True, capture_output=True)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stderr:
        print(stderr, file=sys.stderr)
    brightness = None
    state = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower in ("on", "off"):
            state = lower
            continue
        try:
            brightness = int(line)
        except ValueError:
            continue
    return result.returncode, brightness, state, stdout


def ensure_keyboard_is_on(tool, desired_brightness):
    rc, brightness, state, _ = query_keyboard_state(tool)
    if rc != 0:
        return True
    if state == "on":
        return True
    if brightness is not None and brightness >= max(1, int(desired_brightness)):
        return True
    if brightness is not None and brightness > 0:
        return True
    return False


def apply_profile_with_verification(tool, commands, desired_brightness):
    rc = run_commands_with_retry(tool, commands)
    if rc != 0:
        return rc

    time.sleep(0.25)
    if ensure_keyboard_is_on(tool, desired_brightness):
        return 0

    print(
        "Keyboard still appears off after restore; retrying with longer delay",
        file=sys.stderr,
    )
    run_cli(tool, ["off"])
    time.sleep(1.8)
    for cmd in commands:
        if cmd == ["off"]:
            continue
        rc = run_cli(tool, cmd)
        if rc != 0:
            return rc
    time.sleep(0.25)
    return 0 if ensure_keyboard_is_on(tool, desired_brightness) else 2


def run_commands_with_retry(tool, commands):
    deadline = time.monotonic() + 12.0
    delay = 0.6
    last_rc = 0
    for idx, cmd in enumerate(commands):
        attempt = 0
        while True:
            attempt += 1
            last_rc = run_cli(tool, cmd)
            if last_rc == 0:
                if cmd == ["off"] and idx + 1 < len(commands):
                    time.sleep(0.06)
                break
            now = time.monotonic()
            if now >= deadline:
                return last_rc
            sleep_for = min(delay, max(0.0, deadline - now))
            print(
                f"Retry {attempt}: command {' '.join(cmd)} failed (rc={last_rc}), retrying in {sleep_for:.1f}s",
                file=sys.stderr,
            )
            time.sleep(sleep_for)
            delay = min(delay * 1.6, 2.5)
    return last_rc


def main():
    profile = read_profile()
    if not profile:
        print(f"No profile found at {PROFILE_PATH}. Nothing to restore.")
        return 0

    tool = resolve_tool()
    if not tool:
        print(
            "CLI tool not found. Install 'ite8291r3-ctl' or set "
            f"${TOOL_ENV_VAR} before running this script.",
            file=sys.stderr,
        )
        return 1

    commands = build_commands(profile)
    desired_brightness = clamp(profile.get("brightness"), 0, 50, 40)
    rc = apply_profile_with_verification(tool, commands, desired_brightness)
    if rc != 0:
        printable = " / ".join(" ".join(cmd) for cmd in commands)
        print(f"Command(s) {printable} failed with exit code {rc}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
