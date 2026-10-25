"""Vue d'analyse et de détection des fichiers en doublon dans la base d'empreintes."""

import os
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Dict, List, Any, Tuple

from core.database import DatabaseManager
from core.models import FileRecord, AppConfig
from core.platform_utils import open_in_file_manager, send_file_to_trash
from core.i18n import tr, format_bytes
from ui.styles import COLORS, FONTS, apply_theme_to_widget_tree


def _format_size(bytes_val: int) -> str:
    """Formate une taille d'octets avec les unités localisées."""
    return format_bytes(bytes_val)


class DuplicatesView(tk.Frame):
    """Écran de détection des doublons condensé avec volet maître-détails redimensionnable."""

    def __init__(self, parent, db_manager: DatabaseManager, config: Optional[AppConfig] = None):
        super().__init__(parent, bg=COLORS["bg_main"], padx=16, pady=16)
        self.db_manager = db_manager
        self.config = config

        self.duplicate_groups: List[Dict[str, Any]] = []
        self.selected_group_index: Optional[int] = None
        self.max_display_groups: int = 500
        self._search_id: int = 0

        self._build_header_filters()
        self._build_paned_views()
        self._build_status_banner()

    def _build_header_filters(self):
        """Barre d'en-tête condensée alignée sur le design de la base d'empreintes."""
        self.filter_frame = tk.Frame(self, bg=COLORS["bg_main"])
        self.filter_frame.pack(fill="x", pady=(0, 10))

        self.title_lbl = tk.Label(
            self.filter_frame,
            text=tr("dup_title"),
            font=FONTS["title"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_main"]
        )
        self.title_lbl.pack(side="left")

        self.right_box = tk.Frame(self.filter_frame, bg=COLORS["bg_main"])
        self.right_box.pack(side="right")

        self.lbl_search = tk.Label(
            self.right_box,
            text=tr("dup_search_lbl"),
            font=FONTS["small_bold"],
            bg=COLORS["bg_main"],
            fg=COLORS["text_secondary"]
        )
        self.lbl_search.pack(side="left", padx=(0, 4))

        self.entry_search = ttk.Entry(self.right_box, width=18)
        self.entry_search.pack(side="left", padx=(0, 8))
        self.entry_search.bind("<Return>", lambda e: self.refresh_duplicates())

        # Options sous forme de cases à cocher compactes
        self.match_name_var = tk.BooleanVar(value=False)
        self.match_ext_var = tk.BooleanVar(value=False)
        self.match_mtime_var = tk.BooleanVar(value=False)

        self.chk_name = ttk.Checkbutton(
            self.right_box,
            text=tr("dup_opt_name"),
            variable=self.match_name_var,
            command=self.refresh_duplicates,
            style="Page.TCheckbutton"
        )
        self.chk_name.pack(side="left", padx=(0, 6))

        self.chk_ext = ttk.Checkbutton(
            self.right_box,
            text=tr("dup_opt_ext"),
            variable=self.match_ext_var,
            command=self.refresh_duplicates,
            style="Page.TCheckbutton"
        )
        self.chk_ext.pack(side="left", padx=(0, 6))

        self.chk_mtime = ttk.Checkbutton(
            self.right_box,
            text=tr("dup_opt_mtime"),
            variable=self.match_mtime_var,
            command=self.refresh_duplicates,
            style="Page.TCheckbutton"
        )
        self.chk_mtime.pack(side="left", padx=(0, 8))

        self.btn_refresh = ttk.Button(
            self.right_box,
            text=tr("dup_btn_refresh"),
            style="Secondary.TButton",
            command=self.refresh_duplicates
        )
        self.btn_refresh.pack(side="left")

    def _build_status_banner(self):
        """Bannière d'information indiquant le nombre de doublons et l'espace récupérable."""
        self.banner_frame = tk.Frame(self, bg=COLORS["bg_main"])
        self.banner_frame.pack(fill="x", side="bottom", pady=(6, 0))

        self.lbl_stats = tk.Label(
            self.banner_frame,
            text=tr("dup_no_duplicates"),
            font=FONTS["small_bold"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_main"],
            anchor="w"
        )
        self.lbl_stats.pack(side="left")

        # Indicateur de chargement / recherche en arrière-plan
        self.progress_loading = ttk.Progressbar(self.banner_frame, mode="indeterminate", length=140)

    def _build_paned_views(self):
        """Conteneur vertical scindé (PanedWindow) pour répartir naturellement la hauteur."""
        self.paned = ttk.PanedWindow(self, orient="vertical")
        self.paned.pack(fill="both", expand=True)

        # 1. Volet supérieur : Liste des groupes de doublons
        self.master_frame = tk.Frame(self.paned, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        self.paned.add(self.master_frame, weight=3)

        cols_master = ("name", "ext", "copies", "size", "wasted")
        self.tree_master = ttk.Treeview(self.master_frame, columns=cols_master, show="headings", selectmode="browse", height=7)

        self.tree_master.heading("name", text=tr("dup_col_name"))
        self.tree_master.heading("ext", text=tr("dup_col_ext"))
        self.tree_master.heading("copies", text=tr("dup_col_copies"))
        self.tree_master.heading("size", text=tr("dup_col_size"))
        self.tree_master.heading("wasted", text=tr("dup_col_wasted"))

        # Colonnes ajustées : Nom étirable, extension et copies compactes, tailles resserrées
        self.tree_master.column("name", width=380, minwidth=200, anchor="w", stretch=True)
        self.tree_master.column("ext", width=50, minwidth=40, anchor="center", stretch=False)
        self.tree_master.column("copies", width=55, minwidth=45, anchor="center", stretch=False)
        self.tree_master.column("size", width=85, minwidth=75, anchor="e", stretch=False)
        self.tree_master.column("wasted", width=105, minwidth=90, anchor="e", stretch=False)

        self.scroll_master = ttk.Scrollbar(self.master_frame, orient="vertical", command=self.tree_master.yview)
        self.tree_master.configure(yscrollcommand=self.scroll_master.set)

        self.tree_master.pack(side="left", fill="both", expand=True)
        self.scroll_master.pack(side="right", fill="y")
        self.tree_master.bind("<<TreeviewSelect>>", self._on_group_selected)

        # 2. Volet inférieur : Détails des fichiers du groupe sélectionné
        self.detail_frame = tk.Frame(self.paned, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1, padx=10, pady=8)
        self.paned.add(self.detail_frame, weight=2)

        # En-tête des détails avec l'empreinte au-dessus du tableau
        self.detail_header_bar = tk.Frame(self.detail_frame, bg=COLORS["bg_card"])
        self.detail_header_bar.pack(fill="x", pady=(0, 6))

        self.lbl_detail_summary = tk.Label(
            self.detail_header_bar,
            text="",
            font=FONTS["body_bold"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_card"],
            anchor="w"
        )
        self.lbl_detail_summary.pack(side="left")

        self.btn_delete_copy = ttk.Button(
            self.detail_header_bar,
            text=tr("dup_delete_copy"),
            style="Danger.TButton",
            command=self._delete_selected_copy,
            state="disabled"
        )
        self.btn_delete_copy.pack(side="right")

        self.lbl_detail_hash = tk.Label(
            self.detail_frame,
            text="",
            font=FONTS["mono"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"],
            anchor="w"
        )
        self.lbl_detail_hash.pack(fill="x", pady=(0, 6))

        # Tableau des copies
        cols_det = ("path", "size", "mtime", "status")
        self.tree_details = ttk.Treeview(self.detail_frame, columns=cols_det, show="headings", selectmode="browse", height=4)

        self.tree_details.heading("path", text=tr("col_path"))
        self.tree_details.heading("size", text=tr("col_size"))
        self.tree_details.heading("mtime", text=tr("col_mtime"))
        self.tree_details.heading("status", text=tr("col_status"))

        self.tree_details.column("path", width=520, minwidth=250, anchor="w", stretch=True)
        self.tree_details.column("size", width=85, minwidth=75, anchor="e", stretch=False)
        self.tree_details.column("mtime", width=130, minwidth=110, anchor="center", stretch=False)
        self.tree_details.column("status", width=80, minwidth=70, anchor="center", stretch=False)

        self.scroll_details = ttk.Scrollbar(self.detail_frame, orient="vertical", command=self.tree_details.yview)
        self.tree_details.configure(yscrollcommand=self.scroll_details.set)

        self.tree_details.pack(side="left", fill="both", expand=True)
        self.scroll_details.pack(side="right", fill="y")

        self.tree_details.bind("<Button-3>", self._on_tree_details_context_menu)
        self.tree_details.bind("<Double-Button-1>", self._on_double_click_detail)
        self.tree_details.bind("<<TreeviewSelect>>", self._on_detail_selected)

    def refresh_duplicates(self):
        """Analyse et regroupe les doublons d'après les critères actifs en tâche de fond (non bloquant)."""
        search_filter = self.entry_search.get().strip().lower()
        match_name = self.match_name_var.get()
        match_ext = self.match_ext_var.get()
        match_mtime = self.match_mtime_var.get()

        self._search_id += 1
        current_id = self._search_id

        # Filtrage par emplacements activés (dossiers/disques actifs)
        enabled_target_ids: Optional[List[str]] = None
        total_targets = 0
        if self.config and hasattr(self.config, "targets") and self.config.targets:
            total_targets = len(self.config.targets)
            enabled_target_ids = [t.id for t in self.config.targets if t.enabled]
            if not enabled_target_ids:
                # Tous les emplacements configurés sont désactivés : aucun doublon à afficher
                self.duplicate_groups = []
                for item in self.tree_master.get_children():
                    self.tree_master.delete(item)
                self._clear_details()
                self.lbl_stats.config(
                    text=tr("dup_no_enabled_targets"),
                    fg=COLORS["text_secondary"]
                )
                return

        # Affichage immédiat de l'indicateur de recherche en arrière-plan
        self.btn_refresh.config(state="disabled")
        self.lbl_stats.config(text=tr("dup_searching"), fg=COLORS["primary"])
        self.progress_loading.pack(side="right", padx=(8, 0))
        self.progress_loading.start(10)

        def worker():
            try:
                raw_records = self.db_manager.get_duplicate_records(target_ids=enabled_target_ids)
                grouped: Dict[Tuple, List[FileRecord]] = {}

                for r in raw_records:
                    base_name = os.path.basename(r.path)
                    _, ext = os.path.splitext(base_name)

                    key_parts = [r.hash_value, r.size]
                    if match_name:
                        key_parts.append(base_name.lower())
                    if match_ext:
                        key_parts.append(ext.lower())
                    if match_mtime:
                        key_parts.append(int(r.mtime))

                    key = tuple(key_parts)
                    if key not in grouped:
                        grouped[key] = []
                    grouped[key].append(r)

                valid_groups: List[Dict[str, Any]] = []
                total_wasted_bytes = 0
                total_duplicate_files = 0

                for key, recs in grouped.items():
                    if len(recs) < 2:
                        continue

                    if search_filter:
                        if not any(search_filter in r.path.lower() for r in recs):
                            continue

                    unit_size = recs[0].size
                    count = len(recs)
                    wasted = unit_size * (count - 1)
                    first_name = os.path.basename(recs[0].path)
                    _, first_ext = os.path.splitext(first_name)

                    total_wasted_bytes += wasted
                    total_duplicate_files += (count - 1)

                    valid_groups.append({
                        "wasted": wasted,
                        "unit_size": unit_size,
                        "count": count,
                        "name": first_name,
                        "ext": first_ext or "-",
                        "hash": recs[0].hash_value,
                        "algo": recs[0].hash_algo,
                        "records": recs
                    })

                # Tri du plus gros au plus petit en terme d'espace doublonné
                valid_groups.sort(key=lambda g: (g["wasted"], g["unit_size"]), reverse=True)
                if len(valid_groups) > self.max_display_groups:
                    valid_groups = valid_groups[:self.max_display_groups]

                scope_str = ""
                if enabled_target_ids is not None and total_targets > len(enabled_target_ids):
                    scope_str = tr("dup_target_scope", len(enabled_target_ids), total_targets)

                self.after(0, lambda: self._apply_duplicate_results(
                    current_id, valid_groups, total_wasted_bytes, total_duplicate_files, scope_str
                ))
            except Exception as e:
                from core.logger import logger
                logger.error("Erreur analyse doublons", str(e))
                self.after(0, lambda: self._on_duplicate_error(current_id, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_duplicate_error(self, search_id: int, err_msg: str):
        if search_id != self._search_id:
            return
        self.progress_loading.stop()
        self.progress_loading.pack_forget()
        self.btn_refresh.config(state="normal")
        self.lbl_stats.config(text=f"Erreur lors de la recherche : {err_msg}", fg=COLORS["danger"])

    def _apply_duplicate_results(
        self,
        search_id: int,
        valid_groups: List[Dict[str, Any]],
        total_wasted_bytes: int,
        total_duplicate_files: int,
        scope_str: str
    ):
        if search_id != self._search_id:
            return

        self.progress_loading.stop()
        self.progress_loading.pack_forget()
        self.btn_refresh.config(state="normal")
        self.duplicate_groups = valid_groups

        # Mise à jour bannière
        num_groups = len(valid_groups)
        if num_groups == 0:
            self.lbl_stats.config(
                text=tr("dup_no_duplicates") + scope_str,
                fg=COLORS["text_secondary"]
            )
        else:
            wasted_str = _format_size(total_wasted_bytes)
            self.lbl_stats.config(
                text=tr("dup_stats", num_groups, total_duplicate_files, wasted_str) + scope_str,
                fg=COLORS["warning"] if total_wasted_bytes > 0 else COLORS["success"]
            )

        # Remplissage du tableau maître
        for item in self.tree_master.get_children():
            self.tree_master.delete(item)

        for idx, grp in enumerate(valid_groups):
            self.tree_master.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    grp["name"],
                    grp["ext"],
                    str(grp["count"]),
                    _format_size(grp["unit_size"]),
                    _format_size(grp["wasted"])
                )
            )

        self._clear_details()
        if valid_groups:
            self.tree_master.selection_set("0")
            self.tree_master.focus("0")
            self._display_group_details(0)

    def _clear_details(self):
        for item in self.tree_details.get_children():
            self.tree_details.delete(item)
        self.lbl_detail_summary.config(text="")
        self.lbl_detail_hash.config(text="")
        self.btn_delete_copy.config(state="disabled")
        self.selected_group_index = None

    def _on_group_selected(self, event):
        selection = self.tree_master.selection()
        if not selection:
            return
        try:
            idx = int(selection[0])
            self._display_group_details(idx)
        except (ValueError, IndexError):
            pass

    def _display_group_details(self, group_idx: int):
        if group_idx < 0 or group_idx >= len(self.duplicate_groups):
            return

        self.selected_group_index = group_idx
        grp = self.duplicate_groups[group_idx]
        recs: List[FileRecord] = grp["records"]

        self.lbl_detail_summary.config(
            text=tr("dup_detail_header", grp["count"], _format_size(grp["unit_size"]), _format_size(grp["wasted"]))
        )
        self.lbl_detail_hash.config(
            text=tr("dup_detail_hash", grp["algo"], grp["hash"])
        )

        for item in self.tree_details.get_children():
            self.tree_details.delete(item)

        for i, r in enumerate(recs):
            mtime_str = datetime.fromtimestamp(r.mtime).strftime("%Y-%m-%d %H:%M") if r.mtime > 0 else "-"
            status_val = r.status.value if hasattr(r.status, "value") else str(r.status)

            self.tree_details.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    r.path,
                    _format_size(r.size),
                    mtime_str,
                    status_val
                )
            )

        self.btn_delete_copy.config(state="disabled")

    def _on_detail_selected(self, event):
        selection = self.tree_details.selection()
        if selection:
            self.btn_delete_copy.config(state="normal")
        else:
            self.btn_delete_copy.config(state="disabled")

    def _ask_deletion_mode(self, file_path: str) -> Optional[str]:
        """Affiche un dialogue modal invitant l'utilisateur à choisir entre Corbeille et Suppression définitive."""
        result = {"mode": None}

        dlg_w = 460
        dlg_h = 195

        dialog = tk.Toplevel(self)
        dialog.withdraw()  # Masque immédiatement la fenêtre pour éliminer tout clignotement
        dialog.title(tr("dup_delete_dialog_title"))
        dialog.minsize(420, 180)
        dialog.resizable(True, True)
        dialog.transient(self.winfo_toplevel())

        theme_name = getattr(self.config, "theme", "light") if self.config else "light"
        bg_card = "#111827" if theme_name == "dark" else "#FFFFFF"
        bg_card_alt = "#1E293B" if theme_name == "dark" else "#F1F5F9"
        fg_text = "#F8FAFC" if theme_name == "dark" else "#0F172A"
        fg_sub = "#94A3B8" if theme_name == "dark" else "#64748B"

        dialog.configure(bg=bg_card)

        # Calcul instantané de la position centrée par rapport à la fenêtre parente
        try:
            parent = self.winfo_toplevel()
            parent_x = parent.winfo_rootx()
            parent_y = parent.winfo_rooty()
            parent_w = parent.winfo_width()
            parent_h = parent.winfo_height()
            pos_x = parent_x + max(0, (parent_w - dlg_w) // 2)
            pos_y = parent_y + max(0, (parent_h - dlg_h) // 2)
            dialog.geometry(f"{dlg_w}x{dlg_h}+{pos_x}+{pos_y}")
        except Exception:
            dialog.geometry(f"{dlg_w}x{dlg_h}")

        def choose(mode):
            result["mode"] = mode
            dialog.destroy()

        # 1. Barre de boutons ancrée en bas en PREMIER (visibilité garantie à 100%)
        btn_box = tk.Frame(dialog, bg=bg_card)
        btn_box.pack(side="bottom", fill="x", padx=16, pady=(6, 12))

        # 3 boutons : Supprimer (définitif), Corbeille, Annuler
        btn_cancel = ttk.Button(
            btn_box,
            text=tr("btn_cancel"),
            style="Secondary.TButton",
            command=lambda: choose(None)
        )
        btn_cancel.pack(side="right", padx=(6, 0))

        btn_trash = ttk.Button(
            btn_box,
            text=tr("dup_btn_trash"),
            style="Secondary.TButton",
            command=lambda: choose("trash")
        )
        btn_trash.pack(side="right", padx=(6, 0))

        btn_delete_perm = ttk.Button(
            btn_box,
            text=tr("dup_btn_delete_perm"),
            style="Danger.TButton",
            command=lambda: choose("permanent")
        )
        btn_delete_perm.pack(side="right")

        # 2. Zone de contenu au-dessus
        content = tk.Frame(dialog, bg=bg_card)
        content.pack(side="top", fill="both", expand=True, padx=16, pady=(12, 0))

        lbl_prompt = tk.Label(
            content,
            text=tr("dup_delete_dialog_prompt"),
            font=FONTS["body_bold"],
            fg=fg_text,
            bg=bg_card,
            anchor="w"
        )
        lbl_prompt.pack(fill="x", pady=(0, 4))

        # Boîte de mise en valeur pour le chemin du fichier
        path_box = tk.Frame(content, bg=bg_card_alt, padx=8, pady=5)
        path_box.pack(fill="x", pady=(0, 6))

        lbl_path = tk.Label(
            path_box,
            text=file_path,
            font=FONTS.get("mono_small", ("Consolas", 8)),
            fg=fg_text,
            bg=bg_card_alt,
            anchor="w",
            wraplength=410,
            justify="left"
        )
        lbl_path.pack(fill="x")

        lbl_desc = tk.Label(
            content,
            text=tr("dup_delete_dialog_desc"),
            font=FONTS["small"],
            fg=fg_sub,
            bg=bg_card,
            anchor="w",
            wraplength=410,
            justify="left"
        )
        lbl_desc.pack(fill="x")

        dialog.bind("<Escape>", lambda e: choose(None))
        dialog.deiconify()  # Affiche la fenêtre directement centrée au bon endroit
        dialog.grab_set()
        dialog.focus_force()
        dialog.wait_window()
        return result["mode"]

    def _delete_selected_copy(self):
        selection = self.tree_details.selection()
        if not selection or self.selected_group_index is None:
            return

        item_idx = int(selection[0])
        group = self.duplicate_groups[self.selected_group_index]
        record: FileRecord = group["records"][item_idx]

        mode = self._ask_deletion_mode(record.path)
        if mode is None:
            return

        # 1. Supprimer le fichier physique (Corbeille ou Définitive)
        file_deleted = False
        try:
            if os.path.exists(record.path):
                if mode == "trash":
                    file_deleted = send_file_to_trash(record.path)
                    if not file_deleted:
                        if messagebox.askyesno(
                            tr("dup_delete_confirm_title"),
                            tr("dup_trash_failed_fallback_prompt"),
                            icon="warning"
                        ):
                            os.remove(record.path)
                            file_deleted = True
                        else:
                            return
                else:
                    os.remove(record.path)
                    file_deleted = True
            else:
                file_deleted = True  # Fichier déjà absent
        except Exception as e:
            messagebox.showerror(tr("dup_delete_error_title"), tr("dup_delete_error_msg", str(e)))
            return

        # 2. Supprimer l'enregistrement de la base SQLite et de ses miroirs
        self.db_manager.delete_record(record)

        # 3. Retirer de la mémoire et réévaluer le groupe
        group["records"].pop(item_idx)
        if len(group["records"]) < 2:
            self.duplicate_groups.pop(self.selected_group_index)

        # 4. Actualiser complètement l'affichage
        self.refresh_duplicates()

    def _on_double_click_detail(self, event):
        selection = self.tree_details.selection()
        if not selection or self.selected_group_index is None:
            return
        try:
            item_idx = int(selection[0])
            record = self.duplicate_groups[self.selected_group_index]["records"][item_idx]
            open_in_file_manager(record.path)
        except Exception:
            pass

    def _on_tree_details_context_menu(self, event):
        row_id = self.tree_details.identify_row(event.y)
        if not row_id or self.selected_group_index is None:
            return

        self.tree_details.selection_set(row_id)
        self.btn_delete_copy.config(state="normal")
        try:
            item_idx = int(row_id)
            record = self.duplicate_groups[self.selected_group_index]["records"][item_idx]

            menu = tk.Menu(self, tearoff=0)
            menu.add_command(
                label=tr("ctx_open_folder"),
                command=lambda: open_in_file_manager(record.path)
            )
            menu.add_command(
                label=tr("ctx_copy_path"),
                command=lambda: self._copy_to_clipboard(record.path)
            )
            menu.add_command(
                label=tr("dup_copy_hash"),
                command=lambda: self._copy_to_clipboard(record.hash_value)
            )
            menu.add_separator()
            menu.add_command(
                label=tr("dup_delete_copy"),
                command=self._delete_selected_copy
            )
            menu.post(event.x_root, event.y_root)
        except Exception:
            pass

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    def update_ui_language(self):
        """Met à jour dynamiquement tous les libellés de la vue lors d'un changement de langue."""
        self.title_lbl.config(text=tr("dup_title"))
        self.lbl_search.config(text=tr("dup_search_lbl"))
        self.chk_name.config(text=tr("dup_opt_name"))
        self.chk_ext.config(text=tr("dup_opt_ext"))
        self.chk_mtime.config(text=tr("dup_opt_mtime"))
        self.btn_refresh.config(text=tr("dup_btn_refresh"))

        self.tree_master.heading("name", text=tr("dup_col_name"))
        self.tree_master.heading("ext", text=tr("dup_col_ext"))
        self.tree_master.heading("copies", text=tr("dup_col_copies"))
        self.tree_master.heading("size", text=tr("dup_col_size"))
        self.tree_master.heading("wasted", text=tr("dup_col_wasted"))

        self.btn_delete_copy.config(text=tr("dup_delete_copy"))

        self.tree_details.heading("path", text=tr("dup_col_path"))
        self.tree_details.heading("size", text=tr("dup_col_size"))
        self.tree_details.heading("mtime", text=tr("dup_col_mtime"))
        self.tree_details.heading("status", text=tr("dup_col_status"))

        if self.selected_group_index is not None and 0 <= self.selected_group_index < len(self.duplicate_groups):
            self._display_group_details(self.selected_group_index)
        elif not self.duplicate_groups:
            enabled_count = sum(1 for t in self.config.targets if t.enabled) if self.config and hasattr(self.config, "targets") and self.config.targets else 1
            if self.config and hasattr(self.config, "targets") and self.config.targets and enabled_count == 0:
                self.lbl_stats.config(text=tr("dup_no_enabled_targets"))
            else:
                self.lbl_stats.config(text=tr("dup_no_duplicates"))

    def apply_theme_colors(self, colors: Dict[str, Any]):
        """Met à jour les couleurs pour le Mode Sombre / Mode Clair."""
        self.configure(bg=colors["bg_main"])
        self.master_frame.configure(bg=colors["bg_card"], highlightbackground=colors["border"])
        self.detail_frame.configure(bg=colors["bg_card"], highlightbackground=colors["border"])
        apply_theme_to_widget_tree(self, colors)
