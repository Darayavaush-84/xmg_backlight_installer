"""Restore and verify the active keyboard backlight profile."""

from __future__ import annotations

import sys

from .commands import (
    build_profile_commands,
    parse_keyboard_state,
    state_matches_desired,
)
from .constants import STATE_PATH
from .driver import format_cli_error, run_cmd, run_sequence
from .storage import active_profile_from_raw_store, read_profile_file
from .validation import clamp_int


def apply_profile(profile: dict) -> tuple[bool, str]:
    commands = build_profile_commands(profile)
    rc, out, err, failed_index = run_sequence(commands)
    if rc != 0:
        command = commands[failed_index] if failed_index is not None else []
        detail = format_cli_error(rc, out, err)
        return False, f"Command {' '.join(command)} failed: {detail}"

    rc, out, err = run_cmd(
        ["query", "--brightness", "--state"],
        log_cmd=False,
        log_stdout=False,
        log_stderr=False,
    )
    if rc != 0:
        return False, f"State verification failed: {format_cli_error(rc, out, err)}"

    desired = clamp_int(profile.get("brightness"), 0, 50, 40)
    actual = parse_keyboard_state(out)
    if not state_matches_desired(actual, desired):
        return (
            False,
            "State verification mismatch: "
            f"wanted brightness={desired}, got power={actual.power}, "
            f"brightness={actual.brightness}",
        )
    return True, "Profile restored and verified."


def main():
    try:
        store = read_profile_file()
    except (OSError, ValueError) as exc:
        print(f"Cannot read profile store: {exc}", file=sys.stderr)
        return 1
    profile = active_profile_from_raw_store(store)
    if not profile:
        print(f"No profile found at {STATE_PATH}. Nothing to restore.")
        return 0
    success, message = apply_profile(profile)
    print(message, file=sys.stdout if success else sys.stderr)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
