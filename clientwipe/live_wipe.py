from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .bitlocker import detect_bitlocker
from .disk_wipe import DeviceWipeResult, wipe_device
from .imaging import ImagingResult, restore_golden_image
from .inventory import ToolInventoryResult, inventory_installed_packages
from .luks import LuksEraseResult, LuksHeaderBackupResult, backup_luks_header, detect_luks, erase_luks_key


@dataclass
class LiveWipeReport:
    device: str
    image_name: str
    luks_detected: bool
    bitlocker_detected: bool
    header_backup: Optional[LuksHeaderBackupResult]
    luks_erase: Optional[LuksEraseResult]
    device_wipe: Optional[DeviceWipeResult]
    imaging: ImagingResult
    tool_inventory: Optional[ToolInventoryResult]

    @property
    def passed(self) -> bool:
        if self.luks_detected:
            if self.header_backup is not None and not self.header_backup.backed_up:
                return False
            if self.luks_erase is None or not self.luks_erase.erased:
                return False
        else:
            if self.device_wipe is None or not self.device_wipe.completed:
                return False
        return self.imaging.executed and self.imaging.returncode == 0

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "image_name": self.image_name,
            "luks_detected": self.luks_detected,
            "bitlocker_detected": self.bitlocker_detected,
            "header_backup": asdict(self.header_backup) if self.header_backup else None,
            "luks_erase": asdict(self.luks_erase) if self.luks_erase else None,
            "device_wipe": asdict(self.device_wipe) if self.device_wipe else None,
            "imaging": asdict(self.imaging),
            "tool_inventory": asdict(self.tool_inventory) if self.tool_inventory else None,
            "passed": self.passed,
        }


def live_wipe(
    device: str,
    image_name: str,
    images_repository: Path,
    header_backup_path: Optional[Path] = None,
    fallback_wipe_passes: int = 3,
    inventory_output_dir: Optional[Path] = None,
    inventory_mount_point: Path = Path("/mnt/clientwipe-inventory"),
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

    When `device` isn't LUKS-encrypted, it's also checked for BitLocker
    (Windows) and reported as such; see bitlocker.py for why that's
    detection-only. Either way, a multi-pass overwrite of the whole device
    runs as a fallback (see disk_wipe.py) before reimaging.

    If `inventory_output_dir` is set and the reimage succeeds, the restored
    root partition is mounted read-only and its installed packages (name and
    version) are dumped to a JSON file there, confirming the restored system
    matches the expected golden-image baseline. See inventory.py; this is
    informational only and does not affect LiveWipeReport.passed.
    """
    detection = detect_luks(device)

    header_backup: Optional[LuksHeaderBackupResult] = None
    luks_erase: Optional[LuksEraseResult] = None
    device_wipe: Optional[DeviceWipeResult] = None
    bitlocker_detected = False

    if detection.is_luks:
        backup_ok = True
        if header_backup_path is not None:
            header_backup = backup_luks_header(device, header_backup_path, dry_run=dry_run)
            backup_ok = dry_run or header_backup.backed_up

        if backup_ok:
            luks_erase = erase_luks_key(device, dry_run=dry_run)
    else:
        bitlocker_detected = detect_bitlocker(device).is_bitlocker
        device_wipe = wipe_device(device, passes=fallback_wipe_passes, dry_run=dry_run)

    imaging_result = restore_golden_image(image_name, device, images_repository, dry_run=dry_run)

    tool_inventory: Optional[ToolInventoryResult] = None
    if inventory_output_dir is not None and imaging_result.executed and imaging_result.returncode == 0:
        tool_inventory = inventory_installed_packages(device, inventory_output_dir, inventory_mount_point, dry_run=dry_run)

    return LiveWipeReport(
        device=device,
        image_name=image_name,
        luks_detected=detection.is_luks,
        bitlocker_detected=bitlocker_detected,
        header_backup=header_backup,
        luks_erase=luks_erase,
        device_wipe=device_wipe,
        imaging=imaging_result,
        tool_inventory=tool_inventory,
    )
