"""Vue 'À propos' de RotGuard : informations, crédits, version et lien GitHub."""

import os
import webbrowser
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Optional

from core.i18n import tr
from ui.styles import COLORS, FONTS, apply_theme_to_widget_tree

APP_NAME = "RotGuard"
APP_VERSION = "0.1"
GITHUB_URL = "https://github.com/Mwyann/RotGuard"


class AboutView(tk.Frame):
    """Écran de présentation du logiciel, version, crédits et liens officiels."""

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg_main"], padx=20, pady=20)
        self.logo_img: Optional[tk.PhotoImage] = None

        self._build_content()

    def _build_content(self):
        # 1. Conteneur principal centré
        self.card = tk.Frame(
            self,
            bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=28,
            pady=24
        )
        self.card.pack(fill="both", expand=True)
        self.card.bind("<Configure>", self._on_card_resize)

        # En-tête avec logo et nom
        self.header_frame = tk.Frame(self.card, bg=COLORS["bg_card"])
        self.header_frame.pack(fill="x", pady=(0, 16))

        # Chargement de l'icône RotGuard
        logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", "rotguard_48.png")
        if os.path.exists(logo_path):
            try:
                self.logo_img = tk.PhotoImage(file=logo_path)
                self.lbl_logo = tk.Label(self.header_frame, image=self.logo_img, bg=COLORS["bg_card"])
                self.lbl_logo.pack(side="left", padx=(0, 14))
            except Exception:
                pass

        self.title_box = tk.Frame(self.header_frame, bg=COLORS["bg_card"])
        self.title_box.pack(side="left", fill="y")

        self.lbl_app_name = tk.Label(
            self.title_box,
            text=f"{APP_NAME}  v{APP_VERSION}",
            font=("Segoe UI", 18, "bold"),
            fg=COLORS["primary"],
            bg=COLORS["bg_card"],
            anchor="w"
        )
        self.lbl_app_name.pack(anchor="w")

        self.lbl_subtitle = tk.Label(
            self.title_box,
            text=tr("about_subtitle"),
            font=FONTS["body"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"],
            anchor="w"
        )
        self.lbl_subtitle.pack(anchor="w", pady=(2, 0))

        # Séparateur
        self.sep1 = ttk.Separator(self.card, orient="horizontal")
        self.sep1.pack(fill="x", pady=(0, 16))

        # 2. Section Dépôt GitHub et Téléchargements Releases
        self.gh_frame = tk.LabelFrame(
            self.card,
            text=tr("about_sec_repo"),
            font=FONTS["body_bold"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            padx=14,
            pady=12
        )
        self.gh_frame.pack(fill="x", pady=(0, 14))

        self.lbl_gh_desc = tk.Label(
            self.gh_frame,
            text=tr("about_repo_desc"),
            font=FONTS["body"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"],
            justify="left",
            wraplength=800
        )
        self.lbl_gh_desc.pack(anchor="w", pady=(0, 8))

        gh_btn_box = tk.Frame(self.gh_frame, bg=COLORS["bg_card"])
        gh_btn_box.pack(fill="x")

        self.lbl_gh_url = tk.Label(
            gh_btn_box,
            text=GITHUB_URL,
            font=FONTS["mono_bold"],
            fg=COLORS["accent"],
            bg=COLORS["bg_card"],
            cursor="hand2"
        )
        self.lbl_gh_url.pack(side="left", padx=(0, 12))
        self.lbl_gh_url.bind("<Button-1>", lambda e: webbrowser.open(GITHUB_URL))

        self.btn_open_gh = ttk.Button(
            gh_btn_box,
            text=tr("about_btn_github"),
            style="Primary.TButton",
            command=lambda: webbrowser.open(GITHUB_URL)
        )
        self.btn_open_gh.pack(side="left", padx=(0, 8))

        self.btn_open_releases = ttk.Button(
            gh_btn_box,
            text=tr("about_btn_releases"),
            style="Secondary.TButton",
            command=lambda: webbrowser.open(f"{GITHUB_URL}/releases")
        )
        self.btn_open_releases.pack(side="left")

        # 3. Section Vibe-Coding & Intelligence Artificielle
        self.vibe_frame = tk.LabelFrame(
            self.card,
            text=tr("about_sec_vibe"),
            font=FONTS["body_bold"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            padx=14,
            pady=12
        )
        self.vibe_frame.pack(fill="x", pady=(0, 14))

        self.lbl_vibe_desc = tk.Label(
            self.vibe_frame,
            text=tr("about_vibe_desc"),
            font=FONTS["body"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"],
            justify="left",
            wraplength=850
        )
        self.lbl_vibe_desc.pack(anchor="w")

        # 4. Spécifications & Architecture
        self.specs_frame = tk.LabelFrame(
            self.card,
            text=tr("about_sec_specs"),
            font=FONTS["body_bold"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            padx=14,
            pady=12
        )
        self.specs_frame.pack(fill="x", pady=(0, 14))

        self.lbl_specs_desc = tk.Label(
            self.specs_frame,
            text=tr("about_specs_desc"),
            font=FONTS["body"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"],
            justify="left",
            wraplength=850
        )
        self.lbl_specs_desc.pack(anchor="w")

        # 5. Pied de page & Licence
        self.footer_frame = tk.Frame(self.card, bg=COLORS["bg_card"])
        self.footer_frame.pack(fill="x", side="bottom")

        self.lbl_license = tk.Label(
            self.footer_frame,
            text=tr("about_license"),
            font=FONTS["small"],
            fg=COLORS["text_muted"],
            bg=COLORS["bg_card"],
            anchor="w"
        )
        self.lbl_license.pack(side="left")

    def update_ui_language(self):
        """Actualise dynamiquement les textes traduits."""
        self.lbl_subtitle.config(text=tr("about_subtitle"))
        self.gh_frame.config(text=tr("about_sec_repo"))
        self.lbl_gh_desc.config(text=tr("about_repo_desc"))
        self.btn_open_gh.config(text=tr("about_btn_github"))
        self.btn_open_releases.config(text=tr("about_btn_releases"))

        self.vibe_frame.config(text=tr("about_sec_vibe"))
        self.lbl_vibe_desc.config(text=tr("about_vibe_desc"))

        self.specs_frame.config(text=tr("about_sec_specs"))
        self.lbl_specs_desc.config(text=tr("about_specs_desc"))

        self.lbl_license.config(text=tr("about_license"))

    def apply_theme_colors(self, colors: Dict[str, Any]):
        """Met à jour les couleurs pour le Mode Sombre / Mode Clair."""
        self.configure(bg=colors["bg_main"])
        if hasattr(self, "card"):
            self.card.configure(bg=colors["bg_card"], highlightbackground=colors["border"])
        apply_theme_to_widget_tree(self.card, colors)
        if hasattr(self, "lbl_app_name"):
            self.lbl_app_name.config(fg=colors["primary"], bg=colors["bg_card"])
        if hasattr(self, "lbl_gh_url"):
            self.lbl_gh_url.config(fg=colors["accent"], bg=colors["bg_card"])

    def _on_card_resize(self, event):
        wrap = max(350, event.width - 80)
        if hasattr(self, "lbl_gh_desc"):
            self.lbl_gh_desc.config(wraplength=wrap)
        if hasattr(self, "lbl_vibe_desc"):
            self.lbl_vibe_desc.config(wraplength=wrap)
        if hasattr(self, "lbl_specs_desc"):
            self.lbl_specs_desc.config(wraplength=wrap)
