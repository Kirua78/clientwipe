from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

ProgressCallback = Callable[[Optional[float]], None]

_PARTIMAG = Path("/home/partimag")
_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_LAST_OUTPUT_LOG = Path("/var/log/clientwipe/last-reimaging-output.log")


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


def _open_pty():
    """A separately-monkeypatchable seam around pty.openpty(), imported
    lazily here rather than at module level: pty depends on termios, which
    does not exist on Windows, and this module must stay importable there
    too (clientwipe itself only ever runs on Linux, but its tests are
    developed cross-platform).
    """
    import pty

    return pty.openpty()


def _drain_progress(master_fd: int, progress_callback: ProgressCallback) -> None:
    """Read from `master_fd` until it closes, extracting the latest
    percentage seen so far and reporting it whenever it changes, and
    saving everything read to _LAST_OUTPUT_LOG along the way.

    Reads through a pty rather than a plain pipe: most CLI tools (partclone
    included) fully buffer stdout when it is not a terminal, which would
    hold back all output until the process exits, making "live" progress
    parsing pointless. A pty makes the child think it is talking to an
    interactive terminal, so the carriage-return-driven progress line
    Clonezilla/partclone print actually streams instead of being withheld.

    The log file exists because the percentage is all this function keeps:
    everything else read from ocs-sr is discarded once scanned. Found on
    real hardware to matter: a restore that got far enough to show a
    percentage still failed (ocs-sr returncode 1) with nothing beyond that
    generic code to say why, and by then the only copy of its actual
    output no longer existed anywhere to check.
    """
    buffer = ""
    last_fraction: Optional[float] = None
    _LAST_OUTPUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_LAST_OUTPUT_LOG, "w", encoding="utf-8", errors="replace") as log_file:
        while True:
            try:
                chunk = os.read(master_fd, 1024)
            except OSError:
                break
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            log_file.write(text)
            log_file.flush()

            buffer += text
            buffer = buffer[-4096:]

            # Report every match seen so far, not just the last one: a
            # single read() can return several progress updates at once,
            # and only taking the last would silently skip the ones in
            # between. Already reported fractions are naturally skipped by
            # the last_fraction check even though they stay in `buffer`
            # (a sliding window, not consumed).
            for match in _PERCENT_RE.finditer(buffer):
                try:
                    fraction = min(float(match.group(1)) / 100.0, 0.99)
                except ValueError:
                    continue
                if fraction != last_fraction:
                    last_fraction = fraction
                    progress_callback(fraction)


def _run_ocs_sr_with_progress(
    command: List[str], images_repository: Path, env: dict, progress_callback: ProgressCallback,
) -> int:
    """Same process setup as the plain subprocess.run() path (stdin
    silenced, batch mode, detached session, see restore_golden_image's
    docstring for why each of those is there), but through a pty so
    ocs-sr/partclone's own progress text can be parsed out live instead of
    only reporting start/end. Reintroduced after _bind_mount_partimag was
    found to be the real reason an earlier version of this hung on real
    hardware: that was never actually the pty's fault, just always tested
    together with the /home/partimag bug still present.
    """
    master_fd, slave_fd = _open_pty()
    process = subprocess.Popen(
        command, cwd=str(images_repository), stdin=subprocess.DEVNULL,
        stdout=slave_fd, stderr=slave_fd, env=env, start_new_session=True,
    )
    os.close(slave_fd)
    try:
        _drain_progress(master_fd, progress_callback)
    finally:
        os.close(master_fd)
    return process.wait()


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
    starts, with a fraction between 0.0 and 1.0 (see _drain_progress) each
    time a new percentage is seen in ocs-sr/partclone's own output, and
    with 1.0 (or None on failure) once it finishes. If the pattern it
    expects never shows up (Clonezilla changes its output format, for
    instance), this degrades to only the start/end calls rather than
    showing a stale or fabricated number.

    `stdin=subprocess.DEVNULL` below guarantees ocs-sr's own prompts (some
    read straight from /dev/tty rather than stdin, specifically so a
    redirected stdin cannot silence them) cannot block waiting for input;
    `ocs_batch_mode=1` is the environment variable Clonezilla's own docs
    name for unattended use (meant for exactly this kind of scripted
    deployment), suppressing those prompts at the source; and
    `start_new_session=True` detaches the child from any controlling
    terminal entirely, so even /dev/tty is not available to read from if
    something still tries. All three were found necessary on real
    hardware, but turned out not to be the actual reason ocs-sr kept
    failing there: it was refusing outright, before any of this mattered,
    because it hardcodes /home/partimag as its images repository and
    ignores `cwd` completely. See _bind_mount_partimag. An even earlier
    version used a pty to capture live progress the same way this one
    does, got blamed for the hang that was really /home/partimag, and was
    reverted; reading ocs-sr's output through a pty was never actually the
    problem, so it is back.
    """
    command = [
        "ocs-sr",
        "-g", "auto",
        "-e1", "auto",
        "-e2",
        "-r",
        "-j2",
        "-p", "true",
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
        env = {**os.environ, "ocs_batch_mode": "1"}

        output_log_hint = ""
        if progress_callback is None:
            completed = subprocess.run(
                command, cwd=str(images_repository), stdin=subprocess.DEVNULL,
                env=env, start_new_session=True, check=False,
            )
            returncode = completed.returncode
        else:
            progress_callback(None)
            returncode = _run_ocs_sr_with_progress(command, images_repository, env, progress_callback)
            progress_callback(1.0 if returncode == 0 else None)
            output_log_hint = f" (sortie complete : {_LAST_OUTPUT_LOG})"

        return ImagingResult(
            command=command,
            executed=True,
            returncode=returncode,
            error=None if returncode == 0 else f"ocs-sr a renvoye le code {returncode}{output_log_hint}",
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
