from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

ProgressCallback = Callable[[Optional[float]], None]

_PARTIMAG = Path("/home/partimag")


@dataclass
class ImagingResult:
    command: List[str]
    executed: bool
    returncode: Optional[int] = None
    error: Optional[str] = None


def _bind_mount_partimag(images_repository: Path) -> Optional[str]:
    """ocs-sr hardcodes /home/partimag as its images repository and
    ignores `cwd` entirely: found on real hardware, where it refused
    outright with "Please make sure your /home/partimag is a directory!!!"
    before even starting, independent of every stdin/env/session fix tried
    before this one. Bind-mounts the actual, dynamically found repository
    (see find_images_repository, which can land on any partition) onto
    that fixed path. Returns an error message on failure, None on success.
    """
    _PARTIMAG.mkdir(parents=True, exist_ok=True)
    # Clears out any stale mount left behind by an earlier, interrupted
    # run in the same boot session; harmless no-op otherwise.
    subprocess.run(["umount", str(_PARTIMAG)], capture_output=True, text=True, check=False)
    completed = subprocess.run(
        ["mount", "--bind", str(images_repository), str(_PARTIMAG)],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        return completed.stderr.strip() or "mount --bind a echoue"
    return None


def _unmount_partimag() -> None:
    subprocess.run(["umount", str(_PARTIMAG)], capture_output=True, text=True, check=False)


def restore_golden_image(
    image_name: str,
    device: str,
    images_repository: Path,
    dry_run: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
) -> ImagingResult:
    """Wrap Clonezilla's `ocs-sr` to restore a golden image onto `device`.

    Defaults to dry-run: a full disk restore is destructive, so it must be
    opted into explicitly by the caller (CLI requires --confirm-reset).
    Requires Clonezilla installed on the host; this repository's demo/test
    environment doesn't have real imaging infrastructure, so this function
    is mostly unit-tested with `subprocess.run`/`subprocess.Popen` mocked
    out. Real-condition testing (clientwipe live-wipe on a Kali Live
    session without Clonezilla installed) found that a plain
    subprocess.run() raises FileNotFoundError when the binary itself is
    missing, crashing the caller instead of failing cleanly like every
    other wrapper in this module, hence the explicit `shutil.which` check
    below, matching detect_luks/erase_luks_key/schedule_reimage_on_next_boot.

    `progress_callback`, when given, is called with None just before ocs-sr
    starts and with 1.0 (or None on failure) once it finishes, so a caller
    can show "this step is running" without a stalled or stale display.
    It does not get a real percentage: an earlier version captured ocs-sr's
    output live through a pty to parse one out of Clonezilla/partclone's
    own progress text, but that hung real restores indefinitely on actual
    hardware. Reverted, but the hang turned out not to be the pty after
    all: it reproduced identically with a plain subprocess.run(), stdin
    inherited as usual. Adding `stdin=subprocess.DEVNULL` alone did not fix
    it either: ocs-sr is Clonezilla's live-scripts toolkit, which is known
    to read some of its confirmations straight from /dev/tty rather than
    stdin precisely so a redirected stdin cannot silence them, so it still
    found something to block on even then. The combination below finally
    worked in testing: `ocs_batch_mode=1` is the environment variable
    Clonezilla's own docs name for unattended use (meant for PXE/scripted
    deployments exactly like this one), suppressing those prompts at the
    source instead of trying to out-redirect them, and
    `start_new_session=True` detaches the child from any controlling
    terminal entirely, so even /dev/tty is not available to read from if
    something still tries.

    All three of those were real fixes for real problems, but none of
    them were actually why ocs-sr kept failing on real hardware: it was
    refusing outright, before any of this mattered, because it hardcodes
    /home/partimag as its images repository and ignores `cwd` completely.
    See _bind_mount_partimag.
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

    mount_error = _bind_mount_partimag(images_repository)
    if mount_error is not None:
        return ImagingResult(
            command=command, executed=False,
            error=f"Impossible de preparer /home/partimag (requis par ocs-sr) : {mount_error}",
        )

    try:
        if progress_callback is not None:
            progress_callback(None)

        env = {**os.environ, "ocs_batch_mode": "1"}
        completed = subprocess.run(
            command, cwd=str(images_repository), stdin=subprocess.DEVNULL,
            env=env, start_new_session=True, check=False,
        )

        if progress_callback is not None:
            progress_callback(1.0 if completed.returncode == 0 else None)

        return ImagingResult(
            command=command,
            executed=True,
            returncode=completed.returncode,
            error=None if completed.returncode == 0 else f"ocs-sr a renvoye le code {completed.returncode}",
        )
    finally:
        _unmount_partimag()


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
