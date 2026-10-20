from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from .imaging import RebootScheduleResult, schedule_reimage_on_next_boot
from .luks import LuksEraseResult, detect_luks, erase_luks_key


@dataclass
class FullWipeReport:
    device: str
    boot_entry: str
    luks_detected: bool
    luks_erase: Optional[LuksEraseResult]
    reboot_scheduled: RebootScheduleResult

    @property
    def passed(self) -> bool:
        if self.luks_detected and (self.luks_erase is None or not self.luks_erase.erased):
            return False
        return self.reboot_scheduled.scheduled

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "boot_entry": self.boot_entry,
            "luks_detected": self.luks_detected,
            "luks_erase": asdict(self.luks_erase) if self.luks_erase else None,
            "reboot_scheduled": asdict(self.reboot_scheduled),
            "passed": self.passed,
        }


def full_wipe(device: str, boot_entry: str, dry_run: bool = True) -> FullWipeReport:
    """Reset every compartment of the machine: detect whether `device` is
    LUKS-encrypted and, if so, destroy its keys first (instant, SSD-safe
    cryptographic erase, see luks.py), then arm the next boot into the
    recovery environment that performs the actual full disk reimage (see
    imaging.schedule_reimage_on_next_boot / restore_golden_image).

    When `device` isn't LUKS-encrypted, the crypto-erase step is simply
    skipped and the flow falls back to reimage-only: still a genuine full
    disk reset, just without the instant-erase guarantee.
    """
    detection = detect_luks(device)

    luks_erase: Optional[LuksEraseResult] = None
    if detection.is_luks:
        luks_erase = erase_luks_key(device, dry_run=dry_run)

    reboot_scheduled = schedule_reimage_on_next_boot(boot_entry, dry_run=dry_run)

    return FullWipeReport(
        device=device,
        boot_entry=boot_entry,
        luks_detected=detection.is_luks,
        luks_erase=luks_erase,
        reboot_scheduled=reboot_scheduled,
    )
