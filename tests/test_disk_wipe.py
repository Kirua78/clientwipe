import io

from clientwipe import disk_wipe


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakePopen:
    """Stand-in for subprocess.Popen covering just what _run_shred uses:
    .pid, repeated .poll() until a non-None returncode, .returncode and
    .stderr. `poll_sequence` is consumed one value per call, the last
    (non-None) value becomes the final returncode.
    """

    def __init__(self, poll_sequence, returncode, stderr_text=""):
        self._poll_sequence = list(poll_sequence)
        self.pid = 4242
        self.returncode = returncode
        self.stderr = io.StringIO(stderr_text)

    def poll(self):
        value = self._poll_sequence.pop(0)
        if value is not None:
            self.returncode = value
        return value


def _which_everything_but_nvme(name):
    return None if name == "nvme" else f"/usr/bin/{name}"


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


def test_wipe_device_falls_back_to_user_data_erase_when_crypto_erase_fails(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: f"/usr/bin/{name}")

    calls = []

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls.append(cmd)
        if cmd == ["nvme", "format", "/dev/nvme0n1", "--ses=2", "--force"]:
            return FakeCompleted(returncode=1, stderr="Invalid Format: The LBA Format specified is not supported")
        return FakeCompleted(returncode=0)

    monkeypatch.setattr(disk_wipe.subprocess, "run", fake_run)

    result = disk_wipe.wipe_device("/dev/nvme0n1", passes=3, dry_run=False)

    assert result.method == "nvme-format-user-data-erase"
    assert result.completed is True
    assert calls == [
        ["nvme", "format", "/dev/nvme0n1", "--ses=2", "--force"],
        ["nvme", "format", "/dev/nvme0n1", "--ses=1", "--force"],
    ]


def test_wipe_device_falls_back_to_shred_when_both_nvme_formats_fail(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(disk_wipe.time, "sleep", lambda seconds: None)

    run_calls = []
    monkeypatch.setattr(
        disk_wipe.subprocess, "run",
        lambda cmd, capture_output=True, text=True, check=False: run_calls.append(cmd) or FakeCompleted(returncode=1),
    )

    popen_calls = []
    fake_popen = FakePopen(poll_sequence=[0], returncode=0)
    monkeypatch.setattr(
        disk_wipe.subprocess, "Popen",
        lambda cmd, stdout=None, stderr=None, text=None: popen_calls.append(cmd) or fake_popen,
    )

    result = disk_wipe.wipe_device("/dev/nvme0n1", passes=3, dry_run=False)

    assert result.method == "shred"
    assert result.completed is True
    assert run_calls == [
        ["nvme", "format", "/dev/nvme0n1", "--ses=2", "--force"],
        ["nvme", "format", "/dev/nvme0n1", "--ses=1", "--force"],
    ]
    assert popen_calls == [["shred", "--iterations=3", "--zero", "/dev/nvme0n1"]]


def test_wipe_device_skips_nvme_path_when_nvme_cli_missing(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", _which_everything_but_nvme)
    monkeypatch.setattr(disk_wipe.time, "sleep", lambda seconds: None)

    run_calls = []
    monkeypatch.setattr(
        disk_wipe.subprocess, "run",
        lambda cmd, capture_output=True, text=True, check=False: run_calls.append(cmd) or FakeCompleted(returncode=0),
    )
    fake_popen = FakePopen(poll_sequence=[0], returncode=0)
    monkeypatch.setattr(disk_wipe.subprocess, "Popen", lambda cmd, stdout=None, stderr=None, text=None: fake_popen)

    result = disk_wipe.wipe_device("/dev/nvme0n1", passes=3, dry_run=False)

    assert result.method == "shred"
    assert run_calls == []


def test_wipe_device_skips_nvme_path_for_non_nvme_device(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(disk_wipe.time, "sleep", lambda seconds: None)

    run_calls = []
    monkeypatch.setattr(
        disk_wipe.subprocess, "run",
        lambda cmd, capture_output=True, text=True, check=False: run_calls.append(cmd) or FakeCompleted(returncode=0),
    )
    popen_calls = []
    fake_popen = FakePopen(poll_sequence=[0], returncode=0)
    monkeypatch.setattr(
        disk_wipe.subprocess, "Popen",
        lambda cmd, stdout=None, stderr=None, text=None: popen_calls.append(cmd) or fake_popen,
    )

    result = disk_wipe.wipe_device("/dev/sdb", passes=3, dry_run=False)

    assert result.method == "shred"
    assert run_calls == []
    assert popen_calls == [["shred", "--iterations=3", "--zero", "/dev/sdb"]]


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
    monkeypatch.setattr(disk_wipe.time, "sleep", lambda seconds: None)

    calls = {}
    fake_popen = FakePopen(poll_sequence=[0], returncode=0)

    def fake_popen_factory(cmd, stdout=None, stderr=None, text=None):
        calls["cmd"] = cmd
        return fake_popen

    monkeypatch.setattr(disk_wipe.subprocess, "Popen", fake_popen_factory)

    result = disk_wipe.wipe_device("/dev/sdb", passes=3, dry_run=False)

    assert result.attempted is True
    assert result.completed is True
    assert result.method == "shred"
    assert calls["cmd"] == ["shred", "--iterations=3", "--zero", "/dev/sdb"]


def test_wipe_device_reports_shred_failure(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: "/usr/bin/shred")
    monkeypatch.setattr(disk_wipe.time, "sleep", lambda seconds: None)

    fake_popen = FakePopen(poll_sequence=[1], returncode=1, stderr_text="Device busy")
    monkeypatch.setattr(disk_wipe.subprocess, "Popen", lambda cmd, stdout=None, stderr=None, text=None: fake_popen)

    result = disk_wipe.wipe_device("/dev/sdb", passes=3, dry_run=False)

    assert result.completed is False
    assert "Device busy" in result.error


def test_wipe_device_shred_reports_real_progress_from_proc_io(monkeypatch, tmp_path):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: "/usr/bin/shred")
    monkeypatch.setattr(disk_wipe.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(disk_wipe, "_device_size_bytes", lambda device: 1000)

    write_bytes_sequence = iter([500, 1500])
    monkeypatch.setattr(disk_wipe, "_shred_write_bytes", lambda pid: next(write_bytes_sequence))

    fake_popen = FakePopen(poll_sequence=[None, None, 0], returncode=0)
    monkeypatch.setattr(disk_wipe.subprocess, "Popen", lambda cmd, stdout=None, stderr=None, text=None: fake_popen)

    fractions = []
    result = disk_wipe.wipe_device(
        str(tmp_path / "fake-device"), passes=1, dry_run=False, progress_callback=fractions.append,
    )

    assert result.completed is True
    # total_write_bytes = device size (1000) * (1 pass + 1 final zero pass) = 2000
    assert fractions == [0.25, 0.75, 1.0]


def test_wipe_device_shred_progress_is_none_when_size_unknown(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: "/usr/bin/shred")
    monkeypatch.setattr(disk_wipe.time, "sleep", lambda seconds: None)

    fake_popen = FakePopen(poll_sequence=[None, 0], returncode=0)
    monkeypatch.setattr(disk_wipe.subprocess, "Popen", lambda cmd, stdout=None, stderr=None, text=None: fake_popen)

    fractions = []
    disk_wipe.wipe_device("/dev/does-not-exist-in-this-test", passes=1, dry_run=False, progress_callback=fractions.append)

    assert fractions == [None, 1.0]


def test_wipe_device_overwrite_fallback_writes_random_data(tmp_path, monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: None)

    fake_device = tmp_path / "fake-device"
    fake_device.write_bytes(b"original-sensitive-data")

    fractions = []
    result = disk_wipe.wipe_device(str(fake_device), passes=2, dry_run=False, progress_callback=fractions.append)

    assert result.method == "overwrite-fallback"
    assert result.completed is True
    assert fake_device.read_bytes() != b"original-sensitive-data"
    assert len(fake_device.read_bytes()) == len(b"original-sensitive-data")
    assert fractions[-1] == 1.0


def test_wipe_device_overwrite_fallback_reports_errors(monkeypatch):
    monkeypatch.setattr(disk_wipe.shutil, "which", lambda name: None)

    result = disk_wipe.wipe_device("/path/does/not/exist", passes=1, dry_run=False)

    assert result.method == "overwrite-fallback"
    assert result.completed is False
    assert result.error is not None
