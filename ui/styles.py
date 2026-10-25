"""Thème et styles visuels pour l'interface Tkinter de RotGuard.

Prend en charge le Mode Clair et le Mode Sombre avec une palette soignée,
des contrastes irréprochables et un moteur de propagation récursif.
"""

import tkinter as tk
from tkinter import ttk
from typing import Dict, Any


# Palettes de couleurs à fort contraste
THEMES = {
    "light": {
        "name": "light",
        "bg_main": "#F1F5F9",          # Fond principal (slate 100)
        "bg_card": "#FFFFFF",          # Fond des cartes / panneaux (blanc pur)
        "bg_card_alt": "#E2E8F0",      # Fond secondaire (slate 200)
        "border": "#CBD5E1",           # Bordures (slate 300)
        "text_primary": "#0F172A",     # Texte principal (noir ardoise)
        "text_secondary": "#475569",   # Libellés (slate 600)
        "text_muted": "#64748B",       # Texte atténué (slate 500)
        "primary": "#2563EB",          # Bleu principal (action)
        "primary_hover": "#1D4ED8",
        "success": "#16A34A",          # Vert
        "success_bg": "#DCFCE7",
        "warning": "#D97706",          # Orange
        "warning_bg": "#FEF3C7",
        "danger": "#DC2626",           # Rouge
        "danger_bg": "#FEE2E2",
        "locked": "#7C3AED",           # Violet
        "locked_bg": "#EDE9FE",
        "accent": "#0284C7",           # Cyan
        "nav_bg": "#FFFFFF",           # Fond de la barre d'onglets
        "nav_btn_bg": "#F1F5F9",       # Bouton onglet inactif
        "nav_btn_fg": "#475569",       # Texte onglet inactif
        "nav_active_bg": "#2563EB",    # Fond onglet actif
        "nav_active_fg": "#FFFFFF",    # Texte onglet actif
        "status_bar_bg": "#E2E8F0"
    },
    "dark": {
        "name": "dark",
        "bg_main": "#0B1120",          # Fond principal sombre profond (slate 950)
        "bg_card": "#1E293B",          # Fond des cartes (slate 800)
        "bg_card_alt": "#334155",      # Fond secondaire (slate 700)
        "border": "#475569",           # Bordures bien visibles (slate 600)
        "text_primary": "#F8FAFC",     # Texte principal blanc éclatant
        "text_secondary": "#CBD5E1",   # Libellés clairs (slate 300)
        "text_muted": "#94A3B8",       # Texte estompé clair (slate 400)
        "primary": "#3B82F6",          # Bleu clair vif
        "primary_hover": "#60A5FA",
        "success": "#22C55E",          # Vert vif
        "success_bg": "#14532D",       # Vert foncé
        "warning": "#F59E0B",          # Orange vif
        "warning_bg": "#78350F",       # Orange foncé
        "danger": "#EF4444",           # Rouge vif
        "danger_bg": "#7F1D1D",        # Rouge foncé
        "locked": "#A855F7",           # Violet clair vif
        "locked_bg": "#581C87",        # Violet foncé
        "accent": "#38BDF8",           # Cyan clair
        "nav_bg": "#1E293B",           # Fond de la barre d'onglets
        "nav_btn_bg": "#0B1120",       # Bouton onglet inactif sombre
        "nav_btn_fg": "#94A3B8",       # Texte onglet inactif
        "nav_active_bg": "#3B82F6",    # Fond onglet actif vif
        "nav_active_fg": "#FFFFFF",    # Texte onglet actif
        "status_bar_bg": "#1E293B"
    }
}

CURRENT_THEME = "light"
COLORS = dict(THEMES["light"])

FONTS = {
    "title": ("Segoe UI", 14, "bold"),
    "h2": ("Segoe UI", 11, "bold"),
    "body": ("Segoe UI", 10),
    "body_bold": ("Segoe UI", 10, "bold"),
    "small": ("Segoe UI", 9),
    "small_bold": ("Segoe UI", 9, "bold"),
    "mono": ("Consolas", 9),
    "mono_bold": ("Consolas", 10, "bold"),
    "mono_small": ("Consolas", 8),
    "metric": ("Segoe UI", 18, "bold")
}


def apply_theme(root: tk.Tk, theme_name: str = "light"):
    """Applique le thème graphique et met à jour les styles globaux TTK."""
    global CURRENT_THEME, COLORS
    CURRENT_THEME = theme_name if theme_name in THEMES else "light"
    COLORS.clear()
    COLORS.update(THEMES[CURRENT_THEME])

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(bg=COLORS["bg_main"])

    # TTK Base
    style.configure(".", background=COLORS["bg_main"], foreground=COLORS["text_primary"], font=FONTS["body"])

    # Boutons
    style.configure(
        "Primary.TButton",
        background=COLORS["primary"],
        foreground="#FFFFFF",
        font=FONTS["body_bold"],
        padding=[14, 6],
        relief="flat"
    )
    style.map(
        "Primary.TButton",
        background=[("active", COLORS["primary_hover"]), ("disabled", COLORS["border"])]
    )

    style.configure(
        "Danger.TButton",
        background=COLORS["danger"],
        foreground="#FFFFFF",
        font=FONTS["body_bold"],
        padding=[14, 6],
        relief="flat"
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#B91C1C"), ("disabled", COLORS["border"])]
    )

    style.configure(
        "Secondary.TButton",
        background=COLORS["bg_card_alt"],
        foreground=COLORS["text_primary"],
        font=FONTS["body"],
        padding=[10, 5],
        relief="flat"
    )
    style.map(
        "Secondary.TButton",
        background=[("active", COLORS["border"])]
    )

    # Progressbar
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=COLORS["bg_card_alt"],
        background=COLORS["primary"],
        thickness=10
    )

    # Treeview (Tableaux)
    style.configure(
        "Treeview",
        background=COLORS["bg_card"],
        foreground=COLORS["text_primary"],
        fieldbackground=COLORS["bg_card"],
        rowheight=26,
        font=FONTS["small"]
    )
    style.configure(
        "Treeview.Heading",
        background=COLORS["bg_card_alt"],
        foreground=COLORS["text_primary"],
        font=FONTS["small_bold"],
        padding=[6, 4]
    )
    style.map(
        "Treeview",
        background=[("selected", COLORS["primary"])],
        foreground=[("selected", "#FFFFFF")]
    )

    # Checkbutton & Radiobutton TTK
    ind_bg = COLORS["bg_card_alt"] if CURRENT_THEME == "dark" else "#FFFFFF"

    style.configure(
        "TCheckbutton",
        background=COLORS["bg_card"],
        foreground=COLORS["text_primary"],
        indicatorbackground=ind_bg,
        indicatorforeground=COLORS["primary"],
        upperbordercolor=COLORS["border"],
        lowerbordercolor=COLORS["border"]
    )
    style.map(
        "TCheckbutton",
        background=[("active", COLORS["bg_card"])],
        indicatorbackground=[("pressed", COLORS["bg_card_alt"])]
    )

    style.configure(
        "Page.TCheckbutton",
        background=COLORS["bg_main"],
        foreground=COLORS["text_primary"],
        indicatorbackground=ind_bg,
        indicatorforeground=COLORS["primary"],
        upperbordercolor=COLORS["border"],
        lowerbordercolor=COLORS["border"]
    )
    style.map(
        "Page.TCheckbutton",
        background=[("active", COLORS["bg_main"])],
        indicatorbackground=[("pressed", COLORS["bg_card_alt"])]
    )

    style.configure(
        "TRadiobutton",
        background=COLORS["bg_card"],
        foreground=COLORS["text_primary"],
        indicatorbackground=ind_bg,
        indicatorforeground=COLORS["primary"],
        upperbordercolor=COLORS["border"],
        lowerbordercolor=COLORS["border"]
    )
    style.map(
        "TRadiobutton",
        background=[("active", COLORS["bg_card"])],
        indicatorbackground=[("pressed", COLORS["bg_card_alt"])]
    )

    # Champs de saisie texte (Entry) : texte noir (#0F172A) sur fond blanc (#FFFFFF) conservé en permanence
    style.configure(
        "TEntry",
        fieldbackground="#FFFFFF",
        foreground="#0F172A",
        insertcolor="#0F172A",
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        padding=[6, 4]
    )
    style.map(
        "TEntry",
        fieldbackground=[("active", "#FFFFFF"), ("disabled", "#F1F5F9")],
        foreground=[("active", "#0F172A"), ("disabled", "#64748B")]
    )

    # Champs numériques (Spinbox) : texte noir, fond blanc, boutons et flèches haut/bas ultra-visibles
    style.configure(
        "TSpinbox",
        fieldbackground="#FFFFFF",
        foreground="#0F172A",
        insertcolor="#0F172A",
        background="#E2E8F0",
        arrowcolor="#0F172A",
        arrowsize=11,
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        padding=[4, 3]
    )
    style.map(
        "TSpinbox",
        fieldbackground=[("active", "#FFFFFF"), ("disabled", "#F1F5F9")],
        foreground=[("active", "#0F172A"), ("disabled", "#64748B")],
        background=[("active", "#CBD5E1"), ("pressed", "#94A3B8")],
        arrowcolor=[("active", "#0F172A"), ("pressed", "#0F172A")]
    )

    # Listes déroulantes (Combobox) : texte noir sur fond blanc et flèche visible
    style.configure(
        "TCombobox",
        fieldbackground="#FFFFFF",
        foreground="#0F172A",
        insertcolor="#0F172A",
        background="#E2E8F0",
        arrowcolor="#0F172A",
        arrowsize=11,
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        padding=[6, 4]
    )
    style.map(
        "TCombobox",
        fieldbackground=[("active", "#FFFFFF"), ("disabled", "#F1F5F9")],
        foreground=[("active", "#0F172A"), ("disabled", "#64748B")],
        background=[("active", "#CBD5E1")],
        arrowcolor=[("active", "#0F172A")]
    )

    # Ascenseurs (Scrollbars) : flèches haut/bas et curseur très contrastés et visibles
    if CURRENT_THEME == "dark":
        sb_bg = "#334155"         # Curseur slate 700 bien visible
        sb_trough = "#0B1120"     # Gorge slate 950
        sb_arrow = "#F8FAFC"      # Flèches blanches éclatantes
        sb_active = "#3B82F6"     # Bleu vif au survol
        sb_border = "#475569"     # Bordure
    else:
        sb_bg = "#CBD5E1"         # Curseur slate 300
        sb_trough = "#F1F5F9"     # Gorge slate 100
        sb_arrow = "#0F172A"      # Flèches noires bien nettes
        sb_active = "#2563EB"     # Bleu au survol
        sb_border = "#E2E8F0"

    for sb_name in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(
            sb_name,
            background=sb_bg,
            troughcolor=sb_trough,
            arrowcolor=sb_arrow,
            bordercolor=sb_border,
            lightcolor=sb_bg,
            darkcolor=sb_bg,
            arrowsize=12
        )
        style.map(
            sb_name,
            background=[("active", sb_active), ("disabled", sb_trough)],
            arrowcolor=[("active", "#FFFFFF")]
        )


def apply_theme_to_widget_tree(widget: tk.Widget, colors: Dict[str, Any]):
    """Parcourt récursivement l'arborescence des widgets pour appliquer les couleurs du thème."""
    if getattr(widget, "_is_accent", False):
        return

    w_type = widget.winfo_class()

    try:
        if w_type == "Frame":
            curr_bg = widget.cget("bg")
            accent_colors = {
                THEMES["light"]["primary"], THEMES["dark"]["primary"],
                THEMES["light"]["accent"], THEMES["dark"]["accent"],
                THEMES["light"]["success"], THEMES["dark"]["success"],
                THEMES["light"]["warning"], THEMES["dark"]["warning"],
                THEMES["light"]["danger"], THEMES["dark"]["danger"],
                THEMES["light"]["locked"], THEMES["dark"]["locked"],
            }
            if curr_bg in accent_colors:
                return

            if curr_bg in (THEMES["light"]["bg_card"], THEMES["dark"]["bg_card"]):
                widget.configure(bg=colors["bg_card"])
                if widget.cget("highlightbackground"):
                    widget.configure(highlightbackground=colors["border"])
            elif curr_bg in (THEMES["light"]["bg_card_alt"], THEMES["dark"]["bg_card_alt"]):
                widget.configure(bg=colors["bg_card_alt"])
            elif curr_bg in (THEMES["light"]["status_bar_bg"], THEMES["dark"]["status_bar_bg"]):
                widget.configure(bg=colors["status_bar_bg"])
            else:
                widget.configure(bg=colors["bg_main"])

        elif w_type == "Label":
            curr_bg = widget.cget("bg")
            curr_fg = widget.cget("fg")

            # Ne pas écraser les couleurs d'alerte spécifiques (vert/rouge/orange)
            if curr_fg in (THEMES["light"]["primary"], THEMES["dark"]["primary"]):
                widget.configure(fg=colors["primary"])
            elif curr_fg in (THEMES["light"]["success"], THEMES["dark"]["success"]):
                widget.configure(fg=colors["success"])
            elif curr_fg in (THEMES["light"]["danger"], THEMES["dark"]["danger"]):
                widget.configure(fg=colors["danger"])
            elif curr_fg in (THEMES["light"]["warning"], THEMES["dark"]["warning"]):
                widget.configure(fg=colors["warning"])
            elif curr_fg in (THEMES["light"]["locked"], THEMES["dark"]["locked"]):
                widget.configure(fg=colors["locked"])
            elif curr_fg in (THEMES["light"]["text_secondary"], THEMES["dark"]["text_secondary"]):
                widget.configure(fg=colors["text_secondary"])
            elif curr_fg in (THEMES["light"]["text_muted"], THEMES["dark"]["text_muted"]):
                widget.configure(fg=colors["text_muted"])
            else:
                widget.configure(fg=colors["text_primary"])

            if curr_bg in (THEMES["light"]["bg_card"], THEMES["dark"]["bg_card"]):
                widget.configure(bg=colors["bg_card"])
            elif curr_bg in (THEMES["light"]["bg_main"], THEMES["dark"]["bg_main"]):
                widget.configure(bg=colors["bg_main"])
            elif curr_bg in (THEMES["light"]["status_bar_bg"], THEMES["dark"]["status_bar_bg"]):
                widget.configure(bg=colors["status_bar_bg"])

        elif w_type == "Labelframe":
            widget.configure(bg=colors["bg_card"], fg=colors["text_primary"])

        elif w_type == "Listbox":
            widget.configure(
                bg=colors["bg_card"],
                fg=colors["text_primary"],
                highlightbackground=colors["border"],
                selectbackground=colors["primary"],
                selectforeground="#FFFFFF"
            )

        elif w_type == "Canvas":
            widget.configure(bg=colors["bg_card"])

        elif w_type in ("Entry", "TEntry"):
            try:
                widget.configure(bg="#FFFFFF", fg="#0F172A", insertbackground="#0F172A")
            except Exception:
                pass

        elif w_type in ("Spinbox", "TSpinbox"):
            try:
                widget.configure(bg="#FFFFFF", fg="#0F172A", insertbackground="#0F172A", buttonbackground="#E2E8F0")
            except Exception:
                pass

    except Exception:
        pass

    # Récursion sur les enfants
    for child in widget.winfo_children():
        apply_theme_to_widget_tree(child, colors)
