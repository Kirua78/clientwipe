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
