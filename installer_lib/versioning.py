"""Version parsing helpers for installer update checks."""

from __future__ import annotations

import re


def extract_app_version_from_text(content: str) -> str | None:
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

