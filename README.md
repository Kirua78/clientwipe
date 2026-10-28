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

Entre deux missions, un consultant doit garantir qu'aucune trace du client
precedent (identifiants, projets Burp, configs VPN, documents) ne subsiste
sur son poste. En pratique, cette etape repose souvent sur la memoire et la
bonne volonte de chacun : pas de preuve, pas de tracabilite. C'est un vrai
risque de fuite de donnees entre clients, couvert par NIST SP 800-88
("Guidelines for Media Sanitization") et l'esprit d'ISO 27001.

**ClientWipe** transforme cette etape en un geste simple : on branche une
cle USB dediee, le poste repart integralement a neuf, et un certificat
d'audit (JSON + HTML, horodate, signable GPG) prouve ce qui a ete fait.

## Comment ca marche

Deux facons de declencher ClientWipe :

- **Cle autonome bootable** (`clientwipe live-wipe`) : on redemarre le
  poste directement sur la cle, comme une cle Clonezilla. Elle embarque
  tout (l'outil + une image Kali de reference) : aucune installation
  prealable sur le poste cible. Une interface graphique cliquable
  (`clientwipe live-wipe-gui`) evite meme d'avoir a taper une commande :
  on choisit le disque, on confirme, c'est fini.
- **Declenchement automatique** (`clientwipe trigger`) : installe une fois
  sur un poste deja equipe, il se lance tout seul des qu'une cle USB
  autorisee (liste blanche par numero de serie) est branchee.

Dans les deux cas, le poste est traite au niveau **Purge** de NIST 800-88
quand c'est possible (destruction de cle de chiffrement, instantanee et
irreversible) ou **Clear** sinon (effacement multi-passes), jamais l'un a
la place de l'autre sans que ce soit indique dans le certificat.

## Demarrage rapide (bac a sable de demo)

```bash
git clone <url-du-repo> clientwipe
cd clientwipe
pip install -e ".[dev]"

clientwipe demo --path demo/sandbox
clientwipe run --root demo/sandbox --config config/sanitize_targets.example.yaml

# Ouvrez le certificat genere dans certificates/certificate-*.html
```

Hors du bac a sable de demo, `clientwipe run` refuse de s'executer sans le
flag `--yes`, pour qu'une execution accidentelle sur de vraies donnees ne
passe jamais inapercue.

## Fonctionnalites principales

- Detection et destruction de cle LUKS (effacement cryptographique
  instantane, le plus fiable sur SSD/NVMe).
- Effacement natif du controleur NVMe quand LUKS n'est pas disponible,
  sinon repli logiciel multi-passes.
- Detection BitLocker sur poste Windows (signalee, pas detruite : pas
  d'equivalent fiable a une destruction de cle pour ce format).
- Sauvegarde optionnelle de l'en-tete LUKS avant destruction, pour un vrai
  retour en arriere en cas de declenchement par erreur.
- Certificat d'audit horodate (JSON + HTML), signature GPG optionnelle.
- Mode demo sans risque (`clientwipe demo`) pour tester sans toucher a la
  moindre vraie donnee.

## Utilisation (cle autonome)

1. Branchez la cle sur le poste a nettoyer.
2. Au demarrage, ouvrez le menu de boot (F11 ou equivalent) et choisissez
   de demarrer sur la cle.
3. L'interface s'ouvre automatiquement. Selectionnez le disque a effacer
   dans la liste (le disque de demarrage de la cle elle-meme n'apparait
   jamais, impossible de se tromper de cible).
4. Confirmez. Une phrase de passe peut etre demandee si l'image de
   reference est chiffree, sinon laissez le champ vide et continuez.
5. Laissez l'operation se derouler sans toucher a la machine (effacement
   puis reimagage, de quelques minutes a plusieurs heures selon le
   disque).
6. Une fois termine, un ecran affiche le resultat et le chemin du
   certificat genere. Cliquez sur Eteindre.
7. Debranchez la cle. Le poste redemarre directement sur une installation
   propre, pret pour la mission suivante.

## Licence

MIT. Voir [LICENSE](LICENSE).
