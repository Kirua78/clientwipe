from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class GraphicalSession:
    user: str
    display: str


def _run(cmd: list) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


def find_graphical_session() -> Optional[GraphicalSession]:
    """Best-effort discovery of the active local graphical session, so a
    root-level service can show a dialog on that desktop.

    Picks the first active logind session that has both a user and a
    Display. Tested with LightDM/Xfce (Kali default); other display
    managers may need a different lookup.
    """
    if shutil.which("loginctl") is None:
        return None

    listing = _run(["loginctl", "list-sessions", "--no-legend"])
    for line in listing.splitlines():
        parts = line.split()
        if not parts:
            continue
        session_id = parts[0]
        props = _run([
            "loginctl", "show-session", session_id,
            "-p", "Name", "-p", "Display", "-p", "State",
        ])
        values = dict(re.findall(r"^(\w+)=(.*)$", props, re.MULTILINE))
        if values.get("State") != "active":
            continue
        user = values.get("Name")
        display = values.get("Display")
        if user and display:
            return GraphicalSession(user=user, display=display)
    return None


def _uid_for(user: str) -> Optional[int]:
    # Imported lazily: the pwd module only exists on POSIX, and this whole
    # feature is Linux-only already (udev/systemd), like the rest of the
    # USB-trigger path, but importing it at module level would break
    # collecting this module (and its tests) on a non-POSIX dev machine.
    import pwd

    try:
        return pwd.getpwnam(user).pw_uid
    except KeyError:
        return None


def _find_xauthority(user: str) -> Optional[str]:
    uid = _uid_for(user)
    candidates = [Path(f"/home/{user}/.Xauthority")]
    if uid is not None:
        candidates.append(Path(f"/run/user/{uid}/gdm/Xauthority"))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def ask_confirmation_gui(message: str, timeout: int = 30) -> Optional[bool]:
    """Show a graphical "Autoriser"/"Refuser" dialog on the active desktop
    session, used when there is no terminal to ask in (the USB-triggered
    systemd path). Returns True/False for an actual answer, or None when
    there is simply no one to ask (no zenity, no active graphical session) --
    the caller treats None as "refuse and flag for review", not as "yes".
    """
    if shutil.which("zenity") is None:
        return None

    session = find_graphical_session()
    if session is None:
        return None

    env_args = [f"DISPLAY={session.display}"]
    xauthority = _find_xauthority(session.user)
    if xauthority:
        env_args.append(f"XAUTHORITY={xauthority}")

    cmd = [
        "sudo", "-u", session.user, "env", *env_args,
        "zenity", "--question",
        "--title=ClientWipe",
        f"--text={message}",
        "--ok-label=Autoriser",
        "--cancel-label=Refuser",
        f"--timeout={timeout}",
    ]
    completed = subprocess.run(cmd, check=False)
    return completed.returncode == 0
