# ClientWipe

```
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
```

**Sanitisation automatisee et auditable de postes de pentest entre deux missions.**

## Le probleme

Entre deux missions d'audit/pentest, un consultant doit s'assurer qu'aucune
trace du client precedent (identifiants, projets Burp, configs VPN,
historique shell, documents recuperes) ne subsiste sur son poste avant la
mission suivante. En pratique, cette etape repose souvent sur la memoire et
la bonne volonte de chacun : pas de preuve, pas de tracabilite, et un vrai
risque de fuite de donnees entre clients (sujet directement couvert par
NIST SP 800-88 "Guidelines for Media Sanitization" et par l'esprit d'ISO
27001 sur la protection de l'information).

**ClientWipe** transforme cette etape manuelle en un geste simple et
verifiable : on branche une cle USB dediee et le poste repart integralement
a neuf, comme si un auditeur rallumait une machine jamais utilisee, tous
compartiments compris, pas seulement le profil utilisateur.

## Deux manieres de declencher ClientWipe

- **Cle autonome bootable** (`clientwipe live-wipe`, le modele vise pour la
  cle de production) : on redemarre le poste et on demarre directement sur
  la cle USB, comme une cle Clonezilla ou Kali live. Aucune installation
  prealable sur le poste cible n'est necessaire : la cle embarque tout
  (l'outil, l'image Kali de reference). C'est l'operateur qui choisit de
  booter sur cette cle precise qui constitue l'autorisation, donc pas de
  liste blanche de numero de serie ni de fenetre graphique a gerer, une
  simple confirmation tapee au clavier suffit.
- **Declenchement automatique pendant que le poste tourne** (`clientwipe
  trigger`, installe une fois via `install.sh`) : utile si on prefere que
  le nettoyage se declenche sans redemarrer manuellement sur une cle, des
  qu'une cle autorisee est branchee sur un poste deja equipe. Decrit en
  detail plus bas.

## Architecture

```mermaid
flowchart LR
    USB[Cle USB autorisee] -->|udev: ID_SERIAL_SHORT| Rule[regle udev 99-clientwipe]
    Rule -->|demarre| Service[systemd clientwipe-trigger@.service]
    Service --> Trigger[clientwipe trigger]
    Trigger -->|verifie le numero de serie| Allowlist[(allow-list)]
    Allowlist -->|refuse| Stop[Aucune action]
    Allowlist -->|autorise + confirmation| Mode{Mode}
    Mode -->|full-reset, par defaut| Luks[LUKS detecte ?]
    Luks -->|oui| Erase[Destruction de la cle LUKS<br/>effacement cryptographique instantane]
    Luks -->|non| Reboot
    Erase --> Reboot[Programme le prochain demarrage<br/>vers l'environnement de recuperation]
    Reboot --> Reimage[Reimagage complet<br/>Clonezilla/Rescuezilla, hors ligne]
    Mode -->|targeted, optionnel| Sanitize[Sanitisation ciblee<br/>shred multi-passes]
    Sanitize --> Verify[Verification post-effacement]
    Reboot --> Cert[Certificat d'audit<br/>JSON + HTML, SHA-256, GPG optionnel]
    Verify --> Cert
```

## Fonctionnalites

- **`clientwipe live-wipe` (cle autonome bootable)** : point d'entree pense
  pour tourner depuis un environnement demarre directement sur la cle USB
  (voir `clientwipe/live_wipe.py`). Reutilise exactement la meme logique de
  detection/destruction LUKS et de sauvegarde d'en-tete que le mode
  declenche automatiquement, mais reimage **immediatement** (pas besoin de
  programmer un redemarrage vers un environnement separe : l'environnement
  live demarre sur la cle *est* deja cet environnement de recuperation).
  Confirmation par simple saisie clavier (`OUI` en majuscules) en ligne de
  commande, ou via l'interface graphique cliquable decrite ci-dessous.
- **Interface graphique cliquable (`clientwipe live-wipe-gui`)** : version
  pointer-cliquer de `live-wipe`, pour qu'un operateur n'ait jamais besoin de
  taper une commande (voir `clientwipe/gui_live_wipe.py`). Trois ecrans
  plein ecran (Tkinter, deja fourni avec Python, aucune dependance
  supplementaire hormis le paquet systeme `python3-tk`) : selection du
  disque cible dans une liste (le disque de demarrage de la cle elle-meme
  est automatiquement exclu de la liste, impossible de se cibler soi-meme
  par erreur), confirmation explicite par bouton, puis resultat avec le
  chemin du certificat genere et un bouton pour eteindre la machine quand
  l'operateur a fini de le lire (`ocs-sr` n'eteint plus tout seul des la
  fin du reimagage : ca coupait la machine avant meme que cet ecran, ou
  l'ecriture du certificat juste avant, n'ait eu le temps de s'afficher).
  Le golden master n'a pas besoin d'etre
  indique a la main : l'outil scanne les partitions disponibles pour
  trouver celle qui le contient (`KaliState0-efi` par defaut).
  L'ecran de progression affiche les trois etapes separement (detection
  du chiffrement, effacement, reimagage), chacune avec son propre
  pourcentage quand il est mesurable : reel pour l'effacement logiciel
  de secours (lu depuis `/proc/<pid>/io` pendant que `shred` tourne), reel
  aussi pour le reimagage (sortie de Clonezilla/partclone capturee en
  direct via un pseudo-terminal, pour contourner leur bufferisation de
  stdout qui bloquerait sinon toute sortie "live" jusqu'a la fin), sinon
  un indicateur d'activite simple pour les operations quasi instantanees
  (destruction de cle LUKS, effacement natif NVMe). Si le motif de
  pourcentage attendu dans la sortie de Clonezilla ne correspond pas,
  cette etape degrade proprement vers l'indicateur d'activite plutot que
  d'afficher un chiffre fige ou faux.
  Le script `install_live_wipe_kiosk.sh` (a executer une seule fois, sur
  Cle A elle-meme) configure une **connexion automatique** (LightDM) et un
  **lancement automatique** de cette interface a l'ouverture de session,
  sans mot de passe sudo a saisir (autorisation `sudoers` limitee a
  exactement cette commande). Demarrer le poste cible sur Cle A au
  BIOS/UEFI reste le seul geste d'autorisation requis, comme pour la
  version ligne de commande.
- **Remise a zero complete (mode par defaut du declenchement USB)** : au
  branchement de la cle, l'outil detecte automatiquement si le disque est
  chiffre en LUKS. Si oui, il detruit les cles de chiffrement : un
  effacement cryptographique NIST SP 800-88 niveau "Purge", instantane et
  fiable sur SSD/NVMe, contrairement a un simple multi-passes logiciel qui
  ne garantit rien face au wear-leveling. Il programme ensuite le
  redemarrage vers un environnement de recuperation dedie qui reimage le
  disque entier depuis une image de reference (voir `clientwipe/full_wipe.py`,
  `clientwipe/luks.py`). Resultat : tous les compartiments du poste sont
  couverts, pas seulement le profil utilisateur. Deploiement vise : la cle
  USB elle-meme embarque l'image Kali de reference (64 Go+ recommande) pour
  que l'environnement de recuperation puisse reimager sans dependance
  reseau. Si le disque n'est pas chiffre, l'etape de destruction de cle est
  simplement ignoree et l'outil passe directement au reimagage ; le niveau
  de garantie atteint ("Purge" ou "Clear") est trace explicitement dans le
  certificat genere, jamais suppose equivalent.
- **Sauvegarde de l'en-tete LUKS avant destruction (optionnelle, recommandee)** :
  Timeshift ne protege pas contre une destruction de cle LUKS : son
  snapshot est stocke *dans* le volume chiffre, donc perdu avec le reste.
  Si `header_backup_dir` est configure (typiquement un point de montage de
  la cle USB declencheuse elle-meme), l'outil sauvegarde l'en-tete LUKS
  (`cryptsetup luksHeaderBackup`) juste avant de detruire les cles : un vrai
  retour en arriere possible (`cryptsetup luksHeaderRestore` + l'ancienne
  phrase secrete) en cas de declenchement par erreur. Si l'emplacement
  configure n'est pas un point de montage actif au moment du declenchement
  (cle non branchee/montee), l'outil refuse de detruire la cle plutot que
  d'ecrire la sauvegarde au mauvais endroit.
- **Detection BitLocker (postes Windows)** : le poste cible n'a pas besoin
  d'etre Linux. Si le disque n'est pas chiffre en LUKS, l'outil verifie s'il
  s'agit d'un volume BitLocker (`cryptsetup bitlkDump`, support natif depuis
  cryptsetup 2.3, sans avoir besoin d'outils Windows) et le signale
  explicitement dans le certificat. Volontairement **detection seule, pas
  destruction** : contrairement a LUKS, il n'existe pas d'equivalent a
  `cryptsetup erase` pour le format BitLocker, et ecraser "a la main" les
  bons octets sans machine Windows BitLocker reelle pour valider serait une
  fausse garantie de niveau "Purge". Un poste Windows chiffre BitLocker est
  donc traite au niveau "Clear" (reimagage complet), pas "Purge". Voir
  `clientwipe/bitlocker.py`.
- **Effacement de secours sur le disque entier (uniquement si pas de LUKS)** :
  quand aucun LUKS n'est detecte (disque non chiffre, ou BitLocker que cet
  outil ne sait que detecter), le mode remise a zero complete et le mode cle
  autonome effacent en plus l'integralite du peripherique. Sur une
  partition NVMe avec `nvme-cli` installe, ceci passe par le controleur
  lui-meme via la commande Format NVM : quelques secondes, pas des heures,
  et une vraie garantie de niveau "Purge" au sens NIST 800-88 (la commande
  agit sous le niveau logique vu par l'OS, donc couvre aussi les blocs
  reaffectes par le wear-leveling qu'un ecrasement logiciel ne peut pas
  toujours atteindre). Deux variantes sont tentees dans l'ordre : effacement
  cryptographique (`nvme format --ses=2`, le plus fort) puis, si le
  controleur le refuse (frequent sur des SSD grand public, meme recents :
  observe en conditions reelles), effacement des donnees utilisateur
  (`nvme format --ses=1`, plus largement supporte, toujours au niveau
  controleur). Si aucune des deux n'est possible (pas du NVMe, `nvme-cli`
  absent, ou le controleur refuse les deux), repli sur un ecrasement
  logiciel multi-passes avec des donnees aleatoires (`shred`, ou
  repli pur Python si absent), configurable via `fallback_wipe_passes`
  (defaut 1 passe, suffisant pour le niveau "Clear" selon NIST 800-88 ; les
  recommandations historiques a plusieurs passes type DoD 5220.22-M sont
  considerees obsoletes par ce standard). Le but du repli logiciel : renforcer
  le niveau "Clear" dans ce cas degrade, en detruisant aussi les metadonnees
  de chiffrement eventuelles, pas seulement les donnees visibles. Si LUKS est
  present, toute cette etape est ignoree : la destruction de cle reste la
  seule methode utilisee, instantanee, pas besoin d'ecraser des heures de
  donnees pour un resultat cryptographiquement deja irreversible. Trace dans
  le certificat genere (`clientwipe/disk_wipe.py`).
- **Sanitisation ciblee (mode alternatif, `--mode targeted`)** : effacement
  multi-passes (`shred` si disponible, sinon repli pur Python) des
  emplacements definis dans un fichier de configuration YAML (projets Burp,
  cles SSH, configs VPN, historique shell, profils navigateurs,
  telechargements/temp), sans redemarrage. Plus rapide que le reset complet,
  mais n'offre pas la meme garantie d'exhaustivite. Les patterns sont
  relatifs a `--root` par defaut, mais un pattern commencant par `/` est
  resolu depuis la racine du systeme de fichiers (`/opt/pentest-tools/**`,
  un point de montage de loot...), et une **verification independante**
  re-scanne les memes cibles apres effacement pour detecter tout residu.
- **Declenchement par cle USB** : une regle udev ne reagit qu'aux cles dont
  le numero de serie figure dans une allow-list ; le numero de serie est
  revalide cote Python (defense en profondeur). Pas d'autorun aveugle : une
  cle non enregistree ne declenche rien. Le service systemd tourne sans
  terminal, donc clientwipe affiche a la place une fenetre
  "Autoriser"/"Refuser" sur la session de bureau active (via `zenity`,
  voir `clientwipe/gui_confirm.py`) avant toute action destructive. Si la
  fenetre expire sans reponse, ou si aucune session graphique n'est
  disponible, l'operation est refusee par defaut : jamais d'effacement
  silencieux sans qu'un humain ait pu dire non. `clientwipe run` (usage
  manuel en ligne de commande) garde de son cote une confirmation dans le
  terminal.
- **Snapshot Timeshift automatique** : avant toute operation reelle, le
  declenchement par cle USB (`trigger`) prend par defaut un snapshot
  Timeshift du systeme (`--skip-snapshot` pour desactiver) ; la commande
  manuelle `run` peut faire de meme avec `--snapshot`. Le resultat
  (reussite/echec/non disponible) est trace dans le certificat genere, pour
  toujours savoir si un point de restauration existait avant l'operation.
  Si Timeshift n'est pas installe, l'outil continue sans bloquer
  l'operation : c'est un filet de securite, pas une dependance obligatoire.
- **Certificat d'audit** : rapport horodate (JSON + HTML) avec poste,
  operateur, methode, duree/peripherique, resultat de verification et
  empreinte SHA-256 ; signature GPG optionnelle si une cle est disponible.
- **Inventaire des outils installes (cle autonome uniquement, optionnel)** :
  apres un `clientwipe live-wipe` reussi, si `--inventory-output-dir` est
  fourni, l'outil monte en lecture seule la partition racine qui vient
  d'etre restauree et combine deux sources dans `tool-inventory.json` :
  - `dpkg_packages` : tous les paquets `apt`/`dpkg` installes avec leur
    version exacte (la base `/var/lib/dpkg/status`), qui couvre l'ecrasante
    majorite des outils sur un Kali standard ;
  - `git_clones` : les outils installes manuellement par `git clone` dans
    `/opt` (convention courante sur Kali pour ce qui n'est pas empaquete),
    detectes par la presence d'un dossier `.git`, avec pour chacun l'URL du
    remote, le hash du commit et le resultat de `git describe` (une version
    semantique n'existe pas pour un clone git, le commit en tient lieu).
  But : confirmer que l'image restauree correspond bien au baseline attendu
  (memes outils, memes versions), pas un audit de la mission precedente sur
  le poste client. Uniquement disponible pour `live-wipe` : en mode
  remise a zero complete (`full_reset`), la restauration reelle se produit
  apres le redemarrage programme, une fois que clientwipe s'est deja arrete,
  donc rien a inspecter dans le meme run (voir `clientwipe/inventory.py`).
  Purement informatif : un echec de cette etape n'affecte pas le resultat
  global de la sanitisation. Les outils installes par d'autres moyens
  (pip/pipx, go install, npm global, binaires manuels hors `/opt`) ne sont
  pas couverts pour l'instant.
- **Mode demo sans risque** : `clientwipe demo` cree un faux poste (fausses
  cles SSH, faux projet Burp, faux historique shell...) pour que le cycle de
  sanitisation ciblee soit testable en une commande, sans toucher a la
  moindre vraie donnee.

## Demarrage rapide (bac a sable de demo)

```bash
git clone <url-du-repo> clientwipe
cd clientwipe
pip install -e ".[dev]"

# Cree un faux poste de pentest avec des donnees factices
clientwipe demo --path demo/sandbox

# Sanitise, verifie, genere un certificat (uniquement sur le bac a sable)
clientwipe run --root demo/sandbox --config config/sanitize_targets.example.yaml

# Ouvrez le certificat genere dans certificates/certificate-*.html
```

Hors du bac a sable de demo, `clientwipe run` refuse de s'executer sans le
flag explicite `--yes` : c'est volontaire, pour qu'une execution accidentelle
sur de vraies donnees ne puisse pas passer inapercue.

## Test en conditions reelles (sur VM jetable)

Le declenchement par cle USB (udev/systemd) ne peut pas etre demontre par le
mode demo seul : il necessite un vrai noyau Linux avec un vrai gestionnaire
d'evenements udev. Pour le valider sans aucun risque :

1. **Creez une VM Linux jetable** (Kali ou Debian minimal) via
   VirtualBox/KVM/Proxmox, et prenez un snapshot juste apres l'installation
   de base. Deux options, a combiner si besoin :
   - un **snapshot hyperviseur** (VirtualBox/KVM/Proxmox) si disponible :
     le plus simple, il restaure l'etat complet de la VM en un clic ;
   - **Timeshift**, installe dans la VM elle-meme
     (`sudo apt install timeshift`), pour un snapshot au niveau du systeme
     de fichiers (rsync ou BTRFS), utile si l'hyperviseur ne permet pas de
     snapshot facile, ou pour multiplier les points de restauration sans
     repasser par la console de l'hyperviseur :
     ```bash
     sudo timeshift --create --comments "avant test clientwipe"
     # ... test ...
     sudo timeshift --restore
     ```
2. Copiez ce depot sur la VM, puis installez-le :
   ```bash
   sudo ./install.sh
   ```
   Ce script installe le paquet, cree `/etc/clientwipe/`, copie la regle
   udev et le service systemd, et initialise une allow-list vide. Le
   service installe tourne en mode `full-reset` par defaut (voir
   "Limitations connues" : sa derniere etape, le reimagage, necessite un
   environnement de recuperation que ce depot ne fournit pas). Pour tester
   le mode `targeted` deja valide de bout en bout, editez
   `/etc/systemd/system/clientwipe-trigger@.service` et ajoutez a la fin de
   la commande `ExecStart` : `--mode targeted --root /home/<votre-utilisateur>`,
   puis `sudo systemctl daemon-reload`.
3. **Peuplez un faux profil utilisateur realiste** sur la VM pour simuler un
   vrai poste de pentest (reutilise le meme generateur que le mode demo) :
   ```bash
   python3 demo/seed_sandbox.py /home/<votre-utilisateur>
   ```
4. **Enregistrez le numero de serie** de votre cle USB de test :
   ```bash
   udevadm info --query=property --name=/dev/sdX1 | grep ID_SERIAL_SHORT
   echo "<numero-de-serie>" | sudo tee -a /etc/clientwipe/allowed_usb_serials.txt
   ```
   Notez que ce snapshot (etape 1) sert a *vous*, le testeur, a rejouer le
   scenario plusieurs fois depuis un etat propre. Il est independant du
   snapshot Timeshift que l'outil prend *lui-meme* automatiquement avant
   chaque sanitisation declenchee par cle USB (voir "Fonctionnalites" ci-dessus).
   Les deux se completent : l'un protege vos essais, l'autre protege chaque
   execution reelle en production.
5. **Branchez la cle** et suivez le declenchement en direct :
   ```bash
   journalctl -u 'clientwipe-trigger@*' -f
   ```
   Vous devez voir le service demarrer, puis une fenetre
   "Autoriser"/"Refuser" apparaitre sur le bureau de la VM (sauf si `--yes`
   a ete ajoute au service). Un clic sur "Autoriser" declenche la
   sanitisation, la verification et la generation du certificat dans
   `/var/log/clientwipe/certificates/`.
6. **Revenez au snapshot** (hyperviseur ou `sudo timeshift --restore`) avant
   de rejouer le test, pour repartir d'un etat propre a chaque essai.

Ce parcours valide le mode `--mode targeted` de bout en bout (udev, systemd,
fenetre graphique, effacement, verification, certificat). Le mode
`full-reset` (par defaut) ajoute deux etapes supplementaires non demontrables
de la meme facon :
- la destruction de cle LUKS (`clientwipe/luks.py`) est testable en reel des
  que le disque de la VM est chiffre (installeur Kali : "Assiste - utiliser
  tout un disque avec LVM chiffre") ;
- le reimagage complet lui-meme necessite un environnement de recuperation
  prepare a l'avance (entree GRUB dediee lancant Clonezilla/Rescuezilla sans
  interaction), une infrastructure hors du perimetre de ce depot, couverte
  uniquement par des tests unitaires avec `subprocess`/`grub-reboot` simules.

## Construire ou mettre a jour la golden master (cle autonome)

Le mode cle autonome (`clientwipe live-wipe` / `live-wipe-gui`) restaure une
image Clonezilla ("golden master") preparee a l'avance. Procedure validee en
conditions reelles pour construire ou mettre a jour cette image :

1. **Installer Kali** sur un disque cible (VM jetable ou disque de rechange).
   Pour un chiffrement complet du disque, choisir "Assiste - utiliser tout un
   disque avec LVM chiffre" dans l'installeur.

2. **Ajouter une vraie partition EFI** si l'installation a ete faite en BIOS
   classique/MBR (cas frequent pour une VM creee sans UEFI/OVMF explicite) et
   que la machine cible reelle est en UEFI pur, sans support Legacy/CSM :

   ```
   # Convertir la table de partitions MBR en GPT (preserve les partitions
   # existantes), puis creer une nouvelle partition EFI dans l'espace libre
   sudo gdisk /dev/<disque>
   #   p  -> verifier les partitions existantes
   #   n  -> nouvelle partition, taille +300M, type ef00 (EFI system partition)
   #   w  -> ecrire les changements

   sudo mkfs.fat -F32 /dev/<nouvelle-partition-efi>

   # Monter et chrooter pour installer le chargeur de demarrage UEFI
   sudo mkdir -p /mnt/target
   sudo mount /dev/<partition-racine> /mnt/target   # cryptsetup luksOpen + vgchange -ay avant si LUKS/LVM
   sudo mount /dev/<partition-boot> /mnt/target/boot
   sudo mkdir -p /mnt/target/boot/efi
   sudo mount /dev/<nouvelle-partition-efi> /mnt/target/boot/efi
   sudo mount --bind /dev /mnt/target/dev
   sudo mount --bind /proc /mnt/target/proc
   sudo mount --bind /sys /mnt/target/sys
   sudo chroot /mnt/target

   # Dans le chroot :
   apt update && apt install -y grub-efi-amd64
   grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=Kali --removable
   update-grub
   echo "UUID=<uuid-partition-efi> /boot/efi vfat umask=0077 0 1" >> /etc/fstab   # voir blkid
   exit

   # Demonter proprement (ordre inverse), puis tester que le disque demarre
   # seul (sans Cle A) sur la machine reelle avant de continuer.
   ```

3. **Personnaliser** : ajouter les utilisateurs sudo et les outils voulus
   directement dans cette session (`adduser`, `usermod -aG sudo`,
   `apt install`), puisque c'est exactement cet etat qui sera capture.

4. **Capturer l'image avec Clonezilla**, depuis Cle A (pas depuis la machine
   qu'on vient de personnaliser) :

   ```
   sudo mkdir -p /mnt/images
   sudo mount /dev/<partition-depot-images> /mnt/images   # ex: sda4 sur Cle A
   sudo mkdir -p /home/partimag
   sudo mount --bind /mnt/images /home/partimag
   sudo ocs-sr savedisk <NomDeLImage> <disque>             # ex: KaliState0-efi nvme0n1
   ```

   Repondre aux questions interactives de Clonezilla au fur et a mesure. Le
   message final "Des partitions endommagees ont ete trouvees, ou bien
   certaines ne sont pas verifiables" est attendu si l'image contient une
   partition EFI FAT32 (sauvegardee via `partimage`, que l'outil de
   verification ne sait pas auditer) : ce n'est pas une vraie corruption tant
   que les autres partitions sont explicitement dites restaurables.

5. **Pointer l'outil vers la nouvelle image** : mettre a jour
   `DEFAULT_IMAGE_NAME` dans `clientwipe/gui_live_wipe.py` (et le texte
   d'aide correspondant dans `clientwipe/cli.py`), committer, pousser, et
   deployer sur Cle A (`git pull`).

6. **Valider de bout en bout** : lancer un `clientwipe live-wipe-gui` complet
   contre un disque de test, et confirmer qu'il redemarre seul (sans Cle A)
   une fois termine.

## Configuration

Un seul fichier YAML pilote les deux modes (`config/sanitize_targets.example.yaml`
fournit un point de depart) :

```yaml
# Mode full-reset (par defaut pour le declenchement USB)
full_reset:
  device: /dev/sda3
  boot_entry: "Clonezilla Recovery"
  header_backup_dir: /mnt/clientwipe-usb/luks-headers  # optionnel, voir Fonctionnalites
  fallback_wipe_passes: 1  # repli logiciel uniquement si pas de LUKS ni d'effacement NVMe possible, voir Fonctionnalites

# Mode targeted (--mode targeted, ou clientwipe run)
passes: 3
targets:
  - name: ssh-keys
    patterns:
      - ".ssh/id_*"
      - ".ssh/known_hosts"
```

`clientwipe live-wipe` (cle autonome bootable) ne lit pas ce fichier : il
prend ses parametres directement en ligne de commande, puisqu'il est lance
manuellement depuis la console de l'environnement live, pas par un service
installe a l'avance :

```bash
clientwipe live-wipe \
  --device /dev/sda \
  --image golden-kali \
  --images-repository /mnt/usb-data \
  --header-backup-dir /mnt/usb-data/luks-headers
```

## Conformite

L'approche s'inspire de NIST SP 800-88 "Guidelines for Media Sanitization"
et d'ISO/IEC 27001 sur la protection de l'information :
- le mode `full-reset` (par defaut) vise le niveau "Purge" de NIST 800-88 :
  effacement cryptographique instantane (destruction de cle LUKS) suivi d'un
  reimagage complet, la methode recommandee sur SSD/NVMe la ou un simple
  multi-passes logiciel n'offre pas de garantie face au wear-leveling ;
- le mode `targeted` couvre le niveau "Clear" (multi-passes d'ecrasement,
  verification independante du resultat) ;
- un poste Windows chiffre BitLocker (detection seule, voir
  `clientwipe/bitlocker.py`) reste au niveau "Clear" : le certificat le
  precise explicitement plutot que de laisser croire a un niveau "Purge"
  non verifie.

Chaque execution produit une preuve exploitable en audit interne ou externe
(exigences contractuelles client, traçabilite qualite) : qui, quand, quoi,
avec quel resultat.

## Pourquoi pas de sauvegarde complete avant effacement

Deux approches ont ete evaluees pour le mode `full-reset` :
- **copier integralement le disque avant d'effacer**, pour pouvoir tout
  restaurer en cas d'erreur. Mais sur un poste physique (pas une VM avec
  snapshot hyperviseur instantane), copier un disque entier est une
  operation d'E/S lente (potentiellement des heures selon la taille et la
  vitesse du support), et la copie elle-meme, contenant toutes les donnees
  client, devient un nouvel actif sensible a proteger ;
- **un effacement rapide et definitif une fois confirme**, c'est le choix
  retenu. La protection contre une erreur se fait *avant* l'effacement (le
  numero de serie USB doit correspondre a l'allow-list, puis un humain doit
  cliquer "Autoriser" sur une fenetre explicite), pas apres coup.

La seule exception : la sauvegarde de l'en-tete LUKS (voir ci-dessus), qui
est rapide (quelques Ko) et protege une fenetre courte, le temps ou la cle a
ete detruite par erreur mais le disque n'a pas encore ete reimage. Une fois le
reimagage lance, cette sauvegarde, comme tout le reste, ne permet plus de
revenir en arriere : c'est assume.

**A BIEN COMPRENDRE** : la sauvegarde d'en-tete LUKS ne contient QUE la cle
de chiffrement (quelques Ko), JAMAIS les donnees du client. ClientWipe NE
CONSERVE AUCUNE COPIE DES DONNEES DU POSTE, nulle part, a aucun moment.
Avant reimagage, les donnees restent lisibles UNIQUEMENT si l'en-tete est
restaure avec l'ancien mot de passe (le disque physique n'a pas encore ete
touche). Des que le reimagage a eu lieu, les donnees d'origine sont
definitivement et irremediablement perdues : il n'existe aucun moyen, aucune
sauvegarde, pour les recuperer a ce stade.

## Limitations connues

- Le reimagage complet (etape finale du mode `full-reset`) suppose un
  environnement de recuperation prepare a l'avance sur le poste (entree
  GRUB dediee lancant Clonezilla/Rescuezilla sans interaction) : cette
  infrastructure est hors du perimetre de ce depot et n'est donc pas
  executee reellement ici, seulement couverte par des tests unitaires avec
  `subprocess`/`grub-reboot` simules. Voir "Test en conditions reelles".
- La destruction de cle LUKS, elle, est reelle et testable des que le
  disque cible est chiffre.
- La signature GPG du certificat est optionnelle et desactivee si aucune cle
  n'est configuree ou si `gpg` n'est pas installe.
- Le declenchement udev/systemd est specifique a Linux ; voir la section
  "Test en conditions reelles" pour le valider sur une VM jetable.
- `clientwipe live-wipe` est valide de bout en bout en conditions reelles :
  Cle A (Kali **installe**, pas juste Live, avec ClientWipe + Clonezilla +
  golden master embarque) demarre de facon autonome sur du vrai materiel
  physique (teste en UEFI pur, sans support Legacy/CSM), efface un vrai
  disque NVMe cible et le reimage avec succes. Une coupure de courant en
  plein milieu d'un essai a confirme que le disque cible interrompu reste
  dans un etat recuperable (table de partitions simplement absente, pas de
  corruption bloquante) : relancer l'operation suffit, sans manipulation de
  reparation prealable.
- L'interface graphique (`clientwipe live-wipe-gui`) a ete validee de
  bout en bout en conditions reelles sur Cle A : autologin, lancement
  automatique, selection du disque, effacement NVMe natif, et reimagage
  reel confirme (table de partitions du disque cible correspondant
  exactement a celle du golden master apres l'operation). Trois bugs
  reels ont ete trouves et corriges au passage, tous masques les uns par
  les autres de facon trompeuse :
  - Le certificat genere en fin d'operation s'ecrivait par defaut dans
    `/mnt/clientwipe-gui-images/certificates`, sur la meme partition que
    le golden master, montee en lecture seule expres (voir
    `find_images_repository`). L'ecriture echouait donc systematiquement,
    tuant silencieusement le thread d'arriere-plan sans jamais remonter
    d'erreur a l'interface, qui restait bloquee sur "operation en cours"
    indefiniment, pile comme un vrai blocage de Clonezilla aurait semble
    se comporter. Corrige : le dossier de sortie par defaut est desormais
    `/var/log/clientwipe/certificates` (disque en lecture-ecriture de Cle
    A), et toute exception dans ce thread remonte maintenant
    systematiquement a l'interface comme un echec affiche, plus jamais
    comme un blocage silencieux.
  - `ocs-sr` (Clonezilla) ignore completement le `cwd` qu'on lui passe et
    exige toujours son depot d'images a l'emplacement fixe
    `/home/partimag`, sans quoi il refuse de demarrer. `imaging.py`
    monte desormais le depot reellement trouve a cet endroit (bind mount)
    juste avant de lancer `ocs-sr`.
  - Une premiere tentative de capturer la sortie de Clonezilla/partclone
    en direct (pour en extraire un pourcentage reel, via un
    pseudo-terminal) avait ete accusee a tort d'un blocage indefini et
    retiree : le vrai coupable etait `/home/partimag` manquant, present
    dans les deux versions testees a l'epoque. Reintroduite une fois les
    deux bugs ci-dessus corriges ; si le motif de pourcentage attendu ne
    correspond pas a la sortie reelle de Clonezilla, cette etape degrade
    proprement vers un simple indicateur d'activite plutot que d'afficher
    un chiffre fige ou faux.
- La detection BitLocker (`clientwipe/bitlocker.py`) est testee
  unitairement (`cryptsetup bitlkDump` simule) mais pas encore validee sur
  un vrai volume BitLocker reel, faute de poste Windows chiffre disponible
  pour le test.

## Licence

MIT. Voir [LICENSE](LICENSE).
