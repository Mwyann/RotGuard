# Cahier des Charges & Spécifications Techniques — Projet RotGuard

> **Projet** : Application Windows GUI d'audit, de suivi et de vérification d'intégrité de fichiers (Lutte contre le *bit rot* et la corruption silencieuse).  
> **Dossier de travail** : `RotGuard`  
> **Statut** : Version enrichie (Design moderne par barre d'onglets, Mode Sombre intégral, priorisation intelligente des scans, vitesse I/O agrégée à 0.5s).

---

## 1. Contexte et Objectifs

Au fil du temps, les supports de stockage (disques durs magnétiques HDD, SSD, clés USB, disques externes) subissent des dégradations physiques ou logicielles pouvant causer des corruptions silencieuses (*bit rot*, secteurs défectueux, erreurs de contrôleur).

**RotGuard** est une application Windows autonome, légère, sans compilation préalable, dotée d'une interface graphique native (GUI) moderne conçue pour :
1. Calculer et archiver l'empreinte (checksum/hash) des fichiers sur un ou plusieurs dossiers/disques.
2. Détecter avec précision les corruptions réelles (fichiers dont la date et la taille n'ont pas changé, mais dont le contenu a été altéré).
3. Mettre à jour automatiquement les empreintes des fichiers légitimement modifiés (date de modification ou taille différente) sans fausse alerte.
4. Lancer des scans complets traitant **en priorité les fichiers non scannés/nouveaux**, puis vérifiant les anciens fichiers.
5. Optimiser la lecture disque pour chaque support : limiter à 1 lecture les disques mécaniques (HDD) pour éliminer les allers-retours de tête de lecture (*head thrashing*), tout en parallélisant les SSD.
6. Assurer un fonctionnement robuste avec élévation des privilèges administrateur, gestion des fichiers verrouillés, synchronisation miroir instantanée et export des données.
7. Offrir un confort visuel de premier ordre (Mode Clair & Mode Sombre intégral) avec une navigation moderne par barre d'onglets personnalisée.

---

## 2. Choix Technologiques & Environnement d'Exécution

### 2.1 Décisions retenues
- **Langage** : **Python 3** (version installée sur l'environnement hôte : 3.13).
  - Aucune étape de compilation nécessaire pour coder ou tester.
  - Lancement direct du script.
- **Interface Graphique (GUI)** : **`tkinter` + `ttk` (Bibliothèque standard)**.
  - Design personnalisé avec barre d'onglets moderne (remplaçant les onglets natifs rigides).
  - Support intégral du **Mode Sombre et Mode Clair** sans conflit de contraste.
- **Moteur de Base de Données** : **SQLite 3 (`sqlite3`)**.
  - Intégré d'office dans la bibliothèque standard Python.
  - Zéro serveur, fichier de base unique `.db`.
  - Transactions atomiques (ACID), requêtes de streaming par curseur pour supporter des centaines de milliers de fichiers sans saturer la RAM.
- **Aucune dépendance externe (0 pip install requis)** : Le projet fonctionne immédiatement "out of the box" avec une installation Python standard.

---

## 3. Spécifications Fonctionnelles Détaillées

### 3.1 Gestion des cibles (Dossiers et Disques)
- L'utilisateur peut ajouter un ou plusieurs dossiers ou lecteurs complets (ex: `D:\`, `E:\Backups`, `F:\Archives`).
- **Auto-détection matérielle approfondie par le logiciel** :
  - Dès qu'un lecteur ou dossier est sélectionné, le programme Python interroge le support physique sous-jacent.
  - Prise en charge des supports USB pour identifier le média réel (HDD mécanique externe vs SSD externe).
  - Proposition automatique du parallélisme :
    - **HDD mécanique (interne ou externe)** : configuré par défaut à **1 lecture à la fois**.
    - **SSD / NVMe (interne ou externe)** : configuré par défaut à **4 lectures parallèles**.
    - **Clé USB / Amovible** : configuré par défaut à **1 lecture**.
  - Maintien de la sélection lors des actions et menu contextuel par clic droit (Ouvrir dans l'Explorateur, Modifier, Supprimer).
  - Centrage automatique de la boîte de dialogue d'édition au milieu de la fenêtre principale.
- **Plafond global et files dédiées par disque** : 
  - Chaque dossier/disque possède sa propre file de priorité locale (`PriorityQueue`) au lieu d'une file globale, évitant toute famine ou blocage I/O entre supports.
  - L'exploration s'exécute en parallèle par disque pour alimenter immédiatement chaque support sans attendre la fin des autres arborescences.
  - **Égalisation dynamique et saturation optimale des threads** :
    - L'ordonnanceur comble en permanence tous les threads disponibles jusqu'au plafond global (`global_max_workers`).
    - Répartition équitable entre les supports actifs (ex: 4 disques plafonnés à 4 threads avec 8 threads globaux = 2 threads par disque).
    - Dès qu'un disque a épuisé sa file de fichiers, ses threads sont automatiquement redistribués aux disques restants (ex: 3/3/2 threads, puis 4/4 threads), en respectant scrupuleusement la limite individuelle (`max_workers`) de chaque support (ex: 1 seul thread pour les HDD).

### 3.2 Vitesse I/O Globale et Activité des Tâches de Lecture
- **Agrégation globale exacte** : La vitesse I/O instantanée affichée est la somme exacte des débits de toutes les tâches actives.
- **Suivi d'avancement par fichier** : Chaque tâche de lecture indique en temps réel son avancement individuel sur le fichier en cours (pourcentage et mégaoctets lus).
- **Cadence fixe de 0.5 seconde** : L'ensemble des jauges, métriques et lignes de tâches s'actualisent en un seul bloc toutes les 0.5s, éliminant les scintillements et la surcharge CPU.

### 3.3 Priorisation Intelligente des Scans Complets
- Lorsque le scan complet est lancé :
  1. **Phase 1 (Prioritaire)** : Détection et hachage immédiat des fichiers **non scannés** (nouveaux) ou dont la taille/date a changé (priorité 0 locale).
  2. **Phase 2** : Vérification des fichiers déjà archivés en base (priorité 1 locale), ordonnés du plus ancien au plus récent.

### 3.4 Algorithmes de hachage (Checksums)

1. `BLAKE2b` : Recommandé pour son débit exceptionnel en C sur architecture 64-bit et sa sécurité cryptographique 512-bit.
2. `CRC32` : Rapide, historique.
3. `MD5` : Empreinte 128-bit classique.
4. `SHA-1` : Empreinte 160-bit.
5. `SHA-256` : Standard sécurisé moderne.
6. `SHA-512` : Robustesse 512-bit.
7. `SpookyHash V2` : Empreinte 128-bit de Bob Jenkins haute performance.

### 3.5 Logique de détection d'intégrité & Règles de décision

| Cas | Taille disque vs DB | Date modif (`mtime`) | Hash calculé | Décision / Statut du logiciel |
| :---: | :---: | :---: | :---: | :--- |
| **1** | Identique | Identique | Identique | **OK / Intègre** : Aucune corruption. |
| **2** | **Différente** | **Différente** | Calculé | **Mise à jour légitime** : Modification normale utilisateur sans fausse alerte. |
| **3** | Identique | **Différente** | Calculé | **Mise à jour légitime** : Métadonnées ou contenu réécrit sans alerte. |
| **4** | **Différente** | Identique | Calculé | **Mise à jour de taille** : Tracée sans fausse alerte. |
| **5** | **Identique** | **Identique** | **DIFFÉRENT** | 🚨 **CORRUPTION / BIT ROT DÉTECTÉ** : Alerte critique ! Contenu altéré sans modification OS. |
| **6** | Introuvable | - | - | ⚠️ **Fichier manquant** : Fichier présent en base mais supprimé ou déplacé du disque. |
| **7** | Non présent en DB | - | Calculé | 🆕 **Nouveau fichier** : Découverte et archivage (comptabilisé parmi les fichiers sains). |

> **Règle de comptage** : Les fichiers **Nouveaux** découverts sains sont comptabilisés dans le décompte global des **Fichiers Sains** (`Sains = OK + Nouveaux`).

### 3.6 Journal d'Événements Récents & Filtres Intelligents
- Cases à cocher permettant de filtrer les statuts affichés :
  - **🚨 Corrompus** : Coché par défaut.
  - **✓ Sains** : Coché par défaut.
  - **★ Nouveaux** : Décoché par défaut.
  - **↺ Modifiés** : Décoché par défaut.
  - **🔒 Inaccessibles** : Décoché par défaut.
- Actualisation instantanée et menu contextuel par clic droit pour copier le chemin d'accès.

### 3.7 Protection contre les Blocages (Jonctions NTFS, Fichiers Système, Chemins Longs)
- Le scanner ignore systématiquement les **liens symboliques et points de jonction NTFS** (`entry.is_symlink()`) afin d'éviter les boucles infinies récursives Windows.
- Prise en charge transparente des chemins longs (> 260 caractères) et noms Windows complexes via le préfixe natif `\\?\`.
- Lors de l'arrêt du scan (`Stop`), les tâches résiduelles sont vidées immédiatement et l'arrêt s'exécute de façon asynchrone sans bloquer l'interface graphique.

### 3.8 Onglet Journal Système & Diagnostics (Logs)
- Mémorisation circulaire des **500 dernières actions, événements, avertissements et exceptions**.
- Filtrage par niveau (`TOUS`, `ERROR`, `WARNING`, `INFO`).
- Bouton **📋 Copier les Logs** pour exporter l'historique complet dans le presse-papier en un clic.

### 3.9 Centralisation des Paramètres, Thème Immédiat & Navigation Épurée
- Tous les réglages de l'application sont centralisés de manière unifiée dans l'onglet **Paramètres** :
  - **Thème visuel** : Choix entre `Mode Clair` et `Mode Sombre`, avec **application instantanée en temps réel** dès le clic et persistance dans `config.ini`.
  - **Action post-scan** : `Ne rien faire`, `Mettre en veille le PC`, `Éteindre le PC`.
  - **Avertissement sonore** : Option désactivée par défaut, émettant 1 bip en cas de succès et 3 bips consécutifs si une corruption ou erreur est détectée.
- Barre de navigation moderne par onglets textuels sobres, épurés et sans emojis (`Centre de Scan`, `Dossiers & Disques`, `Base d'Empreintes`, `Paramètres`, `Exportation`, `Logs & Débug`).
- Conteneur à défilement vertical complet dans l'onglet **Paramètres** pour s'adapter à toutes les résolutions d'écran.

### 3.10 Fichier de Configuration Lisible (.ini) & Synchronisation Miroir
- Enregistrement de tous les paramètres généraux (thème, algorithme, parallélisme, tampon, cibles, action post-scan, alerte sonore) dans un fichier `config.ini` clair et facilement modifiable.
- Écriture instantanée de chaque lot dans la base principale et dans tous les fichiers miroirs configurés.

### 3.11 Nettoyage en Fin de Scan & Gestion de l'Alimentation (Mise en veille / Extinction)
- **Nettoyage automatique de l'interface graphique** :
  - Dès que le dernier fichier est vérifié, l'état bascule de façon synchrone en `Scan terminé` avec un message d'intégrité explicite (`✓ Scan terminé avec succès` ou avertissement en cas de corruption détectée).
  - La jauge de progression est calée à 100%, la carte de vitesse passe à `0.0 Mo/s (Scan terminé)`, l'ETA affiche `Terminé` et la durée totale est figée.
  - La liste des tâches de lecture est réinitialisée à `Inactif (Terminé)` et les boutons de commande sont immédiatement réactivés (Lancer scan complet actif, Arrêter et Pause désactivés).
- **Avertissement sonore optionnel (paramétrable dans Paramètres)** :
  - Si activé : joue 1 signal sonore en cas de succès, ou **3 fois de suite** de manière distincte (`winsound.MB_ICONHAND` / `bell()`) en cas de détection d'erreur (corruption, bit rot, fichier verrouillé ou manquant).
- **Gestion de l'alimentation (Mise en veille / Extinction)** :
  - Configurable dans l'onglet Paramètres (`Ne rien faire`, `Mettre en veille le PC`, `Éteindre le PC`).
  - **Dialogue de sécurité avec compte à rebours** :
    - En cas de mise en veille ou d'extinction sélectionnée, une fenêtre modale d'avertissement s'affiche au premier plan avec un décompte visuel de 60 secondes (extinction) ou 30 secondes (veille).
    - L'utilisateur peut à tout instant cliquer sur `❌ Annuler` pour interrompre immédiatement l'extinction/mise en veille programmée, ou sur `Exécuter maintenant` pour l'enclencher sans attendre.

### 3.12 Détecteur de Doublons Multi-Critères
- Onglet dédié **Doublons** permettant d'analyser la base d'empreintes pour identifier l'espace disque gaspillé :
  - **Présentation condensée** : Alignée sur le design épuré de la base d'empreintes.
  - **Critère principal de base** : détection basée sur la **taille** (`size > 0`) et le **hash de contenu** (`hash_value`).
  - **Critères optionnels activables par cases à cocher** :
    - `Même nom de fichier` (respect ou non du nom exact).
    - `Même extension` (regroupement par extension).
    - `Même date de modification` (regroupement par date de modification `mtime`).
  - **Filtre textuel instantané** par nom de fichier ou sous-dossier comme dans l'explorateur d'empreintes.
  - **Tri par défaut du plus gros au plus petit** en fonction du volume d'espace gaspillé récupérable : `taille * (nombre de doublons - 1)`.
  - **Organisation et calibrage précis des colonnes du tableau maître** :
    - `Nom de fichier` en premier (largeur fluide étirable), suivi de `Ext` (50px), `Copies` (nombre brut seul, 55px), `Taille` (85px), `Espace récupérable` (105px).
    - Plafond de fluidité à 500 groupes de doublons.
  - **Affichage maître-détails avec PanedWindow redimensionnable** :
    - Volet supérieur : liste des groupes de doublons.
    - Volet inférieur : empreinte commune affichée au-dessus du tableau de détail, suivie des emplacements précis de chaque copie.
  - **Gestion et suppression sécurisée des copies** :
    - Bouton `Supprimer cette copie...` et menu clic droit avec avertissement de confirmation explicite.
    - Suppression physique sur disque (`os.remove`) et purge immédiate de la base d'empreintes (`db_manager.delete_record`), avec rafraîchissement automatique des tableaux et compteurs.
  - **Garantie d'affichage de la barre d'état** : La barre d'état inférieure est ancrée avant le conteneur principal dans `pack()`, évitant tout masquage sur les petits écrans.

### 3.13 Base d'Empreintes Optimisée
- Capacité portée à **500 enregistrements** par page pour une visibilité accrue.
- Nettoyage des détails de sélection : suppression des crochets disgracieux autour du chemin.
- Alignement soigné des colonnes de dates : date de modification et date de dernier contrôle au format `YYYY-MM-DD HH:MM` placées côte à côte.

### 3.14 Identifiants de Cibles Uniques et Chemins Relatifs (Portabilité et Suppression en Cascade)
- **Identifiant unique de cible (`target_id`)** : Chaque dossier/disque configuré se voit attribuer un identifiant unique interne transparent, stocké dans `config.ini`.
- **Stockage par chemin relatif (`rel_path`)** : La base de données SQLite utilise désormais une clé primaire composite `(target_id, rel_path)`.
- **Portabilité instantanée (zéro recalcul de hash)** :
  - Si l'utilisateur modifie le chemin d'un dossier cible ou si une lettre de lecteur change (ex: clé USB sur `F:\` au lieu de `E:\`), il suffit de mettre à jour le chemin dans la configuration.
  - Tous les fichiers sont immédiatement reconnus et résolus dynamiquement sous leur nouvel emplacement, éliminant tout recalcul d'empreinte.
- **Suppression en cascade propre** :
  - La suppression d'un emplacement cible dans l'interface purge automatiquement tous les fichiers archivés correspondants de la base principale et des miroirs (`DELETE FROM files WHERE target_id = ?`).
- **Élimination des outils manuels superflus** : L'ancienne boîte de dialogue manuelle de transfert de préfixe a été retirée car le renommage/déplacement de cible est désormais 100% natif et automatique.

### 3.15 Internationalisation Modulaire (Fichiers Dédiés par Langue & Menu Déroulant)
- Slogan harmonisé : *"Intégrité des fichiers, dédoublonnage et détection de bit rot"* (Français) / *"File integrity, deduplication and bit rot detection"* (Anglais).
- **Architecture modulaire par fichier** : chaque langue est stockée dans son propre fichier indépendant sous `core/locales/<lang>.py` (ex: [`core/locales/fr.py`](core/locales/fr.py), [`core/locales/en.py`](core/locales/en.py)) pour une maintenance et un ajout simplifiés sans toucher au code applicatif.
- **Auto-découverte dynamique** : le moteur [`core/i18n.py`](core/i18n.py) détecte automatiquement tout nouveau fichier de langue ajouté dans le dossier.
- **Sélection par menu déroulant (Combobox)** : dans l'onglet **Paramètres**, les langues sont proposées avec :
  1. `Automatique (système)` en tout premier (détection selon l'environnement OS).
  2. Suivi de toutes les langues disponibles triées par **ordre alphabétique** de leur nom (ex: *English*, *Français*).
- **Actualisation dynamique instantanée** : mise à jour réactive immédiate de 100% de l'interface sans aucun redémarrage (`update_ui_language()`).

### 3.16 Compatibilité Multi-Plateforme (Linux & Windows)
- Abstraction unifiée des appels système via `core/platform_utils.py` :
  - **Élévation de privilèges** : `ctypes.windll.shell32` sous Windows, `pkexec` / `sudo` sous Linux.
  - **Explorateur de fichiers** : `explorer.exe /select` sous Windows, `xdg-open` / `gio` sous Linux, `open -R` sous macOS.
  - **Gestion de l'alimentation** : `shutdown` / `PowrProf` sous Windows, `systemctl suspend` / `systemctl poweroff` sous Linux.
  - **Avertissements sonores** : `winsound` sous Windows, `bell()` / `paplay` sous Linux.
  - **Détection matérielle HDD vs SSD** : `wmic` / `powershell` sous Windows, lecture directe de `/sys/block/<périphérique>/queue/rotational` sous Linux (0 = SSD, 1 = HDD mécanique).
  - **Dossiers virtuels ignorés** sous Linux : `/proc`, `/sys`, `/dev`, `/run`, etc.

---

## 4. Architecture Logicielle du Codebase

```
RotGuard/
│
├── config.ini                # Configuration persistante au format INI (cibles, thème, langue, threads, buffers, miroirs)
├── main.py                   # Lanceur principal avec fermeture propre
├── build.bat                 # Script de compilation automatisé PyInstaller (pur ASCII)
├── build.py                  # Script Python cross-platform de build exécutable autonome
├── PROJET.md                 # Cahier des charges et spécifications techniques
├── README.md                 # Documentation d'utilisation
│
├── core/
│   ├── __init__.py
│   ├── i18n.py               # Moteur d'internationalisation et auto-découverte des locales
│   ├── locales/              # Fichiers de traduction modulaires par langue
│   │   ├── __init__.py
│   │   ├── fr.py             # Dictionnaire de langue française
│   │   └── en.py             # Dictionnaire de langue anglaise
│   ├── platform_utils.py     # Abstraction cross-platform (Windows / Linux : explorateur, privilèges, veille, sons)
│   ├── logger.py             # Buffer circulaire en mémoire des 500 derniers logs et exceptions
│   ├── models.py             # Dataclasses (TargetFolder, FileRecord, ScanStats, AppConfig avec language)
│   ├── disk_info.py          # Auto-détection HDD vs SSD Windows (PowerShell) & Linux (/sys/block/queue/rotational)
│   ├── spookyhash.py         # Implémentation autonome de SpookyHash V2 (128-bit)
│   ├── hasher.py             # Hachage unifié avec notification de vitesse par bloc
│   ├── database.py           # SQLite avec miroir, relocalisation de chemins, suppression d'enregistrements et doublons
│   ├── scanner.py            # Exploration NTFS & Linux sécurisée (anti-jonctions, dossiers virtuels)
│   ├── worker_pool.py        # Ordonnanceur multithread priorisant les fichiers non scannés (cadence 0.5s)
│   └── exporter.py           # Export CSV Excel en streaming à mémoire constante
│
└── ui/
    ├── __init__.py
    ├── styles.py             # Thèmes Clair et Sombre à fort contraste et propagateur récursif
    ├── app_window.py         # Fenêtre principale avec barre d'onglets personnalisée et ancrage robuste du statut
    ├── widgets/
    │   ├── __init__.py
    │   └── components.py     # MetricCard et StatusBadge dynamiques
    └── views/
        ├── __init__.py
        ├── scan_view.py      # Tableau de bord temps réel avec actualisation à 0.5s et filtres
        ├── targets_view.py   # Gestion cibles, auto-détection matérielle, dialogue de modification et menu clic droit
        ├── database_view.py  # Explorateur d'empreintes (500 lignes), dates alignées et détails épurés
        ├── duplicates_view.py# Détecteur de doublons condensé (PanedWindow, nom en 1er, suppression de copie)
        ├── settings_view.py  # Onglet Paramètres avec sélecteur de langue, ascenseur vertical fluide
        ├── export_view.py    # Boîte de dialogue d'export CSV / Checksums
        ├── logs_view.py      # Journal des 500 logs et exceptions pour diagnostic
        └── about_view.py     # Présentation, version 0.1, crédits et lien vers le dépôt GitHub
```
