from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Set


def _parse_allowlist(lines: Iterable[str]) -> Set[str]:
    serials = set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        serials.add(line)
    return serials


def load_allowlist(path: Path) -> Set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    return _parse_allowlist(path.read_text(encoding="utf-8").splitlines())


def is_allowed(serial: Optional[str], allowlist_path: Path) -> bool:
    """Defense in depth: the udev rule already filters by serial, this is
    re-checked in Python so a misconfigured rule or a crafted ID_SERIAL_SHORT
    cannot bypass the allow-list."""
    if not serial:
        return False
    return serial.strip() in load_allowlist(allowlist_path)
