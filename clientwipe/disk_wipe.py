from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeviceWipeResult:
    device: str
    passes: int
    method: str
    attempted: bool
    completed: bool
    error: Optional[str] = None


def _device_size_bytes(device: str) -> int:
    with open(device, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        return handle.tell()


def wipe_device(device: str, passes: int = 3, dry_run: bool = True) -> DeviceWipeResult:
    """Multi-pass overwrite of an entire block device.

    Used as a fallback only: when no LUKS key is available to destroy
    (no encryption at all, or BitLocker, which this tool can't erase, see
    bitlocker.py). Overwriting every byte destroys any encryption
    metadata too, not just plain data, so this strengthens the Clear-level
    guarantee for those cases, at the cost of a full-disk write (slow:
    hours, not seconds, unlike LUKS key destruction).

    Still only a Clear-level guarantee on SSD/NVMe, not a verified Purge:
    wear-leveling means some physical cells may not be overwritten even
    after multiple logical passes. See luks.py for why LUKS crypto-erase
    is preferred whenever available. This is strictly the degraded-case
    fallback.
    """
    method = "shred" if shutil.which("shred") is not None else "overwrite-fallback"

    if dry_run:
        return DeviceWipeResult(device=device, passes=passes, method=method, attempted=False, completed=False)

    if method == "shred":
        completed = subprocess.run(
            ["shred", f"--iterations={passes}", "--zero", device],
            capture_output=True, text=True, check=False,
        )
        ok = completed.returncode == 0
        return DeviceWipeResult(
            device=device, passes=passes, method=method, attempted=True, completed=ok,
            error=None if ok else (completed.stderr.strip() or "shred a renvoye un code d'erreur"),
        )

    try:
        size = _device_size_bytes(device)
        chunk_size = 4 * 1024 * 1024
        with open(device, "r+b") as handle:
            for _ in range(passes):
                handle.seek(0)
                written = 0
                while written < size:
                    chunk = min(chunk_size, size - written)
                    handle.write(secrets.token_bytes(chunk))
                    written += chunk
                handle.flush()
                os.fsync(handle.fileno())
        return DeviceWipeResult(device=device, passes=passes, method=method, attempted=True, completed=True)
    except OSError as exc:
        return DeviceWipeResult(
            device=device, passes=passes, method=method, attempted=True, completed=False, error=str(exc),
        )
