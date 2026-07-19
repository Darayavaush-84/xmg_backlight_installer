"""Strict recognition of XMG Backlight GUI processes."""

from __future__ import annotations

import os
from pathlib import Path


def _resolved(value: str | os.PathLike | None) -> Path | None:
    if not value:
        return None
    try:
        return Path(value).resolve()
    except OSError:
        return None


def is_managed_gui_process(
    args: list[str],
    *,
    executable: str | None,
    cwd: str | None,
    venv_python: Path,
    share_dir: Path,
) -> bool:
    if not args:
        return False
    resolved_executable = _resolved(executable)
    expected_python = _resolved(venv_python)
    resolved_cwd = _resolved(cwd)
    expected_cwd = _resolved(share_dir)
    if resolved_executable != expected_python or resolved_cwd != expected_cwd:
        return False
    return len(args) >= 3 and args[1:3] == ["-m", "xmg_backlight.app"]
