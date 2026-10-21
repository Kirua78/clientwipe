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
from .live_wipe import LiveWipeReport
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
<li>Chiffrement BitLocker detecte : {bitlocker_detected}</li>
<li>Niveau NIST SP 800-88 atteint : <strong>{nist_level}</strong></li>
<li>Sauvegarde de l'en-tete LUKS : {header_backup_line}</li>
<li>Cle LUKS detruite : {luks_erased}</li>
<li>Multi-passes de secours (si pas de LUKS) : {device_wipe_line}</li>
<li>Entree GRUB de reimagage programmee : {boot_entry} ({reboot_scheduled})</li>
<li>Genere le : {generated_at}</li>
<li>Version ClientWipe : {version}</li>
<li>Snapshot Timeshift avant operation : {snapshot_line}</li>
<li>Empreinte SHA-256 du rapport : <code>{sha256}</code></li>
</ul>
</body>
</html>
"""


LIVE_WIPE_HTML_TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Certificat de remise a zero (cle autonome) - {hostname}</title>
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
<h1>Certificat de remise a zero ClientWipe (cle autonome)</h1>
<p><span class="status {status_class}">{status_label}</span></p>
<ul>
<li>Poste : <code>{hostname}</code></li>
<li>Operateur : <code>{operator}</code></li>
<li>Peripherique efface : <code>{device}</code></li>
<li>Image de reference restauree : <code>{image_name}</code></li>
<li>Chiffrement LUKS detecte : {luks_detected}</li>
<li>Chiffrement BitLocker detecte : {bitlocker_detected}</li>
<li>Niveau NIST SP 800-88 atteint : <strong>{nist_level}</strong></li>
<li>Sauvegarde de l'en-tete LUKS : {header_backup_line}</li>
<li>Cle LUKS detruite : {luks_erased}</li>
<li>Multi-passes de secours (si pas de LUKS) : {device_wipe_line}</li>
<li>Reimagage : {imaging_status}</li>
<li>Genere le : {generated_at}</li>
<li>Version ClientWipe : {version}</li>
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


def _device_wipe_line(device_wipe: Optional[object]) -> str:
    if device_wipe is None:
        return "non applicable (LUKS present)"
    if device_wipe.completed:
        return f"OK ({device_wipe.method}, {device_wipe.passes} passes)"
    if device_wipe.attempted:
        return f"ECHEC ({device_wipe.error})"
    return f"non execute ({device_wipe.error})"


def _nist_level(luks_detected: bool, bitlocker_detected: bool) -> str:
    if luks_detected:
        return "Purge (effacement cryptographique, destruction de cle LUKS)"
    if bitlocker_detected:
        return (
            "Clear (BitLocker detecte mais non detruit, non pris en charge, "
            "voir bitlocker.py ; multi-passes de secours puis reimagage complet effectues)"
        )
    return "Clear (pas de chiffrement detecte ; multi-passes de secours puis reimagage complet effectues)"


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

    nist_level = _nist_level(report.luks_detected, report.bitlocker_detected)

    payload = {
        "tool": "clientwipe",
        "version": __version__,
        "operation": "full-reset",
        "hostname": socket.gethostname(),
        "operator": operator or getpass.getuser(),
        "generated_at": generated_at,
        "nist_800_88_level": nist_level,
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

    header_backup_line = "non demandee"
    if report.luks_detected and report.header_backup is not None:
        hb = report.header_backup
        header_backup_line = f"OK ({hb.backup_path})" if hb.backed_up else f"ECHEC ({hb.error})"

    html_path = out_dir / f"full-reset-certificate-{timestamp_slug}.html"
    html_path.write_text(
        FULL_WIPE_HTML_TEMPLATE.format(
            hostname=payload["hostname"],
            status_class="pass" if payload["overall_passed"] else "fail",
            status_label="REMISE A ZERO PROGRAMMEE" if payload["overall_passed"] else "ECHEC",
            operator=payload["operator"],
            device=report.device,
            luks_detected="oui" if report.luks_detected else "non",
            bitlocker_detected="oui" if report.bitlocker_detected else "non",
            nist_level=nist_level,
            header_backup_line=header_backup_line,
            luks_erased=luks_erased,
            device_wipe_line=_device_wipe_line(report.device_wipe),
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


def generate_live_wipe_certificate(
    report: LiveWipeReport,
    out_dir: Path,
    gpg_key_id: Optional[str] = None,
    operator: Optional[str] = None,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    timestamp_slug = time.strftime("%Y%m%d-%H%M%S")

    nist_level = _nist_level(report.luks_detected, report.bitlocker_detected)

    payload = {
        "tool": "clientwipe",
        "version": __version__,
        "operation": "live-wipe",
        "hostname": socket.gethostname(),
        "operator": operator or getpass.getuser(),
        "generated_at": generated_at,
        "nist_800_88_level": nist_level,
        "live_wipe": report.to_dict(),
        "overall_passed": report.passed,
    }

    sha256 = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    payload["sha256"] = sha256

    json_path = out_dir / f"live-wipe-certificate-{timestamp_slug}.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    luks_erased = "n/a (pas de LUKS)"
    if report.luks_detected:
        luks_erased = "oui" if (report.luks_erase and report.luks_erase.erased) else "ECHEC"

    header_backup_line = "non demandee"
    if report.luks_detected and report.header_backup is not None:
        hb = report.header_backup
        header_backup_line = f"OK ({hb.backup_path})" if hb.backed_up else f"ECHEC ({hb.error})"

    imaging_status = "OK" if (report.imaging.executed and report.imaging.returncode == 0) else "ECHEC"

    html_path = out_dir / f"live-wipe-certificate-{timestamp_slug}.html"
    html_path.write_text(
        LIVE_WIPE_HTML_TEMPLATE.format(
            hostname=payload["hostname"],
            status_class="pass" if payload["overall_passed"] else "fail",
            status_label="REMISE A ZERO REUSSIE" if payload["overall_passed"] else "ECHEC",
            operator=payload["operator"],
            device=report.device,
            image_name=report.image_name,
            luks_detected="oui" if report.luks_detected else "non",
            bitlocker_detected="oui" if report.bitlocker_detected else "non",
            nist_level=nist_level,
            header_backup_line=header_backup_line,
            luks_erased=luks_erased,
            device_wipe_line=_device_wipe_line(report.device_wipe),
            imaging_status=imaging_status,
            generated_at=generated_at,
            version=__version__,
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
