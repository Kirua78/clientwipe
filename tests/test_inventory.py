import json
from pathlib import Path

from clientwipe import inventory


def test_inventory_dry_run_does_not_execute(monkeypatch, tmp_path):
    result = inventory.inventory_installed_packages("/dev/sda", tmp_path, tmp_path / "mnt", dry_run=True)

    assert result.attempted is False
    assert result.completed is False


def test_inventory_fails_when_no_partitions_found(monkeypatch, tmp_path):
    monkeypatch.setattr(inventory, "_list_partitions", lambda device: [])

    result = inventory.inventory_installed_packages("/dev/sda", tmp_path, tmp_path / "mnt", dry_run=False)

    assert result.attempted is True
    assert result.completed is False
    assert "Aucune partition" in result.error


def test_inventory_writes_json_from_dpkg_status(monkeypatch, tmp_path):
    monkeypatch.setattr(inventory, "_list_partitions", lambda device: ["/dev/sda1", "/dev/sda3"])

    class FakeCompleted:
        returncode = 0

    mount_point = tmp_path / "mnt"
    output_dir = tmp_path / "out"
    mount_calls = []

    def fake_run(cmd, capture_output=True, text=True, check=False):
        if cmd[0] == "mount":
            partition = cmd[-2]
            mount_calls.append(partition)
            status_dir = mount_point / "var" / "lib" / "dpkg"
            if partition == "/dev/sda3":
                status_dir.mkdir(parents=True, exist_ok=True)
                (status_dir / "status").write_text(
                    "Package: nmap\nVersion: 7.94\n\nPackage: burpsuite\nVersion: 2024.1\n",
                    encoding="utf-8",
                )
            elif status_dir.exists():
                import shutil
                shutil.rmtree(status_dir)
        return FakeCompleted()

    monkeypatch.setattr(inventory.subprocess, "run", fake_run)

    result = inventory.inventory_installed_packages("/dev/sda", output_dir, mount_point, dry_run=False)

    assert mount_calls == ["/dev/sda1", "/dev/sda3"]
    assert result.completed is True
    assert result.root_partition == "/dev/sda3"
    assert result.package_count == 2
    assert result.git_clone_count == 0

    written = json.loads((output_dir / "tool-inventory.json").read_text(encoding="utf-8"))
    assert written == {"dpkg_packages": {"nmap": "7.94", "burpsuite": "2024.1"}, "git_clones": {}}


def test_inventory_reports_failure_when_no_dpkg_status_found(monkeypatch, tmp_path):
    monkeypatch.setattr(inventory, "_list_partitions", lambda device: ["/dev/sda1"])

    class FakeCompleted:
        returncode = 0

    monkeypatch.setattr(inventory.subprocess, "run", lambda cmd, capture_output=True, text=True, check=False: FakeCompleted())

    result = inventory.inventory_installed_packages("/dev/sda", tmp_path / "out", tmp_path / "mnt", dry_run=False)

    assert result.completed is False
    assert result.attempted is True
    assert "dpkg" in result.error


def test_parse_dpkg_status_extracts_name_and_version():
    text = (
        "Package: nmap\n"
        "Status: install ok installed\n"
        "Version: 7.94\n"
        "\n"
        "Package: sqlmap\n"
        "Version: 1.8\n"
    )

    packages = inventory._parse_dpkg_status(text)

    assert packages == {"nmap": "7.94", "sqlmap": "1.8"}


def test_find_git_repos_stops_at_repo_root(tmp_path):
    opt = tmp_path / "opt"
    (opt / "tool1" / ".git").mkdir(parents=True)
    (opt / "tool1" / ".git" / "not-a-repo" / ".git").mkdir(parents=True)
    (opt / "plain-dir").mkdir(parents=True)
    (opt / "nested" / "tool2" / ".git").mkdir(parents=True)

    repos = inventory._find_git_repos(opt)

    assert sorted(repos) == sorted([opt / "tool1", opt / "nested" / "tool2"])


def test_find_git_repos_returns_empty_when_dir_missing(tmp_path):
    assert inventory._find_git_repos(tmp_path / "does-not-exist") == []


def test_git_info_runs_git_with_safe_directory(monkeypatch, tmp_path):
    calls = []

    class FakeCompleted:
        def __init__(self, stdout, returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls.append(cmd)
        if "remote" in cmd:
            return FakeCompleted("https://github.com/example/tool.git\n")
        if "rev-parse" in cmd:
            return FakeCompleted("abc1234567890\n")
        if "describe" in cmd:
            return FakeCompleted("v1.2-3-gabc1234\n")
        return FakeCompleted("", returncode=1)

    monkeypatch.setattr(inventory.subprocess, "run", fake_run)

    info = inventory._git_info(tmp_path / "opt" / "tool1")

    assert info == {
        "remote": "https://github.com/example/tool.git",
        "commit": "abc1234567890",
        "describe": "v1.2-3-gabc1234",
    }
    assert all("safe.directory=*" in cmd for cmd in calls)


def test_git_info_handles_missing_remote(monkeypatch, tmp_path):
    def fake_run(cmd, capture_output=True, text=True, check=False):
        class FakeCompleted:
            stdout = ""
            returncode = 1

        return FakeCompleted()

    monkeypatch.setattr(inventory.subprocess, "run", fake_run)

    info = inventory._git_info(tmp_path / "opt" / "tool1")

    assert info == {"remote": None, "commit": None, "describe": None}


def test_scan_git_clones_combines_repos_with_their_info(monkeypatch, tmp_path):
    mount_point = tmp_path / "mnt"
    (mount_point / "opt" / "tool1" / ".git").mkdir(parents=True)

    monkeypatch.setattr(
        inventory, "_git_info",
        lambda repo_path: {"remote": "https://example.com/tool1.git", "commit": "deadbeef", "describe": "v1"},
    )

    clones = inventory._scan_git_clones(mount_point, "opt")

    repo_key = str(Path("opt") / "tool1")
    assert clones == {
        repo_key: {"remote": "https://example.com/tool1.git", "commit": "deadbeef", "describe": "v1"},
    }


def test_inventory_includes_git_clones_from_opt(monkeypatch, tmp_path):
    monkeypatch.setattr(inventory, "_list_partitions", lambda device: ["/dev/sda3"])

    mount_point = tmp_path / "mnt"
    output_dir = tmp_path / "out"

    class FakeCompleted:
        def __init__(self, stdout="", returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(cmd, capture_output=True, text=True, check=False):
        if cmd[0] == "mount":
            status_dir = mount_point / "var" / "lib" / "dpkg"
            status_dir.mkdir(parents=True, exist_ok=True)
            (status_dir / "status").write_text("Package: nmap\nVersion: 7.94\n", encoding="utf-8")
            (mount_point / "opt" / "customtool" / ".git").mkdir(parents=True, exist_ok=True)
            return FakeCompleted()
        if cmd[0] == "git":
            if "remote" in cmd:
                return FakeCompleted("https://github.com/example/customtool.git\n")
            if "rev-parse" in cmd:
                return FakeCompleted("1234567\n")
            if "describe" in cmd:
                return FakeCompleted("1234567\n")
        return FakeCompleted()

    monkeypatch.setattr(inventory.subprocess, "run", fake_run)

    result = inventory.inventory_installed_packages("/dev/sda", output_dir, mount_point, dry_run=False)

    assert result.completed is True
    assert result.git_clone_count == 1

    written = json.loads((output_dir / "tool-inventory.json").read_text(encoding="utf-8"))
    repo_key = str(Path("opt") / "customtool")
    assert written["git_clones"][repo_key]["remote"] == "https://github.com/example/customtool.git"
    assert written["git_clones"][repo_key]["commit"] == "1234567"
