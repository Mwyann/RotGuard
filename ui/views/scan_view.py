"""Vue principale de contrôle et de surveillance en temps réel des scans."""

import time
import threading
import subprocess
import ctypes
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Dict, Tuple, Any
from collections import deque

from core.models import AppConfig, ScanStats, FileRecord, FileStatus
from core.database import DatabaseManager
from core.worker_pool import (
    WorkerPool,
    STATUS_WAITING,
    STATUS_IDLE,
    STATUS_DONE,
    STATUS_STOPPED,
)
from core.platform_utils import (
    play_completion_sound,
    suspend_system,
    poweroff_system,
    show_native_notification,
    open_in_file_manager,
)
from core.logger import logger
from core.i18n import tr
from ui.widgets.components import MetricCard
from ui.styles import COLORS, FONTS, apply_theme_to_widget_tree


def _format_worker_status(w_file: str) -> str:
    if w_file == STATUS_WAITING:
        return tr("task_status_waiting")
    if w_file == STATUS_IDLE:
        return tr("task_status_idle")
    if w_file == STATUS_DONE:
        return tr("task_status_done")
    if w_file == STATUS_STOPPED:
        return tr("task_status_stopped")
    return str(w_file)


def _format_duration(seconds: Optional[float]) -> str:
    """Formate une durée en secondes en format lisible avec secondes, minutes, heures et jours si nécessaire.
    
    Exemples :
    - Moins d'une heure : 05:23
    - Une heure ou plus : 02h 15m 30s
    - Un jour ou plus   : 1j 04h 15m 30s (ou 1d 04h 15m 30s)
    """
    if seconds is None or seconds < 0:
        return "--:--"
    total_seconds = int(round(seconds))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    day_unit = tr("unit_day") if tr("unit_day") != "unit_day" else "j"

    if days > 0:
        return f"{days}{day_unit} {hours:02d}h {minutes:02d}m {secs:02d}s"
    elif hours > 0:
        return f"{hours:02d}h {minutes:02d}m {secs:02d}s"
    else:
        return f"{minutes:02d}:{secs:02d}"


class ScanView(tk.Frame):
    """Tableau de bord temps réel : lancement, pause, jauges, vitesse et alertes."""

    def __init__(self, parent, config: AppConfig, db_manager: DatabaseManager):
        super().__init__(parent, bg=COLORS["bg_main"], padx=16, pady=16)
        self.config = config
        self.db_manager = db_manager
        self.pool: Optional[WorkerPool] = None

        self.event_queue: deque = deque(maxlen=200)
        self.events_by_type: Dict[str, deque] = {
            "CORRUPT": deque(maxlen=500),
            "MODIFIED": deque(maxlen=500),
            "NEW": deque(maxlen=500),
            "OK": deque(maxlen=500),
            "LOCKED": deque(maxlen=500),
            "ERROR": deque(maxlen=500),
            "MISSING": deque(maxlen=500),
        }
        self._event_seq: int = 0
        self._scan_completed_handled: bool = False
        self._countdown_dialog: Optional[tk.Toplevel] = None
        self._countdown_timer_id: Optional[str] = None
        self._countdown_seconds_remaining: int = 0
        self.cli_autoclose: bool = False
        self.cli_autoshutdown: bool = False

        self._build_top_controls()
        self._build_metrics_row()
        self._build_progress_section()
        self._build_activity_section()

        self._drain_event_queue()

    def _build_top_controls(self):
        self.ctrl_frame = tk.Frame(self, bg=COLORS["bg_main"])
        self.ctrl_frame.pack(fill="x", pady=(0, 14))

        self.title_lbl = tk.Label(
            self.ctrl_frame,
            text=tr("scan_title"),
            font=FONTS["title"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_main"]
        )
        self.title_lbl.pack(side="left")

        # Colonne droite : Boutons de commande
        self.btn_box = tk.Frame(self.ctrl_frame, bg=COLORS["bg_main"])
        self.btn_box.pack(side="right")

        self.btn_full_scan = ttk.Button(
            self.btn_box,
            text=tr("btn_full_scan"),
            style="Primary.TButton",
            command=self._start_full_scan
        )
        self.btn_full_scan.pack(side="left", padx=4)

        self.btn_update_scan = ttk.Button(
            self.btn_box,
            text=tr("btn_update_scan"),
            style="Secondary.TButton",
            command=self._start_update_scan
        )
        self.btn_update_scan.pack(side="left", padx=4)

        self.btn_simple_check = ttk.Button(
            self.btn_box,
            text=tr("btn_simple_check"),
            style="Secondary.TButton",
            command=self._start_simple_check
        )
        self.btn_simple_check.pack(side="left", padx=4)

        self.btn_pause = ttk.Button(
            self.btn_box,
            text=tr("btn_pause"),
            style="Secondary.TButton",
            command=self._toggle_pause,
            state="disabled"
        )
        self.btn_pause.pack(side="left", padx=4)

        self.btn_stop = ttk.Button(
            self.btn_box,
            text=tr("btn_stop"),
            style="Danger.TButton",
            command=self._stop_scan,
            state="disabled"
        )
        self.btn_stop.pack(side="left", padx=3)

        # Action one-shot en fin de scan
        self.lbl_post_action = tk.Label(
            self.btn_box,
            text=tr("lbl_post_scan_short"),
            font=FONTS["small_bold"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_main"]
        )
        self.lbl_post_action.pack(side="left", padx=(12, 4))

        self.post_action_options = [
            ("none", tr("post_none")),
            ("close", tr("post_close")),
            ("sleep", tr("post_sleep")),
            ("shutdown", tr("post_shutdown"))
        ]
        self.combo_post_action = ttk.Combobox(
            self.btn_box,
            values=[label for _, label in self.post_action_options],
            state="readonly",
            width=18
        )
        self.combo_post_action.pack(side="left", padx=(0, 2))
        self._apply_initial_post_action()

    def _apply_initial_post_action(self):
        """Initialise la sélection de l'action de fin de scan selon la config ou les drapeaux CLI."""
        if getattr(self, "cli_autoclose", False):
            self._set_post_action("close")
        elif getattr(self, "cli_autoshutdown", False):
            self._set_post_action("shutdown")
        else:
            default_action = getattr(self.config, "post_scan_action", "none") or "none"
            self._set_post_action(default_action)

    def apply_cli_options(self):
        """Applique les options reçues en ligne de commande (ex: --auto, --autoclose, --autoshutdown)."""
        if getattr(self, "cli_autoclose", False):
            self._set_post_action("close")
        elif getattr(self, "cli_autoshutdown", False):
            self._set_post_action("shutdown")

    def _set_post_action(self, action_code: str):
        """Sélectionne l'option dans la liste déroulante correspondant au code ('none', 'close', 'sleep', 'shutdown')."""
        for idx, (code, _) in enumerate(self.post_action_options):
            if code == action_code:
                self.combo_post_action.current(idx)
                return
        if self.post_action_options:
            self.combo_post_action.current(0)

    def _get_selected_post_action(self) -> str:
        """Retourne le code de l'action actuellement sélectionnée dans la liste déroulante."""
        idx = self.combo_post_action.current()
        if 0 <= idx < len(self.post_action_options):
            return self.post_action_options[idx][0]
        return "none"

    def update_from_config(self):
        """Synchronise l'action par défaut si elle n'a pas été forcée par la ligne de commande."""
        if not getattr(self, "cli_autoclose", False) and not getattr(self, "cli_autoshutdown", False):
            default_action = getattr(self.config, "post_scan_action", "none") or "none"
            self._set_post_action(default_action)

    def _build_metrics_row(self):
        self.metrics_row = tk.Frame(self, bg=COLORS["bg_main"])
        self.metrics_row.pack(fill="x", pady=(0, 14))

        self.card_speed = MetricCard(self.metrics_row, title=tr("metric_speed"), value="0.0 Mo/s", accent_color=COLORS["primary"], subtitle=tr("metric_speed_waiting"))
        self.card_speed.pack(side="left", fill="both", expand=True, padx=(0, 6))

        self.card_progress = MetricCard(self.metrics_row, title=tr("metric_progress"), value="0 / 0", accent_color=COLORS["accent"], subtitle="0%")
        self.card_progress.pack(side="left", fill="both", expand=True, padx=6)

        self.card_ok = MetricCard(self.metrics_row, title=tr("metric_healthy"), value="0", accent_color=COLORS["success"], subtitle=tr("metric_healthy_sub", 0, 0))
        self.card_ok.pack(side="left", fill="both", expand=True, padx=6)

        self.card_mod = MetricCard(self.metrics_row, title=tr("metric_updated"), value="0", accent_color=COLORS["warning"], subtitle=tr("metric_updated_sub"))
        self.card_mod.pack(side="left", fill="both", expand=True, padx=6)

        self.card_corrupted = MetricCard(self.metrics_row, title=tr("metric_corrupted"), value="0", accent_color=COLORS["danger"], subtitle=tr("metric_corrupted_sub"))
        self.card_corrupted.pack(side="left", fill="both", expand=True, padx=6)

        self.card_locked = MetricCard(self.metrics_row, title=tr("metric_locked"), value="0", accent_color=COLORS["locked"], subtitle=tr("metric_locked_sub"))
        self.card_locked.pack(side="left", fill="both", expand=True, padx=(6, 0))

    def _build_progress_section(self):
        self.progress_frame = tk.Frame(self, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1, padx=12, pady=10)
        self.progress_frame.pack(fill="x", pady=(0, 14))

        self.info_box = tk.Frame(self.progress_frame, bg=COLORS["bg_card"])
        self.info_box.pack(fill="x", pady=(0, 6))

        self.lbl_status_text = tk.Label(
            self.info_box,
            text=tr("ready_scan"),
            font=FONTS["body_bold"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_card"]
        )
        self.lbl_status_text.pack(side="left")

        self.lbl_eta = tk.Label(
            self.info_box,
            text=tr("time_elapsed_empty", "00:00"),
            font=FONTS["small"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"]
        )
        self.lbl_eta.pack(side="right")

        self.progress_bar = ttk.Progressbar(self.progress_frame, orient="horizontal", mode="determinate", style="Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x")

    def _build_activity_section(self):
        self.activity_container = tk.Frame(self, bg=COLORS["bg_main"])
        self.activity_container.pack(fill="both", expand=True)

        # Volet gauche : Tâches actives
        self.left_frame = tk.Frame(self.activity_container, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1, padx=8, pady=8)
        self.left_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))

        self.lbl_threads_title = tk.Label(self.left_frame, text=tr("tasks_title"), font=FONTS["h2"], fg=COLORS["text_primary"], bg=COLORS["bg_card"])
        self.lbl_threads_title.pack(anchor="w", pady=(0, 6))

        self.threads_box = tk.Frame(self.left_frame, bg=COLORS["bg_card"])
        self.threads_box.pack(fill="both", expand=True)

        cols_tasks = ("id", "path", "file", "progress", "speed")
        self.tree_threads = ttk.Treeview(self.threads_box, columns=cols_tasks, show="headings", height=7)
        self.tree_threads.heading("id", text=tr("task_col_id"))
        self.tree_threads.heading("path", text=tr("task_col_path"))
        self.tree_threads.heading("file", text=tr("task_col_file"))
        self.tree_threads.heading("progress", text=tr("task_col_progress"))
        self.tree_threads.heading("speed", text=tr("task_col_speed"))
        self.tree_threads.column("id", width=45, minwidth=40, anchor="center")
        self.tree_threads.column("path", width=180, minwidth=100, anchor="w")
        self.tree_threads.column("file", width=140, minwidth=90, anchor="w")
        self.tree_threads.column("progress", width=110, minwidth=80, anchor="center")
        self.tree_threads.column("speed", width=75, minwidth=60, anchor="center")

        self.scroll_threads = ttk.Scrollbar(self.threads_box, orient="vertical", command=self.tree_threads.yview)
        self.tree_threads.configure(yscrollcommand=self.scroll_threads.set)
        self.tree_threads.pack(side="left", fill="both", expand=True)
        self.scroll_threads.pack(side="right", fill="y")

        # Volet droit : Journal des événements récents filtrable
        self.right_frame = tk.Frame(self.activity_container, bg=COLORS["bg_card"], highlightbackground=COLORS["border"], highlightthickness=1, padx=8, pady=8)
        self.right_frame.pack(side="right", fill="both", expand=True, padx=(6, 0))

        self.header_log = tk.Frame(self.right_frame, bg=COLORS["bg_card"])
        self.header_log.pack(fill="x", pady=(0, 4))

        self.lbl_log_title = tk.Label(self.header_log, text=tr("events_title"), font=FONTS["h2"], fg=COLORS["text_primary"], bg=COLORS["bg_card"])
        self.lbl_log_title.pack(side="left")

        self.filter_bar = tk.Frame(self.right_frame, bg=COLORS["bg_card"])
        self.filter_bar.pack(fill="x", pady=(0, 6))

        self.filter_corrupted = tk.BooleanVar(value=True)
        self.filter_ok = tk.BooleanVar(value=True)
        self.filter_new = tk.BooleanVar(value=True)
        self.filter_mod = tk.BooleanVar(value=True)
        self.filter_locked = tk.BooleanVar(value=False)

        self.chk_flt_corrupted = ttk.Checkbutton(self.filter_bar, text=tr("filter_corrupted"), variable=self.filter_corrupted, command=self._refresh_event_list)
        self.chk_flt_corrupted.pack(side="left", padx=(0, 6))

        self.chk_flt_ok = ttk.Checkbutton(self.filter_bar, text=tr("filter_healthy"), variable=self.filter_ok, command=self._refresh_event_list)
        self.chk_flt_ok.pack(side="left", padx=4)

        self.chk_flt_new = ttk.Checkbutton(self.filter_bar, text=tr("filter_new"), variable=self.filter_new, command=self._refresh_event_list)
        self.chk_flt_new.pack(side="left", padx=4)

        self.chk_flt_mod = ttk.Checkbutton(self.filter_bar, text=tr("filter_modified"), variable=self.filter_mod, command=self._refresh_event_list)
        self.chk_flt_mod.pack(side="left", padx=4)

        self.chk_flt_locked = ttk.Checkbutton(self.filter_bar, text=tr("filter_locked"), variable=self.filter_locked, command=self._refresh_event_list)
        self.chk_flt_locked.pack(side="left", padx=4)

        self.log_box = tk.Frame(self.right_frame, bg=COLORS["bg_card"])
        self.log_box.pack(fill="both", expand=True)

        cols_log = ("time", "status", "file")
        self.tree_log = ttk.Treeview(self.log_box, columns=cols_log, show="headings", height=7)
        self.tree_log.heading("time", text=tr("evt_col_time"))
        self.tree_log.heading("status", text=tr("evt_col_status"))
        self.tree_log.heading("file", text=tr("evt_col_file"))
        self.tree_log.column("time", width=70, anchor="center")
        self.tree_log.column("status", width=95, anchor="center")
        self.tree_log.column("file", width=230, anchor="w")

        self.scroll_log = ttk.Scrollbar(self.log_box, orient="vertical", command=self.tree_log.yview)
        self.tree_log.configure(yscrollcommand=self.scroll_log.set)
        self.tree_log.pack(side="left", fill="both", expand=True)
        self.scroll_log.pack(side="right", fill="y")

        self.tree_log.bind("<Button-3>", self._on_tree_log_context_menu)

    def _apply_initial_post_action(self):
        if getattr(self, "cli_autoshutdown", False):
            self._set_post_action("shutdown")
        elif getattr(self, "cli_autoclose", False):
            self._set_post_action("close")
        else:
            self._set_post_action(getattr(self.config, "post_scan_action", "none"))

    def _set_post_action(self, action_key: str):
        target = (action_key or "none").lower()
        for idx, (key, _) in enumerate(self.post_action_options):
            if key == target:
                self.combo_post_action.current(idx)
                return
        self.combo_post_action.current(0)

    def _get_selected_post_action(self) -> str:
        idx = self.combo_post_action.current()
        if 0 <= idx < len(self.post_action_options):
            return self.post_action_options[idx][0]
        return "none"

    def apply_cli_options(self):
        """Met à jour l'action one-shot après transmission des options CLI."""
        self._apply_initial_post_action()

    def update_from_config(self):
        """Met à jour l'état de la vue si la configuration change."""
        if not getattr(self, "cli_autoshutdown", False) and not getattr(self, "cli_autoclose", False):
            self._set_post_action(getattr(self.config, "post_scan_action", "none"))

    def apply_theme_colors(self, colors: Dict[str, Any]):
        """Met à jour exhaustivement toutes les couleurs pour le Mode Sombre / Mode Clair."""
        self.configure(bg=colors["bg_main"])
        if hasattr(self, "lbl_post_action"):
            self.lbl_post_action.configure(bg=colors["bg_main"], fg=colors["text_secondary"])
        apply_theme_to_widget_tree(self, colors)

        # Mettre à jour les MetricCards avec leurs couleurs d'accent respectives
        self.card_speed.refresh_colors(colors["bg_card"], colors["border"], colors["text_secondary"], colors["text_muted"], colors["primary"])
        self.card_progress.refresh_colors(colors["bg_card"], colors["border"], colors["text_secondary"], colors["text_muted"], colors["accent"])
        self.card_ok.refresh_colors(colors["bg_card"], colors["border"], colors["text_secondary"], colors["text_muted"], colors["success"])
        self.card_mod.refresh_colors(colors["bg_card"], colors["border"], colors["text_secondary"], colors["text_muted"], colors["warning"])
        self.card_corrupted.refresh_colors(colors["bg_card"], colors["border"], colors["text_secondary"], colors["text_muted"], colors["danger"])
        self.card_locked.refresh_colors(colors["bg_card"], colors["border"], colors["text_secondary"], colors["text_muted"], colors["locked"])

    def _start_full_scan(self):
        active_targets = [t for t in self.config.targets if t.enabled]
        if not active_targets:
            messagebox.showwarning(tr("scan_no_target_title"), tr("scan_no_target_msg"))
            return

        self._scan_completed_handled = False
        self._cancel_countdown()
        self._init_pool()
        self.pool.start_full_scan()
        self._update_ui_state(running=True)

    def _start_update_scan(self):
        active_targets = [t for t in self.config.targets if t.enabled]
        if not active_targets:
            messagebox.showwarning(tr("scan_no_target_title"), tr("scan_no_target_msg"))
            return

        self._scan_completed_handled = False
        self._cancel_countdown()
        self._init_pool()
        self.pool.start_update_scan()
        self._update_ui_state(running=True)

    def _start_simple_check(self):
        active_targets = [t for t in self.config.targets if t.enabled]
        if not active_targets:
            messagebox.showwarning(tr("scan_no_target_title"), tr("scan_no_target_msg"))
            return

        self._scan_completed_handled = False
        self._cancel_countdown()
        self._init_pool()
        self.pool.start_simple_check()
        self._update_ui_state(running=True)

    def _init_pool(self):
        for item in self.tree_threads.get_children():
            self.tree_threads.delete(item)
        for item in self.tree_log.get_children():
            self.tree_log.delete(item)
        for b in self.events_by_type.values():
            b.clear()
        self._event_seq = 0

        self.pool = WorkerPool(
            targets=self.config.targets,
            db_manager=self.db_manager,
            global_max_workers=self.config.global_max_workers,
            hash_algorithm=self.config.hash_algorithm,
            on_stats_update=self._on_stats_update,
            on_file_processed=self._on_file_processed,
            config=self.config
        )

        for wid in range(self.config.global_max_workers):
            self.tree_threads.insert("", "end", iid=str(wid), values=(f"#{wid + 1}", "-", tr("task_status_waiting"), "-", "-"))

    def _toggle_pause(self):
        if not self.pool:
            return
        if self.pool.stats.is_paused:
            self.pool.resume()
            self.btn_pause.config(text=tr("btn_pause"))
        else:
            self.pool.pause()
            self.btn_pause.config(text=tr("btn_resume"))

    def _stop_scan(self):
        if self.pool and self.pool.stats.is_running:
            self.btn_stop.config(state="disabled")
            self.btn_pause.config(state="disabled")
            self.lbl_status_text.config(text=tr("stopping"))
            threading.Thread(target=self._async_stop, daemon=True).start()

    def _async_stop(self):
        if self.pool:
            self.pool.stop()

    def _update_ui_state(self, running: bool):
        top = self.winfo_toplevel()
        if hasattr(top, "update_window_title"):
            top.update_window_title(is_scanning=running)

        if running:
            self.btn_full_scan.config(state="disabled")
            self.btn_update_scan.config(state="disabled")
            self.btn_simple_check.config(state="disabled")
            self.btn_pause.config(state="normal", text=tr("btn_pause"))
            self.btn_stop.config(state="normal")
        else:
            self.btn_full_scan.config(state="normal")
            self.btn_update_scan.config(state="normal")
            self.btn_simple_check.config(state="normal")
            self.btn_pause.config(state="disabled", text=tr("btn_pause"))
            self.btn_stop.config(state="disabled")

    def _on_stats_update(self, stats: ScanStats, worker_tasks: Dict[int, Tuple[str, str, float]]):
        """Reçoit les statistiques synchronisées toutes les 0.5s."""
        self.after(0, self._apply_stats_and_speeds, stats, worker_tasks)

    def _apply_stats_and_speeds(self, stats: ScanStats, worker_tasks: Dict[int, Tuple[str, str, float]]):
        # 1. Vitesse globale (Somme de tous les threads)
        if stats.is_running:
            self.card_speed.set_value(
                f"{stats.current_speed_mb_s:.1f} {tr('unit_mb_s')}",
                tr("metric_speed_read", f"{stats.bytes_scanned / (1024*1024):.1f}")
            )
        else:
            self.card_speed.set_value(f"0.0 {tr('unit_mb_s')}", tr("metric_speed_waiting"))

        # 2. Cartes de métriques
        total = stats.total_files_found
        done = stats.scanned_files
        if not stats.is_running and stats.is_completed:
            percent = 100.0
        else:
            percent = (done / total * 100) if total > 0 else 0
        self.card_progress.set_value(f"{done} / {total}", f"{percent:.1f}%")
        self.progress_bar["value"] = percent

        self.card_ok.set_value(str(stats.ok_count), f"{stats.ok_count} / {done}")
        self.card_mod.set_value(
            str(stats.modified_count + stats.new_count),
            tr("metric_sub_new_mod", stats.new_count, stats.modified_count)
        )
        self.card_corrupted.set_value(
            str(stats.corrupted_count),
            tr("metric_sub_no_alert") if stats.corrupted_count == 0 else tr("metric_sub_corrupt")
        )
        self.card_locked.set_value(
            str(stats.locked_count + stats.missing_count),
            tr("metric_sub_locked_missing", stats.locked_count, stats.missing_count)
        )

        # Temps écoulé et restant (secondes, minutes, heures et jours si nécessaire)
        elapsed_str = _format_duration(stats.elapsed_time_s)

        if stats.is_paused:
            status_prefix = tr("paused")
        elif stats.is_running:
            if getattr(stats, "current_phase", "") == "new_files":
                status_prefix = tr("scan_phase_new", stats.new_count)
            elif getattr(stats, "current_phase", "") == "existing_files":
                status_prefix = tr("scan_phase_existing")
            elif stats.scanned_files == 0:
                status_prefix = tr("scan_phase_discovery", stats.total_files_found)
            else:
                status_prefix = tr("scanning")
        elif stats.is_completed:
            if stats.corrupted_count > 0:
                status_prefix = tr("scan_finished_err", stats.corrupted_count, done)
            else:
                status_prefix = tr("scan_finished_ok", done)
        elif stats.is_aborted:
            status_prefix = tr("scan_aborted", done, total)
        else:
            status_prefix = tr("ready_scan")

        self.lbl_status_text.config(text=status_prefix)

        if stats.is_running:
            if stats.eta_seconds is not None and stats.eta_seconds > 0 and stats.scanned_files > 0:
                eta_str = _format_duration(stats.eta_seconds)
                self.lbl_eta.config(text=tr("time_elapsed_eta", elapsed_str, eta_str))
            else:
                self.lbl_eta.config(text=tr("time_elapsed_empty", elapsed_str))
        else:
            self.lbl_eta.config(text=tr("time_total", elapsed_str))

        # 3. Mise à jour synchronisée de TOUTES les tâches
        for wid, task_info in worker_tasks.items():
            wid_str = str(wid)
            if self.tree_threads.exists(wid_str):
                if isinstance(task_info, (tuple, list)):
                    if len(task_info) >= 4:
                        w_path, w_file, w_progress, w_speed = task_info[0], task_info[1], task_info[2], task_info[3]
                    elif len(task_info) == 3:
                        w_path, w_file, w_progress, w_speed = "-", task_info[0], task_info[1], task_info[2]
                    elif len(task_info) == 2:
                        w_path, w_file, w_progress, w_speed = "-", task_info[0], "-", task_info[1]
                    elif len(task_info) == 1:
                        w_path, w_file, w_progress, w_speed = "-", task_info[0], "-", 0.0
                    else:
                        w_path, w_file, w_progress, w_speed = "-", STATUS_IDLE, "-", 0.0
                else:
                    w_path, w_file, w_progress, w_speed = "-", str(task_info), "-", 0.0

                try:
                    speed_val = float(w_speed)
                    speed_str = f"{speed_val:.1f} {tr('unit_mb_s')}" if speed_val > 0 else "-"
                except (ValueError, TypeError):
                    speed_str = "-"

                self.tree_threads.item(wid_str, values=(f"#{wid + 1}", str(w_path), _format_worker_status(w_file), str(w_progress), speed_str))

        if not stats.is_running:
            self._update_ui_state(running=False)
            if stats.is_completed and not stats.is_aborted and not self._scan_completed_handled:
                self._scan_completed_handled = True
                self._handle_scan_completed(stats)

    def _handle_scan_completed(self, stats: ScanStats):
        """Déclenché une seule fois à la fin naturelle du scan."""
        has_blocking_issue = (stats.corrupted_count > 0 or getattr(stats, "error_count", 0) > 0 or bool(stats.safety_alerts))
        has_error = (has_blocking_issue or stats.locked_count > 0 or stats.missing_count > 0)

        # Avertissement de sécurité si un dossier était vide/inaccessible (sécurité >= 90% manquants)
        if stats.safety_alerts:
            alert_text = "\n\n".join(stats.safety_alerts)
            messagebox.showwarning(tr("safety_alert_title"), alert_text)

        # 1. Notifications natives et sonores standard
        if getattr(self.config, "native_notifications", True):
            if stats.corrupted_count > 0:
                title = tr("notif_corrupt_title")
                msg = tr("notif_corrupt_msg", stats.corrupted_count, stats.scanned_files)
            else:
                title = tr("notif_success_title")
                msg = tr("notif_success_msg", stats.scanned_files)
            show_native_notification(title, msg, is_error=has_error)

        if getattr(self.config, "sound_notification", False):
            self._play_finish_sound(has_error)

        # 2. Action automatique one-shot sélectionnée dans le centre de scan
        action = self._get_selected_post_action()

        if action == "close":
            if not has_blocking_issue:
                logger.info("Fermeture automatique du logiciel.")
                def _do_close():
                    top = self.winfo_toplevel()
                    if hasattr(top, "on_close"):
                        top.on_close()
                    else:
                        top.destroy()
                self.after(1500, _do_close)
            else:
                err_cnt = getattr(stats, "error_count", 0)
                logger.warning(tr("log_auto_close_cancelled", stats.corrupted_count, err_cnt))

        elif action in ("sleep", "shutdown"):
            if not has_blocking_issue:
                self._show_post_scan_dialog(action)
            else:
                err_cnt = getattr(stats, "error_count", 0)
                logger.warning(tr("log_power_action_cancelled", action, stats.corrupted_count, err_cnt))

    def _play_finish_sound(self, has_error: bool):
        """Joue un avertissement sonore à la fin du scan : 1 fois si sain, 3 fois de suite en cas d'erreur."""
        threading.Thread(target=play_completion_sound, args=(has_error, self), daemon=True).start()

    def _cancel_countdown(self):
        """Annule le compte à rebours et ferme le dialogue de mise en veille/extinction s'il est actif."""
        if self._countdown_timer_id is not None:
            try:
                self.after_cancel(self._countdown_timer_id)
            except Exception:
                pass
            self._countdown_timer_id = None

        if self._countdown_dialog is not None:
            try:
                self._countdown_dialog.destroy()
            except Exception:
                pass
            self._countdown_dialog = None

    def _show_post_scan_dialog(self, action: str):
        """Affiche une fenêtre modale avec compte à rebours pour la mise en veille ou l'extinction."""
        self._cancel_countdown()

        is_shutdown = (action == "shutdown")
        total_seconds = 60 if is_shutdown else 30
        self._countdown_seconds_remaining = total_seconds

        dialog = tk.Toplevel(self)
        self._countdown_dialog = dialog
        dialog.title(tr("dlg_power_title"))
        dialog.geometry("480x280")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.transient(self.winfo_toplevel())

        # Déterminer les couleurs du thème
        theme_name = getattr(self.config, "theme", "light")
        bg_main = "#0B0F19" if theme_name == "dark" else "#F8FAFC"
        bg_card = "#111827" if theme_name == "dark" else "#FFFFFF"
        fg_text = "#F8FAFC" if theme_name == "dark" else "#0F172A"
        fg_sub = "#94A3B8" if theme_name == "dark" else "#64748B"
        border_col = "#374151" if theme_name == "dark" else "#E2E8F0"

        dialog.configure(bg=bg_main)

        # Centrage sur la fenêtre parente
        dialog.update_idletasks()
        try:
            parent_x = self.winfo_rootx()
            parent_y = self.winfo_rooty()
            parent_w = self.winfo_width()
            parent_h = self.winfo_height()
            pos_x = parent_x + max(0, (parent_w - 480) // 2)
            pos_y = parent_y + max(0, (parent_h - 280) // 2)
            dialog.geometry(f"480x280+{pos_x}+{pos_y}")
        except Exception:
            pass

        card = tk.Frame(dialog, bg=bg_card, highlightbackground=border_col, highlightthickness=1, padx=20, pady=20)
        card.pack(fill="both", expand=True, padx=12, pady=12)

        icon_text = "🔌" if is_shutdown else "💤"
        action_name = tr("power_shutdown_action") if is_shutdown else tr("power_sleep_action")

        lbl_icon = tk.Label(card, text=icon_text, font=("Segoe UI Emoji", 26), bg=bg_card)
        lbl_icon.pack(pady=(0, 2))

        lbl_title = tk.Label(card, text=tr("power_action_scheduled", action_name), font=FONTS["h2"], fg=fg_text, bg=bg_card)
        lbl_title.pack(pady=(0, 2))

        lbl_sub = tk.Label(
            card,
            text=tr("power_dialog_sub"),
            font=FONTS["small"],
            fg=fg_sub,
            bg=bg_card,
            justify="center"
        )
        lbl_sub.pack(pady=(0, 10))

        self._lbl_countdown = tk.Label(
            card,
            text=tr("power_countdown_sec", total_seconds),
            font=FONTS["body_bold"],
            fg="#EF4444" if is_shutdown else "#3B82F6",
            bg=bg_card
        )
        self._lbl_countdown.pack(pady=(0, 6))

        self._countdown_progress = ttk.Progressbar(card, orient="horizontal", mode="determinate", maximum=total_seconds)
        self._countdown_progress["value"] = total_seconds
        self._countdown_progress.pack(fill="x", pady=(0, 14))

        btn_box = tk.Frame(card, bg=bg_card)
        btn_box.pack(fill="x")

        def on_cancel():
            self._cancel_countdown()
            if is_shutdown:
                try:
                    subprocess.run(["shutdown", "/a"], check=False)
                except Exception:
                    pass

        def on_execute_now():
            self._cancel_countdown()
            self._execute_power_action(action)

        btn_cancel = ttk.Button(btn_box, text=tr("power_btn_cancel"), style="Danger.TButton", command=on_cancel)
        btn_cancel.pack(side="left", fill="x", expand=True, padx=(0, 6))

        exec_label = tr("power_btn_shutdown_now") if is_shutdown else tr("power_btn_sleep_now")
        btn_now = ttk.Button(btn_box, text=exec_label, style="Primary.TButton", command=on_execute_now)
        btn_now.pack(side="right", fill="x", expand=True, padx=(6, 0))

        dialog.protocol("WM_DELETE_WINDOW", on_cancel)

        # Démarrer le décompte
        self._tick_countdown(action, total_seconds)

    def _tick_countdown(self, action: str, total_seconds: int):
        if not self._countdown_dialog or not self._countdown_dialog.winfo_exists():
            return

        self._countdown_seconds_remaining -= 1
        rem = self._countdown_seconds_remaining

        if rem <= 0:
            self._cancel_countdown()
            self._execute_power_action(action)
            return

        if hasattr(self, "_lbl_countdown") and self._lbl_countdown.winfo_exists():
            self._lbl_countdown.config(text=tr("power_countdown_sec", rem))

        if hasattr(self, "_countdown_progress") and self._countdown_progress.winfo_exists():
            self._countdown_progress["value"] = rem

        self._countdown_timer_id = self.after(1000, lambda: self._tick_countdown(action, total_seconds))

    def _execute_power_action(self, action: str):
        """Exécute l'extinction ou la mise en veille sur Windows ou Linux."""
        if action == "shutdown":
            try:
                poweroff_system()
            except Exception as e:
                messagebox.showerror(tr("power_shutdown_error_title"), tr("power_shutdown_error_msg", str(e)))
        elif action == "sleep":
            try:
                suspend_system()
            except Exception as e:
                messagebox.showerror(tr("power_sleep_error_title"), tr("power_sleep_error_msg", str(e)))

    def _on_file_processed(self, record: FileRecord):
        self.event_queue.append(record)

    def _is_record_visible(self, record: FileRecord) -> bool:
        """Détermine si un enregistrement répond aux critères des cases à cocher actives."""
        status_val = record.status.value if hasattr(record.status, "value") else str(record.status)
        if status_val == "CORRUPT" and self.filter_corrupted.get():
            return True
        if status_val == "OK" and self.filter_ok.get():
            return True
        if status_val == "NEW" and self.filter_new.get():
            return True
        if status_val == "MODIFIED" and self.filter_mod.get():
            return True
        if status_val in ("LOCKED", "ERROR", "MISSING") and self.filter_locked.get():
            return True
        return False

    def _refresh_event_list(self):
        """Reconstruit instantanément la liste des événements récents selon les filtres actifs."""
        for item in self.tree_log.get_children():
            self.tree_log.delete(item)

        selected_items = []
        if self.filter_corrupted.get() and "CORRUPT" in self.events_by_type:
            selected_items.extend(self.events_by_type["CORRUPT"])
        if self.filter_mod.get() and "MODIFIED" in self.events_by_type:
            selected_items.extend(self.events_by_type["MODIFIED"])
        if self.filter_new.get() and "NEW" in self.events_by_type:
            selected_items.extend(self.events_by_type["NEW"])
        if self.filter_ok.get() and "OK" in self.events_by_type:
            selected_items.extend(self.events_by_type["OK"])
        if self.filter_locked.get():
            for st_key in ("LOCKED", "ERROR", "MISSING"):
                if st_key in self.events_by_type:
                    selected_items.extend(self.events_by_type[st_key])

        # Trier par numéro de séquence décroissant (événements les plus récents en premier)
        selected_items.sort(key=lambda x: x[0], reverse=True)

        for seq, time_str, record in selected_items[:200]:
            status_val = record.status.value if hasattr(record.status, "value") else str(record.status)
            self.tree_log.insert("", "end", values=(time_str, status_val, record.path))

    def _drain_event_queue(self):
        now_str = time.strftime("%H:%M:%S")
        added = False

        while self.event_queue:
            record = self.event_queue.popleft()
            self._event_seq += 1
            status_val = record.status.value if hasattr(record.status, "value") else str(record.status)
            if status_val not in self.events_by_type:
                self.events_by_type[status_val] = deque(maxlen=500)
            self.events_by_type[status_val].append((self._event_seq, now_str, record))

            if self._is_record_visible(record):
                self.tree_log.insert("", 0, values=(now_str, status_val, record.path))
                added = True

        if added:
            children = self.tree_log.get_children()
            if len(children) > 200:
                for extra in children[200:]:
                    self.tree_log.delete(extra)

        self.after(100, self._drain_event_queue)

    def _on_tree_log_context_menu(self, event):
        row_id = self.tree_log.identify_row(event.y)
        if row_id:
            self.tree_log.selection_set(row_id)
            values = self.tree_log.item(row_id, "values")
            if values and len(values) >= 3:
                file_path = values[2]
                menu = tk.Menu(self, tearoff=0)
                menu.add_command(label=tr("ctx_open_folder"), command=lambda p=file_path: open_in_file_manager(p))
                menu.add_separator()
                menu.add_command(label=tr("ctx_copy_path"), command=lambda p=file_path: self._copy_to_clipboard(p))
                menu.add_command(label=tr("ctx_copy_event_line"), command=lambda line=" | ".join(values): self._copy_to_clipboard(line))
                menu.post(event.x_root, event.y_root)

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    def update_ui_language(self):
        """Met à jour instantanément les textes de la vue lors d'un changement de langue."""
        self.title_lbl.config(text=tr("scan_title"))
        self.btn_full_scan.config(text=tr("btn_full_scan"))
        self.btn_update_scan.config(text=tr("btn_update_scan"))
        self.btn_simple_check.config(text=tr("btn_simple_check"))
        is_paused = bool(self.pool and self.pool.stats.is_paused)
        self.btn_pause.config(text=tr("btn_resume") if is_paused else tr("btn_pause"))
        self.btn_stop.config(text=tr("btn_stop"))

        if hasattr(self, "lbl_post_action"):
            self.lbl_post_action.config(text=tr("lbl_post_scan_short"))
            curr_action = self._get_selected_post_action()
            self.post_action_options = [
                ("none", tr("post_none")),
                ("close", tr("post_close")),
                ("sleep", tr("post_sleep")),
                ("shutdown", tr("post_shutdown"))
            ]
            self.combo_post_action["values"] = [label for _, label in self.post_action_options]
            self._set_post_action(curr_action)

        self.card_speed.set_title(tr("metric_speed"))
        self.card_progress.set_title(tr("metric_progress"))
        self.card_ok.set_title(tr("metric_healthy"))
        self.card_mod.set_title(tr("metric_updated"))
        self.card_corrupted.set_title(tr("metric_corrupted"))
        self.card_locked.set_title(tr("metric_locked"))

        self.lbl_threads_title.config(text=tr("tasks_title"))
        self.tree_threads.heading("id", text=tr("task_col_id"))
        self.tree_threads.heading("path", text=tr("task_col_path"))
        self.tree_threads.heading("file", text=tr("task_col_file"))
        self.tree_threads.heading("progress", text=tr("task_col_progress"))
        self.tree_threads.heading("speed", text=tr("task_col_speed"))

        self.lbl_log_title.config(text=tr("events_title"))
        self.chk_flt_corrupted.config(text=tr("filter_corrupted"))
        self.chk_flt_ok.config(text=tr("filter_healthy"))
        self.chk_flt_new.config(text=tr("filter_new"))
        self.chk_flt_mod.config(text=tr("filter_modified"))
        self.chk_flt_locked.config(text=tr("filter_locked"))

        self.tree_log.heading("time", text=tr("evt_col_time"))
        self.tree_log.heading("status", text=tr("evt_col_status"))
        self.tree_log.heading("file", text=tr("evt_col_file"))

        if not self.pool or not self.pool.stats.is_running:
            if not self.pool or not self.pool.stats.is_completed:
                self.lbl_status_text.config(text=tr("ready_scan"))
                self.lbl_eta.config(text=tr("time_elapsed_empty", "00:00"))
                self.card_speed.set_value(f"0.0 {tr('unit_mb_s')}", tr("metric_speed_waiting"))
                self.card_corrupted.set_value("0", tr("metric_sub_no_alert"))
                self.card_mod.set_value("0", tr("metric_sub_new_mod", 0, 0))
                self.card_locked.set_value("0", tr("metric_sub_locked_missing", 0, 0))
            else:
                self.lbl_eta.config(text=tr("time_total", _format_duration(self.pool.stats.elapsed_time_s)))
                stats = self.pool.stats
                self.card_speed.set_value(f"0.0 {tr('unit_mb_s')}", tr("metric_speed_waiting"))
                self.card_mod.set_value(
                    str(stats.modified_count + stats.new_count),
                    tr("metric_sub_new_mod", stats.new_count, stats.modified_count)
                )
                self.card_corrupted.set_value(
                    str(stats.corrupted_count),
                    tr("metric_sub_no_alert") if stats.corrupted_count == 0 else tr("metric_sub_corrupt")
                )
                self.card_locked.set_value(
                    str(stats.locked_count + stats.missing_count),
                    tr("metric_sub_locked_missing", stats.locked_count, stats.missing_count)
                )

        for wid in range(self.config.global_max_workers):
            wid_str = str(wid)
            if self.tree_threads.exists(wid_str):
                cur_vals = self.tree_threads.item(wid_str, "values")
                if cur_vals and len(cur_vals) >= 5:
                    w_file = cur_vals[2]
                    new_file = _format_worker_status(w_file)
                    self.tree_threads.item(wid_str, values=(cur_vals[0], cur_vals[1], new_file, cur_vals[3], cur_vals[4]))
