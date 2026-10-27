from clientwipe import disk_wipe


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_wipe_device_uses_nvme_crypto_erase_when_available(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: f"/usr/bin/{name}")

    calls = []
    monkeypatch.setattr(
        disk_wipe.subprocess, "run",
        lambda cmd, capture_output=True, text=True, check=False: calls.append(cmd) or FakeCompleted(returncode=0),
    )

    result = disk_wipe.wipe_device("/dev/nvme0n1", passes=3, dry_run=False)

    assert result.method == "nvme-format-crypto-erase"
    assert result.attempted is True
    assert result.completed is True
    assert calls == [["nvme", "format", "/dev/nvme0n1", "--ses=2", "--force"]]


def test_wipe_device_falls_back_to_shred_when_nvme_format_fails(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: f"/usr/bin/{name}")

    calls = []

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls.append(cmd)
        if cmd[0] == "nvme":
            return FakeCompleted(returncode=1, stderr="Crypto erase not supported")
        return FakeCompleted(returncode=0)

    monkeypatch.setattr(disk_wipe.subprocess, "run", fake_run)

    result = disk_wipe.wipe_device("/dev/nvme0n1", passes=3, dry_run=False)

    assert result.method == "shred"
    assert result.completed is True
    assert calls[0] == ["nvme", "format", "/dev/nvme0n1", "--ses=2", "--force"]
    assert calls[1] == ["shred", "--iterations=3", "--zero", "/dev/nvme0n1"]


def test_wipe_device_skips_nvme_path_when_nvme_cli_missing(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: None if name == "nvme" else f"/usr/bin/{name}")

    calls = []
    monkeypatch.setattr(
        disk_wipe.subprocess, "run",
        lambda cmd, capture_output=True, text=True, check=False: calls.append(cmd) or FakeCompleted(returncode=0),
    )

    result = disk_wipe.wipe_device("/dev/nvme0n1", passes=3, dry_run=False)

    assert result.method == "shred"
    assert calls == [["shred", "--iterations=3", "--zero", "/dev/nvme0n1"]]


def test_wipe_device_skips_nvme_path_for_non_nvme_device(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: f"/usr/bin/{name}")

    calls = []
    monkeypatch.setattr(
        disk_wipe.subprocess, "run",
        lambda cmd, capture_output=True, text=True, check=False: calls.append(cmd) or FakeCompleted(returncode=0),
    )

    result = disk_wipe.wipe_device("/dev/sdb", passes=3, dry_run=False)

    assert result.method == "shred"
    assert calls == [["shred", "--iterations=3", "--zero", "/dev/sdb"]]


def test_wipe_device_nvme_dry_run_does_not_execute(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: f"/usr/bin/{name}")

    result = disk_wipe.wipe_device("/dev/nvme0n1", passes=3, dry_run=True)

    assert result.attempted is False
    assert result.completed is False
    assert result.method == "nvme-format-crypto-erase"


def test_wipe_device_dry_run_does_not_execute(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: "/usr/bin/shred")

    result = disk_wipe.wipe_device("/dev/sdb", passes=3, dry_run=True)

    assert result.attempted is False
    assert result.completed is False
    assert result.method == "shred"


def test_wipe_device_uses_shred_when_available(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: "/usr/bin/shred")

    calls = {}

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr(disk_wipe.subprocess, "run", fake_run)

    result = disk_wipe.wipe_device("/dev/sdb", passes=3, dry_run=False)

    assert result.attempted is True
    assert result.completed is True
    assert result.method == "shred"
    assert calls["cmd"] == ["shred", "--iterations=3", "--zero", "/dev/sdb"]


def test_wipe_device_reports_shred_failure(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: "/usr/bin/shred")

    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "Device busy"

    monkeypatch.setattr(disk_wipe.subprocess, "run", lambda cmd, capture_output=True, text=True, check=False: FakeCompleted())

    result = disk_wipe.wipe_device("/dev/sdb", passes=3, dry_run=False)

    assert result.completed is False
    assert "Device busy" in result.error


def test_wipe_device_overwrite_fallback_writes_random_data(tmp_path, monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: None)

    fake_device = tmp_path / "fake-device"
    fake_device.write_bytes(b"original-sensitive-data")

    result = disk_wipe.wipe_device(str(fake_device), passes=2, dry_run=False)

    assert result.method == "overwrite-fallback"
    assert result.completed is True
    assert fake_device.read_bytes() != b"original-sensitive-data"
    assert len(fake_device.read_bytes()) == len(b"original-sensitive-data")


def test_wipe_device_overwrite_fallback_reports_errors(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: None)

    result = disk_wipe.wipe_device("/path/does/not/exist", passes=1, dry_run=False)

    assert result.method == "overwrite-fallback"
    assert result.completed is False
    assert result.error is not None
