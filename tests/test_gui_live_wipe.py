from clientwipe import gui_live_wipe


class FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_boot_device_resolves_parent_disk(monkeypatch):
    def fake_run(cmd, capture_output=True, text=True, check=False):
        if cmd[0] == "findmnt":
            return FakeCompleted("/dev/sda1\n")
        if cmd[0] == "lsblk":
            return FakeCompleted("sda\n")
        return FakeCompleted()

    monkeypatch.setattr(gui_live_wipe.subprocess, "run", fake_run)

    assert gui_live_wipe.boot_device() == "/dev/sda"


def test_boot_device_returns_none_when_findmnt_fails(monkeypatch):
    monkeypatch.setattr(
        gui_live_wipe.subprocess, "run",
        lambda cmd, capture_output=True, text=True, check=False: FakeCompleted("", returncode=1),
    )

    assert gui_live_wipe.boot_device() is None


def test_list_candidate_devices_excludes_boot_device_and_non_disks(monkeypatch):
    lsblk_output = (
        "/dev/sda   1.8T   WD Elements   disk\n"
        "/dev/sda1  97.7G                part\n"
        "/dev/nvme0n1   953.9G   Samsung SSD   disk\n"
    )
    monkeypatch.setattr(
        gui_live_wipe.subprocess, "run",
        lambda cmd, capture_output=True, text=True, check=False: FakeCompleted(lsblk_output),
    )

    devices = gui_live_wipe.list_candidate_devices(exclude="/dev/sda")

    assert len(devices) == 1
    assert devices[0].path == "/dev/nvme0n1"
    assert devices[0].size == "953.9G"
    assert "Samsung" in devices[0].model


def test_list_candidate_devices_returns_empty_on_lsblk_failure(monkeypatch):
    monkeypatch.setattr(
        gui_live_wipe.subprocess, "run",
        lambda cmd, capture_output=True, text=True, check=False: FakeCompleted("", returncode=1),
    )

    assert gui_live_wipe.list_candidate_devices() == []


def test_find_images_repository_lists_partitions_not_only_disks(monkeypatch, tmp_path):
    # Regression test: an earlier version passed lsblk the -d flag, which
    # hides partitions and only lists whole disks, so the golden image
    # partition (sda4, ntfs) was never seen on real hardware even though a
    # manual mount of it worked fine.
    lsblk_calls = []

    def fake_run(cmd, capture_output=True, text=True, check=False):
        if cmd[0] == "lsblk":
            lsblk_calls.append(cmd)
            return FakeCompleted("/dev/sdb4 part\n")
        if cmd[0] == "findmnt":
            return FakeCompleted("")
        if cmd[0] == "mount":
            (tmp_path / "mnt" / "KaliState0").mkdir(parents=True, exist_ok=True)
            return FakeCompleted()
        return FakeCompleted()

    monkeypatch.setattr(gui_live_wipe.subprocess, "run", fake_run)

    found = gui_live_wipe.find_images_repository("KaliState0", tmp_path / "mnt")

    assert found == tmp_path / "mnt"
    assert lsblk_calls == [["lsblk", "-no", "PATH,TYPE"]]


def test_find_images_repository_uses_already_mounted_partition(monkeypatch, tmp_path):
    existing_mount = tmp_path / "already-mounted"
    (existing_mount / "KaliState0").mkdir(parents=True)

    def fake_run(cmd, capture_output=True, text=True, check=False):
        if cmd[0] == "lsblk":
            return FakeCompleted("/dev/sdb4 part\n")
        if cmd[0] == "findmnt":
            return FakeCompleted(f"{existing_mount}\n")
        return FakeCompleted()

    monkeypatch.setattr(gui_live_wipe.subprocess, "run", fake_run)

    found = gui_live_wipe.find_images_repository("KaliState0", tmp_path / "mnt", exclude_device="/dev/nvme0n1")

    assert found == existing_mount


def test_find_images_repository_mounts_unmounted_candidate(monkeypatch, tmp_path):
    mount_point = tmp_path / "mnt"

    def fake_run(cmd, capture_output=True, text=True, check=False):
        if cmd[0] == "lsblk":
            return FakeCompleted("/dev/sdb4 part\n")
        if cmd[0] == "findmnt":
            return FakeCompleted("")
        if cmd[0] == "mount":
            (mount_point / "KaliState0").mkdir(parents=True, exist_ok=True)
            return FakeCompleted()
        return FakeCompleted()

    monkeypatch.setattr(gui_live_wipe.subprocess, "run", fake_run)

    found = gui_live_wipe.find_images_repository("KaliState0", mount_point)

    assert found == mount_point


def test_find_images_repository_skips_excluded_device(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, capture_output=True, text=True, check=False):
        if cmd[0] == "lsblk":
            return FakeCompleted("/dev/nvme0n1p1 part\n")
        calls.append(cmd)
        return FakeCompleted()

    monkeypatch.setattr(gui_live_wipe.subprocess, "run", fake_run)

    found = gui_live_wipe.find_images_repository("KaliState0", tmp_path / "mnt", exclude_device="/dev/nvme0n1p1")

    assert found is None
    assert calls == []


def test_find_images_repository_unmounts_non_matching_candidate(monkeypatch, tmp_path):
    mount_point = tmp_path / "mnt"
    umount_calls = []

    def fake_run(cmd, capture_output=True, text=True, check=False):
        if cmd[0] == "lsblk":
            return FakeCompleted("/dev/sdb4 part\n")
        if cmd[0] == "findmnt":
            return FakeCompleted("")
        if cmd[0] == "mount":
            return FakeCompleted()
        if cmd[0] == "umount":
            umount_calls.append(cmd)
            return FakeCompleted()
        return FakeCompleted()

    monkeypatch.setattr(gui_live_wipe.subprocess, "run", fake_run)

    found = gui_live_wipe.find_images_repository("KaliState0", mount_point)

    assert found is None
    assert len(umount_calls) == 1
