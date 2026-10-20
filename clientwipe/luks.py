from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
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


@dataclass
class LuksHeaderBackupResult:
    device: str
    backup_path: str
    attempted: bool
    backed_up: bool
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None


def backup_luks_header(device: str, backup_path: Path, dry_run: bool = True) -> LuksHeaderBackupResult:
    """Back up the LUKS header (key slots included) to `backup_path` before
    destroying the live keys with erase_luks_key(). This is the only real
    undo: restoring it later with `cryptsetup luksHeaderRestore` makes the
    original passphrase work again.

    `backup_path`'s parent directory must already be an active mount point
    (typically the triggering USB key itself), not just an existing
    directory. Writing the backup anywhere on the device being erased would
    defeat the whole point, so this refuses rather than silently writing to
    the wrong filesystem if nothing is actually mounted there.
    """
    if shutil.which("cryptsetup") is None:
        return LuksHeaderBackupResult(
            device=device, backup_path=str(backup_path), attempted=False, backed_up=False,
            error="cryptsetup n'est pas installe",
        )

    if not backup_path.parent.is_dir() or not os.path.ismount(backup_path.parent):
        return LuksHeaderBackupResult(
            device=device, backup_path=str(backup_path), attempted=False, backed_up=False,
            error=f"{backup_path.parent} n'est pas un point de montage actif (cle USB non montee ?)",
        )

    if dry_run:
        return LuksHeaderBackupResult(device=device, backup_path=str(backup_path), attempted=False, backed_up=False, error="dry-run")

    completed = subprocess.run(
        ["cryptsetup", "luksHeaderBackup", device, "--header-backup-file", str(backup_path)],
        capture_output=True, text=True, check=False,
    )
    backed_up = completed.returncode == 0
    return LuksHeaderBackupResult(
        device=device,
        backup_path=str(backup_path),
        attempted=True,
        backed_up=backed_up,
        stdout=completed.stdout,
        stderr=completed.stderr,
        error=None if backed_up else (completed.stderr.strip() or "cryptsetup a renvoye un code d'erreur"),
    )
