"""Translation loading and language detection."""

from __future__ import annotations

import json
import os

from PySide6 import QtCore

from .constants import LANGUAGE_LABELS, TRANSLATIONS_DIR
from .ui_helpers import normalize_language_code


def load_translations(language):
    lang = normalize_language_code(language)
    if not lang:
        return {}
    path = os.path.join(TRANSLATIONS_DIR, f"{lang}.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def detect_system_language():
    try:
        languages = QtCore.QLocale.system().uiLanguages() or []
    except Exception:
        languages = []
    for lang in languages:
        code = normalize_language_code(lang)
        if code in LANGUAGE_LABELS:
            return code
    return "en"
