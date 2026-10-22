from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ToolInventoryResult:
    device: str
    root_partition: Optional[str]
    attempted: bool
    completed: bool
    package_count: Optional[int] = None
    output_path: Optional[str] = None
    error: Optional[str] = None


def _list_partitions(device: str) -> List[str]:
    completed = subprocess.run(
        ["lsblk", "-ln", "-o", "PATH", device],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip() and line.strip() != device]


def _parse_dpkg_status(status_text: str) -> Dict[str, str]:
    packages: Dict[str, str] = {}
    name: Optional[str] = None
    for line in status_text.splitlines():
        if line.startswith("Package:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Version:") and name is not None:
            packages[name] = line.split(":", 1)[1].strip()
            name = None
    return packages


def inventory_installed_packages(
    device: str,
    output_dir: Path,
    mount_point: Path,
    dry_run: bool = True,
) -> ToolInventoryResult:
    """After live_wipe() restores the golden image onto `device`, mount its
    root partition read-only and dump every installed package with its
    version to a JSON file next to the certificate.

    This confirms the restored system matches the expected golden-image
    baseline. It is informational only: a failure here does not affect
    LiveWipeReport.passed, since the sanitisation and reimage already
    succeeded by the time this runs. Only usable in live-wipe (the restore
    happens in this same process); full-reset schedules the actual restore
    for after reboot, so this step can't run there, see live_wipe.py.

    Each partition of `device` is tried in turn since the root partition's
    number can vary between golden images. A partition only counts once its
    dpkg status database is actually found on it.
    """
    if dry_run:
        return ToolInventoryResult(device=device, root_partition=None, attempted=False, completed=False)

    partitions = _list_partitions(device)
    if not partitions:
        return ToolInventoryResult(
            device=device, root_partition=None, attempted=True, completed=False,
            error="Aucune partition trouvee sur le disque restaure",
        )

    mount_point = Path(mount_point)
    mount_point.mkdir(parents=True, exist_ok=True)

    for partition in partitions:
        mounted = subprocess.run(
            ["mount", "-o", "ro", partition, str(mount_point)],
            capture_output=True, text=True, check=False,
        )
        if mounted.returncode != 0:
            continue
        try:
            status_file = mount_point / "var" / "lib" / "dpkg" / "status"
            if not status_file.exists():
                continue
            packages = _parse_dpkg_status(status_file.read_text(encoding="utf-8", errors="replace"))
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / "tool-inventory.json"
            output_path.write_text(json.dumps(packages, indent=2, sort_keys=True), encoding="utf-8")
            return ToolInventoryResult(
                device=device, root_partition=partition, attempted=True, completed=True,
                package_count=len(packages), output_path=str(output_path),
            )
        finally:
            subprocess.run(["umount", str(mount_point)], capture_output=True, text=True, check=False)

    return ToolInventoryResult(
        device=device, root_partition=None, attempted=True, completed=False,
        error="Aucune partition avec /var/lib/dpkg/status trouvee (image non Debian/Kali, ou restauration incomplete)",
    )
