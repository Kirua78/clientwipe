from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml


@dataclass(frozen=True)
class SanitizeTarget:
    """One category of sensitive data to erase (e.g. 'ssh-keys')."""

    name: str
    patterns: List[str]  # glob patterns, relative to the sanitization root


@dataclass(frozen=True)
class Config:
    targets: List[SanitizeTarget]
    passes: int = 3

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        passes = int(raw.get("passes", 3))
        targets = [
            SanitizeTarget(name=t["name"], patterns=list(t["patterns"]))
            for t in raw.get("targets", [])
        ]
        if not targets:
            raise ValueError(f"No sanitize targets defined in {path}")
        return cls(targets=targets, passes=passes)
