"""BitLocker detection (Windows targets), read-only.

Unlike luks.py, this module does not attempt to destroy key material.
BitLocker stores its key metadata (FVE) in blocks whose exact on-disk
offsets vary across Windows versions, and there is no cryptsetup
equivalent of `cryptsetup erase` for the BITLK format. Overwriting the
wrong bytes "by hand" without a real BitLocker-encrypted Windows machine
to validate against would risk either missing a backup metadata copy
(leaving data recoverable) or corrupting the volume without actually
achieving a verified Purge-level erase. A false guarantee is worse than
an honest Clear-level one. So a detected BitLocker target is reported as
such and routed through the ordinary reimage-only (Clear) path; see
full_wipe.py / live_wipe.py.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class BitlockerDetectionResult:
    device: str
    is_bitlocker: bool
    error: Optional[str] = None


def detect_bitlocker(device: str) -> BitlockerDetectionResult:
    """Check whether `device` is a BitLocker-encrypted volume.

    Uses cryptsetup's BITLK format support (`bitlkDump`, cryptsetup 2.3+),
    which parses BitLocker volume headers from Linux without any Windows
    tooling. Detection only, see the module docstring for why.
    """
    if shutil.which("cryptsetup") is None:
        return BitlockerDetectionResult(device=device, is_bitlocker=False, error="cryptsetup n'est pas installe")

    completed = subprocess.run(
        ["cryptsetup", "bitlkDump", device], capture_output=True, text=True, check=False,
    )
    return BitlockerDetectionResult(device=device, is_bitlocker=completed.returncode == 0)
