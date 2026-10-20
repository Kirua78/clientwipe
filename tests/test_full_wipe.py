from clientwipe import full_wipe as full_wipe_module
from clientwipe.imaging import RebootScheduleResult
from clientwipe.luks import LuksDetectionResult, LuksEraseResult


def test_full_wipe_skips_luks_erase_when_not_encrypted(monkeypatch):
    monkeypatch.setattr(
        full_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=False),
    )
    monkeypatch.setattr(
        full_wipe_module, "schedule_reimage_on_next_boot",
        lambda boot_entry, dry_run: RebootScheduleResult(boot_entry=boot_entry, attempted=True, scheduled=True),
    )

    report = full_wipe_module.full_wipe("/dev/sda", "Clonezilla Recovery", dry_run=False)

    assert report.luks_detected is False
    assert report.luks_erase is None
    assert report.passed is True


def test_full_wipe_erases_luks_key_when_encrypted(monkeypatch):
    monkeypatch.setattr(
        full_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=True),
    )

    erase_calls = {}

    def fake_erase(device, dry_run):
        erase_calls["device"] = device
        return LuksEraseResult(device=device, attempted=True, erased=True)

    monkeypatch.setattr(full_wipe_module, "erase_luks_key", fake_erase)
    monkeypatch.setattr(
        full_wipe_module, "schedule_reimage_on_next_boot",
        lambda boot_entry, dry_run: RebootScheduleResult(boot_entry=boot_entry, attempted=True, scheduled=True),
    )

    report = full_wipe_module.full_wipe("/dev/sda3", "Clonezilla Recovery", dry_run=False)

    assert report.luks_detected is True
    assert report.luks_erase.erased is True
    assert erase_calls["device"] == "/dev/sda3"
    assert report.passed is True


def test_full_wipe_fails_when_luks_erase_fails(monkeypatch):
    monkeypatch.setattr(
        full_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=True),
    )
    monkeypatch.setattr(
        full_wipe_module, "erase_luks_key",
        lambda device, dry_run: LuksEraseResult(device=device, attempted=True, erased=False, error="boom"),
    )
    monkeypatch.setattr(
        full_wipe_module, "schedule_reimage_on_next_boot",
        lambda boot_entry, dry_run: RebootScheduleResult(boot_entry=boot_entry, attempted=True, scheduled=True),
    )

    report = full_wipe_module.full_wipe("/dev/sda3", "Clonezilla Recovery", dry_run=False)

    assert report.passed is False


def test_full_wipe_fails_when_reboot_not_scheduled(monkeypatch):
    monkeypatch.setattr(
        full_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=False),
    )
    monkeypatch.setattr(
        full_wipe_module, "schedule_reimage_on_next_boot",
        lambda boot_entry, dry_run: RebootScheduleResult(boot_entry=boot_entry, attempted=True, scheduled=False, error="no grub-reboot"),
    )

    report = full_wipe_module.full_wipe("/dev/sda", "Clonezilla Recovery", dry_run=False)

    assert report.passed is False
