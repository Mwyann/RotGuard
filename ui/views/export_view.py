"""Vue d'exportation des données de la base vers CSV et formats de checksum avec internationalisation."""

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional, Dict, Any

from core.database import DatabaseManager
from core.exporter import export_to_csv, export_to_checksum_file
from core.i18n import tr
from ui.styles import COLORS, FONTS, apply_theme_to_widget_tree


class ExportView(tk.Frame):
    """Écran de génération d'exports CSV et fichiers de checksum."""

    def __init__(self, parent, db_manager: DatabaseManager):
        super().__init__(parent, bg=COLORS["bg_main"], padx=16, pady=16)
        self.db_manager = db_manager

        self._build_header()
        self._build_options()
        self._build_action_button()

    def _build_header(self):
        self.title_lbl = tk.Label(
            self,
            text=tr("export_title"),
            font=FONTS["title"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_main"]
        )
        self.title_lbl.pack(anchor="w", pady=(0, 4))

        self.desc_lbl = tk.Label(
            self,
            text=tr("export_desc"),
            font=FONTS["body"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_main"]
        )
        self.desc_lbl.pack(anchor="w", pady=(0, 16))

    def _build_options(self):
        self.container = tk.Frame(self, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1, padx=16, pady=16)
        self.container.pack(fill="x", pady=(0, 16))

        # 1. Format
        self.lbl_fmt = tk.Label(self.container, text=tr("export_format_lbl"), font=FONTS["body_bold"], bg=COLORS["bg_card"], fg=COLORS["text_primary"])
        self.lbl_fmt.pack(anchor="w", pady=(0, 4))

        self.format_var = tk.StringVar(value="CSV")
        self.rb_csv = ttk.Radiobutton(self.container, text=tr("export_csv_opt"), value="CSV", variable=self.format_var)
        self.rb_csv.pack(anchor="w", pady=2)
        self.rb_chk = ttk.Radiobutton(self.container, text=tr("export_chk_opt"), value="CHECKSUM", variable=self.format_var)
        self.rb_chk.pack(anchor="w", pady=2)

        # 2. Filtre de statut
        self.lbl_flt = tk.Label(self.container, text=tr("export_filter_lbl"), font=FONTS["body_bold"], bg=COLORS["bg_card"], fg=COLORS["text_primary"])
        self.lbl_flt.pack(anchor="w", pady=(12, 4))

        self.filter_var = tk.StringVar(value="TOUS")
        self.rb_flt_all = ttk.Radiobutton(self.container, text=tr("export_flt_all"), value="TOUS", variable=self.filter_var)
        self.rb_flt_all.pack(anchor="w", pady=2)

        self.rb_flt_corrupted = ttk.Radiobutton(self.container, text=tr("export_flt_corrupted"), value="CORRUPT", variable=self.filter_var)
        self.rb_flt_corrupted.pack(anchor="w", pady=2)

        self.rb_flt_locked = ttk.Radiobutton(self.container, text=tr("export_flt_locked"), value="LOCKED", variable=self.filter_var)
        self.rb_flt_locked.pack(anchor="w", pady=2)

        self.rb_flt_mod = ttk.Radiobutton(self.container, text=tr("export_flt_mod"), value="MODIFIED", variable=self.filter_var)
        self.rb_flt_mod.pack(anchor="w", pady=2)

        self.rb_flt_ok = ttk.Radiobutton(self.container, text=tr("export_flt_ok"), value="OK", variable=self.filter_var)
        self.rb_flt_ok.pack(anchor="w", pady=2)

    def _build_action_button(self):
        self.btn_box = tk.Frame(self, bg=COLORS["bg_main"])
        self.btn_box.pack(fill="x")

        self.btn_export = ttk.Button(
            self.btn_box,
            text=tr("btn_do_export"),
            style="Primary.TButton",
            command=self._do_export
        )
        self.btn_export.pack(side="left")

    def update_ui_language(self):
        """Met à jour instantanément les textes de la vue Export lors d'un changement de langue."""
        self.title_lbl.config(text=tr("export_title"))
        self.desc_lbl.config(text=tr("export_desc"))
        self.lbl_fmt.config(text=tr("export_format_lbl"))
        self.rb_csv.config(text=tr("export_csv_opt"))
        self.rb_chk.config(text=tr("export_chk_opt"))
        self.lbl_flt.config(text=tr("export_filter_lbl"))
        self.rb_flt_all.config(text=tr("export_flt_all"))
        self.rb_flt_corrupted.config(text=tr("export_flt_corrupted"))
        self.rb_flt_locked.config(text=tr("export_flt_locked"))
        self.rb_flt_mod.config(text=tr("export_flt_mod"))
        self.rb_flt_ok.config(text=tr("export_flt_ok"))
        self.btn_export.config(text=tr("btn_do_export"))

    def apply_theme_colors(self, colors: Dict[str, Any]):
        self.configure(bg=colors["bg_main"])
        apply_theme_to_widget_tree(self, colors)

    def _do_export(self):
        fmt = self.format_var.get()
        filter_status = self.filter_var.get()

        if fmt == "CSV":
            chosen = filedialog.asksaveasfilename(
                title=tr("export_csv_dialog_title"),
                defaultextension=".csv",
                filetypes=[("Fichier CSV", "*.csv"), ("Tous les fichiers", "*.*")]
            )
            if not chosen:
                return

            self.btn_export.config(state="disabled", text=tr("btn_exporting"))

            def worker_csv():
                try:
                    count, duration = export_to_csv(
                        self.db_manager,
                        output_path=chosen,
                        status_filter=filter_status
                    )
                    def on_done():
                        self.btn_export.config(state="normal", text=tr("btn_do_export"))
                        messagebox.showinfo(tr("export_success_title"), tr("export_success_msg", chosen, count))
                    self.after(0, on_done)
                except Exception as e:
                    def on_err():
                        self.btn_export.config(state="normal", text=tr("btn_do_export"))
                        messagebox.showerror(tr("export_error_title"), tr("export_error_msg", str(e)))
                    self.after(0, on_err)

            threading.Thread(target=worker_csv, daemon=True).start()

        else:
            chosen = filedialog.asksaveasfilename(
                title=tr("export_chk_dialog_title"),
                defaultextension=".txt",
                filetypes=[("Fichier texte", "*.txt;*.md5;*.sha256;*.b2"), ("Tous les fichiers", "*.*")]
            )
            if not chosen:
                return

            self.btn_export.config(state="disabled", text=tr("btn_exporting"))

            def worker_chk():
                try:
                    count, duration = export_to_checksum_file(
                        self.db_manager,
                        output_path=chosen,
                        status_filter=filter_status
                    )
                    def on_done():
                        self.btn_export.config(state="normal", text=tr("btn_do_export"))
                        messagebox.showinfo(tr("export_success_title"), tr("export_success_msg", chosen, count))
                    self.after(0, on_done)
                except Exception as e:
                    def on_err():
                        self.btn_export.config(state="normal", text=tr("btn_do_export"))
                        messagebox.showerror(tr("export_error_title"), tr("export_error_msg", str(e)))
                    self.after(0, on_err)

            threading.Thread(target=worker_chk, daemon=True).start()
