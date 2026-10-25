"""Fenêtre principale de l'application RotGuard avec barre d'onglets personnalisée moderne

et bascule dynamique du Mode Sombre / Mode Clair.
"""

import os
import sys
import ctypes
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, Any, Optional

from core.models import AppConfig
from core.database import DatabaseManager
from core.logger import logger
from core.platform_utils import is_running_as_admin, request_elevation
from core.i18n import tr, set_active_language
from ui.styles import apply_theme, apply_theme_to_widget_tree, COLORS, FONTS
from ui.views.scan_view import ScanView
from ui.views.targets_view import TargetsView
from ui.views.database_view import DatabaseView
from ui.views.duplicates_view import DuplicatesView
from ui.views.settings_view import SettingsView
from ui.views.export_view import ExportView
from ui.views.logs_view import LogsView
from ui.views.about_view import AboutView, APP_NAME, APP_VERSION


class RotGuardApp(tk.Tk):
    """Application principale RotGuard avec navigation par onglets modernes."""

    def __init__(self, config: AppConfig, db_manager: DatabaseManager, start_minimized: bool = False):
        super().__init__()
        # 0. Masquer immédiatement la fenêtre pour éliminer l'effet de flash / petit carré 200x200
        self.withdraw()

        self.config = config
        self.db_manager = db_manager
        self.current_theme = getattr(self.config, "theme", "light") or "light"

        # Initialiser la langue
        set_active_language(getattr(self.config, "language", "auto"))

        # Titre de base de la fenêtre
        self.update_window_title(is_scanning=False)

        # Positionnement centré et taille initiale sans aucun scintillement ("double-apparition")
        width = 1140
        height = 760
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(960, 580)

        # Configuration de l'icône de la fenêtre (ICO et PNG haute résolution)
        assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        ico_path = os.path.join(assets_dir, "rotguard.ico")
        png_path = os.path.join(assets_dir, "rotguard.png")
        if os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass
        if os.path.exists(png_path):
            try:
                self.app_icon = tk.PhotoImage(file=png_path)
                self.iconphoto(True, self.app_icon)
            except Exception:
                pass

        # 1. Thème initial
        apply_theme(self, self.current_theme)

        if self.db_manager and hasattr(self.config, "targets"):
            self.db_manager.set_targets(self.config.targets)
            self.db_manager.on_ready = self._on_db_ready

        self._build_top_banner()
        self._build_custom_tab_bar()
        # IMPORTANT : pack status_bar AVANT content_container pour qu'elle ne soit jamais masquée
        self._build_status_bar()
        self._build_content_area()

        # Afficher la première vue par défaut
        self._switch_tab("scan")

        # Rendu immédiat et forcé de la fenêtre en mémoire
        self.update_idletasks()

        # Affichage immédiat à la taille exacte ou minimisation
        if start_minimized:
            self.iconify()
        else:
            self.deiconify()

    def update_window_title(self, is_scanning: bool = False):
        """Met à jour le titre de la barre de titre de la fenêtre."""
        base_title = tr("app_title")
        if is_scanning:
            self.title(f"{base_title} - {tr('title_scanning')}")
        else:
            self.title(base_title)

    def _build_top_banner(self):
        self.banner = tk.Frame(self, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1, padx=16, pady=8)
        self.banner.pack(fill="x")

        self.left_box = tk.Frame(self.banner, bg=COLORS["bg_card"])
        self.left_box.pack(side="left")

        # Icône RotGuard dans la bannière
        logo_48_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "rotguard_48.png")
        self.banner_logo: Optional[tk.PhotoImage] = None
        if os.path.exists(logo_48_path):
            try:
                self.banner_logo = tk.PhotoImage(file=logo_48_path)
                self.lbl_logo_img = tk.Label(self.left_box, image=self.banner_logo, bg=COLORS["bg_card"])
                self.lbl_logo_img.pack(side="left", padx=(0, 10))
            except Exception:
                pass

        self.lbl_app = tk.Label(
            self.left_box,
            text=f"{APP_NAME} v{APP_VERSION}",
            font=("Segoe UI", 16, "bold"),
            fg=COLORS["primary"],
            bg=COLORS["bg_card"]
        )
        self.lbl_app.pack(side="left", padx=(0, 10))

        self.lbl_sub = tk.Label(
            self.left_box,
            text=tr("app_subtitle"),
            font=FONTS["body"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"]
        )
        self.lbl_sub.pack(side="left")

        self.right_box = tk.Frame(self.banner, bg=COLORS["bg_card"])
        self.right_box.pack(side="right")

        # Badge Admin
        self.is_admin = is_running_as_admin()
        if self.is_admin:
            self.admin_lbl = tk.Label(
                self.right_box,
                text=tr("admin_badge"),
                font=FONTS["small_bold"],
                fg=COLORS["success"],
                bg=COLORS["success_bg"],
                padx=10,
                pady=4
            )
            self.admin_lbl.pack(side="left")
        else:
            self.btn_elevate = ttk.Button(
                self.right_box,
                text=tr("btn_elevate"),
                style="Secondary.TButton",
                command=request_elevation
            )
            self.btn_elevate.pack(side="left")

    def _build_custom_tab_bar(self):
        self.tab_bar_frame = tk.Frame(self, bg=COLORS["bg_main"], padx=14, pady=8)
        self.tab_bar_frame.pack(fill="x")

        self.tabs_meta = [
            ("scan", tr("tab_scan")),
            ("targets", tr("tab_targets")),
            ("database", tr("tab_database")),
            ("duplicates", tr("tab_duplicates")),
            ("settings", tr("tab_settings")),
            ("export", tr("tab_export")),
            ("logs", tr("tab_logs")),
            ("about", tr("tab_about"))
        ]

        self.tab_buttons: Dict[str, tk.Label] = {}
        self.active_tab_key = "scan"

        for key, label in self.tabs_meta:
            btn = tk.Label(
                self.tab_bar_frame,
                text=label,
                font=FONTS["body_bold"],
                bg=COLORS["nav_btn_bg"],
                fg=COLORS["nav_btn_fg"],
                padx=16,
                pady=7,
                cursor="hand2"
            )
            btn.pack(side="left", padx=(0, 6))
            btn.bind("<Button-1>", lambda e, k=key: self._switch_tab(k))
            self.tab_buttons[key] = btn

    def _build_content_area(self):
        self.content_container = tk.Frame(self, bg=COLORS["bg_main"])
        self.content_container.pack(fill="both", expand=True)

        self.views = {
            "scan": ScanView(self.content_container, self.config, self.db_manager),
            "targets": TargetsView(self.content_container, self.config, db_manager=self.db_manager, on_config_changed=self._on_config_updated),
            "database": DatabaseView(self.content_container, self.db_manager),
            "duplicates": DuplicatesView(self.content_container, self.db_manager, config=self.config),
            "settings": SettingsView(self.content_container, self.config, self.db_manager, on_config_changed=self._on_config_updated),
            "export": ExportView(self.content_container, self.db_manager),
            "logs": LogsView(self.content_container, db_manager=self.db_manager),
            "about": AboutView(self.content_container)
        }

        # Exposer les vues en tant qu'attributs directs
        self.scan_view = self.views["scan"]
        self.targets_view = self.views["targets"]
        self.database_view = self.views["database"]
        self.duplicates_view = self.views["duplicates"]
        self.settings_view = self.views["settings"]
        self.export_view = self.views["export"]
        self.logs_view = self.views["logs"]
        self.about_view = self.views["about"]

    def _build_status_bar(self):
        self.status_bar = tk.Frame(self, bg=COLORS["status_bar_bg"], padx=14, pady=5)
        self.status_bar.pack(fill="x", side="bottom")

        self.lbl_status_algo = tk.Label(
            self.status_bar,
            text=tr("status_algo", self.config.hash_algorithm),
            font=FONTS["small"],
            fg=COLORS["text_secondary"],
            bg=COLORS["status_bar_bg"]
        )
        self.lbl_status_algo.pack(side="left", padx=(0, 16))

        mirror_count = len(self.config.mirror_paths)
        mirror_txt = self._format_mirror_text(mirror_count)
        db_state_txt = mirror_txt if getattr(self.db_manager, "is_ready", True) else f"({tr('status_db_connecting')})"
        self.lbl_status_db = tk.Label(
            self.status_bar,
            text=tr("status_db", os.path.basename(self.config.db_path), db_state_txt),
            font=FONTS["small"],
            fg=COLORS["text_secondary"],
            bg=COLORS["status_bar_bg"]
        )
        self.lbl_status_db.pack(side="left", padx=(0, 16))

        self.lbl_status_targets = tk.Label(
            self.status_bar,
            text=tr("status_targets", sum(1 for t in self.config.targets if t.enabled)),
            font=FONTS["small"],
            fg=COLORS["text_secondary"],
            bg=COLORS["status_bar_bg"]
        )
        self.lbl_status_targets.pack(side="right")

    def _on_db_ready(self):
        """Notification asynchrone dès que la base SQLite et ses miroirs sont prêts."""
        self.after(0, self._update_db_status_ready)

    def _format_mirror_text(self, count: int) -> str:
        if count > 0:
            return tr("status_db_mirrors", count)
        return tr("status_db_no_mirror")

    def _update_db_status_ready(self):
        if hasattr(self, "lbl_status_db"):
            mirror_count = len(self.config.mirror_paths)
            mirror_txt = self._format_mirror_text(mirror_count)
            self.lbl_status_db.config(text=tr("status_db", os.path.basename(self.config.db_path), mirror_txt))

    def _switch_tab(self, key: str):
        if self.active_tab_key == "settings" and key != "settings":
            if hasattr(self, "settings_view") and self.settings_view.has_new_modifications_since_entry():
                resp = messagebox.askyesnocancel(
                    tr("settings_unsaved_title"),
                    tr("settings_unsaved_msg"),
                    parent=self
                )
                if resp is True:
                    # Oui : sauvegarder puis changer d'onglet
                    saved = self.settings_view._save_settings(show_message=False)
                    if not saved:
                        return
                elif resp is False:
                    # Non : continuer sans enregistrer (conserver les réglages modifiés en mémoire sans redemander)
                    self.settings_view.ack_current_modifications()
                else:
                    # Annuler : annuler les modifications (rétablir la configuration précédente)
                    self.settings_view.reset_to_saved_state()

        self.active_tab_key = key

        for k, btn in self.tab_buttons.items():
            if k == key:
                btn.config(
                    bg=COLORS["nav_active_bg"],
                    fg=COLORS["nav_active_fg"],
                    font=("Segoe UI", 10, "bold")
                )
            else:
                btn.config(
                    bg=COLORS["nav_btn_bg"],
                    fg=COLORS["nav_btn_fg"],
                    font=FONTS["body_bold"]
                )

        for k, v in self.views.items():
            if k == key:
                v.pack(fill="both", expand=True)
            else:
                v.pack_forget()

        if key == "database":
            self.views["database"].refresh_data()
        elif key == "duplicates":
            self.views["duplicates"].refresh_duplicates()
        elif key == "logs":
            self.views["logs"].refresh_logs()
        elif key == "settings":
            if hasattr(self, "settings_view"):
                self.settings_view.on_tab_enter()


    def _refresh_theme_ui(self):
        """Met à jour toutes les sections graphiques de la fenêtre principale après un changement de thème."""
        # 1. Mise à jour de la bannière supérieure (élimine tout contour blanc)
        self.banner.config(bg=COLORS["bg_card"], highlightbackground=COLORS["border"])
        self.left_box.config(bg=COLORS["bg_card"])
        self.right_box.config(bg=COLORS["bg_card"])
        self.lbl_app.config(bg=COLORS["bg_card"], fg=COLORS["primary"])
        self.lbl_sub.config(bg=COLORS["bg_card"], fg=COLORS["text_secondary"])
        if hasattr(self, "lbl_logo_img"):
            self.lbl_logo_img.config(bg=COLORS["bg_card"])
        if self.is_admin and hasattr(self, "admin_lbl"):
            self.admin_lbl.config(bg=COLORS["success_bg"], fg=COLORS["success"])

        # 2. Mise à jour de la barre d'onglets
        self.tab_bar_frame.config(bg=COLORS["bg_main"])
        for k, btn in self.tab_buttons.items():
            if k == self.active_tab_key:
                btn.config(bg=COLORS["nav_active_bg"], fg=COLORS["nav_active_fg"])
            else:
                btn.config(bg=COLORS["nav_btn_bg"], fg=COLORS["nav_btn_fg"])

        # 3. Mise à jour de la zone centrale et de TOUTES les vues
        self.content_container.config(bg=COLORS["bg_main"])
        for view in self.views.values():
            if hasattr(view, "apply_theme_colors"):
                view.apply_theme_colors(COLORS)

        # 4. Mise à jour de la barre d'état
        self.status_bar.config(bg=COLORS["status_bar_bg"])
        self.lbl_status_algo.config(bg=COLORS["status_bar_bg"], fg=COLORS["text_secondary"])
        self.lbl_status_db.config(bg=COLORS["status_bar_bg"], fg=COLORS["text_secondary"])
        self.lbl_status_targets.config(bg=COLORS["status_bar_bg"], fg=COLORS["text_secondary"])

    def _on_config_updated(self):
        if hasattr(self.config, "language"):
            set_active_language(self.config.language)
            is_scanning = bool(hasattr(self, "scan_view") and self.scan_view.pool and self.scan_view.pool.stats.is_running)
            self.update_window_title(is_scanning=is_scanning)
            if hasattr(self, "lbl_sub"):
                self.lbl_sub.config(text=tr("app_subtitle"))
            if hasattr(self, "admin_lbl"):
                self.admin_lbl.config(text=tr("admin_badge"))
            if hasattr(self, "btn_elevate"):
                self.btn_elevate.config(text=tr("btn_elevate"))

            tab_labels = {
                "scan": tr("tab_scan"),
                "targets": tr("tab_targets"),
                "database": tr("tab_database"),
                "duplicates": tr("tab_duplicates"),
                "settings": tr("tab_settings"),
                "export": tr("tab_export"),
                "logs": tr("tab_logs"),
                "about": tr("tab_about")
            }
            for k, btn in self.tab_buttons.items():
                if k in tab_labels:
                    btn.config(text=tab_labels[k])

            # Propagation dynamique et instantanée à TOUTES les vues ouvertes
            for view in self.views.values():
                if hasattr(view, "update_ui_language"):
                    try:
                        view.update_ui_language()
                    except Exception:
                        pass

        if hasattr(self.config, "theme") and self.config.theme != self.current_theme:
            self.current_theme = self.config.theme
            apply_theme(self, self.current_theme)
            self._refresh_theme_ui()

        self.lbl_status_algo.config(text=tr("status_algo", self.config.hash_algorithm))
        mirror_count = len(self.config.mirror_paths)
        mirror_txt = self._format_mirror_text(mirror_count)
        self.lbl_status_db.config(text=tr("status_db", os.path.basename(self.config.db_path), mirror_txt))
        self.lbl_status_targets.config(text=tr("status_targets", sum(1 for t in self.config.targets if t.enabled)))

        if self.db_manager and hasattr(self.config, "targets"):
            self.db_manager.set_targets(self.config.targets)

        scan_view = self.views.get("scan")
        if scan_view:
            scan_view.config = self.config
            if hasattr(scan_view, "update_from_config"):
                scan_view.update_from_config()

        dup_view = self.views.get("duplicates")
        if dup_view:
            dup_view.config = self.config
            if self.active_tab_key == "duplicates":
                dup_view.refresh_duplicates()

        db_view = self.views.get("database")
        if db_view and self.active_tab_key == "database":
            db_view.refresh_data()

    def on_close(self):
        """Gestion propre et immédiate de la fermeture de l'application (croix ou OS)."""
        if hasattr(self, "settings_view") and self.settings_view.has_unsaved_changes():
            resp = messagebox.askyesnocancel(
                tr("settings_unsaved_title"),
                tr("settings_unsaved_msg"),
                parent=self
            )
            if resp is None:
                self.settings_view.reset_to_saved_state()
                return
            elif resp is True:
                self.settings_view._save_settings(show_message=False)

        scan_view = self.views.get("scan")
        if scan_view:
            if hasattr(scan_view, "_cancel_countdown"):
                scan_view._cancel_countdown()
            if scan_view.pool and scan_view.pool.stats.is_running:
                scan_view.pool.stop()
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)

