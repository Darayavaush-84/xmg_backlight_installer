"""Install manifest and artifact ownership checks."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


class OwnershipError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory(path: Path) -> str:
    if path.is_symlink() or not path.is_dir():
        raise OwnershipError(f"Cannot hash non-directory: {path}")
    digest = hashlib.sha256()
    for current_root, directory_names, file_names in os.walk(
        path, topdown=True, followlinks=False
    ):
        directory_names.sort()
        file_names.sort()
        root = Path(current_root)
        entries = [
            *(root / name for name in directory_names),
            *(root / name for name in file_names),
        ]
        for entry in entries:
            relative = entry.relative_to(path).as_posix()
            info = entry.lstat()
            if entry.is_symlink():
                kind = "link"
                payload = os.readlink(entry).encode("utf-8", "surrogateescape")
            elif entry.is_dir():
                kind = "dir"
                payload = b""
            elif entry.is_file():
                kind = "file"
                payload = sha256_file(entry).encode("ascii")
            else:
                raise OwnershipError(f"Unsupported filesystem entry: {entry}")
            digest.update(kind.encode("ascii") + b"\0")
            digest.update(relative.encode("utf-8", "surrogateescape") + b"\0")
            digest.update(f"{info.st_mode & 0o7777:o}".encode("ascii") + b"\0")
            digest.update(payload + b"\0")
    return digest.hexdigest()


def load_install_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise OwnershipError(f"Install manifest is not a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OwnershipError(f"Cannot read install manifest {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise OwnershipError(f"Unsupported install manifest at {path}")
    files = payload.get("files")
    directories = payload.get("directories")
    directory_hashes = payload.get("directory_hashes")
    if (
        not isinstance(files, dict)
        or not isinstance(directories, list)
        or not isinstance(directory_hashes, dict)
        or set(directory_hashes) != set(directories)
    ):
        raise OwnershipError(f"Malformed install manifest at {path}")
    return payload


def verify_owned_file(path: Path, manifest: dict) -> bool:
    expected = manifest.get("files", {}).get(str(path))
    if not expected or not path.is_file() or path.is_symlink():
        return False
    return sha256_file(path) == expected


def assert_replaceable_file(
    path: Path,
    manifest: dict,
    *,
    legacy_validator=None,
) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if verify_owned_file(path, manifest):
        return
    if legacy_validator and path.is_file() and not path.is_symlink():
        try:
            if legacy_validator(path.read_text(encoding="utf-8", errors="strict")):
                return
        except OSError:
            pass
    raise OwnershipError(f"Refusing to replace unowned file: {path}")


def verify_owned_directory(path: Path, manifest: dict) -> bool:
    if str(path) not in manifest.get("directories", []):
        return False
    if not path.is_dir() or path.is_symlink():
        return False
    marker = path / ".xmg-backlight-owner.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expected_hash = manifest.get("directory_hashes", {}).get(str(path))
    if payload.get("install_id") != manifest.get("install_id") or not expected_hash:
        return False
    try:
        return sha256_directory(path) == expected_hash
    except (OSError, OwnershipError):
        return False


def assert_replaceable_directory(
    path: Path,
    manifest: dict,
    *,
    legacy_validator=None,
) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if verify_owned_directory(path, manifest):
        return
    if legacy_validator and path.is_dir() and not path.is_symlink():
        if legacy_validator(path):
            return
    raise OwnershipError(f"Refusing to replace unowned directory: {path}")


def atomic_write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
