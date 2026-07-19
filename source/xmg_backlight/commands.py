"""Pure command construction and device-state parsing."""

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import (
    DIRECTIONS,
    DYNAMIC_COLORS,
    EFFECTS,
    STATIC_COLORS,
    capability_for,
)
from .validation import clamp_int, sanitize_choice


@dataclass(frozen=True)
class KeyboardState:
    brightness: int | None
    power: str | None


def parse_keyboard_state(output: str) -> KeyboardState:
    brightness = None
    power = None
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered in {"on", "off"}:
            power = lowered
            continue
        try:
            brightness = int(line)
        except ValueError:
            continue
    return KeyboardState(brightness=brightness, power=power)


def state_matches_desired(state: KeyboardState, desired_brightness: int) -> bool:
    desired = clamp_int(desired_brightness, 0, 50, 40)
    if desired == 0:
        return state.power == "off"
    return state.power == "on" and state.brightness == desired


def build_profile_commands(profile: dict) -> list[list[str]]:
    brightness = clamp_int(profile.get("brightness"), 0, 50, 40)
    if brightness == 0:
        return [["off"]]

    mode = sanitize_choice(profile.get("mode"), EFFECTS, "static")
    commands = [["off"]]
    if mode == "static":
        color = sanitize_choice(profile.get("static_color"), STATIC_COLORS, "white")
        commands.append(["monocolor", "-b", str(brightness), "--name", color])
        commands.append(["brightness", str(brightness)])
        return commands

    capability = capability_for(mode)
    args = ["effect", "-b", str(brightness)]
    if capability.speed:
        speed = clamp_int(profile.get("speed"), 0, 10, 5)
        if speed != 5:
            args.extend(["-s", str(speed)])
    if capability.color:
        color = profile.get("color") or "none"
        if color != "none":
            color = sanitize_choice(color, DYNAMIC_COLORS, "none")
        if color != "none":
            args.extend(["-c", color])
    if capability.reactive and bool(profile.get("reactive")):
        args.append("-r")
    elif capability.direction:
        direction = sanitize_choice(profile.get("direction"), DIRECTIONS, "none")
        if direction != "none":
            args.extend(["-d", direction])
    args.append(mode)
    commands.append(args)
    commands.append(["brightness", str(brightness)])
    return commands
