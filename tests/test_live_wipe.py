from clientwipe import live_wipe as live_wipe_module
from clientwipe.bitlocker import BitlockerDetectionResult
from clientwipe.imaging import ImagingResult
from clientwipe.luks import LuksDetectionResult, LuksEraseResult, LuksHeaderBackupResult


def test_live_wipe_reimages_directly_without_luks(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "detect_bitlocker",
        lambda device: BitlockerDetectionResult(device=device, is_bitlocker=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "restore_golden_image",
        lambda image_name, device, images_repository, dry_run: ImagingResult(
            command=["ocs-sr", "restoredisk", image_name, device], executed=True, returncode=0,
        ),
    )

    report = live_wipe_module.live_wipe("/dev/sda", "golden-kali", tmp_path, dry_run=False)

    assert report.luks_detected is False
    assert report.bitlocker_detected is False
    assert report.luks_erase is None
    assert report.imaging.returncode == 0
    assert report.passed is True


def test_live_wipe_reports_bitlocker_on_windows_target(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "detect_bitlocker",
        lambda device: BitlockerDetectionResult(device=device, is_bitlocker=True),
    )
    monkeypatch.setattr(
        live_wipe_module, "restore_golden_image",
        lambda image_name, device, images_repository, dry_run: ImagingResult(
            command=["ocs-sr", "restoredisk", image_name, device], executed=True, returncode=0,
        ),
    )

    report = live_wipe_module.live_wipe("/dev/sda", "golden-windows", tmp_path, dry_run=False)

    assert report.bitlocker_detected is True
    assert report.luks_erase is None
    assert report.passed is True


def test_live_wipe_erases_luks_before_reimaging(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=True),
    )

    erase_calls = []
    monkeypatch.setattr(
        live_wipe_module, "erase_luks_key",
        lambda device, dry_run: erase_calls.append(device) or LuksEraseResult(device=device, attempted=True, erased=True),
    )

    imaging_calls = []
    monkeypatch.setattr(
        live_wipe_module, "restore_golden_image",
        lambda image_name, device, images_repository, dry_run: imaging_calls.append(device) or
        ImagingResult(command=["ocs-sr"], executed=True, returncode=0),
    )

    report = live_wipe_module.live_wipe("/dev/sda3", "golden-kali", tmp_path, dry_run=False)

    assert erase_calls == ["/dev/sda3"]
    assert imaging_calls == ["/dev/sda3"]
    assert report.luks_erase.erased is True
    assert report.passed is True


def test_live_wipe_skips_erase_when_header_backup_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=True),
    )
    monkeypatch.setattr(
        live_wipe_module, "backup_luks_header",
        lambda device, path, dry_run: LuksHeaderBackupResult(
            device=device, backup_path=str(path), attempted=True, backed_up=False, error="cle USB non montee",
        ),
    )
    erase_calls = []
    monkeypatch.setattr(
        live_wipe_module, "erase_luks_key",
        lambda device, dry_run: erase_calls.append(device) or LuksEraseResult(device=device, attempted=True, erased=True),
    )
    monkeypatch.setattr(
        live_wipe_module, "restore_golden_image",
        lambda image_name, device, images_repository, dry_run: ImagingResult(command=["ocs-sr"], executed=True, returncode=0),
    )

    report = live_wipe_module.live_wipe(
        "/dev/sda3", "golden-kali", tmp_path, header_backup_path=tmp_path / "header.bin", dry_run=False,
    )

    assert erase_calls == []
    assert report.luks_erase is None
    assert report.passed is False


def test_live_wipe_fails_when_imaging_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "restore_golden_image",
        lambda image_name, device, images_repository, dry_run: ImagingResult(command=["ocs-sr"], executed=True, returncode=1),
    )

    report = live_wipe_module.live_wipe("/dev/sda", "golden-kali", tmp_path, dry_run=False)

    assert report.passed is False
