"""Composants visuels spécialisés pour l'interface RotGuard."""

import tkinter as tk
from tkinter import ttk
from typing import Optional
from core.i18n import tr
from ui.styles import COLORS, FONTS


class MetricCard(tk.Frame):
    """Carte affichant une métrique clé avec titre, valeur grand format et barre d'accent."""

    def __init__(
        self,
        parent,
        title: str,
        value: str = "0",
        accent_color: Optional[str] = None,
        subtitle: str = "",
        **kwargs
    ):
        self.accent_color = accent_color or COLORS["primary"]
        super().__init__(
            parent,
            bg=COLORS["bg_card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=12,
            pady=10,
            **kwargs
        )

        self.accent_bar = tk.Frame(self, bg=self.accent_color, height=3)
        self.accent_bar._is_accent = True
        self.accent_bar.pack(fill="x", side="top", pady=(0, 6))

        self.lbl_title = tk.Label(
            self,
            text=title,
            font=FONTS["small_bold"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"],
            anchor="w"
        )
        self.lbl_title.pack(fill="x")

        self.lbl_val = tk.Label(
            self,
            text=value,
            font=FONTS["metric"],
            fg=self.accent_color,
            bg=COLORS["bg_card"],
            anchor="w"
        )
        self.lbl_val._is_accent = True
        self.lbl_val.pack(fill="x", pady=(2, 0))

        self.lbl_sub = tk.Label(
            self,
            text=subtitle,
            font=FONTS["small"],
            fg=COLORS["text_muted"],
            bg=COLORS["bg_card"],
            anchor="w"
        )
        if subtitle:
            self.lbl_sub.pack(fill="x")

    def set_title(self, new_title: str):
        self.lbl_title.config(text=new_title)

    def set_value(self, new_value: str, subtitle: Optional[str] = None):
        self.lbl_val.config(text=new_value)
        if subtitle is not None:
            self.lbl_sub.config(text=subtitle)
            if not self.lbl_sub.winfo_ismapped():
                self.lbl_sub.pack(fill="x")

    def refresh_colors(self, new_bg: str, new_border: str, new_fg_title: str, new_fg_sub: str, new_accent: Optional[str] = None):
        if new_accent:
            self.accent_color = new_accent
        self.config(bg=new_bg, highlightbackground=new_border)
        self.accent_bar.config(bg=self.accent_color)
        self.lbl_title.config(bg=new_bg, fg=new_fg_title)
        self.lbl_val.config(bg=new_bg, fg=self.accent_color)
        self.lbl_sub.config(bg=new_bg, fg=new_fg_sub)


class StatusBadge(tk.Label):
    """Badge textuel stylisé selon le statut (OK, MODIFIED, CORRUPT, LOCKED)."""

    def __init__(self, parent, status: str, **kwargs):
        status_upper = status.upper()

        if status_upper == "OK":
            bg = COLORS["success_bg"]
            fg = COLORS["success"]
            text = tr("badge_ok")
        elif status_upper == "MODIFIED":
            bg = COLORS["warning_bg"]
            fg = COLORS["warning"]
            text = tr("badge_modified")
        elif status_upper == "CORRUPT":
            bg = COLORS["danger_bg"]
            fg = COLORS["danger"]
            text = tr("badge_corrupt")
        elif status_upper == "LOCKED":
            bg = COLORS["locked_bg"]
            fg = COLORS["locked"]
            text = tr("badge_locked")
        elif status_upper == "NEW":
            bg = "#0284C7" if COLORS.get("name") == "dark" else "#E0F2FE"
            fg = "#E0F2FE" if COLORS.get("name") == "dark" else "#0369A1"
            text = tr("badge_new")
        elif status_upper == "MISSING":
            bg = COLORS["bg_card_alt"]
            fg = COLORS["text_secondary"]
            text = tr("badge_missing")
        else:
            bg = COLORS["bg_card_alt"]
            fg = COLORS["text_secondary"]
            text = status

        super().__init__(
            parent,
            text=text,
            bg=bg,
            fg=fg,
            font=FONTS["small_bold"],
            padx=8,
            pady=2,
            relief="flat",
            **kwargs
        )
