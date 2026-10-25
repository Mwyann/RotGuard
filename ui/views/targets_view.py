"""Vue de gestion des dossiers et disques cibles."""

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable, Optional, Dict, Any

from core.models import TargetFolder, DiskType, AppConfig
from core.database import DatabaseManager
from core.disk_info import detect_disk_type, get_disk_space_info
from core.platform_utils import open_in_file_manager
from core.i18n import tr
from ui.styles import COLORS, FONTS, apply_theme_to_widget_tree


class TargetsView(tk.Frame):
    """Écran de configuration des dossiers et disques cibles."""

    def __init__(
        self,
        parent,
        config: AppConfig,
        db_manager: Optional[DatabaseManager] = None,
        on_config_changed: Optional[Callable[[], None]] = None
    ):
        super().__init__(parent, bg=COLORS["bg_main"], padx=16, pady=16)
        self.config = config
        self.db_manager = db_manager
        self.on_config_changed = on_config_changed
        self._space_cache: Dict[str, str] = {}
        self._refresh_req_id = 0

        self._build_header()
        self._build_treeview()
        self._build_buttons()
        self._build_context_menu()
        self._refresh_list()

    def _build_header(self):
        self.header_frame = tk.Frame(self, bg=COLORS["bg_main"])
        self.header_frame.pack(fill="x", pady=(0, 10))

        self.title_lbl = tk.Label(
            self.header_frame,
            text=tr("targets_title"),
            font=FONTS["title"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_main"]
        )
        self.title_lbl.pack(side="left")

    def _build_treeview(self):
        self.container = tk.Frame(self, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        self.container.pack(fill="both", expand=True, pady=(0, 12))

        columns = ("alias", "path", "disk_type", "workers", "buffer", "space", "status")
        self.tree = ttk.Treeview(self.container, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("alias", text=tr("col_target_alias"))
        self.tree.heading("path", text=tr("col_target_path"))
        self.tree.heading("disk_type", text=tr("col_target_disk"))
        self.tree.heading("workers", text=tr("col_target_workers"))
        self.tree.heading("buffer", text=tr("col_target_buffer"))
        self.tree.heading("space", text=tr("col_target_space"))
        self.tree.heading("status", text=tr("col_target_status"))

        self.tree.column("alias", width=140, anchor="w")
        self.tree.column("path", width=280, anchor="w")
        self.tree.column("disk_type", width=110, anchor="center")
        self.tree.column("workers", width=120, anchor="center")
        self.tree.column("buffer", width=90, anchor="center")
        self.tree.column("space", width=120, anchor="center")
        self.tree.column("status", width=70, anchor="center")

        self.scroll = ttk.Scrollbar(self.container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")

        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Double-1>", lambda e: self._edit_target())

    def _build_context_menu(self):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label=tr("btn_edit_target"), command=self._edit_target)
        self.context_menu.add_command(label=tr("btn_toggle_target"), command=self._toggle_target)
        self.context_menu.add_command(label=tr("ctx_open_folder"), command=self._open_in_explorer)
        self.context_menu.add_separator()
        self.context_menu.add_command(label=tr("btn_remove_target"), command=self._remove_target)

    def _on_right_click(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
            self.context_menu.post(event.x_root, event.y_root)

    def _open_in_explorer(self):
        idx = self._get_selected_index()
        if idx is None:
            return
        target = self.config.targets[idx]
        open_in_file_manager(target.path)

    def _build_buttons(self):
        self.btn_frame = tk.Frame(self, bg=COLORS["bg_main"])
        self.btn_frame.pack(fill="x")

        self.btn_add = ttk.Button(self.btn_frame, text=tr("btn_add_target"), style="Primary.TButton", command=self._add_target)
        self.btn_add.pack(side="left", padx=(0, 8))

        self.btn_edit = ttk.Button(self.btn_frame, text=tr("btn_edit_target"), style="Secondary.TButton", command=self._edit_target)
        self.btn_edit.pack(side="left", padx=(0, 8))

        self.btn_toggle = ttk.Button(self.btn_frame, text=tr("btn_toggle_target"), style="Secondary.TButton", command=self._toggle_target)
        self.btn_toggle.pack(side="left", padx=(0, 8))

        self.btn_remove = ttk.Button(self.btn_frame, text=tr("btn_remove_target"), style="Danger.TButton", command=self._remove_target)
        self.btn_remove.pack(side="right")

    def _browse_dir_into(self, entry: ttk.Entry):
        chosen = filedialog.askdirectory(title=tr("dlg_target_choose_folder"))
        if chosen:
            entry.delete(0, "end")
            entry.insert(0, os.path.normpath(chosen))


    def apply_theme_colors(self, colors: Dict[str, Any]):
        self.configure(bg=colors["bg_main"])
        apply_theme_to_widget_tree(self, colors)

    def _refresh_list(self, reselect_idx: Optional[int] = None):
        for item in self.tree.get_children():
            self.tree.delete(item)

        self._refresh_req_id += 1
        current_req = self._refresh_req_id

        for i, target in enumerate(self.config.targets):
            disk_type_val = target.disk_type.value if hasattr(target.disk_type, "value") else str(target.disk_type)
            if disk_type_val == "HDD":
                type_display = tr('target_media_hdd')
            elif disk_type_val == "SSD":
                type_display = tr('target_media_ssd')
            elif disk_type_val == "REMOVABLE":
                type_display = tr('target_media_removable')
            else:
                type_display = tr('target_media_unknown')

            space_str = self._space_cache.get(target.path, "Calcul...")
            buf_mb = round(target.buffer_size_bytes / (1024 * 1024), 1)
            status_str = f"✓ {tr('target_active')}" if target.enabled else f"✗ {tr('target_inactive')}"

            self.tree.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    target.alias,
                    target.path,
                    type_display,
                    f"{target.max_workers}",
                    f"{buf_mb} Mo",
                    space_str,
                    status_str
                )
            )

        if reselect_idx is not None and 0 <= reselect_idx < len(self.config.targets):
            self.tree.selection_set(str(reselect_idx))
            self.tree.focus(str(reselect_idx))

        # Résolution asynchrone du type de disque et de l'espace libre pour ne jamais bloquer l'UI
        targets_copy = list(self.config.targets)
        def bg_disk_info():
            for i, target in enumerate(targets_copy):
                # 1. Type de disque si inconnu
                disk_type_val = target.disk_type.value if hasattr(target.disk_type, "value") else str(target.disk_type)
                if disk_type_val == "UNKNOWN":
                    detected_type, recommended_workers = detect_disk_type(target.path)
                    if detected_type != DiskType.UNKNOWN:
                        target.disk_type = detected_type
                        if target.max_workers in (1, 4) or target.max_workers == 2:
                            target.max_workers = recommended_workers
                        try:
                            self.config.save_to_file()
                        except Exception:
                            pass

                # 2. Espace disque
                space_info = get_disk_space_info(target.path)
                s_str = tr("target_space_free", space_info['free_gb'], space_info['free_percent']) if space_info['total_gb'] > 0 else "N/A"
                self._space_cache[target.path] = s_str

                def update_row(idx=i, s=s_str, t=target):
                    if current_req != self._refresh_req_id:
                        return
                    iid = str(idx)
                    if self.tree.exists(iid):
                        disk_type_str = t.disk_type.value if hasattr(t.disk_type, "value") else str(t.disk_type)
                        if disk_type_str == "HDD":
                            td = tr('target_media_hdd')
                        elif disk_type_str == "SSD":
                            td = tr('target_media_ssd')
                        elif disk_type_str == "REMOVABLE":
                            td = tr('target_media_removable')
                        else:
                            td = tr('target_media_unknown')
                        buf = round(t.buffer_size_bytes / (1024 * 1024), 1)
                        st = f"✓ {tr('target_active')}" if t.enabled else f"✗ {tr('target_inactive')}"
                        self.tree.item(iid, values=(t.alias, t.path, td, f"{t.max_workers}", f"{buf} {tr('unit_mb')}", s, st))

                self.after(0, update_row)

        threading.Thread(target=bg_disk_info, daemon=True).start()

    def _add_target(self):
        folder_selected = filedialog.askdirectory(title=tr("dlg_target_select_folder"))
        if not folder_selected:
            return

        folder_selected = os.path.abspath(folder_selected)

        for t in self.config.targets:
            if t.path.lower() == folder_selected.lower():
                messagebox.showwarning(tr("target_exists_title"), tr("target_exists_msg"))
                return

        detected_type, recommended_workers = detect_disk_type(folder_selected)
        alias = os.path.basename(folder_selected.rstrip(os.sep)) or folder_selected

        new_target = TargetFolder(
            path=folder_selected,
            alias=alias,
            max_workers=recommended_workers,
            buffer_size_bytes=int(self.config.default_buffer_size_mb * 1024 * 1024),
            disk_type=detected_type,
            enabled=True
        )

        self.config.targets.append(new_target)
        self.config.save_to_file()
        new_idx = len(self.config.targets) - 1
        self._refresh_list(reselect_idx=new_idx)
        if self.on_config_changed:
            self.on_config_changed()

    def _get_selected_index(self) -> Optional[int]:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _edit_target(self):
        idx = self._get_selected_index()
        if idx is None:
            messagebox.showinfo(tr("target_selection_required_title"), tr("target_selection_required_msg"))
            return

        target = self.config.targets[idx]

        dialog = tk.Toplevel(self)
        dialog.withdraw()  # Élimine le clignotement / affichage en haut à gauche
        dialog.title(f"{tr('dlg_target_edit_title')} : {target.alias}")
        dialog.configure(bg=COLORS["bg_main"], padx=20, pady=20)
        dialog.transient(self)
        dialog.minsize(520, 420)
        dialog.resizable(True, True)

        tk.Label(dialog, text=tr("dlg_target_lbl_alias"), font=FONTS["small_bold"], bg=COLORS["bg_main"], fg=COLORS["text_primary"]).pack(anchor="w", pady=(0, 2))
        entry_alias = ttk.Entry(dialog, width=42)
        entry_alias.insert(0, target.alias)
        entry_alias.pack(fill="x", pady=(0, 10))

        tk.Label(dialog, text=tr("dlg_target_lbl_path"), font=FONTS["small_bold"], bg=COLORS["bg_main"], fg=COLORS["text_primary"]).pack(anchor="w", pady=(0, 2))
        row_p = tk.Frame(dialog, bg=COLORS["bg_main"])
        row_p.pack(fill="x", pady=(0, 10))
        entry_path = ttk.Entry(row_p)
        entry_path.insert(0, target.path)
        entry_path.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row_p, text=tr("dlg_target_btn_browse"), style="Secondary.TButton", command=lambda: self._browse_dir_into(entry_path)).pack(side="right")

        # Type de support physique avec détection matérielle
        tk.Label(dialog, text=f"{tr('col_target_disk')} :", font=FONTS["small_bold"], bg=COLORS["bg_main"], fg=COLORS["text_primary"]).pack(anchor="w", pady=(0, 2))
        row_media = tk.Frame(dialog, bg=COLORS["bg_main"])
        row_media.pack(fill="x", pady=(0, 10))

        media_options = [
            (DiskType.HDD, tr('target_media_hdd_opt')),
            (DiskType.SSD, tr('target_media_ssd_opt')),
            (DiskType.REMOVABLE, tr('target_media_removable')),
            (DiskType.UNKNOWN, tr('target_media_unknown'))
        ]
        media_labels = [label for _, label in media_options]
        combo_media = ttk.Combobox(row_media, values=media_labels, state="readonly")

        curr_type_str = target.disk_type.value if hasattr(target.disk_type, "value") else str(target.disk_type)
        sel_media_idx = 0
        for m_idx, (dt, _) in enumerate(media_options):
            if dt.value == curr_type_str:
                sel_media_idx = m_idx
                break
        combo_media.current(sel_media_idx)
        combo_media.pack(side="left", fill="x", expand=True, padx=(0, 8))

        def on_redetect():
            curr_p = entry_path.get().strip()
            if curr_p:
                dt, rec_w = detect_disk_type(curr_p)
                for opt_idx, (opt_dt, _) in enumerate(media_options):
                    if opt_dt == dt:
                        combo_media.current(opt_idx)
                        break
                spin_workers.set(rec_w)

        ttk.Button(row_media, text=tr("btn_redetect"), style="Secondary.TButton", command=on_redetect).pack(side="right")

        tk.Label(dialog, text=tr("dlg_target_lbl_workers"), font=FONTS["small_bold"], bg=COLORS["bg_main"], fg=COLORS["text_primary"]).pack(anchor="w", pady=(0, 2))
        spin_workers = ttk.Spinbox(dialog, from_=1, to=16, width=10)
        spin_workers.set(target.max_workers)
        spin_workers.pack(anchor="w", pady=(0, 10))

        def on_media_selected(event=None):
            m_idx = combo_media.current()
            if m_idx >= 0:
                selected_dt = media_options[m_idx][0]
                if selected_dt == DiskType.HDD:
                    spin_workers.set(1)
                elif selected_dt == DiskType.SSD:
                    spin_workers.set(4)
        combo_media.bind("<<ComboboxSelected>>", on_media_selected)

        tk.Label(dialog, text=tr("dlg_target_lbl_buffer"), font=FONTS["small_bold"], bg=COLORS["bg_main"], fg=COLORS["text_primary"]).pack(anchor="w", pady=(0, 2))
        spin_buffer = ttk.Spinbox(dialog, from_=0.5, to=32.0, increment=0.5, width=10)
        spin_buffer.set(round(target.buffer_size_bytes / (1024 * 1024), 1))
        spin_buffer.pack(anchor="w", pady=(0, 14))

        # Cadre inférieur pour les boutons avec espacement confortable
        btn_box = tk.Frame(dialog, bg=COLORS["bg_main"])
        btn_box.pack(fill="x", side="bottom", pady=(12, 0))

        def save_and_close():
            try:
                target.alias = entry_alias.get().strip() or target.alias
                new_p = entry_path.get().strip()
                if new_p:
                    if len(new_p) == 2 and new_p[1] == ":":
                        new_p += os.sep
                    target.path = os.path.abspath(new_p)

                m_idx = combo_media.current()
                if m_idx >= 0:
                    target.disk_type = media_options[m_idx][0]

                target.max_workers = max(1, int(spin_workers.get()))
                buf_mb = float(spin_buffer.get())
                target.buffer_size_bytes = max(64 * 1024, int(buf_mb * 1024 * 1024))
                self.config.save_to_file()
                self._refresh_list(reselect_idx=idx)
                if self.on_config_changed:
                    self.on_config_changed()
                dialog.destroy()
            except ValueError:
                messagebox.showerror(tr("dlg_target_invalid_numeric_title"), tr("dlg_target_invalid_numeric_msg"))

        btn_cancel = ttk.Button(btn_box, text=tr("dlg_target_btn_cancel"), style="Secondary.TButton", command=dialog.destroy)
        btn_cancel.pack(side="right", padx=(8, 0))

        btn_save = ttk.Button(btn_box, text=tr("dlg_target_btn_save"), style="Primary.TButton", command=save_and_close)
        btn_save.pack(side="right")

        # Dimensions agrandies (520x420) et centrage parfait sur la fenêtre principale
        dialog.update_idletasks()
        dlg_w = 520
        dlg_h = 420
        root_w = self.winfo_toplevel().winfo_width()
        root_h = self.winfo_toplevel().winfo_height()
        root_x = self.winfo_toplevel().winfo_rootx()
        root_y = self.winfo_toplevel().winfo_rooty()

        pos_x = root_x + max(0, (root_w - dlg_w) // 2)
        pos_y = root_y + max(0, (root_h - dlg_h) // 2)
        dialog.geometry(f"{dlg_w}x{dlg_h}+{pos_x}+{pos_y}")
        dialog.deiconify()  # Affiche directement à la bonne position
        dialog.grab_set()
        dialog.focus_force()

    def _toggle_target(self):
        idx = self._get_selected_index()
        if idx is None:
            return
        self.config.targets[idx].enabled = not self.config.targets[idx].enabled
        self.config.save_to_file()
        self._refresh_list(reselect_idx=idx)
        if self.on_config_changed:
            self.on_config_changed()

    def _remove_target(self):
        idx = self._get_selected_index()
        if idx is None:
            return
        target = self.config.targets[idx]
        msg = tr("target_delete_confirm_msg", target.alias)
        if messagebox.askyesno(tr("target_delete_confirm_title"), msg, icon="warning"):
            target_id = getattr(target, "id", None)
            alias = target.alias
            del self.config.targets[idx]
            self.config.save_to_file()
            new_idx = min(idx, len(self.config.targets) - 1) if self.config.targets else None
            self._refresh_list(reselect_idx=new_idx)
            if self.on_config_changed:
                self.on_config_changed()

            # Purge BDD et optimisation SQLite en tâche de fond (non bloquant)
            if self.db_manager and target_id:
                def worker():
                    try:
                        from core.logger import logger
                        logger.info(tr("target_purging", alias))
                        self.db_manager.delete_target_records(target_id)
                        logger.info(tr("target_purge_done", alias))
                    except Exception as e:
                        from core.logger import logger
                        logger.error(tr("log_target_purge_error"), str(e))

                threading.Thread(target=worker, daemon=True).start()

    def update_ui_language(self):
        """Met à jour les libellés de la vue lors d'un changement de langue."""
        self.title_lbl.config(text=tr("targets_title"))
        self.tree.heading("alias", text=tr("col_target_alias"))
        self.tree.heading("path", text=tr("col_target_path"))
        self.tree.heading("disk_type", text=tr("col_target_disk"))
        self.tree.heading("workers", text=tr("col_target_workers"))
        self.tree.heading("buffer", text=tr("col_target_buffer"))
        self.tree.heading("space", text=tr("col_target_space"))
        self.tree.heading("status", text=tr("col_target_status"))

        self.btn_add.config(text=tr("btn_add_target"))
        self.btn_edit.config(text=tr("btn_edit_target"))
        self.btn_toggle.config(text=tr("btn_toggle_target"))
        self.btn_remove.config(text=tr("btn_remove_target"))

        self.context_menu.entryconfig(0, label=tr("btn_edit_target"))
        self.context_menu.entryconfig(1, label=tr("btn_toggle_target"))
        self.context_menu.entryconfig(2, label=tr("ctx_open_folder"))
        self.context_menu.entryconfig(4, label=tr("btn_remove_target"))

        self._refresh_list()
