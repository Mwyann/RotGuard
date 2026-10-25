"""Point d'entrée principal de l'application RotGuard."""

import sys
import os

# Ajout du répertoire courant au PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import argparse
from core.models import AppConfig
from core.database import DatabaseManager
from core.platform_utils import apply_process_priorities
from ui.app_window import RotGuardApp


def main():
    """Démarre l'application RotGuard."""
    # S'assurer que le répertoire de travail courant est celui du binaire (.exe) ou du script
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))

    try:
        os.chdir(app_dir)
    except Exception:
        pass

    # 0. Analyse des arguments en ligne de commande (CLI)
    parser = argparse.ArgumentParser(
        description="RotGuard — Intégrité des fichiers, dédoublonnage et détection de bit rot",
        add_help=True
    )
    parser.add_argument(
        "--scan", "-s",
        action="store_true",
        help="Démarre automatiquement le scan complet d'intégrité dès l'ouverture."
    )
    parser.add_argument(
        "--update", "-u",
        action="store_true",
        help="Démarre automatiquement la mise à jour rapide (traite uniquement la file n°1 : nouveaux et modifiés)."
    )
    parser.add_argument(
        "--simple", "-c",
        action="store_true",
        help="Démarre automatiquement un contrôle simple d'intégrité (lecture seule, sans nouveaux/modifiés)."
    )
    parser.add_argument(
        "--minimized", "-m",
        action="store_true",
        help="Démarre l'application minimisée dans la barre des tâches (idéal pour les tâches planifiées)."
    )
    parser.add_argument(
        "--autoclose",
        action="store_true",
        help="Quitte automatiquement le logiciel après le scan si aucune erreur n'a été détectée."
    )
    parser.add_argument(
        "--autoshutdown",
        action="store_true",
        help="Éteint automatiquement l'ordinateur après le scan si aucune erreur n'a été détectée."
    )
    args = parser.parse_args()

    # 1. Chargement de la configuration persistante
    config = AppConfig.load_from_file("config.ini")
    apply_process_priorities(config.cpu_priority, config.io_priority)

    # 2. Initialisation de la base SQLite et de ses miroirs
    db_manager = DatabaseManager(
        primary_db_path=config.db_path,
        mirror_db_paths=config.mirror_paths,
        targets=config.targets
    )

    # 3. Lancement de l'interface graphique Tkinter
    app = RotGuardApp(config=config, db_manager=db_manager, start_minimized=args.minimized)

    # Transmission des drapeaux d'automatisation CLI
    app.scan_view.cli_autoclose = args.autoclose
    app.scan_view.cli_autoshutdown = args.autoshutdown
    app.scan_view.apply_cli_options()

    if not args.minimized:
        try:
            app.lift()
        except Exception:
            pass

    if args.scan:
        # Lancement asynchrone différé une fois l'UI Tkinter initialisée
        app.after(500, app.scan_view._start_full_scan)
    elif args.update:
        app.after(500, app.scan_view._start_update_scan)
    elif args.simple:
        app.after(500, app.scan_view._start_simple_check)

    # Gestion de la fermeture propre de la fenêtre
    def on_closing():
        app.on_close()

    app.protocol("WM_DELETE_WINDOW", on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
