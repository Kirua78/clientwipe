from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .config import Config, SanitizeTarget


@dataclass
class TargetResult:
    name: str
    files_wiped: int = 0
    bytes_wiped: int = 0
    errors: List[str] = field(default_factory=list)


@dataclass
class SanitizeReport:
    root: str
    method: str
    passes: int
    started_at: float
    finished_at: float
    targets: List[TargetResult]

    @property
    def duration_seconds(self) -> float:
        return round(self.finished_at - self.started_at, 3)

    @property
    def total_files_wiped(self) -> int:
        return sum(t.files_wiped for t in self.targets)

    @property
    def total_bytes_wiped(self) -> int:
        return sum(t.bytes_wiped for t in self.targets)

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "method": self.method,
            "passes": self.passes,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "total_files_wiped": self.total_files_wiped,
            "total_bytes_wiped": self.total_bytes_wiped,
            "targets": [
                {
                    "name": t.name,
                    "files_wiped": t.files_wiped,
                    "bytes_wiped": t.bytes_wiped,
                    "errors": t.errors,
                }
                for t in self.targets
            ],
        }


def _shred_available() -> bool:
    return shutil.which("shred") is not None


def _overwrite_and_remove(path: Path, passes: int) -> None:
    size = path.stat().st_size
    with open(path, "r+b") as handle:
        for _ in range(passes):
            handle.seek(0)
            handle.write(secrets.token_bytes(size))
            handle.flush()
            os.fsync(handle.fileno())
    path.unlink()


def secure_delete_file(path: Path, passes: int = 3, use_shred: Optional[bool] = None) -> int:
    """Securely erase a single file and return the number of bytes wiped.

    Prefers the Linux `shred` utility (real multi-pass overwrite) when
    available, and falls back to a pure-Python overwrite so the tool still
    works for development/testing on platforms without `shred`.
    """
    size = path.stat().st_size
    if use_shred is None:
        use_shred = _shred_available()
    if use_shred:
        subprocess.run(
            ["shred", "--remove", f"--iterations={passes}", "--zero", str(path)],
            check=True,
        )
    else:
        _overwrite_and_remove(path, passes)
    return size


def resolve_target_files(root: Path, target: SanitizeTarget) -> List[Path]:
    """Resolve a target's glob patterns to actual files.

    A pattern starting with "/" is absolute and resolved from the
    filesystem root, independent of --root (for known sensitive locations
    outside the user profile, e.g. "/opt/pentest-tools/**" or a mounted
    loot drive). Any other pattern stays relative to --root, as before.
    """
    files: List[Path] = []
    for pattern in target.patterns:
        if pattern.startswith("/"):
            base, relative_pattern = Path("/"), pattern.lstrip("/")
        else:
            base, relative_pattern = root, pattern
        files.extend(p for p in base.glob(relative_pattern) if p.is_file())
    seen = set()
    unique: List[Path] = []
    for file_path in files:
        if file_path not in seen:
            seen.add(file_path)
            unique.append(file_path)
    return unique


def sanitize(root: Path, config: Config) -> SanitizeReport:
    root = Path(root)
    method = "shred" if _shred_available() else "overwrite-fallback"
    started_at = time.time()
    target_results: List[TargetResult] = []

    for target in config.targets:
        result = TargetResult(name=target.name)
        for file_path in resolve_target_files(root, target):
            try:
                result.bytes_wiped += secure_delete_file(file_path, passes=config.passes)
                result.files_wiped += 1
            except OSError as exc:
                result.errors.append(f"{file_path}: {exc}")
        target_results.append(result)

    finished_at = time.time()
    return SanitizeReport(
        root=str(root),
        method=method,
        passes=config.passes,
        started_at=started_at,
        finished_at=finished_at,
        targets=target_results,
    )
