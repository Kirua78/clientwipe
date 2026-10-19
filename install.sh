#!/usr/bin/env bash
# Installe ClientWipe en mode "declenchement USB reel" sur une machine
# Linux de test. Utilisez une VM jetable (avec snapshot) pour vos premiers
# essais, PAS un poste de production avant d'avoir valide le comportement
# complet. Voir README.md > "Test en conditions reelles".
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Ce script doit etre execute en root (sudo ./install.sh)." >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installation du paquet clientwipe"
pip install "$REPO_DIR"

echo "==> Creation des repertoires de configuration"
install -d -m 755 /etc/clientwipe
install -d -m 700 /var/log/clientwipe/certificates

if [[ ! -f /etc/clientwipe/allowed_usb_serials.txt ]]; then
  echo "# Un numero de serie autorise par ligne (ID_SERIAL_SHORT de la cle USB)" \
    > /etc/clientwipe/allowed_usb_serials.txt
  echo "==> Allow-list creee (vide) : /etc/clientwipe/allowed_usb_serials.txt"
  echo "    Trouvez le numero de serie de votre cle de test avec :"
  echo "    udevadm info --query=property --name=/dev/sdX1 | grep ID_SERIAL_SHORT"
fi

if [[ ! -f /etc/clientwipe/sanitize_targets.yaml ]]; then
  cp "$REPO_DIR/config/sanitize_targets.example.yaml" /etc/clientwipe/sanitize_targets.yaml
  echo "==> Configuration copiee : /etc/clientwipe/sanitize_targets.yaml"
fi

echo "==> Installation de la regle udev et du service systemd"
cp "$REPO_DIR/udev/99-clientwipe.rules" /etc/udev/rules.d/99-clientwipe.rules
cp "$REPO_DIR/systemd/clientwipe-trigger@.service" /etc/systemd/system/clientwipe-trigger@.service

udevadm control --reload-rules
systemctl daemon-reload

if ! command -v timeshift >/dev/null 2>&1; then
  echo "==> Timeshift n'est pas installe : le snapshot automatique avant"
  echo "    sanitisation (trigger) sera ignore sans bloquer l'outil."
  echo "    Pour l'activer : sudo apt install timeshift (puis configurez-le"
  echo "    une premiere fois avec 'sudo timeshift --setup' avant le test)."
fi

cat <<'EOF'

Installation terminee.

Prochaines etapes (voir README.md > "Test en conditions reelles") :
  1. Ajoutez le numero de serie de votre cle USB de test dans
     /etc/clientwipe/allowed_usb_serials.txt
  2. Adaptez /etc/clientwipe/sanitize_targets.yaml et le --root du service
     systemd a votre environnement de test.
  3. Branchez la cle USB autorisee et suivez les logs avec :
     journalctl -u 'clientwipe-trigger@*' -f
EOF
