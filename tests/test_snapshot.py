from clientwipe import snapshot


def test_create_snapshot_noops_when_timeshift_not_installed(monkeypatch):
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: None)

    result = snapshot.create_snapshot("test comment")

    assert result.attempted is False
    assert result.created is False
    assert "timeshift" in result.error.lower()


def test_create_snapshot_success(monkeypatch):
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: "/usr/bin/timeshift")

    class FakeCompleted:
        returncode = 0
        stdout = "Snapshot saved successfully"
        stderr = ""

    calls = {}

    def fake_run(command, capture_output=False, text=False, check=False):
        calls["command"] = command
        return FakeCompleted()

    monkeypatch.setattr(snapshot.subprocess, "run", fake_run)

    result = snapshot.create_snapshot("avant sanitisation")

    assert result.attempted is True
    assert result.created is True
    assert result.error is None
    assert "--comments" in calls["command"]
    assert "avant sanitisation" in calls["command"]


def test_create_snapshot_failure_reports_stderr(monkeypatch):
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: "/usr/bin/timeshift")

    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "Error: no backup device configured"

    monkeypatch.setattr(snapshot.subprocess, "run", lambda *a, **k: FakeCompleted())

    result = snapshot.create_snapshot("avant sanitisation")

    assert result.attempted is True
    assert result.created is False
    assert "no backup device configured" in result.error
