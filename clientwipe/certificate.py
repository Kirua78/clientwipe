from __future__ import annotations

import getpass
import hashlib
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

from . import __version__
from .full_wipe import FullWipeReport
from .sanitize import SanitizeReport
from .verify import VerificationReport

HTML_TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Certificat de sanitisation - {hostname}</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 720px; margin: 2rem auto; color: #1a1a1a; }}
h1 {{ font-size: 1.3rem; }}
.status {{ display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px; font-weight: bold; }}
.pass {{ background: #d4f7dc; color: #157347; }}
.fail {{ background: #f8d7da; color: #842029; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
td, th {{ border: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; font-size: 0.9rem; }}
code {{ background: #f4f4f4; padding: 0.1rem 0.3rem; }}
</style>
</head>
<body>
<h1>Certificat de sanitisation ClientWipe</h1>
<p><span class="status {status_class}">{status_label}</span></p>
<ul>
<li>Poste : <code>{hostname}</code></li>
<li>Operateur : <code>{operator}</code></li>
<li>Racine sanitisee : <code>{root}</code></li>
<li>Methode d'effacement : <code>{method}</code> ({passes} passes)</li>
<li>Duree : {duration_seconds} s</li>
<li>Genere le : {generated_at}</li>
<li>Version ClientWipe : {version}</li>
<li>Snapshot Timeshift avant sanitisation : {snapshot_line}</li>
<li>Empreinte SHA-256 du rapport : <code>{sha256}</code></li>
</ul>
<h2>Detail par cible</h2>
<table>
<tr><th>Cible</th><th>Fichiers effaces</th><th>Octets effaces</th><th>Verification</th></tr>
{rows}
</table>
</body>
</html>
"""


FULL_WIPE_HTML_TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Certificat de remise a zero - {hostname}</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 720px; margin: 2rem auto; color: #1a1a1a; }}
h1 {{ font-size: 1.3rem; }}
.status {{ display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px; font-weight: bold; }}
.pass {{ background: #d4f7dc; color: #157347; }}
.fail {{ background: #f8d7da; color: #842029; }}
code {{ background: #f4f4f4; padding: 0.1rem 0.3rem; }}
</style>
</head>
<body>
<h1>Certificat de remise a zero complete ClientWipe</h1>
<p><span class="status {status_class}">{status_label}</span></p>
<ul>
<li>Poste : <code>{hostname}</code></li>
<li>Operateur : <code>{operator}</code></li>
<li>Peripherique : <code>{device}</code></li>
<li>Chiffrement LUKS detecte : {luks_detected}</li>
<li>Cle LUKS detruite : {luks_erased}</li>
<li>Entree GRUB de reimagage programmee : {boot_entry} ({reboot_scheduled})</li>
<li>Genere le : {generated_at}</li>
<li>Version ClientWipe : {version}</li>
<li>Snapshot Timeshift avant operation : {snapshot_line}</li>
<li>Empreinte SHA-256 du rapport : <code>{sha256}</code></li>
</ul>
</body>
</html>
"""


def _build_rows(sanitize_report: SanitizeReport, verify_report: VerificationReport) -> str:
    verify_by_name = {t.name: t for t in verify_report.targets}
    rows = []
    for target_result in sanitize_report.targets:
        verification = verify_by_name.get(target_result.name)
        verdict = "PASS" if (verification and verification.passed) else "FAIL"
        rows.append(
            f"<tr><td>{target_result.name}</td><td>{target_result.files_wiped}</td>"
            f"<td>{target_result.bytes_wiped}</td><td>{verdict}</td></tr>"
        )
    return "\n".join(rows)


def _gpg_sign(json_path: Path, key_id: Optional[str]) -> Optional[Path]:
    if not key_id or shutil.which("gpg") is None:
        return None
    sig_path = json_path.with_suffix(json_path.suffix + ".asc")
    subprocess.run(
        [
            "gpg", "--batch", "--yes", "--local-user", key_id,
            "--armor", "--detach-sign", "--output", str(sig_path), str(json_path),
        ],
        check=True,
    )
    return sig_path


def _snapshot_line(snapshot: Optional[dict]) -> str:
    if snapshot is None:
        return "non demande"
    if snapshot.get("created"):
        return f"OK (\"{snapshot.get('comment')}\")"
    if snapshot.get("attempted"):
        return f"ECHEC ({snapshot.get('error')})"
    return f"non disponible ({snapshot.get('error')})"


def generate_certificate(
    sanitize_report: SanitizeReport,
    verify_report: VerificationReport,
    out_dir: Path,
    gpg_key_id: Optional[str] = None,
    operator: Optional[str] = None,
    snapshot: Optional[dict] = None,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    timestamp_slug = time.strftime("%Y%m%d-%H%M%S")

    payload = {
        "tool": "clientwipe",
        "version": __version__,
        "hostname": socket.gethostname(),
        "operator": operator or getpass.getuser(),
        "generated_at": generated_at,
        "pre_snapshot": snapshot,
        "sanitize": sanitize_report.to_dict(),
        "verify": verify_report.to_dict(),
        "overall_passed": verify_report.passed,
    }

    sha256 = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    payload["sha256"] = sha256

    json_path = out_dir / f"certificate-{timestamp_slug}.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    html_path = out_dir / f"certificate-{timestamp_slug}.html"
    html_path.write_text(
        HTML_TEMPLATE.format(
            hostname=payload["hostname"],
            status_class="pass" if payload["overall_passed"] else "fail",
            status_label="SANITISATION VALIDEE" if payload["overall_passed"] else "ECHEC - RESIDUS DETECTES",
            operator=payload["operator"],
            root=sanitize_report.root,
            method=sanitize_report.method,
            passes=sanitize_report.passes,
            duration_seconds=sanitize_report.duration_seconds,
            generated_at=generated_at,
            version=__version__,
            snapshot_line=_snapshot_line(snapshot),
            sha256=sha256,
            rows=_build_rows(sanitize_report, verify_report),
        ),
        encoding="utf-8",
    )

    signature_path = _gpg_sign(json_path, gpg_key_id)

    return {
        "json_path": str(json_path),
        "html_path": str(html_path),
        "signature_path": str(signature_path) if signature_path else None,
        "sha256": sha256,
        "overall_passed": payload["overall_passed"],
    }


def generate_full_wipe_certificate(
    report: FullWipeReport,
    out_dir: Path,
    gpg_key_id: Optional[str] = None,
    operator: Optional[str] = None,
    snapshot: Optional[dict] = None,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    timestamp_slug = time.strftime("%Y%m%d-%H%M%S")

    payload = {
        "tool": "clientwipe",
        "version": __version__,
        "operation": "full-reset",
        "hostname": socket.gethostname(),
        "operator": operator or getpass.getuser(),
        "generated_at": generated_at,
        "pre_snapshot": snapshot,
        "full_wipe": report.to_dict(),
        "overall_passed": report.passed,
    }

    sha256 = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    payload["sha256"] = sha256

    json_path = out_dir / f"full-reset-certificate-{timestamp_slug}.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    luks_erased = "n/a (pas de LUKS)"
    if report.luks_detected:
        luks_erased = "oui" if (report.luks_erase and report.luks_erase.erased) else "ECHEC"

    html_path = out_dir / f"full-reset-certificate-{timestamp_slug}.html"
    html_path.write_text(
        FULL_WIPE_HTML_TEMPLATE.format(
            hostname=payload["hostname"],
            status_class="pass" if payload["overall_passed"] else "fail",
            status_label="REMISE A ZERO PROGRAMMEE" if payload["overall_passed"] else "ECHEC",
            operator=payload["operator"],
            device=report.device,
            luks_detected="oui" if report.luks_detected else "non",
            luks_erased=luks_erased,
            boot_entry=report.boot_entry,
            reboot_scheduled="OK" if report.reboot_scheduled.scheduled else "ECHEC",
            generated_at=generated_at,
            version=__version__,
            snapshot_line=_snapshot_line(snapshot),
            sha256=sha256,
        ),
        encoding="utf-8",
    )

    signature_path = _gpg_sign(json_path, gpg_key_id)

    return {
        "json_path": str(json_path),
        "html_path": str(html_path),
        "signature_path": str(signature_path) if signature_path else None,
        "sha256": sha256,
        "overall_passed": payload["overall_passed"],
    }
