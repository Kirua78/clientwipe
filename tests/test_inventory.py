import json

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

    written = json.loads((output_dir / "tool-inventory.json").read_text(encoding="utf-8"))
    assert written == {"nmap": "7.94", "burpsuite": "2024.1"}


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
