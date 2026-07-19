"""Pure validation helpers shared by GUI and headless services."""

from __future__ import annotations


def normalize_language_code(value):
    if not value:
        return ""
    return str(value).split("-")[0].split("_")[0].lower()


def clamp_int(value, minimum, maximum, fallback):
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, ivalue))


def sanitize_choice(value, options, fallback):
    return value if value in options else fallback
