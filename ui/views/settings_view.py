"""Vue de configuration globale avec ascenseur vertical fluide et internationalisation."""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable, Optional, Dict, Any

from core.models import AppConfig
from core.database import DatabaseManager
from core.hasher import SUPPORTED_ALGORITHMS
from core.i18n import tr, get_available_languages
from core.platform_utils import apply_process_priorities
from ui.styles import COLORS, FONTS, apply_theme_to_widget_tree

CPU_PRIORITIES = [
    ("low", "prio_cpu_low"),
    ("below_normal", "prio_cpu_below_normal"),
    ("normal", "prio_cpu_normal"),
    ("above_normal", "prio_cpu_above_normal"),
    ("high", "prio_cpu_high"),
]

IO_PRIORITIES = [
    ("very_low", "prio_io_very_low"),
    ("low", "prio_io_low"),
    ("normal", "prio_io_normal"),
    ("high", "prio_io_high"),
]


class SettingsView(tk.Frame):
    """Écran des paramètres avec défilement vertical complet et traduction instantanée."""

    def __init__(
        self,
        parent,
        config: AppConfig,
        db_manager: DatabaseManager,
        on_config_changed: Optional[Callable[[], None]] = None
    ):
        super().__init__(parent, bg=COLORS["bg_main"])
        self.config = config
        self.db_manager = db_manager
        self.on_config_changed = on_config_changed

        self._build_scrollable_container()
        self._build_header()
        self._build_general_section()
        self._build_filters_section()
        self._build_algo_section()
        self._build_concurrency_section()
        self._build_db_and_mirrors_section()
        self._saved_state = self._get_current_state()
        self._tab_entry_state = dict(self._saved_state)
        self._bind_change_listeners()

    def _build_scrollable_container(self):
        # Création d'un Canvas avec barre de défilement verticale
        self.canvas = tk.Canvas(self, bg=COLORS["bg_main"], highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)

        self.scrollable_frame = tk.Frame(self.canvas, bg=COLORS["bg_main"], padx=18, pady=16)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width)
        )

        # Liaison avec la molette de souris
        self.bind_all("<MouseWheel>", self._on_mousewheel)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

    def _on_mousewheel(self, event):
        # Défilement uniquement si la vue est affichée
        if self.winfo_ismapped():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _build_header(self):
        self.header_frame = tk.Frame(self.scrollable_frame, bg=COLORS["bg_main"])
        self.header_frame.pack(fill="x", pady=(0, 14))

        self.title_lbl = tk.Label(
            self.header_frame,
            text=tr("settings_title"),
            font=FONTS["title"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_main"]
        )
        self.title_lbl.pack(side="left")

        self.btn_save = ttk.Button(
            self.header_frame,
            text=tr("btn_save_settings"),
            style="Primary.TButton",
            command=self._save_settings
        )
        self.btn_save.pack(side="right")

        self.btn_cancel = ttk.Button(
            self.header_frame,
            text=tr("btn_cancel_settings"),
            style="Secondary.TButton",
            command=self._cancel_modifications,
            state="disabled"
        )
        self.btn_cancel.pack(side="right", padx=(0, 8))

    def _bind_change_listeners(self):
        """Attache des écouteurs de modification sur l'ensemble des champs pour actualiser l'état du bouton Annuler."""
        # Variables Tkinter
        self.theme_var.trace_add("write", lambda *a: self.check_modified_status())
        self.sound_var.trace_add("write", lambda *a: self.check_modified_status())
        self.preserve_atime_var.trace_add("write", lambda *a: self.check_modified_status())
        self.native_notif_var.trace_add("write", lambda *a: self.check_modified_status())
        self.algo_var.trace_add("write", lambda *a: self.check_modified_status())

        # Comboboxes
        self.combo_post_scan.bind("<<ComboboxSelected>>", lambda e: self.check_modified_status())
        self.combo_cpu_prio.bind("<<ComboboxSelected>>", lambda e: self.check_modified_status())
        self.combo_io_prio.bind("<<ComboboxSelected>>", lambda e: self.check_modified_status())

        # Entrées texte
        for entry in (self.entry_exclude_patterns, self.entry_include_patterns, self.entry_db_path):
            entry.bind("<KeyRelease>", lambda e: self.check_modified_status())
            entry.bind("<FocusOut>", lambda e: self.check_modified_status())

        # Spinbox (clavier + incrément/décrément souris)
        for spin in (self.spin_min_size, self.spin_max_size, self.spin_global_workers, self.spin_default_buffer):
            spin.bind("<KeyRelease>", lambda e: self.check_modified_status())
            spin.bind("<FocusOut>", lambda e: self.check_modified_status())
            spin.bind("<<Increment>>", lambda e: self.after_idle(self.check_modified_status))
            spin.bind("<<Decrement>>", lambda e: self.after_idle(self.check_modified_status))
            spin.bind("<ButtonRelease-1>", lambda e: self.after_idle(self.check_modified_status))

    def _build_general_section(self):
        self.sec1_frame = tk.LabelFrame(
            self.scrollable_frame,
            text=tr("sec_appearance"),
            font=FONTS["body_bold"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            padx=14,
            pady=10
        )
        self.sec1_frame.pack(fill="x", pady=(0, 14))

        self.lbl_theme_desc = tk.Label(
            self.sec1_frame,
            text=tr("lbl_theme_desc"),
            font=FONTS["body"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"]
        )
        self.lbl_theme_desc.pack(anchor="w", pady=(0, 8))

        theme_box = tk.Frame(self.sec1_frame, bg=COLORS["bg_card"])
        theme_box.pack(fill="x")

        self.theme_var = tk.StringVar(value=getattr(self.config, "theme", "light") or "light")

        self.rb_theme_light = ttk.Radiobutton(
            theme_box,
            text=tr("theme_light"),
            value="light",
            variable=self.theme_var,
            command=self._on_theme_changed
        )
        self.rb_theme_light.pack(side="left", padx=(0, 20))

        self.rb_theme_dark = ttk.Radiobutton(
            theme_box,
            text=tr("theme_dark"),
            value="dark",
            variable=self.theme_var,
            command=self._on_theme_changed
        )
        self.rb_theme_dark.pack(side="left")

        # Sélection de la langue sous forme de menu déroulant (par défaut en premier, puis ordre alphabétique)
        self.lbl_lang = tk.Label(
            self.sec1_frame,
            text=tr("lbl_language"),
            font=FONTS["body_bold"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_card"]
        )
        self.lbl_lang.pack(anchor="w", pady=(14, 6))

        lang_box = tk.Frame(self.sec1_frame, bg=COLORS["bg_card"])
        lang_box.pack(fill="x")

        self.current_lang_code = getattr(self.config, "language", "auto") or "auto"
        self.combo_lang_items = get_available_languages()

        self.combo_lang = ttk.Combobox(
            lang_box,
            state="readonly",
            width=28,
            values=[name for _, name in self.combo_lang_items]
        )
        self._set_combobox_to_code(self.current_lang_code)
        self.combo_lang.pack(side="left")
        self.combo_lang.bind("<<ComboboxSelected>>", self._on_language_combobox_selected)

        # Action en fin de scan
        self.lbl_post_scan = tk.Label(
            self.sec1_frame,
            text=tr("lbl_post_scan"),
            font=FONTS["body_bold"],
            fg=COLORS["text_primary"],
            bg=COLORS["bg_card"]
        )
        self.lbl_post_scan.pack(anchor="w", pady=(14, 6))

        post_box = tk.Frame(self.sec1_frame, bg=COLORS["bg_card"])
        post_box.pack(fill="x")

        self.post_scan_options = [
            ("none", tr("post_none")),
            ("close", tr("post_close")),
            ("sleep", tr("post_sleep")),
            ("shutdown", tr("post_shutdown"))
        ]
        self.combo_post_scan = ttk.Combobox(
            post_box,
            state="readonly",
            width=28,
            values=[label for _, label in self.post_scan_options]
        )
        self._set_post_scan_combobox(getattr(self.config, "post_scan_action", "none") or "none")
        self.combo_post_scan.pack(side="left")

        # Avertissement sonore
        self.sound_var = tk.BooleanVar(value=getattr(self.config, "sound_notification", False))
        self.chk_sound = ttk.Checkbutton(
            self.sec1_frame,
            text=tr("lbl_sound"),
            variable=self.sound_var
        )
        self.chk_sound.pack(anchor="w", pady=(12, 0))

        # Intégration système & furtivité
        self.preserve_atime_var = tk.BooleanVar(value=getattr(self.config, "preserve_atime", True))
        self.chk_preserve_atime = ttk.Checkbutton(
            self.sec1_frame,
            text=tr("lbl_preserve_atime"),
            variable=self.preserve_atime_var
        )
        self.chk_preserve_atime.pack(anchor="w", pady=(8, 0))

        self.native_notif_var = tk.BooleanVar(value=getattr(self.config, "native_notifications", True))
        self.chk_native_notif = ttk.Checkbutton(
            self.sec1_frame,
            text=tr("lbl_native_notifications"),
            variable=self.native_notif_var
        )
        self.chk_native_notif.pack(anchor="w", pady=(8, 0))

    def _build_filters_section(self):
        self.sec_flt_frame = tk.LabelFrame(
            self.scrollable_frame,
            text=tr("sec_filters"),
            font=FONTS["body_bold"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            padx=14,
            pady=10
        )
        self.sec_flt_frame.pack(fill="x", pady=(0, 14))

        self.lbl_filters_desc = tk.Label(
            self.sec_flt_frame,
            text=tr("lbl_filters_desc"),
            font=FONTS["body"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"],
            wraplength=750,
            justify="left"
        )
        self.lbl_filters_desc.pack(anchor="w", pady=(0, 8))

        # Motifs d'exclusion
        self.lbl_exclude_patterns = tk.Label(
            self.sec_flt_frame,
            text=tr("lbl_exclude_patterns"),
            font=FONTS["small_bold"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"]
        )
        self.lbl_exclude_patterns.pack(anchor="w", pady=(4, 2))

        self.entry_exclude_patterns = ttk.Entry(self.sec_flt_frame)
        self.entry_exclude_patterns.insert(0, getattr(self.config, "exclude_patterns", "") or "")
        self.entry_exclude_patterns.pack(fill="x", pady=(0, 8))

        # Motifs d'inclusion
        self.lbl_include_patterns = tk.Label(
            self.sec_flt_frame,
            text=tr("lbl_include_patterns"),
            font=FONTS["small_bold"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"]
        )
        self.lbl_include_patterns.pack(anchor="w", pady=(4, 2))

        init_inc = self.config.include_patterns or ""
        self.entry_include_patterns = ttk.Entry(self.sec_flt_frame)
        self.entry_include_patterns.insert(0, init_inc)
        self.entry_include_patterns.pack(fill="x", pady=(0, 8))

        # Tailles min et max
        size_grid = tk.Frame(self.sec_flt_frame, bg=COLORS["bg_card"])
        size_grid.pack(fill="x", pady=(4, 0))

        self.lbl_min_file_size = tk.Label(
            size_grid,
            text=tr("lbl_min_file_size"),
            font=FONTS["body"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"]
        )
        self.lbl_min_file_size.grid(row=0, column=0, sticky="w", pady=4)

        self.spin_min_size = ttk.Spinbox(size_grid, from_=0, to=100000000, increment=1, width=12)
        self.spin_min_size.set(getattr(self.config, "min_file_size_kb", 0) or 0)
        self.spin_min_size.grid(row=0, column=1, sticky="w", padx=8, pady=4)

        self.lbl_max_file_size = tk.Label(
            size_grid,
            text=tr("lbl_max_file_size"),
            font=FONTS["body"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"]
        )
        self.lbl_max_file_size.grid(row=1, column=0, sticky="w", pady=4)

        self.spin_max_size = ttk.Spinbox(size_grid, from_=0, to=100000000, increment=1, width=12)
        self.spin_max_size.set(getattr(self.config, "max_file_size_mb", 0) or 0)
        self.spin_max_size.grid(row=1, column=1, sticky="w", padx=8, pady=4)

    def _build_algo_section(self):
        self.sec2_frame = tk.LabelFrame(
            self.scrollable_frame,
            text=tr("sec_algo"),
            font=FONTS["body_bold"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            padx=14,
            pady=10
        )
        self.sec2_frame.pack(fill="x", pady=(0, 14))

        self.lbl_algo_desc = tk.Label(
            self.sec2_frame,
            text=tr("lbl_algo_desc"),
            font=FONTS["body"],
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"],
            wraplength=750,
            justify="left"
        )
        self.lbl_algo_desc.pack(anchor="w", pady=(0, 8))

        algo_box = tk.Frame(self.sec2_frame, bg=COLORS["bg_card"])
        algo_box.pack(fill="x")

        self.algo_var = tk.StringVar(value=self.config.hash_algorithm)

        for algo in SUPPORTED_ALGORITHMS:
            text = algo
            if algo == "BLAKE2b":
                text = "BLAKE2b (C ultra-rapide 64-bit natif, 512-bit)"
            elif algo == "CRC32":
                text = "CRC32 (Standard rapide, non cryptographique)"
            elif algo == "SpookyHash":
                text = "SpookyHash V2 (128-bit Bob Jenkins, haute performance)"

            rb = ttk.Radiobutton(
                algo_box,
                text=text,
                value=algo,
                variable=self.algo_var,
                command=self._on_algo_changed
            )
            rb.pack(anchor="w", pady=2)

    def _build_concurrency_section(self):
        self.sec3_frame = tk.LabelFrame(
            self.scrollable_frame,
            text=tr("sec_perf"),
            font=FONTS["body_bold"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            padx=14,
            pady=10
        )
        self.sec3_frame.pack(fill="x", pady=(0, 14))

        grid = tk.Frame(self.sec3_frame, bg=COLORS["bg_card"])
        grid.pack(fill="x")

        self.lbl_max_workers = tk.Label(grid, text=tr("lbl_max_workers"), font=FONTS["body"], bg=COLORS["bg_card"], fg=COLORS["text_primary"])
        self.lbl_max_workers.grid(row=0, column=0, sticky="w", pady=4)
        self.spin_global_workers = ttk.Spinbox(grid, from_=1, to=32, width=8)
        self.spin_global_workers.set(self.config.global_max_workers)
        self.spin_global_workers.grid(row=0, column=1, sticky="w", padx=8, pady=4)

        self.lbl_default_buffer = tk.Label(grid, text=tr("lbl_default_buffer"), font=FONTS["body"], bg=COLORS["bg_card"], fg=COLORS["text_primary"])
        self.lbl_default_buffer.grid(row=1, column=0, sticky="w", pady=4)
        self.spin_default_buffer = ttk.Spinbox(grid, from_=0.5, to=32.0, increment=0.5, width=8)
        self.spin_default_buffer.set(self.config.default_buffer_size_mb)
        self.spin_default_buffer.grid(row=1, column=1, sticky="w", padx=8, pady=4)

        self.lbl_cpu_prio = tk.Label(grid, text=tr("lbl_cpu_priority"), font=FONTS["body"], bg=COLORS["bg_card"], fg=COLORS["text_primary"])
        self.lbl_cpu_prio.grid(row=2, column=0, sticky="w", pady=4)
        self.combo_cpu_prio = ttk.Combobox(grid, state="readonly", width=28)
        self.combo_cpu_prio.grid(row=2, column=1, sticky="w", padx=8, pady=4)

        self.lbl_io_prio = tk.Label(grid, text=tr("lbl_io_priority"), font=FONTS["body"], bg=COLORS["bg_card"], fg=COLORS["text_primary"])
        self.lbl_io_prio.grid(row=3, column=0, sticky="w", pady=4)
        self.combo_io_prio = ttk.Combobox(grid, state="readonly", width=28)
        self.combo_io_prio.grid(row=3, column=1, sticky="w", padx=8, pady=4)

        self._refresh_priority_comboboxes()

    def _build_db_and_mirrors_section(self):
        self.sec4_frame = tk.LabelFrame(
            self.scrollable_frame,
            text=tr("sec_db"),
            font=FONTS["body_bold"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"],
            padx=14,
            pady=10
        )
        self.sec4_frame.pack(fill="x", pady=(0, 14))

        self.lbl_db_path = tk.Label(self.sec4_frame, text=tr("lbl_db_path"), font=FONTS["small_bold"], bg=COLORS["bg_card"], fg=COLORS["text_primary"])
        self.lbl_db_path.pack(anchor="w", pady=(0, 2))

        db_row = tk.Frame(self.sec4_frame, bg=COLORS["bg_card"])
        db_row.pack(fill="x", pady=(0, 10))

        self.entry_db_path = ttk.Entry(db_row)
        self.entry_db_path.insert(0, self.config.db_path)
        self.entry_db_path.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_browse_db = ttk.Button(db_row, text=tr("dlg_target_btn_browse"), style="Secondary.TButton", command=self._browse_primary_db)
        self.btn_browse_db.pack(side="right")

        self.lbl_mirrors = tk.Label(
            self.sec4_frame,
            text=tr("lbl_mirrors"),
            font=FONTS["small_bold"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"]
        )
        self.lbl_mirrors.pack(anchor="w", pady=(0, 2))

        mirror_container = tk.Frame(self.sec4_frame, bg=COLORS["bg_card"])
        mirror_container.pack(fill="x")

        self.listbox_mirrors = tk.Listbox(
            mirror_container,
            height=3,
            font=FONTS["small"],
            selectmode="browse",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            bg=COLORS["bg_card"],
            fg=COLORS["text_primary"]
        )
        for m in self.config.mirror_paths:
            self.listbox_mirrors.insert("end", m)
        self.listbox_mirrors.pack(side="left", fill="x", expand=True, padx=(0, 8))

        mirror_btns = tk.Frame(mirror_container, bg=COLORS["bg_card"])
        mirror_btns.pack(side="right", fill="y")

        self.btn_add_mirror = ttk.Button(mirror_btns, text=tr("btn_add_mirror"), style="Secondary.TButton", command=self._add_mirror)
        self.btn_add_mirror.pack(fill="x", pady=2)

        self.btn_del_mirror = ttk.Button(mirror_btns, text=tr("btn_remove_mirror"), style="Secondary.TButton", command=self._remove_mirror)
        self.btn_del_mirror.pack(fill="x", pady=2)

    def update_ui_language(self):
        """Met à jour instantanément tous les textes de la vue Paramètres."""
        self.title_lbl.config(text=tr("settings_title"))
        self.sec1_frame.config(text=tr("sec_appearance"))
        self.lbl_theme_desc.config(text=tr("lbl_theme_desc"))
        self.rb_theme_light.config(text=tr("theme_light"))
        self.rb_theme_dark.config(text=tr("theme_dark"))
        self.lbl_lang.config(text=tr("lbl_language"))

        # Actualiser les libellés de la liste déroulante
        self.combo_lang_items = get_available_languages()
        self.combo_lang.config(values=[name for _, name in self.combo_lang_items])
        self._set_combobox_to_code(self.current_lang_code)

        self.lbl_post_scan.config(text=tr("lbl_post_scan"))
        cur_post = self._get_selected_post_scan()
        self.post_scan_options = [
            ("none", tr("post_none")),
            ("close", tr("post_close")),
            ("sleep", tr("post_sleep")),
            ("shutdown", tr("post_shutdown"))
        ]
        self.combo_post_scan.config(values=[label for _, label in self.post_scan_options])
        self._set_post_scan_combobox(cur_post)
        self.chk_sound.config(text=tr("lbl_sound"))
        self.chk_preserve_atime.config(text=tr("lbl_preserve_atime"))
        self.chk_native_notif.config(text=tr("lbl_native_notifications"))

        self.sec_flt_frame.config(text=tr("sec_filters"))
        self.lbl_filters_desc.config(text=tr("lbl_filters_desc"))
        self.lbl_exclude_patterns.config(text=tr("lbl_exclude_patterns"))
        self.lbl_include_patterns.config(text=tr("lbl_include_patterns"))
        self.lbl_min_file_size.config(text=tr("lbl_min_file_size"))
        self.lbl_max_file_size.config(text=tr("lbl_max_file_size"))

        self.sec2_frame.config(text=tr("sec_algo"))
        self.lbl_algo_desc.config(text=tr("lbl_algo_desc"))

        self.sec3_frame.config(text=tr("sec_perf"))
        self.lbl_max_workers.config(text=tr("lbl_max_workers"))
        self.lbl_default_buffer.config(text=tr("lbl_default_buffer"))
        self.lbl_cpu_prio.config(text=tr("lbl_cpu_priority"))
        self.lbl_io_prio.config(text=tr("lbl_io_priority"))
        self._refresh_priority_comboboxes()

        self.sec4_frame.config(text=tr("sec_db"))
        self.lbl_db_path.config(text=tr("lbl_db_path"))
        self.btn_browse_db.config(text=tr("dlg_target_btn_browse"))
        self.lbl_mirrors.config(text=tr("lbl_mirrors"))
        self.btn_add_mirror.config(text=tr("btn_add_mirror"))
        self.btn_del_mirror.config(text=tr("btn_remove_mirror"))

        self.btn_save.config(text=tr("btn_save_settings"))
        if hasattr(self, "btn_cancel"):
            self.btn_cancel.config(text=tr("btn_cancel_settings"))

    def apply_theme_colors(self, colors: Dict[str, Any]):
        self.configure(bg=colors["bg_main"])
        self.canvas.configure(bg=colors["bg_main"])
        self.scrollable_frame.configure(bg=colors["bg_main"])
        if hasattr(self, "header_frame"):
            self.header_frame.configure(bg=colors["bg_main"])
        apply_theme_to_widget_tree(self.scrollable_frame, colors)

    def _set_combobox_to_code(self, lang_code: str):
        """Positionne le Combobox sur le libellé correspondant au code donné."""
        for idx, (code, _) in enumerate(self.combo_lang_items):
            if code == lang_code:
                self.combo_lang.current(idx)
                return
        if self.combo_lang_items:
            self.combo_lang.current(0)

    def _set_post_scan_combobox(self, action_code: str):
        """Positionne la liste déroulante sur l'action de fin de scan spécifiée."""
        for idx, (code, _) in enumerate(self.post_scan_options):
            if code == action_code:
                self.combo_post_scan.current(idx)
                return
        if self.post_scan_options:
            self.combo_post_scan.current(0)

    def _get_selected_post_scan(self) -> str:
        """Retourne le code de l'action de fin de scan sélectionnée."""
        idx = self.combo_post_scan.current()
        if 0 <= idx < len(self.post_scan_options):
            return self.post_scan_options[idx][0]
        return "none"

    def _refresh_priority_comboboxes(self):
        """Met à jour les libellés traduits et la sélection des menus de priorité CPU et I/O."""
        c_idx = self.combo_cpu_prio.current()
        current_cpu = CPU_PRIORITIES[c_idx][0] if 0 <= c_idx < len(CPU_PRIORITIES) else (getattr(self.config, "cpu_priority", "normal") or "normal")

        i_idx = self.combo_io_prio.current()
        current_io = IO_PRIORITIES[i_idx][0] if 0 <= i_idx < len(IO_PRIORITIES) else (getattr(self.config, "io_priority", "normal") or "normal")

        cpu_labels = [tr(k) for _, k in CPU_PRIORITIES]
        self.combo_cpu_prio.config(values=cpu_labels)
        for i, (code, _) in enumerate(CPU_PRIORITIES):
            if code == current_cpu:
                self.combo_cpu_prio.current(i)
                break
        else:
            self.combo_cpu_prio.current(2)

        io_labels = [tr(k) for _, k in IO_PRIORITIES]
        self.combo_io_prio.config(values=io_labels)
        for i, (code, _) in enumerate(IO_PRIORITIES):
            if code == current_io:
                self.combo_io_prio.current(i)
                break
        else:
            self.combo_io_prio.current(2)

    def _on_language_combobox_selected(self, event=None):
        """Active immédiatement la nouvelle langue sélectionnée pour prévisualisation."""
        idx = self.combo_lang.current()
        if 0 <= idx < len(self.combo_lang_items):
            selected_code = self.combo_lang_items[idx][0]
            self.current_lang_code = selected_code
            self.config.language = selected_code
            if self.on_config_changed:
                self.on_config_changed()
        self.check_modified_status()

    def _on_theme_changed(self):
        """Active immédiatement le thème choisi pour prévisualisation."""
        new_theme = self.theme_var.get()
        self.config.theme = new_theme
        if self.on_config_changed:
            self.on_config_changed()
        self.check_modified_status()

    def _on_algo_changed(self):
        """Prise en compte de l'algorithme sélectionné."""
        self.check_modified_status()

    def _browse_primary_db(self):
        chosen = filedialog.asksaveasfilename(
            title=tr("dlg_db_browse_title"),
            defaultextension=".db",
            filetypes=[("Base SQLite", "*.db"), ("Tous les fichiers", "*.*")]
        )
        if chosen:
            self.entry_db_path.delete(0, "end")
            self.entry_db_path.insert(0, os.path.abspath(chosen))
            self.check_modified_status()

    def _add_mirror(self):
        chosen = filedialog.asksaveasfilename(
            title=tr("dlg_mirror_browse_title"),
            defaultextension=".db",
            filetypes=[("Base SQLite", "*.db"), ("Tous les fichiers", "*.*")]
        )
        if chosen:
            path = os.path.abspath(chosen)
            if path not in self.listbox_mirrors.get(0, "end"):
                self.listbox_mirrors.insert("end", path)
                self.check_modified_status()

    def _remove_mirror(self):
        sel = self.listbox_mirrors.curselection()
        if sel:
            self.listbox_mirrors.delete(sel[0])
            self.check_modified_status()

    def _get_current_state(self) -> Dict[str, Any]:
        """Capture l'état actuel de tous les champs et contrôles de la vue."""
        cpu_code = "normal"
        c_idx = self.combo_cpu_prio.current()
        if 0 <= c_idx < len(CPU_PRIORITIES):
            cpu_code = CPU_PRIORITIES[c_idx][0]

        io_code = "normal"
        i_idx = self.combo_io_prio.current()
        if 0 <= i_idx < len(IO_PRIORITIES):
            io_code = IO_PRIORITIES[i_idx][0]

        try:
            min_sz = max(0, int(self.spin_min_size.get()))
        except (ValueError, TypeError):
            min_sz = 0

        try:
            max_sz = max(0, int(self.spin_max_size.get()))
        except (ValueError, TypeError):
            max_sz = 0

        try:
            workers = int(self.spin_global_workers.get())
        except (ValueError, TypeError):
            workers = 4

        try:
            buf = float(self.spin_default_buffer.get())
        except (ValueError, TypeError):
            buf = 2.0

        return {
            "theme": self.theme_var.get(),
            "language": getattr(self, "current_lang_code", "auto"),
            "post_scan_action": self._get_selected_post_scan(),
            "sound_notification": bool(self.sound_var.get()),
            "preserve_atime": bool(self.preserve_atime_var.get()),
            "native_notifications": bool(self.native_notif_var.get()),
            "exclude_patterns": self.entry_exclude_patterns.get().strip(),
            "include_patterns": self.entry_include_patterns.get().strip(),
            "min_file_size_kb": min_sz,
            "max_file_size_mb": max_sz,
            "hash_algorithm": self.algo_var.get(),
            "global_max_workers": workers,
            "default_buffer_size_mb": buf,
            "cpu_priority": cpu_code,
            "io_priority": io_code,
            "db_path": self.entry_db_path.get().strip(),
            "mirror_paths": list(self.listbox_mirrors.get(0, "end")),
        }

    def on_tab_enter(self):
        """Enregistre l'état des réglages au moment où l'utilisateur entre dans l'onglet."""
        self._tab_entry_state = self._get_current_state()
        self.check_modified_status()

    def ack_current_modifications(self):
        """Valide la conservation des modifications en mémoire sans les écrire sur le disque."""
        self._tab_entry_state = self._get_current_state()

    def has_new_modifications_since_entry(self) -> bool:
        """Retourne True si un paramètre a été modifié depuis l'entrée dans l'onglet."""
        if not hasattr(self, "_tab_entry_state"):
            return self.has_unsaved_changes()
        return self._get_current_state() != self._tab_entry_state

    def has_unsaved_changes(self) -> bool:
        """Retourne True si un ou plusieurs paramètres ont été modifiés sans être enregistrés."""
        if not hasattr(self, "_saved_state"):
            return False
        return self._get_current_state() != self._saved_state

    def check_modified_status(self, *args):
        """Active ou désactive le bouton Annuler selon s'il y a des modifications non enregistrées."""
        if hasattr(self, "btn_cancel"):
            is_dirty = self.has_unsaved_changes()
            self.btn_cancel.config(state="normal" if is_dirty else "disabled")

    def _cancel_modifications(self):
        """Annule toutes les modifications non enregistrées et rétablit la configuration sauvegardée."""
        self.reset_to_saved_state()

    def reset_to_saved_state(self):
        """Réinitialise tous les contrôles graphiques à leur état sauvegardé."""
        if not hasattr(self, "_saved_state"):
            return
        s = self._saved_state
        self.theme_var.set(s["theme"])
        self.current_lang_code = s["language"]
        self._set_combobox_to_code(s["language"])
        self._set_post_scan_combobox(s["post_scan_action"])
        self.sound_var.set(s["sound_notification"])
        self.preserve_atime_var.set(s["preserve_atime"])
        self.native_notif_var.set(s["native_notifications"])

        self.entry_exclude_patterns.delete(0, "end")
        self.entry_exclude_patterns.insert(0, s["exclude_patterns"])

        self.entry_include_patterns.delete(0, "end")
        self.entry_include_patterns.insert(0, s["include_patterns"])

        self.spin_min_size.set(s["min_file_size_kb"])
        self.spin_max_size.set(s["max_file_size_mb"])

        self.algo_var.set(s["hash_algorithm"])
        self.spin_global_workers.set(s["global_max_workers"])
        self.spin_default_buffer.set(s["default_buffer_size_mb"])

        for i, (code, _) in enumerate(CPU_PRIORITIES):
            if code == s["cpu_priority"]:
                self.combo_cpu_prio.current(i)
                break

        for i, (code, _) in enumerate(IO_PRIORITIES):
            if code == s["io_priority"]:
                self.combo_io_prio.current(i)
                break

        self.entry_db_path.delete(0, "end")
        self.entry_db_path.insert(0, s["db_path"])

        self.listbox_mirrors.delete(0, "end")
        for m in s["mirror_paths"]:
            self.listbox_mirrors.insert("end", m)

        # Restaurer la configuration et actualiser le thème / la langue si modifiés
        need_refresh = (self.config.theme != s["theme"] or getattr(self.config, "language", "auto") != s["language"])
        self.config.theme = s["theme"]
        self.config.language = s["language"]
        if need_refresh and self.on_config_changed:
            self.on_config_changed()

        self._tab_entry_state = dict(self._saved_state)
        self.check_modified_status()

    def _save_settings(self, show_message: bool = True) -> bool:
        """Enregistre la configuration dans le fichier config.ini et applique les réglages."""
        try:
            self.config.theme = self.theme_var.get()
            self.config.language = getattr(self, "current_lang_code", "auto")
            self.config.post_scan_action = self._get_selected_post_scan()
            self.config.sound_notification = self.sound_var.get()
            self.config.preserve_atime = self.preserve_atime_var.get()
            self.config.native_notifications = self.native_notif_var.get()

            self.config.exclude_patterns = self.entry_exclude_patterns.get().strip()
            inc_val = self.entry_include_patterns.get().strip()
            self.config.include_patterns = inc_val
            try:
                self.config.min_file_size_kb = max(0, int(self.spin_min_size.get()))
            except ValueError:
                self.config.min_file_size_kb = 0
            try:
                self.config.max_file_size_mb = max(0, int(self.spin_max_size.get()))
            except ValueError:
                self.config.max_file_size_mb = 0

            self.config.hash_algorithm = self.algo_var.get()
            self.config.global_max_workers = int(self.spin_global_workers.get())
            self.config.default_buffer_size_mb = float(self.spin_default_buffer.get())

            cpu_idx = self.combo_cpu_prio.current()
            if 0 <= cpu_idx < len(CPU_PRIORITIES):
                self.config.cpu_priority = CPU_PRIORITIES[cpu_idx][0]

            io_idx = self.combo_io_prio.current()
            if 0 <= io_idx < len(IO_PRIORITIES):
                self.config.io_priority = IO_PRIORITIES[io_idx][0]

            self.config.db_path = self.entry_db_path.get().strip() or "rotguard_hashes.db"
            self.config.mirror_paths = list(self.listbox_mirrors.get(0, "end"))

            self.config.save_to_file()
            self.db_manager.update_mirror_paths(self.config.mirror_paths)
            apply_process_priorities(self.config.cpu_priority, self.config.io_priority)

            self._saved_state = self._get_current_state()
            self._tab_entry_state = dict(self._saved_state)
            self.check_modified_status()

            if self.on_config_changed:
                self.on_config_changed()

            if show_message:
                messagebox.showinfo(tr("settings_saved_title"), tr("settings_saved_msg"), parent=self)
            return True
        except Exception as e:
            messagebox.showerror(tr("settings_save_error_title"), tr("settings_save_error_msg", str(e)), parent=self)
            return False
