from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

_NVME_NAMESPACE_RE = re.compile(r"^/dev/nvme\d+n\d+$")


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


def _is_nvme_namespace(device: str) -> bool:
    return bool(_NVME_NAMESPACE_RE.match(device))


def _nvme_crypto_erase(device: str) -> DeviceWipeResult:
    """Cryptographic erase via the NVMe controller's own Format NVM command
    (ses=2), through nvme-cli. Near instant regardless of capacity, and
    unlike a software overwrite it also reaches blocks the OS can never
    address directly (over-provisioning, wear-leveled remaps), so this is
    the Purge-level method NIST SP 800-88 actually recommends for
    NVMe/SSD media, well ahead of a multi-hour software overwrite.
    """
    completed = subprocess.run(
        ["nvme", "format", device, "--ses=2", "--force"],
        capture_output=True, text=True, check=False,
    )
    ok = completed.returncode == 0
    return DeviceWipeResult(
        device=device, passes=1, method="nvme-format-crypto-erase", attempted=True, completed=ok,
        error=None if ok else (completed.stderr.strip() or completed.stdout.strip() or "nvme format a echoue"),
    )


def wipe_device(device: str, passes: int = 3, dry_run: bool = True) -> DeviceWipeResult:
    """Erase an entire block device.

    On an NVMe namespace with nvme-cli available, tries a controller-level
    cryptographic erase first (see _nvme_crypto_erase): seconds, not hours,
    and a real Purge-level guarantee since it operates below the OS's view
    of the drive. Falls back to a multi-pass software overwrite only when
    that is not possible (not NVMe, nvme-cli missing, or the controller
    rejects the command, e.g. no crypto erase support).

    The software fallback is used when no LUKS key is available to destroy
    either (no encryption at all, or BitLocker, which this tool can't
    erase, see bitlocker.py). Overwriting every byte destroys any
    encryption metadata too, not just plain data, so this strengthens the
    Clear-level guarantee for those cases, at the cost of a full-disk
    write (much slower than either erase method above).

    Still only a Clear-level guarantee on SSD/NVMe, not a verified Purge:
    wear-leveling means some physical cells may not be overwritten even
    after multiple logical passes. See luks.py for why LUKS crypto-erase
    is preferred whenever available. This is strictly the degraded-case
    fallback.
    """
    if _is_nvme_namespace(device) and shutil.which("nvme") is not None:
        if dry_run:
            return DeviceWipeResult(
                device=device, passes=1, method="nvme-format-crypto-erase", attempted=False, completed=False,
            )
        nvme_result = _nvme_crypto_erase(device)
        if nvme_result.completed:
            return nvme_result

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
