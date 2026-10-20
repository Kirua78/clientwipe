from clientwipe import imaging


def test_restore_golden_image_dry_run_does_not_execute(tmp_path):
    result = imaging.restore_golden_image("golden-kali", "/dev/sda", tmp_path, dry_run=True)

    assert result.executed is False
    assert result.returncode is None
    assert "ocs-sr" in result.command[0]


def test_restore_golden_image_executes_when_confirmed(tmp_path, monkeypatch):
    calls = {}

    class FakeCompleted:
        returncode = 0

    def fake_run(command, cwd=None, check=False):
        calls["command"] = command
        calls["cwd"] = cwd
        return FakeCompleted()

    monkeypatch.setattr(imaging.subprocess, "run", fake_run)

    result = imaging.restore_golden_image("golden-kali", "/dev/sda", tmp_path, dry_run=False)

    assert result.executed is True
    assert result.returncode == 0
    assert calls["cwd"] == str(tmp_path)
    assert "golden-kali" in calls["command"]
    assert "/dev/sda" in calls["command"]


def test_schedule_reimage_dry_run_does_not_execute(monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/sbin/grub-reboot")

    result = imaging.schedule_reimage_on_next_boot("Clonezilla Recovery", dry_run=True)

    assert result.attempted is False
    assert result.scheduled is False


def test_schedule_reimage_returns_false_without_grub_reboot(monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: None)

    result = imaging.schedule_reimage_on_next_boot("Clonezilla Recovery", dry_run=False)

    assert result.scheduled is False
    assert "grub-reboot" in result.error


def test_schedule_reimage_success(monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/sbin/grub-reboot")

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    calls = {}

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr(imaging.subprocess, "run", fake_run)

    result = imaging.schedule_reimage_on_next_boot("Clonezilla Recovery", dry_run=False)

    assert result.scheduled is True
    assert calls["cmd"] == ["grub-reboot", "Clonezilla Recovery"]


def test_reboot_now_dry_run_does_nothing(monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/bin/systemctl")
    assert imaging.reboot_now(dry_run=True) is False


def test_reboot_now_calls_systemctl_reboot(monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/bin/systemctl")

    class FakeCompleted:
        returncode = 0

    calls = {}

    def fake_run(cmd, check=False):
        calls["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr(imaging.subprocess, "run", fake_run)

    assert imaging.reboot_now(dry_run=False) is True
    assert calls["cmd"] == ["systemctl", "reboot"]
