from __future__ import annotations

from pathlib import Path

FAKE_BURP_PROJECT = b"Burp Suite Professional project file (demo placeholder, not a real project)"
FAKE_SSH_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "THIS IS A FAKE DEMO KEY, NOT A REAL CREDENTIAL\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)
FAKE_BASH_HISTORY = (
    "ssh root@10.10.10.42\n"
    "mysql -u admin -p'SuperSecretDemo123'\n"
    "cat /etc/shadow\n"
)
FAKE_OVPN = (
    "client\n"
    "remote vpn.fake-client-demo.example 1194\n"
    "auth-user-pass demo-credentials.txt\n"
)


def create_sandbox(path: Path) -> Path:
    """Populate `path` with fake-but-realistic sensitive files, standing in
    for a real pentest workstation. Never touches anything outside `path`,
    so it's safe to run against any throwaway directory."""
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)

    (root / ".ssh").mkdir(parents=True, exist_ok=True)
    (root / ".ssh" / "id_rsa").write_text(FAKE_SSH_KEY, encoding="utf-8")
    (root / ".ssh" / "known_hosts").write_text("fake-host ssh-ed25519 AAAA...\n", encoding="utf-8")

    (root / ".BurpSuite").mkdir(parents=True, exist_ok=True)
    (root / "client-acme-corp.burp").write_bytes(FAKE_BURP_PROJECT)

    (root / ".openvpn").mkdir(parents=True, exist_ok=True)
    (root / "acme-corp-access.ovpn").write_text(FAKE_OVPN, encoding="utf-8")

    (root / ".bash_history").write_text(FAKE_BASH_HISTORY, encoding="utf-8")

    (root / "Downloads").mkdir(parents=True, exist_ok=True)
    (root / "Downloads" / "acme-corp-network-diagram.pdf").write_bytes(b"%PDF-1.4 demo placeholder")

    return root
