from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class SnapshotResult:
    attempted: bool
    created: bool
    comment: str
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None


def timeshift_available() -> bool:
    return shutil.which("timeshift") is not None


def create_snapshot(comment: str) -> SnapshotResult:
    """Take a Timeshift system snapshot right before a real sanitization run,
    so there is always a rollback point if something goes wrong.

    This is a safety net baked into the tool itself (distinct from the
    snapshot a tester takes manually before trying the tool on a VM): every
    real `run`/`trigger` execution can leave its own restore point behind.
    No-ops safely when Timeshift isn't installed or configured, which is
    expected on the demo sandbox and in CI, where this doesn't apply.
    """
    if not timeshift_available():
        return SnapshotResult(
            attempted=False, created=False, comment=comment,
            error="timeshift n'est pas installe sur ce poste",
        )

    completed = subprocess.run(
        ["timeshift", "--create", "--comments", comment, "--scripted"],
        capture_output=True,
        text=True,
        check=False,
    )
    created = completed.returncode == 0
    return SnapshotResult(
        attempted=True,
        created=created,
        comment=comment,
        stdout=completed.stdout,
        stderr=completed.stderr,
        error=None if created else (completed.stderr.strip() or "timeshift a renvoye un code d'erreur"),
    )
