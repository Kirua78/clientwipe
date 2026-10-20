from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .certificate import generate_certificate, generate_full_wipe_certificate
from .config import Config
from .full_wipe import full_wipe
from .imaging import reboot_now, restore_golden_image
from .sanitize import sanitize
from .snapshot import create_snapshot
from .usb_trigger import is_allowed
from .verify import verify

SANDBOX_DIR_NAME = "sandbox"


def _is_safe_root(root: Path) -> bool:
    """Only the demo sandbox is allowed to run without an explicit --yes:
    anything else is presumed to be real data and requires confirmation."""
    resolved = root.resolve()
    return resolved.name == SANDBOX_DIR_NAME and "demo" in resolved.parts


def _run_pipeline(
    root: Path,
    config: Config,
    out_dir: Path,
    gpg_key_id: Optional[str],
    operator: Optional[str],
    take_snapshot: bool = False,
) -> dict:
    snapshot_result = None
    if take_snapshot:
        snapshot_result = dataclasses.asdict(create_snapshot(f"clientwipe: avant sanitisation de {root}"))

    sanitize_report = sanitize(root, config)
    verify_report = verify(root, config)
    certificate = generate_certificate(
        sanitize_report, verify_report, out_dir,
        gpg_key_id=gpg_key_id, operator=operator, snapshot=snapshot_result,
    )
    return {
        "sanitize": sanitize_report.to_dict(),
        "verify": verify_report.to_dict(),
        "certificate": certificate,
        "snapshot": snapshot_result,
    }


def _print_snapshot_status(snapshot_result: Optional[dict]) -> None:
    if snapshot_result is None:
        return
    if snapshot_result["created"]:
        print("Snapshot Timeshift: OK")
    elif snapshot_result["attempted"]:
        print(f"Snapshot Timeshift: ECHEC ({snapshot_result['error']})")
    else:
        print(f"Snapshot Timeshift: non disponible ({snapshot_result['error']})")


def cmd_demo(args: argparse.Namespace) -> int:
    from .demo_sandbox import create_sandbox

    sandbox_path = create_sandbox(Path(args.path))
    print(f"Bac a sable de demo cree dans {sandbox_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if not _is_safe_root(root) and not args.yes:
        print(
            "ATTENTION: cette racine n'est pas le bac a sable de demo.\n"
            "Cette commande efface DEFINITIVEMENT les fichiers cibles par la configuration.\n"
            "Relancez avec --yes si c'est intentionnel.",
            file=sys.stderr,
        )
        return 2

    config = Config.load(Path(args.config))
    result = _run_pipeline(root, config, Path(args.out_dir), args.gpg_key, args.operator, take_snapshot=args.snapshot)
    _print_snapshot_status(result["snapshot"])
    print(f"Fichiers effaces: {result['sanitize']['total_files_wiped']}")
    print(f"Verification: {'OK' if result['verify']['passed'] else 'ECHEC'}")
    print(f"Certificat: {result['certificate']['json_path']}")
    return 0 if result["verify"]["passed"] else 1


def cmd_verify(args: argparse.Namespace) -> int:
    config = Config.load(Path(args.config))
    report = verify(Path(args.root), config)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0 if report.passed else 1


def _confirm_destructive_action(message: str) -> Optional[bool]:
    """Ask for confirmation before a real destructive action: a terminal
    prompt when one is available, otherwise an "Autoriser"/"Refuser" dialog
    on the active desktop session (the USB-triggered systemd path has no
    TTY). Returns None when there is no terminal AND no graphical session
    to ask in at all. The caller treats that as a refusal to flag for
    review, never as an implicit yes.
    """
    try:
        answer = input(f"{message} [y/N] ")
        return answer.strip().lower() == "y"
    except EOFError:
        from .gui_confirm import ask_confirmation_gui
        return ask_confirmation_gui(message)


def _require_confirmation(message: str, yes: bool) -> Optional[int]:
    """Returns an exit code to return immediately if the action must NOT
    proceed (declined, or nobody could be asked), or None when confirmed
    and the caller should continue."""
    if yes:
        return None
    confirmed = _confirm_destructive_action(message)
    if confirmed is None:
        print(
            "Pas de terminal interactif et aucune confirmation graphique "
            "disponible (zenity ou session de bureau introuvable) : "
            "operation annulee.",
            file=sys.stderr,
        )
        return 1
    if not confirmed:
        print("Annule par l'operateur.")
        return 0
    return None


def _cmd_trigger_full_reset(args: argparse.Namespace, config: Config) -> int:
    if config.full_reset is None:
        print(
            "Mode full-reset demande mais la configuration ne contient pas "
            "de section 'full_reset' (device, boot_entry).",
            file=sys.stderr,
        )
        return 1

    message = (
        f"Cle USB autorisee detectee. Lancer la remise a zero complete de "
        f"{config.full_reset.device} ? Le poste va redemarrer et repartir "
        f"d'une image propre."
    )
    exit_code = _require_confirmation(message, args.yes)
    if exit_code is not None:
        return exit_code

    snapshot_result = None
    if not args.skip_snapshot:
        snapshot_result = dataclasses.asdict(create_snapshot("clientwipe: avant remise a zero complete"))
        _print_snapshot_status(snapshot_result)

    report = full_wipe(config.full_reset.device, config.full_reset.boot_entry, dry_run=False)
    certificate = generate_full_wipe_certificate(
        report, Path(args.out_dir), args.gpg_key, args.operator, snapshot=snapshot_result,
    )

    print(f"LUKS detecte: {'oui' if report.luks_detected else 'non'}")
    if report.luks_detected:
        erased = bool(report.luks_erase and report.luks_erase.erased)
        print(f"Cle LUKS detruite: {'OK' if erased else 'ECHEC'}")
    print(f"Reimagage programme au prochain demarrage: {'OK' if report.reboot_scheduled.scheduled else 'ECHEC'}")
    print(f"Certificat: {certificate['json_path']}")

    if report.passed and not args.no_auto_reboot:
        print("Redemarrage du poste...")
        reboot_now(dry_run=False)

    return 0 if report.passed else 1


def _cmd_trigger_targeted(args: argparse.Namespace, config: Config) -> int:
    message = f"Cle USB autorisee detectee. Lancer la sanitisation de {args.root} ?"
    exit_code = _require_confirmation(message, args.yes)
    if exit_code is not None:
        return exit_code

    result = _run_pipeline(
        Path(args.root), config, Path(args.out_dir), args.gpg_key, args.operator,
        take_snapshot=not args.skip_snapshot,
    )
    _print_snapshot_status(result["snapshot"])
    print(f"Certificat: {result['certificate']['json_path']}")
    return 0 if result["verify"]["passed"] else 1


def cmd_trigger(args: argparse.Namespace) -> int:
    allowlist_path = Path(args.allowlist)
    if not is_allowed(args.serial, allowlist_path):
        print(f"Cle USB non reconnue (serial={args.serial!r}), aucune action.", file=sys.stderr)
        return 1

    config = Config.load(Path(args.config))

    if args.mode == "full-reset":
        return _cmd_trigger_full_reset(args, config)
    return _cmd_trigger_targeted(args, config)


def cmd_reset(args: argparse.Namespace) -> int:
    result = restore_golden_image(
        args.image, args.device, Path(args.images_repository), dry_run=not args.confirm_reset
    )
    print("Commande:", " ".join(result.command))
    if not result.executed:
        print("Mode simulation (--confirm-reset non fourni) : aucune action effectuee.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clientwipe",
        description="Sanitisation automatisee et auditable de postes de pentest entre deux missions",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_demo = subparsers.add_parser("demo", help="Creer un bac a sable de demonstration (donnees factices)")
    p_demo.add_argument("--path", default="demo/sandbox")
    p_demo.set_defaults(func=cmd_demo)

    p_run = subparsers.add_parser("run", help="Sanitise, verifie et genere un certificat")
    p_run.add_argument("--root", required=True, help="Racine a sanitiser")
    p_run.add_argument("--config", required=True, help="Fichier sanitize_targets.yaml")
    p_run.add_argument("--out-dir", default="certificates")
    p_run.add_argument("--gpg-key", default=None, help="Key id GPG pour signer le certificat (optionnel)")
    p_run.add_argument("--operator", default=None)
    p_run.add_argument("--yes", action="store_true", help="Confirme une sanitisation hors bac a sable")
    p_run.add_argument(
        "--snapshot", action="store_true",
        help="Prend un snapshot Timeshift du systeme avant la sanitisation (necessite timeshift installe)",
    )
    p_run.set_defaults(func=cmd_run)

    p_verify = subparsers.add_parser("verify", help="Verifie l'absence de residus sans rien effacer")
    p_verify.add_argument("--root", required=True)
    p_verify.add_argument("--config", required=True)
    p_verify.set_defaults(func=cmd_verify)

    p_trigger = subparsers.add_parser("trigger", help="Point d'entree udev/systemd declenche par cle USB")
    p_trigger.add_argument("--serial", default=None, help="Numero de serie USB (sinon lu depuis $ID_SERIAL_SHORT)")
    p_trigger.add_argument("--allowlist", default="/etc/clientwipe/allowed_usb_serials.txt")
    p_trigger.add_argument(
        "--mode", choices=["full-reset", "targeted"], default="full-reset",
        help="full-reset (par defaut) detruit la cle LUKS si presente et programme un reimagage complet ; "
             "targeted efface seulement les emplacements listes dans la configuration",
    )
    p_trigger.add_argument("--root", default="/home/pentest", help="Utilise seulement en mode targeted")
    p_trigger.add_argument("--config", default="/etc/clientwipe/sanitize_targets.yaml")
    p_trigger.add_argument("--out-dir", default="/var/log/clientwipe/certificates")
    p_trigger.add_argument("--gpg-key", default=None)
    p_trigger.add_argument("--operator", default=None)
    p_trigger.add_argument("--yes", action="store_true", help="Ignore la confirmation interactive (usage non surveille)")
    p_trigger.add_argument(
        "--skip-snapshot", action="store_true",
        help="Desactive le snapshot Timeshift automatique (pris par defaut avant chaque operation declenchee par cle USB)",
    )
    p_trigger.add_argument(
        "--no-auto-reboot", action="store_true",
        help="En mode full-reset, n'eteint/ne redemarre pas automatiquement apres la destruction de cle (laisse l'operateur rebooter)",
    )
    p_trigger.set_defaults(func=cmd_trigger)

    p_reset = subparsers.add_parser("reset", help="Restaure une image golden via Clonezilla (mode avance, optionnel)")
    p_reset.add_argument("--image", required=True)
    p_reset.add_argument("--device", required=True)
    p_reset.add_argument("--images-repository", default="/home/partimag")
    p_reset.add_argument("--confirm-reset", action="store_true", help="Execute reellement la restauration (sinon: simulation)")
    p_reset.set_defaults(func=cmd_reset)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "trigger" and args.serial is None:
        args.serial = os.environ.get("ID_SERIAL_SHORT")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
