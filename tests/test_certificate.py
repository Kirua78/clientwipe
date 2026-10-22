import json
from pathlib import Path

from clientwipe.certificate import generate_certificate, generate_full_wipe_certificate, generate_live_wipe_certificate
from clientwipe.config import Config, SanitizeTarget
from clientwipe.full_wipe import FullWipeReport
from clientwipe.imaging import ImagingResult, RebootScheduleResult
from clientwipe.inventory import ToolInventoryResult
from clientwipe.live_wipe import LiveWipeReport
from clientwipe.luks import LuksEraseResult
from clientwipe.sanitize import sanitize
from clientwipe.verify import verify


def test_generate_certificate_reports_pass_and_writes_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / ".bash_history").write_text("ssh root@10.0.0.1", encoding="utf-8")

    config = Config(targets=[SanitizeTarget(name="history", patterns=[".bash_history"])], passes=1)
    sanitize_report = sanitize(root, config)
    verify_report = verify(root, config)

    out_dir = tmp_path / "certificates"
    result = generate_certificate(sanitize_report, verify_report, out_dir, operator="test-operator")

    assert result["overall_passed"] is True
    json_path = Path(result["json_path"])
    assert json_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["operator"] == "test-operator"
    assert payload["overall_passed"] is True
    assert payload["sha256"] == result["sha256"]

    assert Path(result["html_path"]).exists()
    assert "SANITISATION VALIDEE" in Path(result["html_path"]).read_text(encoding="utf-8")


def test_generate_certificate_includes_snapshot_status(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / ".bash_history").write_text("ssh root@10.0.0.1", encoding="utf-8")

    config = Config(targets=[SanitizeTarget(name="history", patterns=[".bash_history"])], passes=1)
    sanitize_report = sanitize(root, config)
    verify_report = verify(root, config)

    snapshot = {"attempted": True, "created": True, "comment": "avant sanitisation", "error": None}
    result = generate_certificate(sanitize_report, verify_report, tmp_path / "certificates", snapshot=snapshot)

    payload = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    assert payload["pre_snapshot"] == snapshot

    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "avant sanitisation" in html


def test_generate_certificate_reports_failure_when_residual_file_remains(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / ".bash_history").write_text("ssh root@10.0.0.1", encoding="utf-8")

    config = Config(targets=[SanitizeTarget(name="history", patterns=[".bash_history"])], passes=1)
    sanitize_report = sanitize(root, config)
    # Simulate a residual file surviving the wipe.
    (root / ".bash_history").write_text("leftover", encoding="utf-8")
    verify_report = verify(root, config)

    result = generate_certificate(sanitize_report, verify_report, tmp_path / "certificates")

    assert result["overall_passed"] is False
    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "ECHEC" in html


def test_generate_full_wipe_certificate_reports_pass(tmp_path):
    report = FullWipeReport(
        device="/dev/sda3",
        boot_entry="Clonezilla Recovery",
        luks_detected=True,
        bitlocker_detected=False,
        device_wipe=None,
        header_backup=None,
        luks_erase=LuksEraseResult(device="/dev/sda3", attempted=True, erased=True),
        reboot_scheduled=RebootScheduleResult(boot_entry="Clonezilla Recovery", attempted=True, scheduled=True),
    )

    result = generate_full_wipe_certificate(report, tmp_path / "certificates", operator="test-operator")

    assert result["overall_passed"] is True
    payload = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    assert payload["operation"] == "full-reset"
    assert payload["operator"] == "test-operator"
    assert payload["full_wipe"]["device"] == "/dev/sda3"
    assert "Purge" in payload["nist_800_88_level"]

    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "REMISE A ZERO PROGRAMMEE" in html
    assert "Purge" in html


def test_generate_full_wipe_certificate_reports_failure_when_luks_erase_fails(tmp_path):
    report = FullWipeReport(
        device="/dev/sda3",
        boot_entry="Clonezilla Recovery",
        luks_detected=True,
        bitlocker_detected=False,
        device_wipe=None,
        header_backup=None,
        luks_erase=LuksEraseResult(device="/dev/sda3", attempted=True, erased=False, error="boom"),
        reboot_scheduled=RebootScheduleResult(boot_entry="Clonezilla Recovery", attempted=True, scheduled=True),
    )

    result = generate_full_wipe_certificate(report, tmp_path / "certificates")

    assert result["overall_passed"] is False
    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "ECHEC" in html


def test_generate_full_wipe_certificate_reports_clear_level_without_luks(tmp_path):
    report = FullWipeReport(
        device="/dev/sda3",
        boot_entry="Clonezilla Recovery",
        luks_detected=False,
        bitlocker_detected=False,
        device_wipe=None,
        header_backup=None,
        luks_erase=None,
        reboot_scheduled=RebootScheduleResult(boot_entry="Clonezilla Recovery", attempted=True, scheduled=True),
    )

    result = generate_full_wipe_certificate(report, tmp_path / "certificates")

    payload = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    assert "Clear" in payload["nist_800_88_level"]
    assert "Purge" not in payload["nist_800_88_level"]


def test_generate_live_wipe_certificate_reports_pass(tmp_path):
    report = LiveWipeReport(
        device="/dev/sda",
        image_name="golden-kali",
        luks_detected=True,
        bitlocker_detected=False,
        device_wipe=None,
        header_backup=None,
        luks_erase=LuksEraseResult(device="/dev/sda", attempted=True, erased=True),
        imaging=ImagingResult(command=["ocs-sr"], executed=True, returncode=0),
        tool_inventory=None,
    )

    result = generate_live_wipe_certificate(report, tmp_path / "certificates", operator="test-operator")

    assert result["overall_passed"] is True
    payload = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    assert payload["operation"] == "live-wipe"
    assert payload["live_wipe"]["image_name"] == "golden-kali"
    assert "Purge" in payload["nist_800_88_level"]

    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "REMISE A ZERO REUSSIE" in html


def test_generate_live_wipe_certificate_reports_tool_inventory(tmp_path):
    report = LiveWipeReport(
        device="/dev/sda",
        image_name="golden-kali",
        luks_detected=True,
        bitlocker_detected=False,
        device_wipe=None,
        header_backup=None,
        luks_erase=LuksEraseResult(device="/dev/sda", attempted=True, erased=True),
        imaging=ImagingResult(command=["ocs-sr"], executed=True, returncode=0),
        tool_inventory=ToolInventoryResult(
            device="/dev/sda", root_partition="/dev/sda3", attempted=True, completed=True,
            package_count=1842, output_path="/mnt/key/tool-inventory.json",
        ),
    )

    result = generate_live_wipe_certificate(report, tmp_path / "certificates")

    payload = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    assert payload["live_wipe"]["tool_inventory"]["package_count"] == 1842

    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "1842 paquets" in html


def test_generate_live_wipe_certificate_reports_failure_when_imaging_fails(tmp_path):
    report = LiveWipeReport(
        device="/dev/sda",
        image_name="golden-kali",
        luks_detected=False,
        bitlocker_detected=False,
        device_wipe=None,
        header_backup=None,
        luks_erase=None,
        imaging=ImagingResult(command=["ocs-sr"], executed=True, returncode=1),
        tool_inventory=None,
    )

    result = generate_live_wipe_certificate(report, tmp_path / "certificates")

    assert result["overall_passed"] is False
    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "ECHEC" in html


def test_generate_live_wipe_certificate_reports_clear_level_with_bitlocker(tmp_path):
    report = LiveWipeReport(
        device="/dev/sda",
        image_name="golden-windows",
        luks_detected=False,
        bitlocker_detected=True,
        device_wipe=None,
        header_backup=None,
        luks_erase=None,
        imaging=ImagingResult(command=["ocs-sr"], executed=True, returncode=0),
        tool_inventory=None,
    )

    result = generate_live_wipe_certificate(report, tmp_path / "certificates")

    payload = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    assert "Clear" in payload["nist_800_88_level"]
    assert "BitLocker" in payload["nist_800_88_level"]
    assert "Purge" not in payload["nist_800_88_level"]

    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "Chiffrement BitLocker detecte : oui" in html
