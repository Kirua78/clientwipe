from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .imaging import ImagingResult, restore_golden_image
from .luks import LuksEraseResult, LuksHeaderBackupResult, backup_luks_header, detect_luks, erase_luks_key


@dataclass
class LiveWipeReport:
    device: str
    image_name: str
    luks_detected: bool
    header_backup: Optional[LuksHeaderBackupResult]
    luks_erase: Optional[LuksEraseResult]
    imaging: ImagingResult

    @property
    def passed(self) -> bool:
        if self.luks_detected:
            if self.header_backup is not None and not self.header_backup.backed_up:
                return False
            if self.luks_erase is None or not self.luks_erase.erased:
                return False
        return self.imaging.executed and self.imaging.returncode == 0

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "image_name": self.image_name,
            "luks_detected": self.luks_detected,
            "header_backup": asdict(self.header_backup) if self.header_backup else None,
            "luks_erase": asdict(self.luks_erase) if self.luks_erase else None,
            "imaging": asdict(self.imaging),
            "passed": self.passed,
        }


def live_wipe(
    device: str,
    image_name: str,
    images_repository: Path,
    header_backup_path: Optional[Path] = None,
    dry_run: bool = True,
) -> LiveWipeReport:
    """Erase and reimage `device` immediately, from within a live boot
    environment running ON the trusted USB key itself (see the
    `clientwipe live-wipe` command).

    This is the standalone counterpart to full_wipe() (used for the
    USB-trigger-while-the-OS-is-running path): there, the live OS can only
    arm the next boot into a separate recovery environment because it can't
    safely reimage its own running root filesystem. Here, the live-booted
    key *is* that recovery environment already, booting from this key is
    itself the operator's authorization (no udev/systemd/allow-list/GUI
    dialog needed), so the reimage runs right away instead of being
    scheduled.
    """
    detection = detect_luks(device)

    header_backup: Optional[LuksHeaderBackupResult] = None
    luks_erase: Optional[LuksEraseResult] = None

    if detection.is_luks:
        backup_ok = True
        if header_backup_path is not None:
            header_backup = backup_luks_header(device, header_backup_path, dry_run=dry_run)
            backup_ok = dry_run or header_backup.backed_up

        if backup_ok:
            luks_erase = erase_luks_key(device, dry_run=dry_run)

    imaging_result = restore_golden_image(image_name, device, images_repository, dry_run=dry_run)

    return LiveWipeReport(
        device=device,
        image_name=image_name,
        luks_detected=detection.is_luks,
        header_backup=header_backup,
        luks_erase=luks_erase,
        imaging=imaging_result,
    )
