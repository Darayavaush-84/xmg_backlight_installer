"""Bounded and serialized ite8291r3-ctl invocation."""

from __future__ import annotations

import fcntl
import html
import os
import shlex
import subprocess
import time
from contextlib import contextmanager

from .constants import CONFIG_DIR, DRIVER_WRAPPER_PATH
from .storage import ensure_config_dir

COMMAND_TIMEOUT_SECONDS = 6.0
HARDWARE_LOCK_TIMEOUT_SECONDS = 8.0
HARDWARE_LOCK_PATH = os.path.join(CONFIG_DIR, "hardware.lock")


class HardwareBusyError(TimeoutError):
    pass


def resolve_tool():
    if os.path.isfile(DRIVER_WRAPPER_PATH) and os.access(
        DRIVER_WRAPPER_PATH, os.X_OK
    ):
        return DRIVER_WRAPPER_PATH
    return None


def tool_hint():
    return DRIVER_WRAPPER_PATH


MISSING_TOOL_MESSAGE = "Bundled CLI tool not found. Reinstall the application."

LOG_COLORS = {
    "info": "#e5e7eb",
    "cmd": "#7dd3fc",
    "stdout": "#c7f9cc",
    "stderr": "#fca5a5",
    "error": "#f87171",
}


def format_log(text, level="info"):
    color = LOG_COLORS.get(level, LOG_COLORS["info"])
    return f'<span style="color:{color}">{html.escape(str(text))}</span>'


@contextmanager
def hardware_lock(timeout: float = HARDWARE_LOCK_TIMEOUT_SECONDS):
    ensure_config_dir()
    descriptor = os.open(
        HARDWARE_LOCK_PATH,
        os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    os.fchmod(descriptor, 0o600)
    lock_file = os.fdopen(descriptor, "a+", encoding="utf-8")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise HardwareBusyError("Timed out waiting for keyboard controller lock")
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


def _run_unlocked(tool: str, args, *, timeout: float):
    try:
        process = subprocess.run(
            [tool, *args],
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
        message = stderr or f"Command timed out after {timeout:.1f}s"
        return 124, stdout, message
    except FileNotFoundError:
        return 127, "", f"{MISSING_TOOL_MESSAGE} Searched: {tool_hint()}."
    return (
        process.returncode,
        (process.stdout or "").strip(),
        (process.stderr or "").strip(),
    )


def run_cmd(
    args,
    log_cb=None,
    *,
    log_cmd=True,
    log_stdout=True,
    log_stderr=True,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
):
    cmd_display = " ".join(shlex.quote(str(arg)) for arg in args)
    if log_cb and log_cmd:
        log_cb(f"$ {cmd_display}", level="cmd")
    tool = resolve_tool()
    if not tool:
        message = f"{MISSING_TOOL_MESSAGE} Searched: {tool_hint()}."
        if log_cb:
            log_cb(message, level="error")
        return 127, "", message
    try:
        with hardware_lock():
            result = _run_unlocked(tool, args, timeout=timeout)
    except HardwareBusyError as exc:
        result = (125, "", str(exc))
    rc, stdout, stderr = result
    if stdout and log_cb and log_stdout:
        log_cb(stdout, level="stdout")
    if stderr and log_cb and log_stderr:
        log_cb(stderr, level="stderr")
    return result


def run_sequence(
    commands,
    log_cb=None,
    *,
    timeout_per_command: float = COMMAND_TIMEOUT_SECONDS,
    inter_command_delay: float = 0.06,
):
    tool = resolve_tool()
    if not tool:
        message = f"{MISSING_TOOL_MESSAGE} Searched: {tool_hint()}."
        return 127, "", message, None
    try:
        with hardware_lock():
            last = (0, "", "")
            for index, args in enumerate(commands):
                if log_cb:
                    display = " ".join(shlex.quote(str(arg)) for arg in args)
                    log_cb(f"$ {display}", level="cmd")
                last = _run_unlocked(tool, args, timeout=timeout_per_command)
                rc, stdout, stderr = last
                if stdout and log_cb:
                    log_cb(stdout, level="stdout")
                if stderr and log_cb:
                    log_cb(stderr, level="stderr")
                if rc != 0:
                    return rc, stdout, stderr, index
                if index + 1 < len(commands) and inter_command_delay:
                    time.sleep(inter_command_delay)
            return (*last, None)
    except HardwareBusyError as exc:
        return 125, "", str(exc), None


def format_cli_error(rc, out, err):
    text = (err or out or "").strip()
    lower = text.lower()
    if rc == 127 or "cli tool not found" in lower:
        return f"{MISSING_TOOL_MESSAGE} Searched: {tool_hint()}."
    if rc == 124:
        return text or "Keyboard command timed out."
    if rc == 125:
        return text or "Keyboard controller is busy."
    if "libusb_error_access" in lower or "permission denied" in lower:
        return "Insufficient permissions to access the keyboard."
    if "device handle could not be acquired" in lower or "no such device" in lower:
        return "Keyboard not detected. Check the USB connection and try again."
    if text:
        return f"Error ({rc}): {text}"
    return f"Error ({rc}): unknown"
