"""Vue du journal système et de diagnostic pour RotGuard avec menu contextuel et internationalisation."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Dict, Any

from core.logger import logger
from core.database import DatabaseManager
from core.i18n import tr
from ui.styles import COLORS, FONTS, apply_theme_to_widget_tree


class LogsView(tk.Frame):
    """Écran de consultation des logs et exceptions pour diagnostic et support."""

    def __init__(self, parent, db_manager: Optional[DatabaseManager] = None):
        super().__init__(parent, bg=COLORS["bg_main"], padx=16, pady=16)
        self.db_manager = db_manager

        self._build_header()
        self._build_treeview()
        self._build_bottom_actions()
        self._build_context_menu()

        logger.add_listener(self._on_new_log_entry)
        self.refresh_logs()

    def _build_header(self):
        self.header_frame = tk.Frame(self, bg=COLORS["bg_main"])
        self.header_frame.pack(fill="x", pady=(0, 10))

        self.title_lbl = tk.Label(
            self.header_frame,
            text=tr("logs_title"),
            font=FONTS["title"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_main"]
        )
        self.title_lbl.pack(side="left")

        self.filter_box = tk.Frame(self.header_frame, bg=COLORS["bg_main"])
        self.filter_box.pack(side="right")

        self.lbl_flt = tk.Label(self.filter_box, text=tr("lbl_log_level"), font=FONTS["small_bold"], bg=COLORS["bg_main"], fg=COLORS["text_secondary"])
        self.lbl_flt.pack(side="left", padx=(0, 6))

        self.combo_level = ttk.Combobox(
            self.filter_box,
            values=[tr("filter_all"), "ERROR", "WARNING", "INFO", "DEBUG"],
            state="readonly",
            width=12
        )
        self.combo_level.set(tr("filter_all"))
        self.combo_level.pack(side="left", padx=(0, 8))
        self.combo_level.bind("<<ComboboxSelected>>", lambda e: self.refresh_logs())

        self.btn_refresh = ttk.Button(self.filter_box, text=tr("btn_refresh"), style="Secondary.TButton", command=self.refresh_logs)
        self.btn_refresh.pack(side="left")

    def _build_treeview(self):
        self.container = tk.Frame(self, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1)
        self.container.pack(fill="both", expand=True, pady=(0, 10))

        cols = ("time", "level", "message", "details")
        self.tree = ttk.Treeview(self.container, columns=cols, show="headings", selectmode="browse")

        self.tree.heading("time", text=tr("col_log_time"))
        self.tree.heading("level", text=tr("col_log_level"))
        self.tree.heading("message", text=tr("col_log_action"))
        self.tree.heading("details", text=tr("col_log_details"))

        self.tree.column("time", width=75, anchor="center")
        self.tree.column("level", width=90, anchor="center")
        self.tree.column("message", width=360, anchor="w")
        self.tree.column("details", width=420, anchor="w")

        self.scroll = ttk.Scrollbar(self.container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")

        self._configure_tree_tags()

        # Clic droit pour menu contextuel sur une ligne
        self.tree.bind("<Button-3>", self._on_tree_right_click)

    def _build_context_menu(self):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label=tr("ctx_copy_line"), command=self._copy_selected_line)
        self.context_menu.add_command(label=tr("ctx_copy_all"), command=self._copy_to_clipboard)
        self.context_menu.add_separator()
        self.context_menu.add_command(label=tr("ctx_clear_logs"), command=self._clear_logs)

    def _on_tree_right_click(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
            self.context_menu.post(event.x_root, event.y_root)

    def _copy_selected_line(self):
        selection = self.tree.selection()
        if not selection:
            return

        item = self.tree.item(selection[0])
        values = item["values"]
        if not values:
            return

        time_val, level_val, msg_val, det_val = values
        details_txt = f" | {det_val}" if det_val else ""
        line_to_copy = f"[{time_val}] [{level_val}] {msg_val}{details_txt}"

        self.clipboard_clear()
        self.clipboard_append(line_to_copy)
        messagebox.showinfo(tr("logs_copied_line_title"), tr("logs_copied_line_msg"))

    def _configure_tree_tags(self):
        self.tree.tag_configure("ERROR", foreground=COLORS["danger"])
        self.tree.tag_configure("WARNING", foreground=COLORS["warning"])
        self.tree.tag_configure("INFO", foreground=COLORS["text_primary"])

    def _build_bottom_actions(self):
        self.bar = tk.Frame(self, bg=COLORS["bg_main"])
        self.bar.pack(fill="x")

        self.lbl_count = tk.Label(
            self.bar,
            text="",
            font=FONTS["small"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_main"]
        )
        self.lbl_count.pack(side="left")

        btn_box = tk.Frame(self.bar, bg=COLORS["bg_main"])
        btn_box.pack(side="right")

        self.btn_copy_all = ttk.Button(btn_box, text=tr("btn_copy_logs"), style="Secondary.TButton", command=self._copy_to_clipboard)
        self.btn_copy_all.pack(side="left", padx=4)

        self.btn_clear = ttk.Button(btn_box, text=tr("btn_clear_logs"), style="Secondary.TButton", command=self._clear_logs)
        self.btn_clear.pack(side="left", padx=4)

        if self.db_manager:
            self.btn_optimize_db = ttk.Button(btn_box, text=tr("btn_optimize_db"), style="Secondary.TButton", command=self._optimize_db_async)
            self.btn_optimize_db.pack(side="left", padx=4)

    def _optimize_db_async(self):
        """Déclenche l'optimisation SQLite en tâche de fond avec indicateur d'activité."""
        if not self.db_manager:
            return

        self.btn_optimize_db.config(state="disabled", text=tr("btn_optimizing_db"))

        def worker():
            try:
                self.db_manager.optimize_database()
                def on_done():
                    self.btn_optimize_db.config(state="normal", text=tr("btn_optimize_db"))
                    messagebox.showinfo(tr("optimize_db_success_title"), tr("optimize_db_success_msg"))
                self.after(0, on_done)
            except Exception as e:
                logger.error("Erreur optimisation SQLite manuelle", str(e))
                def on_err():
                    self.btn_optimize_db.config(state="normal", text=tr("btn_optimize_db"))
                    messagebox.showerror(tr("optimize_db_error_title"), tr("optimize_db_error_msg", str(e)))
                self.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def update_ui_language(self):
        """Met à jour instantanément les libellés de la vue Logs."""
        self.title_lbl.config(text=tr("logs_title"))
        self.lbl_flt.config(text=tr("lbl_log_level"))
        self.btn_refresh.config(text=tr("btn_refresh"))

        self.tree.heading("time", text=tr("col_log_time"))
        self.tree.heading("level", text=tr("col_log_level"))
        self.tree.heading("message", text=tr("col_log_action"))
        self.tree.heading("details", text=tr("col_log_details"))

        self.context_menu.entryconfig(0, label=tr("ctx_copy_line"))
        self.context_menu.entryconfig(1, label=tr("ctx_copy_all"))
        self.context_menu.entryconfig(3, label=tr("ctx_clear_logs"))

        self.btn_copy_all.config(text=tr("btn_copy_logs"))
        self.btn_clear.config(text=tr("btn_clear_logs"))
        if hasattr(self, "btn_optimize_db"):
            self.btn_optimize_db.config(text=tr("btn_optimize_db"))

        curr_lvl = self.combo_level.get()
        self.combo_level["values"] = [tr("filter_all"), "ERROR", "WARNING", "INFO", "DEBUG"]
        if curr_lvl in ("TOUS", "ALL") or curr_lvl not in self.combo_level["values"]:
            self.combo_level.set(tr("filter_all"))

        self.refresh_logs()

    def apply_theme_colors(self, colors: Dict[str, Any]):
        self.configure(bg=colors["bg_main"])
        apply_theme_to_widget_tree(self, colors)
        self._configure_tree_tags()

    def refresh_logs(self):
        raw_filter = self.combo_level.get()
        level_filter = None if raw_filter in ("TOUS", "ALL", tr("filter_all")) else raw_filter
        entries = logger.get_recent_entries(level_filter=level_filter)

        for item in self.tree.get_children():
            self.tree.delete(item)

        for e in reversed(entries):
            lvl = e["level"]
            tag = lvl if lvl in ("ERROR", "WARNING", "INFO") else "INFO"
            self.tree.insert("", "end", values=(e["time"], lvl, e["message"], e["details"]), tags=(tag,))

        self.lbl_count.config(text=tr("logs_events_count", len(entries)))

    def _on_new_log_entry(self, entry):
        self.after(100, self.refresh_logs)

    def _copy_to_clipboard(self):
        raw_filter = self.combo_level.get()
        level_filter = None if raw_filter in ("TOUS", "ALL", tr("filter_all")) else raw_filter
        entries = logger.get_recent_entries(level_filter=level_filter)
        if not entries:
            messagebox.showinfo(tr("logs_no_logs_title"), tr("logs_no_logs_msg"))
            return

        lines = [f"[{e['time']}] [{e['level']}] {e['message']} | {e['details']}" for e in entries]
        text_to_copy = "\n".join(lines)

        self.clipboard_clear()
        self.clipboard_append(text_to_copy)
        messagebox.showinfo(tr("logs_copied_all_title"), tr("logs_copied_all_msg", len(entries)))

    def _clear_logs(self):
        if messagebox.askyesno(tr("logs_clear_confirm_title"), tr("logs_clear_confirm_msg")):
            logger.clear()
            self.refresh_logs()
