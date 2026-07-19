"""Validation for bundled, immutable wheel artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class ArtifactValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class BundledArtifact:
    path: Path
    sha256: str


@dataclass(frozen=True)
class ArtifactManifest:
    driver_distribution: str
    driver_version: str
    artifacts: tuple[BundledArtifact, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_and_validate_manifest(manifest_path: Path) -> ArtifactManifest:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError(f"Cannot read artifact manifest: {exc}") from exc
    if payload.get("schema") != 1:
        raise ArtifactValidationError("Unsupported artifact manifest schema")
    distribution = payload.get("driver_distribution")
    version = payload.get("driver_version")
    rows = payload.get("artifacts")
    if not isinstance(distribution, str) or not distribution:
        raise ArtifactValidationError("Missing driver distribution")
    if not isinstance(version, str) or not version:
        raise ArtifactValidationError("Missing driver version")
    if not isinstance(rows, list) or not rows:
        raise ArtifactValidationError("Artifact list is empty")
    root = manifest_path.resolve().parent
    artifacts = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ArtifactValidationError("Invalid artifact record")
        filename = row.get("filename")
        expected = row.get("sha256")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ArtifactValidationError(f"Unsafe artifact filename: {filename!r}")
        if filename in seen:
            raise ArtifactValidationError(f"Duplicate artifact: {filename}")
        seen.add(filename)
        if not isinstance(expected, str) or len(expected) != 64:
            raise ArtifactValidationError(f"Invalid SHA-256 for {filename}")
        path = root / filename
        if not path.is_file() or path.is_symlink():
            raise ArtifactValidationError(f"Missing regular artifact: {path}")
        actual = _sha256(path)
        if actual != expected.lower():
            raise ArtifactValidationError(
                f"SHA-256 mismatch for {filename}: expected {expected}, got {actual}"
            )
        artifacts.append(BundledArtifact(path=path, sha256=actual))
    driver_prefix = f"ite8291r3_ctl-{version}-"
    if not any(item.path.name.startswith(driver_prefix) for item in artifacts):
        raise ArtifactValidationError(
            f"No driver wheel matches declared version {version}"
        )
    return ArtifactManifest(
        driver_distribution=distribution,
        driver_version=version,
        artifacts=tuple(artifacts),
    )
