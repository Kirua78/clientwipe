from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Optional

_NVME_NAMESPACE_RE = re.compile(r"^/dev/nvme\d+n\d+$")

ProgressCallback = Callable[[Optional[float]], None]


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


def _shred_write_bytes(pid: int) -> Optional[int]:
    """Bytes written so far by the shred process `pid`, from its own
    /proc/<pid>/io. A thin, separately-monkeypatchable seam so tests do not
    need a real process and a real /proc filesystem to exercise the
    polling loop in _run_shred below.
    """
    try:
        with open(f"/proc/{pid}/io", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("write_bytes:"):
                    return int(line.split(":", 1)[1].strip())
    except (OSError, ValueError):
        return None
    return None


def _nvme_format_erase(device: str, ses: int, method: str) -> DeviceWipeResult:
    completed = subprocess.run(
        ["nvme", "format", device, f"--ses={ses}", "--force"],
        capture_output=True, text=True, check=False,
    )
    ok = completed.returncode == 0
    return DeviceWipeResult(
        device=device, passes=1, method=method, attempted=True, completed=ok,
        error=None if ok else (completed.stderr.strip() or completed.stdout.strip() or "nvme format a echoue"),
    )


def _nvme_erase(device: str) -> DeviceWipeResult:
    """Erase via the NVMe controller's own Format NVM command, through
    nvme-cli. Near instant regardless of capacity, and unlike a software
    overwrite it also reaches blocks the OS can never address directly
    (over-provisioning, wear-leveled remaps), so this is a Purge-level
    method NIST SP 800-88 recognizes for NVMe/SSD media, well ahead of a
    multi-hour software overwrite.

    Tries Cryptographic Erase (ses=2) first: strongest and still instant.
    Not every controller implements it though (observed on real consumer
    hardware: rejected with an "Invalid Format" status, not a clearer
    "unsupported" one), so User Data Erase (ses=1) is tried next if it
    fails: a weaker but still controller-level, NIST-recognized Purge
    technique, and much more widely supported.
    """
    crypto_erase = _nvme_format_erase(device, ses=2, method="nvme-format-crypto-erase")
    if crypto_erase.completed:
        return crypto_erase
    return _nvme_format_erase(device, ses=1, method="nvme-format-user-data-erase")


def _notify(progress_callback: Optional[ProgressCallback], fraction: Optional[float]) -> None:
    if progress_callback is not None:
        progress_callback(fraction)


def _run_shred(device: str, passes: int, progress_callback: Optional[ProgressCallback]) -> DeviceWipeResult:
    """Run shred while reporting real progress, polling /proc/<pid>/io for
    bytes written so far against the total bytes shred will write (device
    size times passes, plus the final --zero pass). Found this necessary
    in practice: shred itself prints nothing in between start and finish,
    and without it an operator watching the GUI has no way to tell a
    multi-hour overwrite is progressing from one that has silently died.
    """
    total_bytes: Optional[int]
    try:
        total_bytes = _device_size_bytes(device)
    except OSError:
        total_bytes = None
    total_write_bytes = total_bytes * (passes + 1) if total_bytes else None

    process = subprocess.Popen(
        ["shred", f"--iterations={passes}", "--zero", device],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )

    while process.poll() is None:
        time.sleep(1)
        fraction = None
        if total_write_bytes:
            written = _shred_write_bytes(process.pid)
            if written is not None:
                fraction = min(written / total_write_bytes, 0.99)
        _notify(progress_callback, fraction)

    stderr = process.stderr.read() if process.stderr else ""
    ok = process.returncode == 0
    _notify(progress_callback, 1.0 if ok else None)
    return DeviceWipeResult(
        device=device, passes=passes, method="shred", attempted=True, completed=ok,
        error=None if ok else (stderr.strip() or "shred a renvoye un code d'erreur"),
    )


def wipe_device(
    device: str, passes: int = 3, dry_run: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
) -> DeviceWipeResult:
    """Erase an entire block device.

    On an NVMe namespace with nvme-cli available, tries a controller-level
    erase first (see _nvme_erase): seconds, not hours, and a real
    Purge-level guarantee since it operates below the OS's view of the
    drive. Falls back to a multi-pass software overwrite only when that is
    not possible (not NVMe, nvme-cli missing, or the controller rejects
    both Format NVM variants it tries).

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

    `progress_callback`, when given, is called with a fraction between 0.0
    and 1.0, or None when progress cannot be estimated (the NVMe and
    pure-Python-overwrite paths only report start/end; real intermediate
    progress is only available for the shred path, see _run_shred).
    """
    if _is_nvme_namespace(device) and shutil.which("nvme") is not None:
        if dry_run:
            return DeviceWipeResult(
                device=device, passes=1, method="nvme-format-crypto-erase", attempted=False, completed=False,
            )
        _notify(progress_callback, None)
        nvme_result = _nvme_erase(device)
        if nvme_result.completed:
            _notify(progress_callback, 1.0)
            return nvme_result

    method = "shred" if shutil.which("shred") is not None else "overwrite-fallback"

    if dry_run:
        return DeviceWipeResult(device=device, passes=passes, method=method, attempted=False, completed=False)

    if method == "shred":
        return _run_shred(device, passes, progress_callback)

    try:
        size = _device_size_bytes(device)
        chunk_size = 4 * 1024 * 1024
        total_chunks = passes * max((size + chunk_size - 1) // chunk_size, 1)
        chunks_done = 0
        with open(device, "r+b") as handle:
            for _ in range(passes):
                handle.seek(0)
                written = 0
                while written < size:
                    chunk = min(chunk_size, size - written)
                    handle.write(secrets.token_bytes(chunk))
                    written += chunk
                    chunks_done += 1
                    _notify(progress_callback, min(chunks_done / total_chunks, 0.99))
                handle.flush()
                os.fsync(handle.fileno())
        _notify(progress_callback, 1.0)
        return DeviceWipeResult(device=device, passes=passes, method=method, attempted=True, completed=True)
    except OSError as exc:
        _notify(progress_callback, None)
        return DeviceWipeResult(
            device=device, passes=passes, method=method, attempted=True, completed=False, error=str(exc),
        )
