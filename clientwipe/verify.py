from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .config import Config
from .sanitize import resolve_target_files


@dataclass
class TargetVerification:
    name: str
    residual_files: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.residual_files


@dataclass
class VerificationReport:
    root: str
    targets: List[TargetVerification]

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.targets)

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "passed": self.passed,
            "targets": [
                {
                    "name": t.name,
                    "passed": t.passed,
                    "residual_files": t.residual_files,
                }
                for t in self.targets
            ],
        }


def verify(root: Path, config: Config) -> VerificationReport:
    """Re-scan the sanitized root for any file still matching a target.

    This is independent from the sanitize pass: it re-globs the same
    patterns against what is actually left on disk, so a bug in the
    erase step (permission error, race condition, etc.) shows up as a
    failed verification instead of a false sense of security.
    """
    root = Path(root)
    target_verifications = []
    for target in config.targets:
        remaining = resolve_target_files(root, target)
        target_verifications.append(
            TargetVerification(name=target.name, residual_files=[str(p) for p in remaining])
        )
    return VerificationReport(root=str(root), targets=target_verifications)
