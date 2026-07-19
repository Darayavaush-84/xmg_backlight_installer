"""Recoverable filesystem transaction used by the installer."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path


class FilesystemTransaction:
    def __init__(self, backup_parent: Path):
        backup_parent.mkdir(parents=True, exist_ok=True)
        self.backup_root = Path(
            tempfile.mkdtemp(prefix=".xmg-backlight-transaction-", dir=backup_parent)
        )
        self._undo = []
        self._backups = set()
        self._closed = False

    def _backup_path(self, target: Path) -> Path:
        return target.parent / (
            f".{target.name}.xmg-backlight-backup-{uuid.uuid4().hex}"
        )

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _remove_backup(path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def replace_directory(self, staged: Path, target: Path) -> None:
        if not staged.is_dir() or staged.is_symlink():
            raise ValueError(f"Staged directory is invalid: {staged}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if staged.stat().st_dev != target.parent.stat().st_dev:
            raise ValueError(
                f"Staged directory is on a different filesystem: {staged}"
            )
        backup = None
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_dir():
                raise ValueError(f"Target is not a regular directory: {target}")
            backup = self._backup_path(target)
            os.replace(target, backup)
            self._backups.add(backup)
        try:
            os.replace(staged, target)
            self._fsync_directory(target.parent)
        except Exception:
            if backup is not None:
                os.replace(backup, target)
                self._backups.discard(backup)
            raise

        def undo():
            if target.exists():
                shutil.rmtree(target)
            if backup is not None and backup.exists():
                os.replace(backup, target)
                self._backups.discard(backup)
            self._fsync_directory(target.parent)

        self._undo.append(undo)

    def replace_file(self, staged: Path, target: Path, *, mode: int) -> None:
        if not staged.is_file() or staged.is_symlink():
            raise ValueError(f"Staged file is invalid: {staged}")
        target.parent.mkdir(parents=True, exist_ok=True)
        localized = target.parent / (
            f".{target.name}.xmg-backlight-stage-{uuid.uuid4().hex}"
        )
        try:
            shutil.copyfile(staged, localized, follow_symlinks=False)
            os.chmod(localized, mode)
            descriptor = os.open(localized, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except Exception:
            try:
                localized.unlink()
            except FileNotFoundError:
                pass
            raise
        backup = None
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file():
                localized.unlink()
                raise ValueError(f"Target is not a regular file: {target}")
            backup = self._backup_path(target)
            os.replace(target, backup)
            self._backups.add(backup)
        try:
            os.replace(localized, target)
            self._fsync_directory(target.parent)
        except Exception:
            try:
                localized.unlink()
            except FileNotFoundError:
                pass
            if backup is not None:
                os.replace(backup, target)
                self._backups.discard(backup)
            raise

        def undo():
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            if backup is not None and backup.exists():
                os.replace(backup, target)
                self._backups.discard(backup)
            self._fsync_directory(target.parent)

        self._undo.append(undo)

    def remove_file(self, target: Path) -> None:
        if not target.exists() and not target.is_symlink():
            return
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"Target is not a regular file: {target}")
        backup = self._backup_path(target)
        os.replace(target, backup)
        self._backups.add(backup)
        self._fsync_directory(target.parent)

        def undo():
            if backup.exists():
                os.replace(backup, target)
                self._backups.discard(backup)
                self._fsync_directory(target.parent)

        self._undo.append(undo)

    def remove_directory(self, target: Path) -> None:
        if not target.exists() and not target.is_symlink():
            return
        if target.is_symlink() or not target.is_dir():
            raise ValueError(f"Target is not a regular directory: {target}")
        backup = self._backup_path(target)
        os.replace(target, backup)
        self._backups.add(backup)
        self._fsync_directory(target.parent)

        def undo():
            if backup.exists():
                os.replace(backup, target)
                self._backups.discard(backup)
                self._fsync_directory(target.parent)

        self._undo.append(undo)

    def commit(self) -> None:
        if self._closed:
            return
        for backup in tuple(self._backups):
            self._remove_backup(backup)
            self._backups.discard(backup)
            self._fsync_directory(backup.parent)
        shutil.rmtree(self.backup_root)
        self._closed = True

    def rollback(self) -> None:
        if self._closed:
            return
        errors = []
        for undo in reversed(self._undo):
            try:
                undo()
            except OSError as exc:
                errors.append(exc)
        try:
            shutil.rmtree(self.backup_root)
        except OSError as exc:
            errors.append(exc)
        if self._backups:
            errors.append(
                RuntimeError(
                    "Recovery backups retained at: "
                    + ", ".join(sorted(map(str, self._backups)))
                )
            )
        self._closed = True
        if errors:
            raise RuntimeError(
                "Filesystem rollback failed: " + "; ".join(map(str, errors))
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False
