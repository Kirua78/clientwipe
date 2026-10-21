from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class ImagingResult:
    command: List[str]
    executed: bool
    returncode: Optional[int] = None
    error: Optional[str] = None


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
    is mostly unit-tested with `subprocess.run` mocked out. Real-condition
    testing (clientwipe live-wipe on a Kali Live session without Clonezilla
    installed) found that a plain subprocess.run() raises FileNotFoundError
    when the binary itself is missing, crashing the caller instead of
    failing cleanly like every other wrapper in this module, hence the
    explicit `shutil.which` check below, matching detect_luks/erase_luks_key/
    schedule_reimage_on_next_boot.
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
    if shutil.which("ocs-sr") is None:
        return ImagingResult(command=command, executed=False, error="ocs-sr (Clonezilla) n'est pas installe")

    if dry_run:
        return ImagingResult(command=command, executed=False)

    completed = subprocess.run(command, cwd=str(images_repository), check=False)
    return ImagingResult(
        command=command,
        executed=True,
        returncode=completed.returncode,
        error=None if completed.returncode == 0 else f"ocs-sr a renvoye le code {completed.returncode}",
    )


@dataclass
class RebootScheduleResult:
    boot_entry: str
    attempted: bool
    scheduled: bool
    error: Optional[str] = None


def schedule_reimage_on_next_boot(boot_entry: str, dry_run: bool = True) -> RebootScheduleResult:
    """Arm the next boot to go straight into a dedicated recovery/imaging
    environment (a GRUB entry running Clonezilla unattended) via
    `grub-reboot`.

    A full disk reimage cannot safely run from the live, currently-booted
    OS. Clonezilla itself is designed to run from separate boot media,
    not against its own running root filesystem. So the USB-triggered path
    only arms the next boot here; the actual restore_golden_image() call
    happens from that recovery environment, after reboot.
    """
    if shutil.which("grub-reboot") is None:
        return RebootScheduleResult(boot_entry=boot_entry, attempted=False, scheduled=False, error="grub-reboot n'est pas disponible")

    if dry_run:
        return RebootScheduleResult(boot_entry=boot_entry, attempted=False, scheduled=False, error="dry-run")

    completed = subprocess.run(["grub-reboot", boot_entry], capture_output=True, text=True, check=False)
    scheduled = completed.returncode == 0
    return RebootScheduleResult(
        boot_entry=boot_entry,
        attempted=True,
        scheduled=scheduled,
        error=None if scheduled else (completed.stderr.strip() or "grub-reboot a renvoye un code d'erreur"),
    )


def reboot_now(dry_run: bool = True) -> bool:
    """Reboot the machine immediately via systemctl. Defaults to dry-run
    (returns False without doing anything) since this is a disruptive,
    irreversible-in-the-moment action."""
    if dry_run or shutil.which("systemctl") is None:
        return False
    completed = subprocess.run(["systemctl", "reboot"], check=False)
    return completed.returncode == 0
