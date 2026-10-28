import os

from clientwipe import imaging


def _make_fake_popen(output: bytes, returncode: int):
    class FakePopen:
        def __init__(self, command, cwd=None, stdout=None, stderr=None, close_fds=None):
            self.command = command
            self.cwd = cwd
            if output:
                os.write(stdout, output)

        def wait(self):
            return returncode

    return FakePopen


def test_restore_golden_image_dry_run_does_not_execute(tmp_path, monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/sbin/ocs-sr")

    result = imaging.restore_golden_image("golden-kali", "/dev/sda", tmp_path, dry_run=True)

    assert result.executed is False
    assert result.returncode is None
    assert "ocs-sr" in result.command[0]


def test_restore_golden_image_fails_cleanly_without_ocs_sr(tmp_path, monkeypatch):
    # Real-condition finding (clientwipe live-wipe on a Kali Live session
    # without Clonezilla installed): subprocess.run() would otherwise raise
    # FileNotFoundError and crash the caller instead of failing cleanly.
    monkeypatch.setattr(imaging.shutil, "which", lambda name: None)

    result = imaging.restore_golden_image("golden-kali", "/dev/sda", tmp_path, dry_run=False)

    assert result.executed is False
    assert "ocs-sr" in result.error


def test_restore_golden_image_executes_when_confirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/sbin/ocs-sr")

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
    assert result.error is None
    assert calls["cwd"] == str(tmp_path)
    assert "golden-kali" in calls["command"]
    assert "/dev/sda" in calls["command"]


def test_restore_golden_image_reports_error_on_nonzero_returncode(tmp_path, monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/sbin/ocs-sr")
    monkeypatch.setattr(imaging.subprocess, "run", lambda command, cwd=None, check=False: type("R", (), {"returncode": 1})())

    result = imaging.restore_golden_image("golden-kali", "/dev/sda", tmp_path, dry_run=False)

    assert result.executed is True
    assert result.returncode == 1
    assert "1" in result.error


def test_restore_golden_image_reports_progress_from_output(tmp_path, monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/sbin/ocs-sr")

    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(imaging, "_open_pty", lambda: (read_fd, write_fd))
    monkeypatch.setattr(
        imaging.subprocess, "Popen",
        _make_fake_popen(output=b"Completed: 12%\rCompleted: 57%\rCompleted: 100%\r", returncode=0),
    )

    fractions = []
    result = imaging.restore_golden_image(
        "golden-kali", "/dev/sda", tmp_path, dry_run=False, progress_callback=fractions.append,
    )

    assert result.executed is True
    assert result.returncode == 0
    assert fractions == [0.12, 0.57, 0.99, 1.0]


def test_restore_golden_image_progress_reports_none_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/sbin/ocs-sr")

    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(imaging, "_open_pty", lambda: (read_fd, write_fd))
    monkeypatch.setattr(imaging.subprocess, "Popen", _make_fake_popen(output=b"", returncode=1))

    fractions = []
    result = imaging.restore_golden_image(
        "golden-kali", "/dev/sda", tmp_path, dry_run=False, progress_callback=fractions.append,
    )

    assert result.executed is True
    assert result.returncode == 1
    assert fractions == [None]


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
