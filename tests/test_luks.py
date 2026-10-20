from clientwipe import luks


def test_detect_luks_returns_false_without_cryptsetup(monkeypatch):
    monkeypatch.setattr(luks.shutil, "which", lambda name: None)

    result = luks.detect_luks("/dev/sda3")

    assert result.is_luks is False
    assert "cryptsetup" in result.error


def test_detect_luks_true_when_cryptsetup_confirms(monkeypatch):
    monkeypatch.setattr(luks.shutil, "which", lambda name: "/usr/sbin/cryptsetup")

    class FakeCompleted:
        returncode = 0

    monkeypatch.setattr(luks.subprocess, "run", lambda cmd, capture_output=True, text=True, check=False: FakeCompleted())

    result = luks.detect_luks("/dev/sda3")

    assert result.is_luks is True
    assert result.error is None


def test_detect_luks_false_when_not_a_luks_device(monkeypatch):
    monkeypatch.setattr(luks.shutil, "which", lambda name: "/usr/sbin/cryptsetup")

    class FakeCompleted:
        returncode = 1

    monkeypatch.setattr(luks.subprocess, "run", lambda cmd, capture_output=True, text=True, check=False: FakeCompleted())

    assert luks.detect_luks("/dev/sda1").is_luks is False


def test_erase_luks_key_dry_run_does_not_execute(monkeypatch):
    monkeypatch.setattr(luks.shutil, "which", lambda name: "/usr/sbin/cryptsetup")

    result = luks.erase_luks_key("/dev/sda3", dry_run=True)

    assert result.attempted is False
    assert result.erased is False


def test_erase_luks_key_success(monkeypatch):
    monkeypatch.setattr(luks.shutil, "which", lambda name: "/usr/sbin/cryptsetup")

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    calls = {}

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr(luks.subprocess, "run", fake_run)

    result = luks.erase_luks_key("/dev/sda3", dry_run=False)

    assert result.attempted is True
    assert result.erased is True
    assert "erase" in calls["cmd"]
    assert "/dev/sda3" in calls["cmd"]


def test_erase_luks_key_failure_reports_stderr(monkeypatch):
    monkeypatch.setattr(luks.shutil, "which", lambda name: "/usr/sbin/cryptsetup")

    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "Device is still in use."

    monkeypatch.setattr(luks.subprocess, "run", lambda cmd, capture_output=True, text=True, check=False: FakeCompleted())

    result = luks.erase_luks_key("/dev/sda3", dry_run=False)

    assert result.erased is False
    assert "still in use" in result.error
