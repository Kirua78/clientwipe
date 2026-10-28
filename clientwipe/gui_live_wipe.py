from __future__ import annotations

import queue
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .certificate import generate_live_wipe_certificate
from .live_wipe import LiveWipeReport, live_wipe

DEFAULT_IMAGE_NAME = "KaliState0-efi"
DEFAULT_MOUNT_POINT = Path("/mnt/clientwipe-gui-images")
# Deliberately NOT under DEFAULT_MOUNT_POINT: that partition holds the
# golden master and is mounted read-only (see find_images_repository), so
# writing a certificate there always failed with OSError (read-only file
# system), silently killing the background thread and leaving the GUI
# stuck on "operation en cours" forever, with no result ever shown. Found
# on real hardware: every "stuck" run in testing was actually this crash,
# not a slow or hung wipe/reimage. /var/log is Cle A's own writable root
# filesystem, independent of both the golden master partition and the
# disk being wiped.
DEFAULT_OUT_DIR = Path("/var/log/clientwipe/certificates")
DEFAULT_FALLBACK_WIPE_PASSES = 1

STEPS = [
    ("detection", "1. Detection du chiffrement"),
    ("effacement", "2. Effacement"),
    ("reimagage", "3. Reimagage"),
]

COLOR_BG = "#000000"
COLOR_CARD = "#060a07"
COLOR_BORDER = "#00ff9f"
COLOR_TEXT = "#d9ffe6"
COLOR_SUBTEXT = "#4f9a6c"
COLOR_ACCENT = "#00ff9f"
COLOR_ACCENT_DARK = "#00cc7f"
COLOR_ACCENT_TEXT = "#001a10"
COLOR_DANGER = "#ff2b4e"
COLOR_DANGER_DARK = "#cc0033"
COLOR_SUCCESS = "#00ff9f"
COLOR_NEUTRAL = "#0e1510"
COLOR_NEUTRAL_DARK = "#050a06"
FONT_MONO = "Monospace"

DRAGON_ART = r"""
                 ___====-_  _-====___
           _--^^^#####//      \\#####^^^--_
        _-^##########// (    ) \\##########^-_
       -############//  |\^^/|  \\############-
     _/############//   (@::@)   \\############\_
    /#############((     \\//     ))#############\
   -###############\\    (oo)    //###############-
  -#################\\  / VV \  //#################-
 -###################\\/      \//###################-
_#/|##########/\######(   /\   )######/\##########|\#_
|/ |#/\#/\#/\/  \#/\##\  |  |  /##/\#/  \/\#/\#/\#| \|
`  |/  V  V  `   V  \#\| |  | |/#/  V   '  V  V  \|  '
   `   `  `      `   / | |  | | \   '      '  '   '
""".strip("\n")


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
    """Locate the partition holding the golden master, by scanning every
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
        ["lsblk", "-no", "PATH,TYPE"], capture_output=True, text=True, check=False,
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
        self.root.configure(bg=COLOR_BG)

        self._configure_style()

        self.container = tk.Frame(self.root, bg=COLOR_BG)
        self.container.pack(expand=True, fill="both")

        self._show_device_selection()

    def run(self) -> None:
        self.root.mainloop()

    def _configure_style(self) -> None:
        from tkinter import ttk

        style = ttk.Style(self.root)
        style.theme_use("clam")

        # A border alone (tried first) was still too subtle to spot at a
        # glance. Focus now fully inverts the button to a plain white
        # background with black text, on top of the white border, same as
        # a terminal's reverse-video cursor: unmistakable regardless of
        # which of these colors the button normally uses.
        style.configure(
            "Primary.TButton", background=COLOR_ACCENT, foreground=COLOR_ACCENT_TEXT,
            font=(FONT_MONO, 14, "bold"), borderwidth=3, bordercolor=COLOR_ACCENT, padding=(26, 12),
        )
        style.map(
            "Primary.TButton",
            background=[("focus", "#ffffff"), ("active", COLOR_ACCENT_DARK)],
            foreground=[("focus", "#000000")],
            bordercolor=[("focus", "#ffffff")],
        )

        style.configure(
            "Danger.TButton", background=COLOR_DANGER, foreground="black",
            font=(FONT_MONO, 14, "bold"), borderwidth=3, bordercolor=COLOR_DANGER, padding=(26, 12),
        )
        style.map(
            "Danger.TButton",
            background=[("focus", "#ffffff"), ("active", COLOR_DANGER_DARK)],
            foreground=[("focus", "#000000")],
            bordercolor=[("focus", "#ffffff")],
        )

        style.configure(
            "Secondary.TButton", background=COLOR_NEUTRAL, foreground=COLOR_ACCENT,
            font=(FONT_MONO, 14, "bold"), borderwidth=3, bordercolor=COLOR_NEUTRAL, padding=(26, 12),
        )
        style.map(
            "Secondary.TButton",
            background=[("focus", "#ffffff"), ("active", COLOR_NEUTRAL_DARK)],
            foreground=[("focus", "#000000")],
            bordercolor=[("focus", "#ffffff")],
        )

        style.configure(
            "Accent.Horizontal.TProgressbar", troughcolor=COLOR_CARD,
            background=COLOR_ACCENT, bordercolor=COLOR_CARD,
            lightcolor=COLOR_ACCENT, darkcolor=COLOR_ACCENT,
        )

        style.configure(
            "Devices.Treeview", background=COLOR_CARD, fieldbackground=COLOR_CARD,
            foreground=COLOR_TEXT, rowheight=36, font=(FONT_MONO, 12), borderwidth=0,
        )
        style.configure(
            "Devices.Treeview.Heading", background=COLOR_NEUTRAL_DARK, foreground=COLOR_ACCENT,
            font=(FONT_MONO, 11, "bold"), borderwidth=0,
        )
        style.map(
            "Devices.Treeview",
            background=[("selected", COLOR_ACCENT)],
            foreground=[("selected", COLOR_ACCENT_TEXT)],
        )

    def _clear(self) -> None:
        for widget in self.container.winfo_children():
            widget.destroy()

    def _header(self, title: str, subtitle: str = "") -> None:
        import tkinter as tk

        wrapper = tk.Frame(self.container, bg=COLOR_BG)
        wrapper.pack(fill="x", pady=(36, 30))

        tk.Frame(wrapper, bg=COLOR_ACCENT, height=2).pack(fill="x", padx=120)

        tk.Label(
            wrapper, text="root@clientwipe:~#", font=(FONT_MONO, 12),
            fg=COLOR_SUBTEXT, bg=COLOR_BG,
        ).pack(pady=(16, 0))
        tk.Label(
            wrapper, text=f"{title.upper()} █", font=(FONT_MONO, 26, "bold"),
            fg=COLOR_ACCENT, bg=COLOR_BG,
        ).pack(pady=(4, 0))
        if subtitle:
            tk.Label(
                wrapper, text=f"> {subtitle}", font=(FONT_MONO, 12),
                fg=COLOR_SUBTEXT, bg=COLOR_BG, wraplength=760, justify="center",
            ).pack(pady=(10, 0))

        tk.Frame(wrapper, bg=COLOR_ACCENT, height=2).pack(fill="x", padx=120, pady=(20, 0))

    def _bind_activate(self, widget, command) -> None:
        """Return/Space do not reliably invoke a focused ttk.Button in
        this environment: found in testing, Tab moving focus onto a
        button worked (after the explicit handling added for it) but
        pressing Return then did nothing at all, native ttk activation
        silently not firing. Every actionable button gets this bound
        explicitly instead of relying on ttk's default key bindings.
        """
        widget.bind("<Return>", lambda event: command())
        widget.bind("<space>", lambda event: command())

    def _card(self) -> "tk.Frame":
        import tkinter as tk

        border = tk.Frame(self.container, bg=COLOR_BORDER)
        border.pack(padx=40)
        inner = tk.Frame(border, bg=COLOR_CARD)
        inner.pack(padx=2, pady=2)
        return inner

    def _show_device_selection(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._clear()
        self._header(
            "Selection du disque",
            "Choisissez le disque a nettoyer. Le disque de demarrage de cette cle "
            "est automatiquement exclu de la liste.",
        )

        tk.Label(
            self.container, text=DRAGON_ART, font=(FONT_MONO, 8),
            fg=COLOR_ACCENT, bg=COLOR_BG, justify="left",
        ).pack(pady=(0, 20))

        excluded = boot_device()
        devices = list_candidate_devices(exclude=excluded)

        card = self._card()

        if not devices:
            tk.Label(
                card, text="Aucun disque cible detecte (hors cle de demarrage).",
                font=(FONT_MONO, 14), fg=COLOR_SUBTEXT, bg=COLOR_CARD,
            ).pack(padx=60, pady=60)
            self._exit_button()
            return

        columns = ("device", "size", "model")
        tree = ttk.Treeview(
            card, columns=columns, show="headings", style="Devices.Treeview",
            height=8, selectmode="browse",
        )
        tree.heading("device", text="PERIPHERIQUE")
        tree.heading("size", text="TAILLE")
        tree.heading("model", text="MODELE")
        tree.column("device", width=180, anchor="w")
        tree.column("size", width=110, anchor="center")
        tree.column("model", width=320, anchor="w")

        for device in devices:
            tree.insert("", "end", iid=device.path, values=(device.path, device.size, device.model))

        tree.pack(padx=30, pady=30)

        children = tree.get_children()
        if children:
            tree.selection_set(children[0])
            tree.focus(children[0])

        def on_next(event=None) -> None:
            selection = tree.selection()
            if not selection:
                return
            self.selected_device = selection[0]
            self._show_confirmation()

        actions = tk.Frame(self.container, bg=COLOR_BG)
        actions.pack(pady=30)
        quit_button = ttk.Button(
            actions, text="[ QUITTER ]", style="Secondary.TButton", command=self.root.destroy,
        )
        quit_button.pack(side="left", padx=10)
        self._bind_activate(quit_button, self.root.destroy)
        next_button = ttk.Button(actions, text="[ SUIVANT ]", style="Primary.TButton", command=on_next)
        next_button.pack(side="left", padx=10)
        self._bind_activate(next_button, on_next)

        # Fleches haut/bas deja gerees nativement par le Treeview en mode
        # "browse" ; Entree valide la selection sans avoir a tabuler
        # jusqu'au bouton, Echap quitte directement.
        tree.bind("<Return>", on_next)
        tree.focus_set()
        self.root.bind("<Escape>", lambda event: self.root.destroy())

    def _show_confirmation(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._clear()
        self._header("Confirmation", "Verifiez bien le disque cible avant de continuer.")

        card = self._card()
        tk.Label(card, text="[ ! ]", font=(FONT_MONO, 36, "bold"), fg=COLOR_DANGER, bg=COLOR_CARD).pack(pady=(40, 10))
        tk.Label(
            card,
            text=(
                f"Ceci va effacer DEFINITIVEMENT {self.selected_device}\n"
                f"et le reimager avec le golden master '{self.image_name}'."
            ),
            font=(FONT_MONO, 16, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD, justify="center", wraplength=620,
        ).pack(padx=50, pady=10)
        tk.Label(
            card, text="Cette action est irreversible.",
            font=(FONT_MONO, 13, "bold"), fg=COLOR_DANGER, bg=COLOR_CARD,
        ).pack(pady=(0, 40))

        buttons = tk.Frame(self.container, bg=COLOR_BG)
        buttons.pack(pady=30)
        cancel_button = ttk.Button(
            buttons, text="[ ANNULER ]", style="Secondary.TButton", command=self._show_device_selection,
        )
        cancel_button.pack(side="left", padx=10)
        self._bind_activate(cancel_button, self._show_device_selection)
        confirm_button = ttk.Button(
            buttons, text="[ CONFIRMER ET EFFACER ]", style="Danger.TButton", command=self._start_wipe,
        )
        confirm_button.pack(side="left", padx=10)
        self._bind_activate(confirm_button, self._start_wipe)

        # Focus par defaut sur Annuler, jamais sur l'action destructive :
        # Entree/Echap sans navigation explicite au clavier n'efface rien.
        # Tab/Shift-Tab geres explicitement plutot que de compter sur le
        # parcours de focus par defaut de Tkinter, qui s'est avere ne rien
        # faire du tout entre ces boutons au style personnalise.
        cancel_button.focus_set()
        self.root.bind("<Escape>", lambda event: self._show_device_selection())

        def focus_confirm(event=None):
            confirm_button.focus_set()
            return "break"

        def focus_cancel(event=None):
            cancel_button.focus_set()
            return "break"

        cancel_button.bind("<Tab>", focus_confirm)
        cancel_button.bind("<Shift-Tab>", focus_confirm)
        confirm_button.bind("<Tab>", focus_cancel)
        confirm_button.bind("<Shift-Tab>", focus_cancel)

    def _start_wipe(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._clear()
        self._header("Operation en cours", "Ne pas eteindre la machine ni debrancher le disque.")

        # Aucune sortie possible au clavier pendant l'operation : aucun
        # bouton Quitter n'est propose non plus sur cet ecran (voir
        # _exit_button), fermer la fenetre interromprait l'effacement ou
        # le reimagage en plein milieu.
        self.root.unbind("<Escape>")
        self.root.unbind("<Return>")

        card = self._card()
        self.step_rows = {}
        for step_key, step_label in STEPS:
            row = tk.Frame(card, bg=COLOR_CARD)
            row.pack(fill="x", padx=50, pady=16)

            header_row = tk.Frame(row, bg=COLOR_CARD)
            header_row.pack(fill="x")
            name_label = tk.Label(
                header_row, text=step_label, font=(FONT_MONO, 14, "bold"),
                fg=COLOR_SUBTEXT, bg=COLOR_CARD, anchor="w",
            )
            name_label.pack(side="left")
            percent_label = tk.Label(
                header_row, text="...", font=(FONT_MONO, 14), fg=COLOR_SUBTEXT, bg=COLOR_CARD,
            )
            percent_label.pack(side="right")

            progress = ttk.Progressbar(row, mode="determinate", length=560, style="Accent.Horizontal.TProgressbar")
            progress.pack(fill="x", pady=(8, 0))

            self.step_rows[step_key] = {"name": name_label, "percent": percent_label, "progress": progress, "mode": "idle"}

        thread = threading.Thread(target=self._run_wipe, daemon=True)
        thread.start()
        self.root.after(200, self._poll_queue)

    def _run_wipe(self) -> None:
        # This runs in a background thread: an exception here that escapes
        # uncaught does NOT reach the Tkinter main thread at all, it just
        # prints a traceback nobody sees (buried in .xsession-errors) and
        # kills this thread silently, leaving the GUI stuck on "operation
        # en cours" forever with no result ever shown. Found on real
        # hardware this way: an OSError writing the certificate (see
        # DEFAULT_OUT_DIR) looked identical to live_wipe() itself hanging,
        # costing a lot of time to tell apart. This try/except guarantees
        # the operator always sees *something* (an error screen, even for
        # a bug), never an indefinite silent hang again.
        try:
            images_repository = find_images_repository(
                self.image_name, self.mount_point, exclude_device=self.selected_device,
            )
            if images_repository is None:
                self.result_queue.put(("error", "Golden master introuvable sur les disques disponibles."))
                return

            def on_progress(step: str, fraction: Optional[float], detail: str) -> None:
                self.result_queue.put(("progress", step, fraction, detail))

            report = live_wipe(
                self.selected_device,
                self.image_name,
                images_repository,
                fallback_wipe_passes=self.fallback_wipe_passes,
                dry_run=False,
                progress_callback=on_progress,
            )
            certificate = generate_live_wipe_certificate(report, self.out_dir)
            self.result_queue.put(("done", report, certificate))
        except Exception as exc:  # noqa: BLE001 - last resort, see comment above
            self.result_queue.put(("error", f"Erreur inattendue : {exc}"))

    def _update_step(self, step: str, fraction: Optional[float]) -> None:
        widgets = self.step_rows.get(step)
        if widgets is None:
            return

        widgets["name"].configure(fg=COLOR_SUCCESS if fraction == 1.0 else COLOR_ACCENT)

        if fraction is None:
            if widgets["mode"] != "indeterminate":
                widgets["progress"].configure(mode="indeterminate")
                widgets["progress"].start(15)
                widgets["mode"] = "indeterminate"
            widgets["percent"].configure(text="...")
        else:
            if widgets["mode"] == "indeterminate":
                widgets["progress"].stop()
            widgets["progress"].configure(mode="determinate")
            widgets["progress"]["value"] = fraction * 100
            widgets["mode"] = "determinate"
            widgets["percent"].configure(text=f"{round(fraction * 100)}%")

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.result_queue.get_nowait()
                if item[0] == "progress":
                    self._update_step(item[1], item[2])
                else:
                    self._finish(item)
                    return
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _finish(self, item: tuple) -> None:
        if item[0] == "error":
            self._show_error(item[1])
        else:
            self._show_result(item[1], item[2])

    def _show_error(self, message: str) -> None:
        import tkinter as tk

        self._clear()
        self._header("Echec")

        card = self._card()
        tk.Label(card, text="[ FAIL ]", font=(FONT_MONO, 32, "bold"), fg=COLOR_DANGER, bg=COLOR_CARD).pack(pady=(40, 10))
        tk.Label(
            card, text=message, font=(FONT_MONO, 14), fg=COLOR_TEXT, bg=COLOR_CARD,
            wraplength=620, justify="center",
        ).pack(padx=50, pady=(0, 40))

        self._exit_button()

    def _show_result(self, report: LiveWipeReport, certificate: dict) -> None:
        import tkinter as tk

        self._clear()
        success = report.passed
        self._header("Remise a zero reussie" if success else "Echec")

        card = self._card()
        icon = "[ OK ]" if success else "[ FAIL ]"
        color = COLOR_SUCCESS if success else COLOR_DANGER
        tk.Label(card, text=icon, font=(FONT_MONO, 32, "bold"), fg=color, bg=COLOR_CARD).pack(pady=(40, 10))
        tk.Label(
            card, text=f"Certificat : {certificate['json_path']}",
            font=(FONT_MONO, 13), fg=COLOR_SUBTEXT, bg=COLOR_CARD, wraplength=620, justify="center",
        ).pack(padx=50, pady=(0, 40))

        self._exit_button()

    def _exit_button(self) -> None:
        from tkinter import ttk

        self.exit_button = ttk.Button(
            self.container, text="[ QUITTER ]", style="Secondary.TButton", command=self.root.destroy,
        )
        self.exit_button.pack(pady=30)
        self.exit_button.focus_set()
        self.root.bind("<Return>", lambda event: self.root.destroy())
        self.root.bind("<Escape>", lambda event: self.root.destroy())


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
