#!/usr/bin/env bash
# Configure Cle A (la cle autonome bootable) pour demarrer directement sur
# l'interface graphique de live-wipe, sans mot de passe ni ligne de
# commande a taper : autologin LightDM + lancement automatique de
# `clientwipe live-wipe-gui` des l'ouverture de session.
#
# A executer UNE SEULE FOIS, sur Cle A elle-meme (pas sur un poste cible),
# apres avoir installe Kali + ClientWipe + Clonezilla dessus. Voir
# README.md > "Interface graphique".
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Ce script doit etre execute en root (sudo ./install_live_wipe_kiosk.sh <utilisateur>)." >&2
  exit 1
fi

TARGET_USER="${1:-}"
if [[ -z "$TARGET_USER" ]]; then
  echo "Usage: sudo ./install_live_wipe_kiosk.sh <utilisateur>" >&2
  echo "  <utilisateur> : le compte Linux de Cle A qui doit s'ouvrir automatiquement" >&2
  exit 1
fi

if ! id "$TARGET_USER" >/dev/null 2>&1; then
  echo "Utilisateur '$TARGET_USER' introuvable sur ce systeme." >&2
  exit 1
fi

CLIENTWIPE_BIN="$(command -v clientwipe || true)"
if [[ -z "$CLIENTWIPE_BIN" ]]; then
  echo "clientwipe introuvable dans le PATH : installez-le d'abord (voir README.md)." >&2
  exit 1
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
  echo "==> python3-tk n'est pas installe (necessaire pour l'interface graphique)."
  apt-get install -y python3-tk
fi

echo "==> Autorisation sans mot de passe pour le lancement de l'interface (uniquement cette commande)"
cat > /etc/sudoers.d/clientwipe-live-wipe-gui <<EOF
$TARGET_USER ALL=(root) NOPASSWD: $CLIENTWIPE_BIN live-wipe-gui
EOF
chmod 440 /etc/sudoers.d/clientwipe-live-wipe-gui
visudo -c -f /etc/sudoers.d/clientwipe-live-wipe-gui

echo "==> Connexion automatique au demarrage (LightDM)"
mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/50-clientwipe-autologin.conf <<EOF
[Seat:*]
autologin-user=$TARGET_USER
autologin-user-timeout=0
EOF

echo "==> Lancement automatique de l'interface a l'ouverture de session"
USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
AUTOSTART_DIR="$USER_HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/clientwipe-live-wipe-gui.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ClientWipe
Exec=sudo $CLIENTWIPE_BIN live-wipe-gui
X-GNOME-Autostart-enable=true
EOF
chown -R "$TARGET_USER":"$TARGET_USER" "$AUTOSTART_DIR"

cat <<EOF

Installation terminee.

Au prochain demarrage sur Cle A : connexion automatique en tant que
'$TARGET_USER', puis ouverture automatique de l'interface ClientWipe.
Demarrer sur cette cle (choix fait au BIOS/UEFI) vaut autorisation de
l'operateur, comme pour 'clientwipe live-wipe' en ligne de commande.
EOF
