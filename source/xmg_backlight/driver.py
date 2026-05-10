"""ite8291r3-ctl discovery, invocation, and error handling."""

from __future__ import annotations

import html
import os
import shlex
import shutil
import subprocess

from .constants import TOOL_CANDIDATES, TOOL_ENV_VAR


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


def tool_hint():
    candidates = [c for c in TOOL_CANDIDATES if c]
    return ", ".join(candidates) if candidates else "ite8291r3-ctl"


TOOL = resolve_tool()
MISSING_TOOL_MESSAGE = (
    f"CLI tool not found. Install 'ite8291r3-ctl' or set ${TOOL_ENV_VAR}."
)

LOG_COLORS = {
    "info": "#e5e7eb",
    "cmd": "#7dd3fc",
    "stdout": "#c7f9cc",
    "stderr": "#fca5a5",
    "error": "#f87171",
}


def format_log(text, level="info"):
    color = LOG_COLORS.get(level, LOG_COLORS["info"])
    safe = html.escape(text)
    return f'<span style="color:{color}">{safe}</span>'


def run_cmd(args, log_cb=None, *, log_cmd=True, log_stdout=True, log_stderr=True):
    cmd_display = " ".join(shlex.quote(str(a)) for a in args)
    if log_cb and log_cmd:
        log_cb(f"$ {cmd_display}", level="cmd")

    if not TOOL:
        msg = f"{MISSING_TOOL_MESSAGE} (candidati: {tool_hint()})"
        if log_cb:
            log_cb(msg, level="error")
        return 127, "", msg

    try:
        p = subprocess.run([TOOL, *args], text=True, capture_output=True)
        stdout = (p.stdout or "").strip()
        stderr = (p.stderr or "").strip()
        if stdout and log_cb and log_stdout:
            log_cb(stdout, level="stdout")
        if stderr and log_cb and log_stderr:
            log_cb(stderr, level="stderr")
        return p.returncode, stdout, stderr
    except FileNotFoundError:
        msg = f"{MISSING_TOOL_MESSAGE} (candidati: {tool_hint()})"
        if log_cb:
            log_cb(msg, level="error")
        return 127, "", msg


def format_cli_error(rc, out, err):
    text = (err or out or "").strip()
    lower = text.lower()

    if rc == 127 or "cli tool non trovato" in lower or "cli tool not found" in lower:
        return f"{MISSING_TOOL_MESSAGE} Searched: {tool_hint()}."

    if "libusb_error_access" in lower or "permission denied" in lower:
        return (
            "Insufficient permissions to access the keyboard. "
            "Run as root or create a udev rule."
        )

    if "device handle could not be acquired" in lower or "no such device" in lower:
        return "Keyboard not detected. Check the USB connection and try again."

    if text:
        return f"Error ({rc}): {text}"

    return f"Error ({rc}): unknown"


def drop_flag(args, flag):
    out = []
    i = 0
    while i < len(args):
        if args[i] == flag:
            if flag in ("-s", "-b", "-c", "-d") and i + 1 < len(args):
                i += 2
                continue
            i += 1
            continue
        out.append(args[i])
        i += 1
    return out


def apply_effect_with_fallback(args, runner=run_cmd):
    rc, out, err = runner(args)
    if rc == 0:
        return rc, out, err, args

    msg = (err or out or "").lower()
    if "attr is not needed by effect" not in msg:
        return rc, out, err, args

    candidates = [
        ("direction", "-d"),
        ("reactive", "-r"),
        ("color", "-c"),
        ("speed", "-s"),
        ("brightness", "-b"),
    ]

    tried = set()
    current = list(args)

    for _ in range(6):
        m = (err or out or "").lower()
        changed = False
        for key, flag in candidates:
            if key in m and flag not in tried:
                tried.add(flag)
                current = drop_flag(current, flag)
                rc, out, err = runner(current)
                changed = True
                if rc == 0:
                    return rc, out, err, current
                break
        if not changed:
            break

    return rc, out, err, current
