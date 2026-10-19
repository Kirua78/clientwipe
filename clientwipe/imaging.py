from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class ImagingResult:
    command: List[str]
    executed: bool
    returncode: Optional[int] = None


def restore_golden_image(
    image_name: str,
    device: str,
    images_repository: Path,
    dry_run: bool = True,
) -> ImagingResult:
    """Wrap Clonezilla's `ocs-sr` to restore a golden image onto `device`.

    Defaults to dry-run: a full disk restore is destructive, so it must be
    opted into explicitly by the caller (CLI requires --confirm-reset).
    Requires Clonezilla installed on the host; this repository's demo/test
    environment doesn't have real imaging infrastructure, so this function
    is unit-tested with `subprocess.run` mocked out rather than executed
    for real.
    """
    command = [
        "ocs-sr",
        "-g", "auto",
        "-e1", "auto",
        "-e2",
        "-r",
        "-j2",
        "-p", "poweroff",
        "restoredisk", image_name, device,
    ]
    if dry_run:
        return ImagingResult(command=command, executed=False)

    completed = subprocess.run(command, cwd=str(images_repository), check=False)
    return ImagingResult(command=command, executed=True, returncode=completed.returncode)
