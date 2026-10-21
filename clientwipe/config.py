from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass(frozen=True)
class SanitizeTarget:
    """One category of sensitive data to erase (e.g. 'ssh-keys')."""

    name: str
    patterns: List[str]  # glob patterns, relative to the sanitization root


@dataclass(frozen=True)
class FullResetConfig:
    """Where to perform a full disk reset: which block device to check for
    LUKS/erase, which GRUB entry to boot into for the actual reimage, and
    (optionally) a mount point, typically the triggering USB key itself,
    where the LUKS header is backed up before the keys are destroyed, as a
    real undo path."""

    device: str
    boot_entry: str
    header_backup_dir: Optional[str] = None
    fallback_wipe_passes: int = 3


@dataclass(frozen=True)
class Config:
    targets: List[SanitizeTarget]
    passes: int = 3
    full_reset: Optional[FullResetConfig] = None

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        passes = int(raw.get("passes", 3))
        targets = [
            SanitizeTarget(name=t["name"], patterns=list(t["patterns"]))
            for t in raw.get("targets", [])
        ]

        full_reset = None
        full_reset_raw = raw.get("full_reset")
        if full_reset_raw:
            full_reset = FullResetConfig(
                device=full_reset_raw["device"],
                boot_entry=full_reset_raw["boot_entry"],
                header_backup_dir=full_reset_raw.get("header_backup_dir"),
                fallback_wipe_passes=int(full_reset_raw.get("fallback_wipe_passes", 3)),
            )

        if not targets and full_reset is None:
            raise ValueError(f"No sanitize targets or full_reset config defined in {path}")
        return cls(targets=targets, passes=passes, full_reset=full_reset)
