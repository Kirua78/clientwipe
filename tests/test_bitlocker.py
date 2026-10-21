from clientwipe import bitlocker


def test_detect_bitlocker_returns_false_without_cryptsetup(monkeypatch):
    monkeypatch.setattr(bitlocker.shutil, "which", lambda name: None)

    result = bitlocker.detect_bitlocker("/dev/sda2")

    assert result.is_bitlocker is False
    assert "cryptsetup" in result.error


def test_detect_bitlocker_true_when_cryptsetup_confirms(monkeypatch):
    monkeypatch.setattr(bitlocker.shutil, "which", lambda name: "/usr/sbin/cryptsetup")

    class FakeCompleted:
        returncode = 0

    monkeypatch.setattr(bitlocker.subprocess, "run", lambda cmd, capture_output=True, text=True, check=False: FakeCompleted())

    result = bitlocker.detect_bitlocker("/dev/sda2")

    assert result.is_bitlocker is True
    assert result.error is None


def test_detect_bitlocker_false_when_not_bitlocker(monkeypatch):
    monkeypatch.setattr(bitlocker.shutil, "which", lambda name: "/usr/sbin/cryptsetup")

    class FakeCompleted:
        returncode = 1

    monkeypatch.setattr(bitlocker.subprocess, "run", lambda cmd, capture_output=True, text=True, check=False: FakeCompleted())

    assert bitlocker.detect_bitlocker("/dev/sda2").is_bitlocker is False
