"""Vue d'exploration et de recherche dans la base de données d'empreintes."""

import os
import secrets
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Dict, Any

from core.database import DatabaseManager
from core.models import FileRecord, FileStatus
from core.platform_utils import open_in_file_manager
from core.i18n import tr, format_bytes
from ui.widgets.components import StatusBadge
from ui.styles import COLORS, FONTS, apply_theme_to_widget_tree


class DatabaseView(tk.Frame):
    """Écran d'inspection de la base SQLite avec filtres par statut et recherche instantanée."""

    def __init__(self, parent, db_manager: DatabaseManager):
        super().__init__(parent, bg=COLORS["bg_main"], padx=16, pady=16)
        self.db_manager = db_manager
        self.current_page = 0
        self.page_size = 200
        self._data_loaded = False
        self._query_id = 0
        self._records_by_iid: Dict[str, FileRecord] = {}

        self._build_header_filters()
        self._build_treeview()
        self._build_pagination_and_details()
        # Chargement différé (Lazy Loading) : les données sont lues uniquement
        # lorsque l'utilisateur affiche cet onglet, garantissant un démarrage instantané.

    def _build_header_filters(self):
        self.filter_frame = tk.Frame(self, bg=COLORS["bg_main"])
        self.filter_frame.pack(fill="x", pady=(0, 12))

        self.title_lbl = tk.Label(
            self.filter_frame,
            text=tr("db_title"),
            font=FONTS["title"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_main"]
        )
        self.title_lbl.pack(side="left")

        self.right_box = tk.Frame(self.filter_frame, bg=COLORS["bg_main"])
        self.right_box.pack(side="right")

        self.lbl_status_flt = tk.Label(self.right_box, text=tr("filter_lbl"), font=FONTS["small_bold"], bg=COLORS["bg_main"], fg=COLORS["text_secondary"])
        self.lbl_status_flt.pack(side="left", padx=(0, 4))

        self.combo_status = ttk.Combobox(
            self.right_box,
            values=[tr("filter_all"), "CORRUPT", "LOCKED", "MODIFIED", "OK", "NEW", "MISSING"],
            state="readonly",
            width=13
        )
        self.combo_status.set(tr("filter_all"))
        self.combo_status.pack(side="left", padx=(0, 12))
        self.combo_status.bind("<<ComboboxSelected>>", lambda e: self._on_filter_changed())

        self.lbl_search_flt = tk.Label(self.right_box, text=tr("search_lbl"), font=FONTS["small_bold"], bg=COLORS["bg_main"], fg=COLORS["text_secondary"])
        self.lbl_search_flt.pack(side="left", padx=(0, 4))

        self.entry_search = ttk.Entry(self.right_box, width=22)
        self.entry_search.pack(side="left", padx=(0, 8))
        self.entry_search.bind("<Return>", lambda e: self._on_filter_changed())

        self.btn_search = ttk.Button(self.right_box, text=tr("btn_filter"), style="Secondary.TButton", command=self._on_filter_changed)
        self.btn_search.pack(side="left")

    def _build_treeview(self):
        self.container = tk.Frame(self, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        self.container.pack(fill="both", expand=True, pady=(0, 10))

        cols = ("status", "path", "size", "mtime", "last_checked", "algo", "hash")
        self.tree = ttk.Treeview(self.container, columns=cols, show="headings", selectmode="browse")

        self.tree.heading("status", text=tr("col_status"))
        self.tree.heading("path", text=tr("col_path"))
        self.tree.heading("size", text=tr("col_size"))
        self.tree.heading("mtime", text=tr("col_mtime"))
        self.tree.heading("last_checked", text=tr("col_last_checked"))
        self.tree.heading("algo", text=tr("col_algo"))
        self.tree.heading("hash", text=tr("col_hash"))

        self.tree.column("status", width=95, anchor="center")
        self.tree.column("path", width=340, anchor="w")
        self.tree.column("size", width=85, anchor="e")
        self.tree.column("mtime", width=130, anchor="center")
        self.tree.column("last_checked", width=130, anchor="center")
        self.tree.column("algo", width=75, anchor="center")
        self.tree.column("hash", width=220, anchor="w")

        self.scroll = ttk.Scrollbar(self.container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_select_record)
        self.tree.bind("<Button-3>", self._on_tree_context_menu)

    def _build_pagination_and_details(self):
        self.nav_frame = tk.Frame(self, bg=COLORS["bg_main"])
        self.nav_frame.pack(fill="x", pady=(0, 8))

        self.lbl_page_info = tk.Label(
            self.nav_frame,
            text="",
            font=FONTS["small"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_main"]
        )
        self.lbl_page_info.pack(side="left")

        # Indicateur de chargement asynchrone
        self.progress_loading = ttk.Progressbar(self.nav_frame, mode="indeterminate", length=120)

        btn_box = tk.Frame(self.nav_frame, bg=COLORS["bg_main"])
        btn_box.pack(side="right")

        self.btn_prev = ttk.Button(btn_box, text=tr("btn_prev"), style="Secondary.TButton", command=self._prev_page)
        self.btn_prev.pack(side="left", padx=4)

        self.btn_next = ttk.Button(btn_box, text=tr("btn_next"), style="Secondary.TButton", command=self._next_page)
        self.btn_next.pack(side="left", padx=4)

        self.detail_frame = tk.Frame(self, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1, padx=12, pady=8)
        self.detail_frame.pack(fill="x")

        self.lbl_detail_path = tk.Label(
            self.detail_frame,
            text=tr("db_select_file"),
            font=FONTS["body_bold"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_card"],
            anchor="w"
        )
        self.lbl_detail_path.pack(fill="x")

        self.lbl_detail_extra = tk.Label(
            self.detail_frame,
            text="",
            font=FONTS["mono"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"],
            anchor="w"
        )
        self.lbl_detail_extra.pack(fill="x")

    def apply_theme_colors(self, colors: Dict[str, Any]):
        self.configure(bg=colors["bg_main"])
        apply_theme_to_widget_tree(self, colors)

    def _on_filter_changed(self):
        self.current_page = 0
        self.refresh_data()

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_data()

    def _next_page(self):
        self.current_page += 1
        self.refresh_data()

    def refresh_data(self):
        """Récupère les enregistrements paginés en tâche de fond (non bloquant)."""
        raw_status = self.combo_status.get()
        status_filter = None if raw_status in ("TOUS", "ALL", tr("filter_all")) else raw_status
        search_term = self.entry_search.get().strip() or None

        self._query_id += 1
        query_id = self._query_id

        offset = self.current_page * self.page_size

        # Affichage immédiat de l'indicateur d'activité
        self.lbl_page_info.config(text=tr("db_loading_records"))
        self.progress_loading.pack(side="left", padx=(10, 0))
        self.progress_loading.start(10)
        self.btn_prev.config(state="disabled")
        self.btn_next.config(state="disabled")

        def worker():
            try:
                total = self.db_manager.get_total_count(status_filter=status_filter, search_term=search_term)
                records = self.db_manager.get_all_records(
                    status_filter=status_filter,
                    search_term=search_term,
                    limit=self.page_size,
                    offset=offset
                )
                self.after(0, lambda: self._apply_database_results(query_id, records, total, offset))
            except Exception as e:
                from core.logger import logger
                logger.error("Erreur chargement base d'empreintes", str(e))
                self.after(0, lambda: self._on_database_error(query_id, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_database_error(self, query_id: int, err_msg: str):
        if query_id != self._query_id:
            return
        self.progress_loading.stop()
        self.progress_loading.pack_forget()
        self.lbl_page_info.config(text=tr("db_read_error", err_msg))

    def _apply_database_results(self, query_id: int, records: list, total: int, offset: int):
        if query_id != self._query_id:
            return

        self.progress_loading.stop()
        self.progress_loading.pack_forget()

        for item in self.tree.get_children():
            self.tree.delete(item)
        self._records_by_iid.clear()

        for i, r in enumerate(records):
            size_str = format_bytes(r.size)

            mtime_str = datetime.fromtimestamp(r.mtime).strftime("%Y-%m-%d %H:%M") if r.mtime > 0 else "-"
            last_chk_str = r.last_checked_date[:16] if r.last_checked_date else "-"
            status_val = r.status.value if hasattr(r.status, "value") else str(r.status)

            iid = str(i)
            self._records_by_iid[iid] = r
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    status_val,
                    r.path,
                    size_str,
                    mtime_str,
                    last_chk_str,
                    r.hash_algo,
                    r.hash_value
                )
            )

        start_num = offset + 1 if total > 0 else 0
        end_num = min(offset + len(records), total)
        self.lbl_page_info.config(text=tr("pagination_info", start_num, end_num, total))

        self.btn_prev.config(state="normal" if self.current_page > 0 else "disabled")
        self.btn_next.config(state="normal" if end_num < total else "disabled")

        if not self.tree.selection():
            self.lbl_detail_path.config(text=tr("db_select_file"))
            self.lbl_detail_extra.config(text="")

    def _on_select_record(self, event):
        selection = self.tree.selection()
        if not selection:
            return

        item = self.tree.item(selection[0])
        values = item["values"]
        if not values or len(values) < 7:
            return

        status, path, size_str, mtime, last_chk, algo, hash_val = values
        self.lbl_detail_path.config(text=path)
        self.lbl_detail_extra.config(
            text=tr("db_detail_format", status, size_str, mtime, last_chk, algo, hash_val)
        )

    def _on_tree_context_menu(self, event):
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return

        self.tree.selection_set(row_id)
        self.tree.focus(row_id)
        self._on_select_record(None)

        record = self._records_by_iid.get(row_id)
        values = self.tree.item(row_id, "values")
        file_path = record.path if (record and record.path) else (values[1] if values and len(values) > 1 else None)
        if not file_path:
            return

        hash_val = record.hash_value if (record and record.hash_value) else (values[6] if values and len(values) > 6 else "")

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=tr("ctx_open_folder"), command=lambda p=file_path: open_in_file_manager(p))
        menu.add_separator()
        menu.add_command(label=tr("ctx_db_copy_path"), command=lambda p=file_path: self._copy_to_clipboard(p))
        menu.add_command(label=tr("ctx_db_copy_hash"), command=lambda h=hash_val: self._copy_to_clipboard(h))
        if record:
            menu.add_separator()
            menu.add_command(label=tr("ctx_db_verify_file"), command=lambda r=record: self._verify_file(r))
            menu.add_command(label=tr("ctx_db_simulate_corrupt"), command=lambda r=record: self._simulate_corruption(r))
            menu.add_separator()
            menu.add_command(label=tr("ctx_db_delete_record"), command=lambda r=record: self._delete_record(r))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    def _verify_file(self, record: FileRecord):
        from core.hasher import hash_file_stream
        if not os.path.isfile(record.path):
            messagebox.showwarning(tr("ctx_db_file_not_found_title"), tr("ctx_db_file_not_found_msg", record.path))
            return

        self.lbl_page_info.config(text=tr("ctx_db_verifying_file", os.path.basename(record.path)))

        def worker():
            try:
                algo = record.hash_algo or "BLAKE2b"
                computed_hash, bytes_read, duration = hash_file_stream(record.path, algorithm=algo)
                self.after(0, lambda: self._on_verify_complete(record, computed_hash))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(tr("ctx_db_verify_error_title"), tr("ctx_db_verify_error_msg", str(e))))

        threading.Thread(target=worker, daemon=True).start()

    def _on_verify_complete(self, record: FileRecord, computed_hash: str):
        if computed_hash.lower() == (record.hash_value or "").lower():
            record.last_checked_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            record.status = FileStatus.OK
            record.error_message = None
            try:
                st = os.stat(record.path)
                record.size = st.st_size
                record.mtime = st.st_mtime
            except Exception:
                pass
            try:
                self.db_manager.upsert_batch([record])
                self.refresh_data()
                messagebox.showinfo(tr("ctx_db_verify_ok_title"), tr("ctx_db_verify_ok_msg", record.path, computed_hash))
            except Exception as e:
                messagebox.showerror(tr("ctx_db_verify_error_title"), tr("ctx_db_verify_error_msg", str(e)))
        else:
            diff_confirm = messagebox.askyesno(
                tr("ctx_db_verify_diff_title"),
                tr("ctx_db_verify_diff_msg", record.path, record.hash_value, computed_hash)
            )
            if diff_confirm:
                try:
                    st = os.stat(record.path)
                    record.size = st.st_size
                    record.mtime = st.st_mtime
                except Exception:
                    pass
                record.hash_value = computed_hash
                record.status = FileStatus.OK
                record.last_checked_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                record.error_message = None
                try:
                    self.db_manager.upsert_batch([record])
                    self.refresh_data()
                    messagebox.showinfo(tr("ctx_db_verify_updated_title"), tr("ctx_db_verify_updated_msg"))
                except Exception as e:
                    messagebox.showerror(tr("ctx_db_verify_error_title"), tr("ctx_db_verify_error_msg", str(e)))

    def _simulate_corruption(self, record: FileRecord):
        confirm = messagebox.askyesno(
            tr("ctx_db_sim_confirm_title"),
            tr("ctx_db_sim_confirm_msg", record.path)
        )
        if not confirm:
            return

        expected_len = len(record.hash_value) if record.hash_value else 64
        if expected_len < 8:
            expected_len = 8
        prefix = "deadbeef"
        rem_len = expected_len - len(prefix)
        if rem_len > 0:
            rand_hex = secrets.token_hex((rem_len + 1) // 2)[:rem_len].lower()
            fake_hash = prefix + rand_hex
        else:
            fake_hash = prefix

        try:
            record.hash_value = fake_hash
            self.db_manager.upsert_batch([record])
            self.refresh_data()
            messagebox.showinfo(tr("ctx_db_sim_success_title"), tr("ctx_db_sim_success_msg", fake_hash))
        except Exception as e:
            messagebox.showerror(tr("ctx_db_sim_error_title"), tr("ctx_db_sim_error_msg", str(e)))

    def _delete_record(self, record: FileRecord):
        confirm = messagebox.askyesno(
            tr("ctx_db_delete_confirm_title"),
            tr("ctx_db_delete_confirm_msg", record.path)
        )
        if not confirm:
            return

        try:
            self.db_manager.delete_record(record)
            self.refresh_data()
        except Exception as e:
            messagebox.showerror(tr("ctx_db_delete_error_title"), tr("ctx_db_delete_error_msg", str(e)))

    def update_ui_language(self):
        """Met à jour les libellés de la vue lors d'un changement de langue."""
        self.title_lbl.config(text=tr("db_title"))
        self.lbl_status_flt.config(text=tr("filter_lbl"))
        self.lbl_search_flt.config(text=tr("search_lbl"))
        self.btn_search.config(text=tr("btn_filter"))

        self.tree.heading("status", text=tr("col_status"))
        self.tree.heading("path", text=tr("col_path"))
        self.tree.heading("size", text=tr("col_size"))
        self.tree.heading("mtime", text=tr("col_mtime"))
        self.tree.heading("last_checked", text=tr("col_last_checked"))
        self.tree.heading("algo", text=tr("col_algo"))
        self.tree.heading("hash", text=tr("col_hash"))

        self.btn_prev.config(text=tr("btn_prev"))
        self.btn_next.config(text=tr("btn_next"))
        if not self.tree.selection():
            self.lbl_detail_path.config(text=tr("db_select_file"))

        curr_filter = self.combo_status.get()
        self.combo_status["values"] = [tr("filter_all"), "CORRUPT", "LOCKED", "MODIFIED", "OK", "NEW", "MISSING"]
        if curr_filter in ("TOUS", "ALL") or curr_filter not in self.combo_status["values"]:
            self.combo_status.set(tr("filter_all"))

        self.refresh_data()
