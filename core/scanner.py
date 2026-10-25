"""Module d'exploration d'arborescence et de logique d'intégrité pour RotGuard."""

import os
import threading
from collections import deque
from datetime import datetime
from typing import List, Generator, Tuple, Optional, Set
from core.models import TargetFolder, FileRecord, FileStatus
from core.logger import logger
from core.i18n import tr


# Noms de dossiers Windows/Linux/système à ignorer pour éviter les blocages I/O et les boucles
IGNORED_DIR_NAMES = {
    "$recycle.bin",
    "system volume information",
    "recovery",
    "appdata",
    "windowsapps",
    "wpsystem",
    "deliveryoptimization",
    "dumpstack.log",
    "pagefile.sys",
    "hiberfil.sys",
    "swapfile.sys",
    # Linux / Unix
    "proc",
    "sys",
    "dev",
    "run",
    ".trash",
    ".trash-1000",
    ".cache"
}


import fnmatch


def is_ignored_dir(name: str) -> bool:
    """Vérifie si un nom de dossier doit être écarté du scan (insensible à la casse)."""
    return name.lower() in IGNORED_DIR_NAMES


def matches_pattern(name: str, path: str, pattern: str) -> bool:
    """Vérifie si un fichier ou dossier correspond à un motif (nom, dossier, extension ou wildcard)."""
    p = pattern.strip().lower()
    if not p:
        return False

    lower_name = name.lower()
    lower_path = path.lower().replace("\\", "/")
    p_norm = p.replace("\\", "/")

    # 1. Extension seule (ex: .jpg, .tmp ou *.jpg)
    if p_norm.startswith("."):
        if lower_name.endswith(p_norm):
            return True
        if fnmatch.fnmatch(lower_name, f"*{p_norm}"):
            return True

    # 2. Correspondance exacte sur le nom de fichier ou de dossier
    if lower_name == p_norm:
        return True

    # 3. Correspondance wildcard standard (fnmatch)
    if fnmatch.fnmatch(lower_name, p_norm) or fnmatch.fnmatch(lower_path, p_norm):
        return True
    if fnmatch.fnmatch(lower_path, f"*/{p_norm}") or fnmatch.fnmatch(lower_path, f"*/{p_norm}/*"):
        return True

    # 4. Correspondance de dossier ou segment de chemin (ex: p_norm = "temp", "logs" ou "docs/archive")
    clean_p = p_norm.strip("/")
    path_segments = [seg for seg in lower_path.split("/") if seg]
    if clean_p in path_segments:
        return True
    wrapped_path = f"/{lower_path.strip('/')}/"
    if f"/{clean_p}/" in wrapped_path:
        return True

    return False


def _should_exclude_dir(dir_name: str, dir_path: str, ex_patterns: List[str], inc_patterns: List[str]) -> bool:
    """Détermine si un dossier doit être ignoré du parcours BFS."""
    lower_dir = dir_name.lower()

    # 1. Si le dossier lui-même est expressément inclus ou visé par une inclusion
    is_explicitly_included = False
    if inc_patterns:
        for p in inc_patterns:
            p_clean = p.strip().lower().replace("\\", "/")
            if matches_pattern(dir_name, dir_path, p_clean):
                is_explicitly_included = True
                break
            if "/" in p_clean and (p_clean.startswith(lower_dir + "/") or f"/{lower_dir}/" in f"/{p_clean}"):
                is_explicitly_included = True
                break

    if is_explicitly_included:
        return False

    # 2. Dossiers système protégés (IGNORED_DIR_NAMES)
    if is_ignored_dir(dir_name):
        return True

    # 3. Motifs d'exclusion configurés
    if ex_patterns:
        for p in ex_patterns:
            if matches_pattern(dir_name, dir_path, p):
                return True

    return False


def _should_exclude_file(
    file_name: str,
    file_path: str,
    file_size: int,
    ex_patterns: List[str],
    inc_patterns: List[str],
    min_size: int,
    max_size: int
) -> bool:
    """Détermine si un fichier doit être écarté du scan selon les filtres configurés.
    
    Règle d'or : l'inclusion l'emporte toujours sur l'exclusion.
    """
    # 1. Filtre de taille
    if min_size > 0 and file_size < min_size:
        return True
    if max_size > 0 and file_size > max_size:
        return True

    # 2. Vérification de l'inclusion
    matches_inc = False
    if inc_patterns:
        for p in inc_patterns:
            if matches_pattern(file_name, file_path, p):
                matches_inc = True
                break

    # 3. Vérification de l'exclusion
    matches_ex = False
    if ex_patterns:
        for p in ex_patterns:
            if matches_pattern(file_name, file_path, p):
                matches_ex = True
                break

    # Règle : un fichier exclu mais finalement inclus sera scanné !
    if matches_inc:
        return False

    if matches_ex:
        return True

    # Si des motifs d'inclusion sont spécifiés et que le fichier n'en fait pas partie
    if inc_patterns:
        return True

    return False


def discover_files_in_target(
    target: TargetFolder,
    cancel_event: Optional[threading.Event] = None,
    exclude_patterns: Optional[List[str]] = None,
    include_patterns: Optional[List[str]] = None,
    min_size_bytes: int = 0,
    max_size_bytes: int = 0
) -> Generator[str, None, None]:
    """Parcourt récursivement un dossier/disque cible en Breadth-First Search (BFS).
    
    Prend en compte les filtres d'exclusion/inclusion par noms de dossiers, fichiers,
    extensions et taille. L'inclusion a priorité absolue sur l'exclusion.
    """
    if not os.path.exists(target.path):
        logger.warning(f"Cible introuvable : {target.path}")
        return

    # Préparation des motifs d'exclusion et d'inclusion
    ex_patterns = [p.strip() for p in (exclude_patterns or []) if p.strip()]
    inc_patterns = [p.strip() for p in (include_patterns or []) if p.strip()]

    # Si la cible est un fichier unique
    if os.path.isfile(target.path):
        try:
            st = os.stat(target.path)
            f_size = st.st_size
            f_name = os.path.basename(target.path)
            if not _should_exclude_file(f_name, target.path, f_size, ex_patterns, inc_patterns, min_size_bytes, max_size_bytes):
                yield os.path.abspath(target.path)
        except Exception:
            yield os.path.abspath(target.path)
        return

    visited_dirs: Set[str] = set()
    queue = deque([os.path.abspath(target.path)])

    while queue:
        if cancel_event and cancel_event.is_set():
            break

        current_dir = queue.popleft()
        norm_current = os.path.normcase(os.path.abspath(current_dir))
        if norm_current in visited_dirs:
            continue
        visited_dirs.add(norm_current)

        try:
            with os.scandir(current_dir) as it:
                subdirs = []
                for entry in it:
                    if cancel_event and cancel_event.is_set():
                        break

                    try:
                        # 1. Vérification stricte des Reparse Points Windows (jonctions, liens symboliques, points de montage)
                        try:
                            st = entry.stat(follow_symlinks=False)
                            if hasattr(st, "st_file_attributes") and (st.st_file_attributes & 0x0400):
                                continue  # FILE_ATTRIBUTE_REPARSE_POINT : junction ou symlink NTFS ignoré
                        except (PermissionError, OSError):
                            continue

                        if entry.is_symlink():
                            continue

                        # 2. Séparation dossiers / fichiers avec filtrage
                        if entry.is_dir(follow_symlinks=False):
                            if not _should_exclude_dir(entry.name, entry.path, ex_patterns, inc_patterns):
                                subdirs.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            f_size = st.st_size
                            if not _should_exclude_file(entry.name, entry.path, f_size, ex_patterns, inc_patterns, min_size_bytes, max_size_bytes):
                                yield os.path.abspath(entry.path)

                    except (PermissionError, OSError):
                        continue

                # Ajout des sous-dossiers dans la file BFS
                for sdir in subdirs:
                    queue.append(sdir)

        except (PermissionError, OSError):
            continue


class IntegrityDecider:
    """Applique les règles d'or de décision d'intégrité définies dans le cahier des charges."""

    @staticmethod
    def evaluate_file_integrity(
        file_path: str,
        computed_hash: str,
        hash_algo: str,
        existing_record: Optional[FileRecord],
        current_size: int,
        current_mtime: float,
        target_id: str = "",
        rel_path: str = ""
    ) -> FileRecord:
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tid = target_id or (existing_record.target_id if existing_record else "")
        rpath = rel_path or (existing_record.rel_path if existing_record else "")

        if not existing_record:
            return FileRecord(
                target_id=tid,
                rel_path=rpath,
                path=file_path,
                size=current_size,
                mtime=current_mtime,
                hash_value=computed_hash,
                hash_algo=hash_algo,
                last_checked_date=now_iso,
                status=FileStatus.NEW,
                error_message=None
            )

        mtime_changed = abs(current_mtime - existing_record.mtime) > 1.0
        size_changed = current_size != existing_record.size

        if mtime_changed or size_changed:
            return FileRecord(
                target_id=tid,
                rel_path=rpath,
                path=file_path,
                size=current_size,
                mtime=current_mtime,
                hash_value=computed_hash,
                hash_algo=hash_algo,
                last_checked_date=now_iso,
                status=FileStatus.MODIFIED,
                error_message=None
            )

        # Changement d'algorithme de hachage (re-indexation normale si date et taille inchangées)
        algo_mismatch = (
            existing_record.hash_algo
            and hash_algo.upper().replace("-", "") != existing_record.hash_algo.upper().replace("-", "")
        )
        if algo_mismatch:
            return FileRecord(
                target_id=tid,
                rel_path=rpath,
                path=file_path,
                size=current_size,
                mtime=current_mtime,
                hash_value=computed_hash,
                hash_algo=hash_algo,
                last_checked_date=now_iso,
                status=FileStatus.OK,
                error_message=None
            )

        # Corruption réelle (Bit Rot)
        if computed_hash.lower() != existing_record.hash_value.lower():
            err_msg = tr("err_bit_rot_detected", existing_record.hash_value, computed_hash)
            logger.error(f"CORRUPTION SUR : {file_path}", err_msg)
            return FileRecord(
                target_id=tid,
                rel_path=rpath,
                path=file_path,
                size=current_size,
                mtime=current_mtime,
                hash_value=existing_record.hash_value,  # RÈGLE D'OR : préserver l'empreinte saine d'origine pour maintenir l'alerte
                hash_algo=existing_record.hash_algo or hash_algo,
                last_checked_date=now_iso,
                status=FileStatus.CORRUPT,
                error_message=err_msg
            )

        return FileRecord(
            target_id=tid,
            rel_path=rpath,
            path=file_path,
            size=current_size,
            mtime=current_mtime,
            hash_value=computed_hash,
            hash_algo=hash_algo,
            last_checked_date=now_iso,
            status=FileStatus.OK,
            error_message=None
        )
