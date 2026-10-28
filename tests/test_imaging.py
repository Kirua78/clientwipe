from clientwipe import imaging


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

    def fake_run(command, cwd=None, stdin=None, env=None, start_new_session=False, check=False):
        calls["command"] = command
        calls["cwd"] = cwd
        calls["stdin"] = stdin
        calls["env"] = env
        calls["start_new_session"] = start_new_session
        return FakeCompleted()

    monkeypatch.setattr(imaging.subprocess, "run", fake_run)

    result = imaging.restore_golden_image("golden-kali", "/dev/sda", tmp_path, dry_run=False)

    assert result.executed is True
    assert result.returncode == 0
    assert result.error is None
    assert calls["cwd"] == str(tmp_path)
    assert "golden-kali" in calls["command"]
    assert "/dev/sda" in calls["command"]
    # Regression test: ocs-sr was found to block forever reading a
    # confirmation under the GUI's launch chain (see restore_golden_image's
    # docstring). stdin=DEVNULL alone was not enough (Clonezilla reads some
    # prompts from /dev/tty, bypassing a redirected stdin); ocs_batch_mode
    # suppresses them at the source and start_new_session removes any
    # controlling terminal to read from even if something still tries.
    assert calls["stdin"] == imaging.subprocess.DEVNULL
    assert calls["env"]["ocs_batch_mode"] == "1"
    assert calls["start_new_session"] is True


def test_restore_golden_image_reports_error_on_nonzero_returncode(tmp_path, monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/sbin/ocs-sr")
    monkeypatch.setattr(
        imaging.subprocess, "run",
        lambda command, cwd=None, stdin=None, env=None, start_new_session=False, check=False: type("R", (), {"returncode": 1})(),
    )

    result = imaging.restore_golden_image("golden-kali", "/dev/sda", tmp_path, dry_run=False)

    assert result.executed is True
    assert result.returncode == 1
    assert "1" in result.error


def test_restore_golden_image_reports_start_and_success(tmp_path, monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/sbin/ocs-sr")
    monkeypatch.setattr(
        imaging.subprocess, "run",
        lambda command, cwd=None, stdin=None, env=None, start_new_session=False, check=False: type("R", (), {"returncode": 0})(),
    )

    fractions = []
    result = imaging.restore_golden_image(
        "golden-kali", "/dev/sda", tmp_path, dry_run=False, progress_callback=fractions.append,
    )

    assert result.executed is True
    assert result.returncode == 0
    assert fractions == [None, 1.0]


def test_restore_golden_image_reports_start_and_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(imaging.shutil, "which", lambda name: "/usr/sbin/ocs-sr")
    monkeypatch.setattr(
        imaging.subprocess, "run",
        lambda command, cwd=None, stdin=None, env=None, start_new_session=False, check=False: type("R", (), {"returncode": 1})(),
    )

    fractions = []
    result = imaging.restore_golden_image(
        "golden-kali", "/dev/sda", tmp_path, dry_run=False, progress_callback=fractions.append,
    )

    assert result.executed is True
    assert result.returncode == 1
    assert fractions == [None, None]


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
