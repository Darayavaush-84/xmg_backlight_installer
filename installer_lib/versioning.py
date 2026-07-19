"""Version parsing helpers for installer update checks."""

from __future__ import annotations

import re


_PRERELEASE_ORDER = {"alpha": 0, "beta": 1, "rc": 2}


def parse_version(value: str) -> tuple[int, ...]:
    if not value:
        return tuple()
    trimmed = value.strip()
    if trimmed.lower().startswith("v"):
        trimmed = trimmed[1:]
    trimmed = trimmed.split("+", 1)[0].split("-", 1)[0]
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", trimmed):
        return tuple()
    return tuple(int(part) for part in trimmed.split("."))


def _comparison_key(value: str):
    if not value:
        return None
    trimmed = value.strip()
    if trimmed.lower().startswith("v"):
        trimmed = trimmed[1:]
    trimmed = trimmed.split("+", 1)[0]
    match = re.fullmatch(
        r"(?P<release>[0-9]+(?:\.[0-9]+)*)"
        r"(?:-(?P<label>alpha|beta|rc)(?P<number>[0-9]+))?",
        trimmed,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    release = tuple(int(part) for part in match.group("release").split("."))
    label = match.group("label")
    if label is None:
        prerelease = (1, 0, 0)
    else:
        prerelease = (
            0,
            _PRERELEASE_ORDER[label.lower()],
            int(match.group("number")),
        )
    return release, prerelease


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_key = _comparison_key(candidate)
    current_key = _comparison_key(current)
    if candidate_key is None or current_key is None:
        return False
    candidate_parts, candidate_prerelease = candidate_key
    current_parts, current_prerelease = current_key
    max_len = max(len(candidate_parts), len(current_parts))
    candidate_parts += (0,) * (max_len - len(candidate_parts))
    current_parts += (0,) * (max_len - len(current_parts))
    return (candidate_parts, candidate_prerelease) > (
        current_parts,
        current_prerelease,
    )
