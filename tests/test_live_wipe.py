from clientwipe import live_wipe as live_wipe_module
from clientwipe.bitlocker import BitlockerDetectionResult
from clientwipe.disk_wipe import DeviceWipeResult
from clientwipe.imaging import ImagingResult
from clientwipe.inventory import ToolInventoryResult
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
        live_wipe_module, "wipe_device",
        lambda device, passes, dry_run, progress_callback=None: DeviceWipeResult(device=device, passes=passes, method="shred", attempted=True, completed=True),
    )
    monkeypatch.setattr(
        live_wipe_module, "restore_golden_image",
        lambda image_name, device, images_repository, dry_run, progress_callback=None: ImagingResult(
            command=["ocs-sr", "restoredisk", image_name, device], executed=True, returncode=0,
        ),
    )

    report = live_wipe_module.live_wipe("/dev/sda", "golden-kali", tmp_path, dry_run=False)

    assert report.luks_detected is False
    assert report.bitlocker_detected is False
    assert report.luks_erase is None
    assert report.device_wipe.completed is True
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
        live_wipe_module, "wipe_device",
        lambda device, passes, dry_run, progress_callback=None: DeviceWipeResult(device=device, passes=passes, method="shred", attempted=True, completed=True),
    )
    monkeypatch.setattr(
        live_wipe_module, "restore_golden_image",
        lambda image_name, device, images_repository, dry_run, progress_callback=None: ImagingResult(
            command=["ocs-sr", "restoredisk", image_name, device], executed=True, returncode=0,
        ),
    )

    report = live_wipe_module.live_wipe("/dev/sda", "golden-windows", tmp_path, dry_run=False)

    assert report.bitlocker_detected is True
    assert report.luks_erase is None
    assert report.device_wipe.completed is True
    assert report.passed is True


def test_live_wipe_fails_when_fallback_device_wipe_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "detect_bitlocker",
        lambda device: BitlockerDetectionResult(device=device, is_bitlocker=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "wipe_device",
        lambda device, passes, dry_run, progress_callback=None: DeviceWipeResult(device=device, passes=passes, method="shred", attempted=True, completed=False, error="boom"),
    )
    monkeypatch.setattr(
        live_wipe_module, "restore_golden_image",
        lambda image_name, device, images_repository, dry_run, progress_callback=None: ImagingResult(command=["ocs-sr"], executed=True, returncode=0),
    )

    report = live_wipe_module.live_wipe("/dev/sda", "golden-kali", tmp_path, dry_run=False)

    assert report.passed is False


def test_live_wipe_runs_inventory_when_output_dir_given_and_imaging_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "detect_bitlocker",
        lambda device: BitlockerDetectionResult(device=device, is_bitlocker=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "wipe_device",
        lambda device, passes, dry_run, progress_callback=None: DeviceWipeResult(device=device, passes=passes, method="shred", attempted=True, completed=True),
    )
    monkeypatch.setattr(
        live_wipe_module, "restore_golden_image",
        lambda image_name, device, images_repository, dry_run, progress_callback=None: ImagingResult(command=["ocs-sr"], executed=True, returncode=0),
    )
    inventory_calls = []
    monkeypatch.setattr(
        live_wipe_module, "inventory_installed_packages",
        lambda device, output_dir, mount_point, dry_run: inventory_calls.append(device) or
        ToolInventoryResult(device=device, root_partition="/dev/sda3", attempted=True, completed=True, package_count=42, output_path=str(output_dir / "tool-inventory.json")),
    )

    report = live_wipe_module.live_wipe(
        "/dev/sda", "golden-kali", tmp_path, inventory_output_dir=tmp_path / "out", dry_run=False,
    )

    assert inventory_calls == ["/dev/sda"]
    assert report.tool_inventory.completed is True
    assert report.tool_inventory.package_count == 42
    assert report.passed is True


def test_live_wipe_skips_inventory_when_imaging_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "detect_bitlocker",
        lambda device: BitlockerDetectionResult(device=device, is_bitlocker=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "wipe_device",
        lambda device, passes, dry_run, progress_callback=None: DeviceWipeResult(device=device, passes=passes, method="shred", attempted=True, completed=True),
    )
    monkeypatch.setattr(
        live_wipe_module, "restore_golden_image",
        lambda image_name, device, images_repository, dry_run, progress_callback=None: ImagingResult(command=["ocs-sr"], executed=True, returncode=1),
    )
    inventory_calls = []
    monkeypatch.setattr(
        live_wipe_module, "inventory_installed_packages",
        lambda device, output_dir, mount_point, dry_run: inventory_calls.append(device) or
        ToolInventoryResult(device=device, root_partition=None, attempted=True, completed=True),
    )

    report = live_wipe_module.live_wipe(
        "/dev/sda", "golden-kali", tmp_path, inventory_output_dir=tmp_path / "out", dry_run=False,
    )

    assert inventory_calls == []
    assert report.tool_inventory is None


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
        lambda image_name, device, images_repository, dry_run, progress_callback=None: imaging_calls.append(device) or
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
        lambda image_name, device, images_repository, dry_run, progress_callback=None: ImagingResult(command=["ocs-sr"], executed=True, returncode=0),
    )

    report = live_wipe_module.live_wipe(
        "/dev/sda3", "golden-kali", tmp_path, header_backup_path=tmp_path / "header.bin", dry_run=False,
    )

    assert erase_calls == []
    assert report.luks_erase is None
    assert report.passed is False


def test_live_wipe_reports_progress_through_each_phase(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "detect_bitlocker",
        lambda device: BitlockerDetectionResult(device=device, is_bitlocker=False),
    )

    def fake_wipe_device(device, passes, dry_run, progress_callback=None):
        if progress_callback:
            progress_callback(0.5)
        return DeviceWipeResult(device=device, passes=passes, method="shred", attempted=True, completed=True)

    monkeypatch.setattr(live_wipe_module, "wipe_device", fake_wipe_device)

    def fake_restore(image_name, device, images_repository, dry_run, progress_callback=None):
        if progress_callback:
            progress_callback(0.75)
        return ImagingResult(command=["ocs-sr"], executed=True, returncode=0)

    monkeypatch.setattr(live_wipe_module, "restore_golden_image", fake_restore)

    events = []
    live_wipe_module.live_wipe(
        "/dev/sda", "golden-kali", tmp_path, dry_run=False,
        progress_callback=lambda step, fraction, detail: events.append((step, fraction)),
    )

    assert events == [
        ("detection", None),
        ("detection", 1.0),
        ("effacement", 0.0),
        ("effacement", 0.5),
        ("effacement", 1.0),
        ("reimagage", 0.0),
        ("reimagage", 0.75),
        ("reimagage", 1.0),
    ]


def test_live_wipe_fails_when_imaging_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_wipe_module, "detect_luks",
        lambda device: LuksDetectionResult(device=device, is_luks=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "detect_bitlocker",
        lambda device: BitlockerDetectionResult(device=device, is_bitlocker=False),
    )
    monkeypatch.setattr(
        live_wipe_module, "wipe_device",
        lambda device, passes, dry_run, progress_callback=None: DeviceWipeResult(device=device, passes=passes, method="shred", attempted=True, completed=True),
    )
    monkeypatch.setattr(
        live_wipe_module, "restore_golden_image",
        lambda image_name, device, images_repository, dry_run, progress_callback=None: ImagingResult(command=["ocs-sr"], executed=True, returncode=1),
    )

    report = live_wipe_module.live_wipe("/dev/sda", "golden-kali", tmp_path, dry_run=False)

    assert report.passed is False
