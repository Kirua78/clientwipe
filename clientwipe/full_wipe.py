from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .bitlocker import detect_bitlocker
from .disk_wipe import DeviceWipeResult, wipe_device
from .imaging import RebootScheduleResult, schedule_reimage_on_next_boot
from .luks import LuksEraseResult, LuksHeaderBackupResult, backup_luks_header, detect_luks, erase_luks_key


@dataclass
class FullWipeReport:
    device: str
    boot_entry: str
    luks_detected: bool
    bitlocker_detected: bool
    header_backup: Optional[LuksHeaderBackupResult]
    luks_erase: Optional[LuksEraseResult]
    device_wipe: Optional[DeviceWipeResult]
    reboot_scheduled: RebootScheduleResult

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
        return self.reboot_scheduled.scheduled

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "boot_entry": self.boot_entry,
            "luks_detected": self.luks_detected,
            "bitlocker_detected": self.bitlocker_detected,
            "header_backup": asdict(self.header_backup) if self.header_backup else None,
            "luks_erase": asdict(self.luks_erase) if self.luks_erase else None,
            "device_wipe": asdict(self.device_wipe) if self.device_wipe else None,
            "reboot_scheduled": asdict(self.reboot_scheduled),
            "passed": self.passed,
        }


def full_wipe(
    device: str,
    boot_entry: str,
    header_backup_path: Optional[Path] = None,
    fallback_wipe_passes: int = 3,
    dry_run: bool = True,
) -> FullWipeReport:
    """Reset every compartment of the machine: detect whether `device` is
    LUKS-encrypted and, if so, back up its header (if `header_backup_path`
    is given, the real undo path, see luks.backup_luks_header) and
    destroy its keys (instant, SSD-safe cryptographic erase, see luks.py),
    then arm the next boot into the recovery environment that performs the
    actual full disk reimage (see imaging.schedule_reimage_on_next_boot /
    restore_golden_image).

    If a header backup is requested but fails (USB key not mounted, no
    cryptsetup...), the key is NOT erased: destroying the only copy without
    a confirmed backup would defeat the whole point of asking for one.

    When `device` isn't LUKS-encrypted, it's also checked for BitLocker
    (Windows) and reported as such (see bitlocker.py for why that's
    detection-only, not erasure). Either way, a multi-pass overwrite of the
    whole device runs as a fallback (see disk_wipe.py): slower than LUKS
    key destruction, but it also destroys any BitLocker metadata along
    with the rest, since there is no equivalent of `cryptsetup erase` for
    that format.
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

    reboot_scheduled = schedule_reimage_on_next_boot(boot_entry, dry_run=dry_run)

    return FullWipeReport(
        device=device,
        boot_entry=boot_entry,
        luks_detected=detection.is_luks,
        bitlocker_detected=bitlocker_detected,
        header_backup=header_backup,
        luks_erase=luks_erase,
        device_wipe=device_wipe,
        reboot_scheduled=reboot_scheduled,
    )
