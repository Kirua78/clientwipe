from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

ProgressCallback = Callable[[Optional[float]], None]

_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def _open_pty():
    """A separately-monkeypatchable seam around pty.openpty(), imported
    lazily here rather than at module level: pty depends on termios, which
    does not exist on Windows, and this whole module must stay importable
    there too (clientwipe itself only ever runs on Linux, but its test
    suite is developed cross-platform).
    """
    import pty

    return pty.openpty()


@dataclass
class ImagingResult:
    command: List[str]
    executed: bool
    returncode: Optional[int] = None
    error: Optional[str] = None


def _drain_progress(master_fd: int, progress_callback: ProgressCallback) -> None:
    """Read from `master_fd` until it closes, extracting the latest
    percentage seen so far and reporting it whenever it changes.

    Reads through a pty rather than a plain pipe: most CLI tools (partclone
    included) fully buffer stdout when it is not a terminal, which would
    hold back all output until the process exits, making "live" progress
    parsing pointless. A pty makes the child think it is talking to an
    interactive terminal, so the carriage-return-driven progress line
    Clonezilla/partclone print actually streams instead of being withheld.
    """
    buffer = ""
    last_fraction: Optional[float] = None
    while True:
        try:
            chunk = os.read(master_fd, 1024)
        except OSError:
            break
        if not chunk:
            break
        buffer += chunk.decode("utf-8", errors="replace")
        buffer = buffer[-4096:]

        # Report every match seen so far, not just the last one: a single
        # read() can return several progress updates at once (observed in
        # tests, and plausible in practice under OS buffering jitter), and
        # only taking the last would silently skip the ones in between.
        # Already-reported fractions are naturally skipped by the
        # last_fraction check below even though they stay in `buffer` (it
        # is a sliding window, not consumed).
        for match in _PERCENT_RE.finditer(buffer):
            try:
                fraction = min(float(match.group(1)) / 100.0, 0.99)
            except ValueError:
                continue
            if fraction != last_fraction:
                last_fraction = fraction
                progress_callback(fraction)


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

    `progress_callback`, when given, is called with a fraction between 0.0
    and 1.0 (see _drain_progress) each time a new percentage is seen in
    ocs-sr/partclone's output, and once more with 1.0 (or None on failure)
    when the restore finishes. When it is not given, this runs exactly as
    before (a plain blocking subprocess.run()), so existing callers (the
    CLI) are unaffected.
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

    if progress_callback is None:
        completed = subprocess.run(command, cwd=str(images_repository), check=False)
        return ImagingResult(
            command=command,
            executed=True,
            returncode=completed.returncode,
            error=None if completed.returncode == 0 else f"ocs-sr a renvoye le code {completed.returncode}",
        )

    master_fd, slave_fd = _open_pty()
    process = subprocess.Popen(command, cwd=str(images_repository), stdout=slave_fd, stderr=slave_fd, close_fds=True)
    os.close(slave_fd)
    try:
        _drain_progress(master_fd, progress_callback)
    finally:
        os.close(master_fd)

    returncode = process.wait()
    progress_callback(1.0 if returncode == 0 else None)
    return ImagingResult(
        command=command,
        executed=True,
        returncode=returncode,
        error=None if returncode == 0 else f"ocs-sr a renvoye le code {returncode}",
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
