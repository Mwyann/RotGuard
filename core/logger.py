"""Système de journalisation en mémoire pour RotGuard.

Conserve les 500 dernières actions, événements et exceptions rencontrées
pour faciliter le diagnostic sans saturer la mémoire ni le disque.
"""

import time
import threading
from typing import List, Dict, Any, Optional, Callable
from collections import deque


class AppLogger:
    """Buffer circulaire thread-safe conservant les N derniers messages de log."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self, max_entries: int = 500):
        self.max_entries = max_entries
        self.entries: deque = deque(maxlen=max_entries)
        self.lock = threading.Lock()
        self.listeners: List[Callable[[Dict[str, Any]], None]] = []

    @classmethod
    def get_instance(cls) -> "AppLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def log(self, level: str, message: str, details: Optional[str] = None):
        """Enregistre un message (INFO, WARNING, ERROR, DEBUG)."""
        now = time.strftime("%H:%M:%S")
        entry = {
            "time": now,
            "level": level.upper(),
            "message": message,
            "details": details or ""
        }

        with self.lock:
            self.entries.append(entry)

        # Affichage direct dans le terminal console
        try:
            extra = f" - {details}" if details else ""
            print(f"[{now}] [{entry['level']}] {message}{extra}", flush=True)
        except Exception:
            pass

        # Notification des écouteurs éventuels (UI)
        for listener in self.listeners:
            try:
                listener(entry)
            except Exception:
                pass

    def info(self, message: str, details: Optional[str] = None):
        self.log("INFO", message, details)

    def warning(self, message: str, details: Optional[str] = None):
        self.log("WARNING", message, details)

    def error(self, message: str, details: Optional[str] = None):
        self.log("ERROR", message, details)

    def debug(self, message: str, details: Optional[str] = None):
        self.log("DEBUG", message, details)

    def get_recent_entries(self, level_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Renvoie une copie des logs récents, avec filtre de niveau optionnel."""
        with self.lock:
            items = list(self.entries)

        if level_filter and level_filter.upper() not in ("TOUS", "ALL"):
            items = [item for item in items if item["level"] == level_filter.upper()]

        return items

    def clear(self):
        """Vide le journal de log."""
        with self.lock:
            self.entries.clear()

    def add_listener(self, callback: Callable[[Dict[str, Any]], None]):
        """Enregistre un écouteur de nouveaux messages."""
        if callback not in self.listeners:
            self.listeners.append(callback)


# Helper global pour faciliter l'accès
logger = AppLogger.get_instance()
