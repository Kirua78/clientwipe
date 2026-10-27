from pathlib import Path

from clientwipe import cli
from clientwipe.cli import main
from clientwipe.imaging import ImagingResult, RebootScheduleResult
from clientwipe.luks import LuksDetectionResult


def test_full_pipeline_demo_to_certificate(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "sanitize_targets.yaml"
    config_path.write_text(
        "passes: 1\ntargets:\n  - name: ssh\n    patterns: ['.ssh/id_*']\n",
        encoding="utf-8",
    )

    assert main(["demo", "--path", "demo/sandbox"]) == 0
    assert (tmp_path / "demo" / "sandbox" / ".ssh" / "id_rsa").exists()

    exit_code = main(["run", "--root", "demo/sandbox", "--config", str(config_path), "--yes"])
    assert exit_code == 0
    assert not (tmp_path / "demo" / "sandbox" / ".ssh" / "id_rsa").exists()

    out = capsys.readouterr().out
    assert "Verification: OK" in out

    verify_exit_code = main(["verify", "--root", "demo/sandbox", "--config", str(config_path)])
    assert verify_exit_code == 0


def test_run_refuses_non_sandbox_root_without_yes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    real_root = tmp_path / "real-workstation"
    real_root.mkdir()

    config_path = tmp_path / "sanitize_targets.yaml"
    config_path.write_text(
        "passes: 1\ntargets:\n  - name: ssh\n    patterns: ['.ssh/id_*']\n",
        encoding="utf-8",
    )

    exit_code = main(["run", "--root", str(real_root), "--config", str(config_path)])

    assert exit_code == 2
    assert "ATTENTION" in capsys.readouterr().err


def test_trigger_without_tty_fails_safe_instead_of_crashing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    allowlist_path = tmp_path / "allowed.txt"
    allowlist_path.write_text("AB12CD34\n", encoding="utf-8")

    config_path = tmp_path / "sanitize_targets.yaml"
    config_path.write_text(
        "passes: 1\ntargets:\n  - name: ssh\n    patterns: ['.ssh/id_*']\n",
        encoding="utf-8",
    )

    def raise_eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    # No desktop session to fall back to in this test environment either.
    monkeypatch.setattr("clientwipe.gui_confirm.ask_confirmation_gui", lambda message, timeout=30: None)

    exit_code = main([
        "trigger",
        "--mode", "targeted",
        "--serial", "AB12CD34",
        "--allowlist", str(allowlist_path),
        "--config", str(config_path),
        "--root", str(tmp_path),
    ])

    assert exit_code == 1
    assert "terminal interactif" in capsys.readouterr().err


def test_trigger_full_reset_requires_full_reset_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    allowlist_path = tmp_path / "allowed.txt"
    allowlist_path.write_text("AB12CD34\n", encoding="utf-8")

    config_path = tmp_path / "sanitize_targets.yaml"
    config_path.write_text(
        "passes: 1\ntargets:\n  - name: ssh\n    patterns: ['.ssh/id_*']\n",
        encoding="utf-8",
    )

    exit_code = main([
        "trigger",
        "--serial", "AB12CD34",
        "--allowlist", str(allowlist_path),
        "--config", str(config_path),
        "--yes",
    ])

    assert exit_code == 1
    assert "full_reset" in capsys.readouterr().err


def _fake_full_wipe_report():
    from clientwipe.full_wipe import FullWipeReport
    from clientwipe.luks import LuksEraseResult

    return FullWipeReport(
        device="/dev/sda3",
        boot_entry="Clonezilla Recovery",
        luks_detected=True,
        bitlocker_detected=False,
        device_wipe=None,
        header_backup=None,
        luks_erase=LuksEraseResult(device="/dev/sda3", attempted=True, erased=True),
        reboot_scheduled=RebootScheduleResult(boot_entry="Clonezilla Recovery", attempted=True, scheduled=True),
    )


def test_trigger_full_reset_happy_path_reboots_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    allowlist_path = tmp_path / "allowed.txt"
    allowlist_path.write_text("AB12CD34\n", encoding="utf-8")

    config_path = tmp_path / "sanitize_targets.yaml"
    config_path.write_text(
        "full_reset:\n  device: /dev/sda3\n  boot_entry: Clonezilla Recovery\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "full_wipe", lambda device, boot_entry, header_backup_path=None, fallback_wipe_passes=3, dry_run=False: _fake_full_wipe_report())
    reboot_calls = []
    monkeypatch.setattr(cli, "reboot_now", lambda dry_run: reboot_calls.append(dry_run) or True)

    exit_code = main([
        "trigger",
        "--serial", "AB12CD34",
        "--allowlist", str(allowlist_path),
        "--config", str(config_path),
        "--out-dir", "certificates",
        "--yes",
        "--skip-snapshot",
    ])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Cle LUKS detruite: OK" in out
    assert reboot_calls == [False]


def test_trigger_full_reset_no_auto_reboot_skips_reboot(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    allowlist_path = tmp_path / "allowed.txt"
    allowlist_path.write_text("AB12CD34\n", encoding="utf-8")

    config_path = tmp_path / "sanitize_targets.yaml"
    config_path.write_text(
        "full_reset:\n  device: /dev/sda3\n  boot_entry: Clonezilla Recovery\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "full_wipe", lambda device, boot_entry, header_backup_path=None, fallback_wipe_passes=3, dry_run=False: _fake_full_wipe_report())
    reboot_calls = []
    monkeypatch.setattr(cli, "reboot_now", lambda dry_run: reboot_calls.append(dry_run) or True)

    exit_code = main([
        "trigger",
        "--serial", "AB12CD34",
        "--allowlist", str(allowlist_path),
        "--config", str(config_path),
        "--out-dir", "certificates",
        "--yes",
        "--skip-snapshot",
        "--no-auto-reboot",
    ])

    assert exit_code == 0
    assert reboot_calls == []


def test_live_wipe_requires_typed_confirmation(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "non merci")

    exit_code = main([
        "live-wipe",
        "--device", "/dev/sda",
        "--image", "golden-kali",
        "--images-repository", str(tmp_path),
    ])

    assert exit_code == 0
    assert "Annule" in capsys.readouterr().out


def test_live_wipe_happy_path(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "OUI")

    from clientwipe.live_wipe import LiveWipeReport
    from clientwipe.luks import LuksEraseResult

    fake_report = LiveWipeReport(
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
    monkeypatch.setattr(
        cli, "live_wipe",
        lambda device, image, images_repository, header_backup_path=None, fallback_wipe_passes=3, inventory_output_dir=None, dry_run=False: fake_report,
    )

    exit_code = main([
        "live-wipe",
        "--device", "/dev/sda",
        "--image", "golden-kali",
        "--images-repository", str(tmp_path),
        "--out-dir", "certificates",
    ])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Cle LUKS detruite: OK" in out
    assert "Reimagage: OK" in out


def test_cli_live_wipe_gui_invokes_run_gui_with_parsed_args(monkeypatch, tmp_path):
    from clientwipe import gui_live_wipe

    calls = []
    monkeypatch.setattr(
        gui_live_wipe, "run_gui",
        lambda image_name, mount_point, out_dir, fallback_wipe_passes: calls.append(
            (image_name, mount_point, out_dir, fallback_wipe_passes)
        ),
    )

    exit_code = main([
        "live-wipe-gui",
        "--image", "golden-kali",
        "--mount-point", str(tmp_path / "mnt"),
        "--out-dir", str(tmp_path / "certs"),
        "--fallback-wipe-passes", "5",
    ])

    assert exit_code == 0
    assert calls == [("golden-kali", Path(tmp_path / "mnt"), Path(tmp_path / "certs"), 5)]


def test_cli_live_wipe_gui_uses_defaults_when_omitted(monkeypatch):
    from clientwipe import gui_live_wipe

    calls = []
    monkeypatch.setattr(
        gui_live_wipe, "run_gui",
        lambda image_name, mount_point, out_dir, fallback_wipe_passes: calls.append(
            (image_name, mount_point, out_dir, fallback_wipe_passes)
        ),
    )

    exit_code = main(["live-wipe-gui"])

    assert exit_code == 0
    assert calls == [(
        gui_live_wipe.DEFAULT_IMAGE_NAME, gui_live_wipe.DEFAULT_MOUNT_POINT, gui_live_wipe.DEFAULT_OUT_DIR, 1,
    )]
