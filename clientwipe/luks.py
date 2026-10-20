from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class LuksDetectionResult:
    device: str
    is_luks: bool
    error: Optional[str] = None


def detect_luks(device: str) -> LuksDetectionResult:
    """Check whether `device` is a LUKS container.

    Returns is_luks=False (with an explanatory error) when cryptsetup isn't
    available at all, rather than raising. The caller decides what that
    means for the rest of the flow.
    """
    if shutil.which("cryptsetup") is None:
        return LuksDetectionResult(device=device, is_luks=False, error="cryptsetup n'est pas installe")

    completed = subprocess.run(
        ["cryptsetup", "isLuks", device], capture_output=True, text=True, check=False,
    )
    return LuksDetectionResult(device=device, is_luks=completed.returncode == 0)


@dataclass
class LuksEraseResult:
    device: str
    attempted: bool
    erased: bool
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None


def erase_luks_key(device: str, dry_run: bool = True) -> LuksEraseResult:
    """Destroy every LUKS key slot on `device`.

    This is a NIST SP 800-88 cryptographic erase: once the keys are gone,
    every byte of the already-encrypted data on the device is permanently
    unreadable, instantly, with nothing to physically overwrite. It is the
    one Purge-level method that works reliably on SSD/NVMe regardless of
    wear-leveling, unlike multi-pass file overwrite (see sanitize.py).

    Defaults to dry-run: this is irreversible, so the caller must opt in
    explicitly.
    """
    if shutil.which("cryptsetup") is None:
        return LuksEraseResult(device=device, attempted=False, erased=False, error="cryptsetup n'est pas installe")

    if dry_run:
        return LuksEraseResult(device=device, attempted=False, erased=False, error="dry-run")

    completed = subprocess.run(
        ["cryptsetup", "erase", "--batch-mode", device],
        capture_output=True, text=True, check=False,
    )
    erased = completed.returncode == 0
    return LuksEraseResult(
        device=device,
        attempted=True,
        erased=erased,
        stdout=completed.stdout,
        stderr=completed.stderr,
        error=None if erased else (completed.stderr.strip() or "cryptsetup a renvoye un code d'erreur"),
    )
