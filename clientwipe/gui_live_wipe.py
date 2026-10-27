from __future__ import annotations

import queue
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .certificate import generate_live_wipe_certificate
from .live_wipe import LiveWipeReport, live_wipe

DEFAULT_IMAGE_NAME = "KaliState0"
DEFAULT_MOUNT_POINT = Path("/mnt/clientwipe-gui-images")
DEFAULT_OUT_DIR = Path("/mnt/clientwipe-gui-images/certificates")
DEFAULT_FALLBACK_WIPE_PASSES = 3


@dataclass
class CandidateDevice:
    path: str
    size: str
    model: str


def boot_device() -> Optional[str]:
    """The whole disk ClientWipe itself is currently running from, so the
    device list can exclude it: an operator must never be able to select
    the live key as its own wipe target."""
    root_source = subprocess.run(
        ["findmnt", "-no", "SOURCE", "/"], capture_output=True, text=True, check=False,
    )
    partition = root_source.stdout.strip()
    if root_source.returncode != 0 or not partition:
        return None

    parent = subprocess.run(
        ["lsblk", "-no", "PKNAME", partition], capture_output=True, text=True, check=False,
    )
    pkname = parent.stdout.strip()
    return f"/dev/{pkname}" if pkname else None


def list_candidate_devices(exclude: Optional[str] = None) -> List[CandidateDevice]:
    """Whole disks available as a wipe target, excluding `exclude` (normally
    boot_device(), the disk the live key itself is running from)."""
    completed = subprocess.run(
        ["lsblk", "-ndo", "PATH,SIZE,MODEL,TYPE"], capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        return []

    devices: List[CandidateDevice] = []
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        path, size, *rest = parts
        type_ = rest[-1]
        model = " ".join(rest[:-1]) if len(rest) > 1 else "inconnu"
        if type_ != "disk":
            continue
        if exclude and path == exclude:
            continue
        devices.append(CandidateDevice(path=path, size=size, model=model))
    return devices


def find_images_repository(
    image_name: str,
    mount_point: Path,
    exclude_device: Optional[str] = None,
) -> Optional[Path]:
    """Locate the partition holding the golden image, by scanning every
    partition on the system (except `exclude_device`, the wipe target) for
    a top-level folder matching `image_name`.

    The live key's own disk layout isn't fixed in advance (partition
    numbering has shifted between builds in this very project), so this
    can't hardcode a device path. A partition already mounted elsewhere is
    checked in place; otherwise it's mounted read-only at `mount_point` just
    long enough to check, and left mounted there if it's the match (the
    caller, live_wipe(), needs to read from it next), or unmounted and
    tried again on the next candidate otherwise.
    """
    completed = subprocess.run(
        ["lsblk", "-ndo", "PATH,TYPE"], capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        return None

    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        path, type_ = parts
        if type_ != "part" or path == exclude_device:
            continue

        existing = subprocess.run(
            ["findmnt", "-no", "TARGET", path], capture_output=True, text=True, check=False,
        )
        existing_mount = existing.stdout.strip()
        if existing_mount:
            if (Path(existing_mount) / image_name).is_dir():
                return Path(existing_mount)
            continue

        mount_point.mkdir(parents=True, exist_ok=True)
        mounted = subprocess.run(
            ["mount", "-o", "ro", path, str(mount_point)], capture_output=True, text=True, check=False,
        )
        if mounted.returncode != 0:
            continue
        if (mount_point / image_name).is_dir():
            return mount_point
        subprocess.run(["umount", str(mount_point)], capture_output=True, text=True, check=False)

    return None


class LiveWipeGuiApp:
    """Point-and-click wizard around live_wipe(), for an operator who should
    never have to type a command: select the target disk, confirm, watch
    progress, read the result. Meant to autostart full-screen on Cle A (see
    install_live_wipe_kiosk.sh), with booting from this key in BIOS/UEFI
    already standing in for the operator's authorization, same as
    `clientwipe live-wipe` on the command line.

    Business logic stays in live_wipe()/generate_live_wipe_certificate():
    this class is a thin Tkinter shell around them, run in a background
    thread so the window stays responsive while the wipe is underway.
    """

    def __init__(
        self,
        image_name: str = DEFAULT_IMAGE_NAME,
        mount_point: Path = DEFAULT_MOUNT_POINT,
        out_dir: Path = DEFAULT_OUT_DIR,
        fallback_wipe_passes: int = DEFAULT_FALLBACK_WIPE_PASSES,
    ) -> None:
        import tkinter as tk

        self.image_name = image_name
        self.mount_point = mount_point
        self.out_dir = out_dir
        self.fallback_wipe_passes = fallback_wipe_passes
        self.selected_device: Optional[str] = None
        self.result_queue: "queue.Queue[tuple]" = queue.Queue()

        self.root = tk.Tk()
        self.root.title("ClientWipe")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg="#1a1a1a")

        self.container = tk.Frame(self.root, bg="#1a1a1a")
        self.container.pack(expand=True, fill="both")

        self._show_device_selection()

    def run(self) -> None:
        self.root.mainloop()

    def _clear(self) -> None:
        for widget in self.container.winfo_children():
            widget.destroy()

    def _label(self, text: str, size: int = 16, bold: bool = False) -> "tk.Label":
        import tkinter as tk

        font = ("Sans", size, "bold" if bold else "normal")
        return tk.Label(self.container, text=text, font=font, fg="white", bg="#1a1a1a", wraplength=900, justify="left")

    def _show_device_selection(self) -> None:
        import tkinter as tk

        self._clear()
        self._label("ClientWipe - Selection du disque a nettoyer", size=22, bold=True).pack(pady=20)

        excluded = boot_device()
        devices = list_candidate_devices(exclude=excluded)

        if not devices:
            self._label("Aucun disque cible detecte (hors cle de demarrage).").pack(pady=10)
            return

        listbox = tk.Listbox(self.container, font=("Monospace", 14), width=70, height=10)
        for device in devices:
            listbox.insert("end", f"{device.path}   {device.size}   {device.model}")
        listbox.pack(pady=10)
        listbox.selection_set(0)

        def on_next() -> None:
            index = listbox.curselection()
            if not index:
                return
            self.selected_device = devices[index[0]].path
            self._show_confirmation()

        tk.Button(self.container, text="Suivant", font=("Sans", 14), command=on_next).pack(pady=20)

    def _show_confirmation(self) -> None:
        import tkinter as tk

        self._clear()
        self._label("ATTENTION", size=22, bold=True).pack(pady=20)
        self._label(
            f"Ceci va effacer DEFINITIVEMENT {self.selected_device} et le "
            f"reimager avec l'image '{self.image_name}'.\n\nCette action est irreversible."
        ).pack(pady=10)

        buttons = tk.Frame(self.container, bg="#1a1a1a")
        buttons.pack(pady=30)
        tk.Button(buttons, text="Annuler", font=("Sans", 14), command=self._show_device_selection).pack(side="left", padx=20)
        tk.Button(buttons, text="Confirmer et effacer", font=("Sans", 14), command=self._start_wipe).pack(side="left", padx=20)

    def _start_wipe(self) -> None:
        self._clear()
        self._label("Operation en cours, ne pas eteindre la machine...", size=18, bold=True).pack(pady=40)
        self._label("Detection du chiffrement, effacement, reimagage...").pack(pady=10)

        thread = threading.Thread(target=self._run_wipe, daemon=True)
        thread.start()
        self.root.after(500, self._poll_result)

    def _run_wipe(self) -> None:
        images_repository = find_images_repository(self.image_name, self.mount_point, exclude_device=self.selected_device)
        if images_repository is None:
            self.result_queue.put(("error", "Image dorée introuvable sur les disques disponibles."))
            return

        report = live_wipe(
            self.selected_device,
            self.image_name,
            images_repository,
            fallback_wipe_passes=self.fallback_wipe_passes,
            dry_run=False,
        )
        certificate = generate_live_wipe_certificate(report, self.out_dir)
        self.result_queue.put(("done", report, certificate))

    def _poll_result(self) -> None:
        try:
            outcome = self.result_queue.get_nowait()
        except queue.Empty:
            self.root.after(500, self._poll_result)
            return

        if outcome[0] == "error":
            self._show_error(outcome[1])
        else:
            self._show_result(outcome[1], outcome[2])

    def _show_error(self, message: str) -> None:
        self._clear()
        self._label("ECHEC", size=22, bold=True).pack(pady=20)
        self._label(message).pack(pady=10)
        self._exit_button()

    def _show_result(self, report: LiveWipeReport, certificate: dict) -> None:
        self._clear()
        status = "REMISE A ZERO REUSSIE" if report.passed else "ECHEC"
        self._label(status, size=22, bold=True).pack(pady=20)
        self._label(f"Certificat : {certificate['json_path']}").pack(pady=10)
        self._exit_button()

    def _exit_button(self) -> None:
        import tkinter as tk

        tk.Button(self.container, text="Quitter", font=("Sans", 14), command=self.root.destroy).pack(pady=30)


def run_gui(
    image_name: str = DEFAULT_IMAGE_NAME,
    mount_point: Path = DEFAULT_MOUNT_POINT,
    out_dir: Path = DEFAULT_OUT_DIR,
    fallback_wipe_passes: int = DEFAULT_FALLBACK_WIPE_PASSES,
) -> None:
    app = LiveWipeGuiApp(
        image_name=image_name, mount_point=mount_point, out_dir=out_dir, fallback_wipe_passes=fallback_wipe_passes,
    )
    app.run()
