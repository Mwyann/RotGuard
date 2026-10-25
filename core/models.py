"""Modèles de données pour RotGuard."""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Dict, Any
import os
import configparser
import uuid


class FileStatus(str, Enum):
    """Statuts possibles pour un fichier audité."""
    OK = "OK"                     # Fichier intègre (taille, date et hash identiques)
    MODIFIED = "MODIFIED"         # Fichier modifié légitimement (date ou taille différente, hash mis à jour)
    NEW = "NEW"                   # Nouveau fichier découvert et indexé
    CORRUPT = "CORRUPT"           # ALERTE : taille et date identiques mais hash altéré (Bit Rot)
    LOCKED = "LOCKED"             # Inaccessible ou verrouillé par un autre processus / droits
    MISSING = "MISSING"           # Présent dans la base de données mais disparu du disque
    ERROR = "ERROR"               # Erreur d'I/O imprévue


class DiskType(str, Enum):
    """Type de support physique détecté."""
    HDD = "HDD"                   # Disque dur mécanique (1 seul thread recommandé)
    SSD = "SSD"                   # Disque état solide / NVMe (multithreading recommandé)
    REMOVABLE = "REMOVABLE"       # Clé USB ou support amovible
    UNKNOWN = "UNKNOWN"           # Non déterminé (sécurité : conservateur)


@dataclass
class TargetFolder:
    """Configuration d'un dossier ou lecteur cible à auditer."""
    path: str
    alias: str = ""
    max_workers: int = 1          # 1 pour HDD, 4 pour SSD
    buffer_size_bytes: int = 2 * 1024 * 1024  # 2 Mo par défaut
    disk_type: DiskType = DiskType.UNKNOWN
    enabled: bool = True
    id: str = ""

    def __post_init__(self):
        p = self.path.strip()
        if len(p) == 2 and p[1] == ":":
            p += os.sep
        self.path = os.path.abspath(p)
        if not self.alias:
            self.alias = os.path.basename(self.path.rstrip(os.sep)) or self.path
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        self.max_workers = max(1, int(self.max_workers))
        self.buffer_size_bytes = max(64 * 1024, int(self.buffer_size_bytes))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "alias": self.alias,
            "max_workers": self.max_workers,
            "buffer_size_bytes": self.buffer_size_bytes,
            "disk_type": self.disk_type.value if isinstance(self.disk_type, DiskType) else str(self.disk_type),
            "enabled": self.enabled
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TargetFolder":
        disk_type_val = data.get("disk_type", DiskType.UNKNOWN.value)
        try:
            dtype = DiskType(disk_type_val)
        except ValueError:
            dtype = DiskType.UNKNOWN

        return cls(
            id=data.get("id", ""),
            path=data["path"],
            alias=data.get("alias", ""),
            max_workers=data.get("max_workers", 1),
            buffer_size_bytes=data.get("buffer_size_bytes", 2 * 1024 * 1024),
            disk_type=dtype,
            enabled=data.get("enabled", True)
        )


@dataclass
class FileRecord:
    """Enregistrement d'un fichier dans la base de données SQLite."""
    path: str = ""
    size: int = 0
    mtime: float = 0.0
    hash_value: str = ""
    hash_algo: str = "BLAKE2b"
    last_checked_date: Optional[str] = None  # Format ISO 8601 : YYYY-MM-DD HH:MM:SS
    status: FileStatus = FileStatus.NEW
    error_message: Optional[str] = None
    target_id: str = ""
    rel_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "rel_path": self.rel_path,
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "hash_value": self.hash_value,
            "hash_algo": self.hash_algo,
            "last_checked_date": self.last_checked_date,
            "status": self.status.value if isinstance(self.status, FileStatus) else str(self.status),
            "error_message": self.error_message
        }


@dataclass
class ScanStats:
    """Statistiques instantanées et cumulées de la session de scan."""
    total_files_found: int = 0
    scanned_files: int = 0
    ok_count: int = 0
    modified_count: int = 0
    new_count: int = 0
    corrupted_count: int = 0
    locked_count: int = 0
    missing_count: int = 0
    error_count: int = 0  # Erreurs de lecture système / I/O matérielles (secteurs défectueux)
    total_bytes_to_scan: int = 0
    bytes_scanned: int = 0
    current_speed_mb_s: float = 0.0
    elapsed_time_s: float = 0.0
    eta_seconds: Optional[float] = None
    is_running: bool = False
    is_paused: bool = False
    is_completed: bool = False
    is_aborted: bool = False
    current_phase: str = "discovering"  # "discovering", "new_files", "existing_files"
    deleted_clean_count: int = 0  # Fichiers supprimés du disque et nettoyés de la BDD
    safety_alerts: List[str] = field(default_factory=list)  # Alertes de sécurité (ex: >= 90% manquants)


@dataclass
class AppConfig:
    """Configuration globale de l'application RotGuard."""
    targets: List[TargetFolder] = field(default_factory=list)
    global_max_workers: int = 4
    default_buffer_size_mb: float = 2.0
    hash_algorithm: str = "BLAKE2b"
    db_path: str = "rotguard_hashes.db"
    mirror_paths: List[str] = field(default_factory=list)
    auto_elevate_admin: bool = True
    theme: str = "light"
    language: str = "auto"  # "auto", "fr", "en"
    post_scan_action: str = "none"  # "none", "sleep", "shutdown"
    sound_notification: bool = False  # Avertissement sonore en fin de scan (désactivé par défaut)
    cpu_priority: str = "normal"  # "low", "below_normal", "normal", "above_normal", "high"
    io_priority: str = "normal"  # "very_low", "low", "normal", "high"
    preserve_atime: bool = True  # Ne pas modifier l'horodatage de dernier accès (atime)
    delete_to_trash: bool = True  # Déplacer vers la corbeille par défaut au lieu de supprimer définitivement
    native_notifications: bool = True  # Notifications système natives (Windows Toast / Linux notify)
    exclude_patterns: str = "$RECYCLE.BIN, System Volume Information, Thumbs.db, desktop.ini, *.tmp, *.bak, *.log, ~*"
    include_patterns: str = ""  # Vide = tout, sinon motifs séparés par virgules (*.jpg, docs, keep.tmp, etc.)
    min_file_size_kb: int = 0  # Taille min en Ko (0 = aucune)
    max_file_size_mb: int = 0  # Taille max en Mo (0 = illimitée)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "targets": [t.to_dict() for t in self.targets],
            "global_max_workers": self.global_max_workers,
            "default_buffer_size_mb": self.default_buffer_size_mb,
            "hash_algorithm": self.hash_algorithm,
            "db_path": self.db_path,
            "mirror_paths": self.mirror_paths,
            "auto_elevate_admin": self.auto_elevate_admin,
            "theme": self.theme,
            "language": self.language,
            "post_scan_action": self.post_scan_action,
            "sound_notification": self.sound_notification,
            "cpu_priority": self.cpu_priority,
            "io_priority": self.io_priority,
            "preserve_atime": self.preserve_atime,
            "delete_to_trash": self.delete_to_trash,
            "native_notifications": self.native_notifications,
            "exclude_patterns": self.exclude_patterns,
            "include_patterns": self.include_patterns,
            "min_file_size_kb": self.min_file_size_kb,
            "max_file_size_mb": self.max_file_size_mb
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        targets = [TargetFolder.from_dict(t) for t in data.get("targets", [])]
        return cls(
            targets=targets,
            global_max_workers=data.get("global_max_workers", 4),
            default_buffer_size_mb=float(data.get("default_buffer_size_mb", 2.0)),
            hash_algorithm=data.get("hash_algorithm", "BLAKE2b"),
            db_path=data.get("db_path", "rotguard_hashes.db"),
            mirror_paths=data.get("mirror_paths", []),
            auto_elevate_admin=data.get("auto_elevate_admin", True),
            theme=data.get("theme", "light"),
            language=data.get("language", "auto"),
            post_scan_action=data.get("post_scan_action", "none"),
            sound_notification=bool(data.get("sound_notification", False)),
            cpu_priority=data.get("cpu_priority", "normal"),
            io_priority=data.get("io_priority", "normal"),
            preserve_atime=bool(data.get("preserve_atime", True)),
            delete_to_trash=bool(data.get("delete_to_trash", True)),
            native_notifications=bool(data.get("native_notifications", True)),
            exclude_patterns=data.get("exclude_patterns", "$RECYCLE.BIN, System Volume Information, Thumbs.db, desktop.ini, *.tmp, *.bak, *.log, ~*"),
            include_patterns=data.get("include_patterns", ""),
            min_file_size_kb=int(data.get("min_file_size_kb", 0)),
            max_file_size_mb=int(data.get("max_file_size_mb", 0))
        )

    def save_to_file(self, config_path: str = "config.ini"):
        """Sauvegarde les paramètres généraux et les cibles dans un fichier .ini simple et lisible."""
        parser = configparser.ConfigParser()
        parser["General"] = {
            "theme": self.theme,
            "language": self.language,
            "hash_algorithm": self.hash_algorithm,
            "global_max_workers": str(self.global_max_workers),
            "default_buffer_size_mb": str(self.default_buffer_size_mb),
            "auto_elevate_admin": "true" if self.auto_elevate_admin else "false",
            "post_scan_action": self.post_scan_action,
            "sound_notification": "true" if self.sound_notification else "false",
            "cpu_priority": self.cpu_priority,
            "io_priority": self.io_priority,
            "preserve_atime": "true" if self.preserve_atime else "false",
            "native_notifications": "true" if self.native_notifications else "false"
        }
        parser["Filters"] = {
            "exclude_patterns": self.exclude_patterns,
            "include_patterns": self.include_patterns,
            "min_file_size_kb": str(self.min_file_size_kb),
            "max_file_size_mb": str(self.max_file_size_mb)
        }
        parser["Database"] = {
            "db_path": self.db_path,
            "mirror_paths": ";".join(self.mirror_paths)
        }
        for idx, target in enumerate(self.targets, 1):
            parser[f"Target:{idx}"] = {
                "id": target.id,
                "path": target.path,
                "alias": target.alias,
                "max_workers": str(target.max_workers),
                "buffer_size_bytes": str(target.buffer_size_bytes),
                "disk_type": target.disk_type.value if isinstance(target.disk_type, DiskType) else str(target.disk_type),
                "enabled": "true" if target.enabled else "false"
            }

        with open(config_path, "w", encoding="utf-8") as f:
            parser.write(f)

    @classmethod
    def load_from_file(cls, config_path: str = "config.ini") -> "AppConfig":
        """Charge la configuration depuis un fichier .ini."""
        if os.path.exists(config_path):
            try:
                parser = configparser.ConfigParser()
                parser.read(config_path, encoding="utf-8")

                theme = parser.get("General", "theme", fallback="light")
                language = parser.get("General", "language", fallback="auto")
                hash_algo = parser.get("General", "hash_algorithm", fallback="BLAKE2b")
                global_max_workers = parser.getint("General", "global_max_workers", fallback=4)
                default_buffer_size_mb = parser.getfloat("General", "default_buffer_size_mb", fallback=2.0)
                auto_elevate_admin = parser.getboolean("General", "auto_elevate_admin", fallback=True)
                post_scan_action = parser.get("General", "post_scan_action", fallback="none")
                if post_scan_action not in ("none", "sleep", "shutdown"):
                    post_scan_action = "none"
                sound_notification = parser.getboolean("General", "sound_notification", fallback=False)
                cpu_priority = parser.get("General", "cpu_priority", fallback="normal")
                io_priority = parser.get("General", "io_priority", fallback="normal")
                preserve_atime = parser.getboolean("General", "preserve_atime", fallback=True)
                delete_to_trash = parser.getboolean("General", "delete_to_trash", fallback=True)
                native_notifications = parser.getboolean("General", "native_notifications", fallback=True)

                exclude_patterns = parser.get("Filters", "exclude_patterns", fallback="$RECYCLE.BIN, System Volume Information, Thumbs.db, desktop.ini, *.tmp, *.bak, *.log, ~*")
                include_patterns = parser.get("Filters", "include_patterns", fallback="")
                min_file_size_kb = parser.getint("Filters", "min_file_size_kb", fallback=0)
                max_file_size_mb = parser.getint("Filters", "max_file_size_mb", fallback=0)

                db_path = parser.get("Database", "db_path", fallback="rotguard_hashes.db")
                mirror_str = parser.get("Database", "mirror_paths", fallback="")
                mirror_paths = [p.strip() for p in mirror_str.split(";") if p.strip()]

                targets = []
                for sec in parser.sections():
                    if sec.startswith("Target:"):
                        p = parser.get(sec, "path", fallback="")
                        if not p:
                            continue
                        t_id = parser.get(sec, "id", fallback="")
                        alias = parser.get(sec, "alias", fallback="")
                        max_w = parser.getint(sec, "max_workers", fallback=1)
                        buf = parser.getint(sec, "buffer_size_bytes", fallback=2 * 1024 * 1024)
                        dtype_str = parser.get(sec, "disk_type", fallback=DiskType.UNKNOWN.value)
                        try:
                            dtype = DiskType(dtype_str)
                        except ValueError:
                            dtype = DiskType.UNKNOWN
                        enabled = parser.getboolean(sec, "enabled", fallback=True)
                        targets.append(TargetFolder(
                            id=t_id,
                            path=p,
                            alias=alias,
                            max_workers=max_w,
                            buffer_size_bytes=buf,
                            disk_type=dtype,
                            enabled=enabled
                        ))

                return cls(
                    targets=targets,
                    global_max_workers=global_max_workers,
                    default_buffer_size_mb=default_buffer_size_mb,
                    hash_algorithm=hash_algo,
                    db_path=db_path,
                    mirror_paths=mirror_paths,
                    auto_elevate_admin=auto_elevate_admin,
                    theme=theme,
                    language=language,
                    post_scan_action=post_scan_action,
                    sound_notification=sound_notification,
                    cpu_priority=cpu_priority,
                    io_priority=io_priority,
                    preserve_atime=preserve_atime,
                    delete_to_trash=delete_to_trash,
                    native_notifications=native_notifications,
                    exclude_patterns=exclude_patterns,
                    include_patterns=include_patterns,
                    min_file_size_kb=min_file_size_kb,
                    max_file_size_mb=max_file_size_mb
                )
            except Exception:
                pass

        # Configuration par défaut
        cfg = cls()
        cfg.save_to_file(config_path)
        return cfg
