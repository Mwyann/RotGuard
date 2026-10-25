"""Gestionnaire de base de données SQLite pour RotGuard :
- Stockage par identifiant unique de cible (target_id) et chemin relatif (rel_path)
- Portabilité totale des cibles (renommage, changement de lettre sans recalcul de hash)
- Écriture miroir simultanée et persistance optimisée
- Purge instantanée en cascade lors de la suppression d'une cible
"""

import os
import sqlite3
import threading
from typing import List, Optional, Dict, Any, Generator, Tuple, Callable
from core.models import FileRecord, FileStatus, TargetFolder
from core.logger import logger


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
    target_id TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    hash_value TEXT NOT NULL,
    hash_algo TEXT NOT NULL,
    last_checked_date TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    PRIMARY KEY (target_id, rel_path)
);

CREATE INDEX IF NOT EXISTS idx_files_target ON files(target_id);
CREATE INDEX IF NOT EXISTS idx_files_last_checked ON files(last_checked_date);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_algo ON files(hash_algo);
CREATE INDEX IF NOT EXISTS idx_files_hash_size ON files(hash_value, size);
CREATE INDEX IF NOT EXISTS idx_files_target_status ON files(target_id, status);
CREATE INDEX IF NOT EXISTS idx_files_dup_lookup ON files(target_id, status, size, hash_value, hash_algo);
"""


class DatabaseManager:
    """Gestionnaire SQLite assurant les écritures simultanées sur la base principale et ses miroirs."""

    def __init__(
        self,
        primary_db_path: str,
        mirror_db_paths: Optional[List[str]] = None,
        targets: Optional[List[TargetFolder]] = None,
        on_ready: Optional[Callable[[], None]] = None
    ):
        self.primary_db_path = os.path.abspath(primary_db_path)
        self.mirror_db_paths = [os.path.abspath(p) for p in (mirror_db_paths or []) if p and p != primary_db_path]
        self._lock = threading.RLock()
        self.targets: List[TargetFolder] = list(targets or [])
        self.target_map: Dict[str, TargetFolder] = {t.id: t for t in self.targets}
        self.is_ready = False
        self.on_ready = on_ready
        # Initialisation non-bloquante du schéma et du mode WAL en arrière-plan
        threading.Thread(target=self._init_all_dbs_background, daemon=True).start()

    def _init_all_dbs_background(self):
        with self._lock:
            self._init_all_dbs()
            self.is_ready = True
        if self.on_ready:
            try:
                self.on_ready()
            except Exception:
                pass

    def set_targets(self, targets: List[TargetFolder]):
        """Met à jour le dictionnaire des cibles connues pour la résolution des chemins complets."""
        with self._lock:
            self.targets = list(targets)
            self.target_map = {t.id: t for t in self.targets}

    def update_mirror_paths(self, new_mirror_paths: List[str]):
        """Met à jour dynamiquement la liste des bases miroirs."""
        with self._lock:
            self.mirror_db_paths = [
                os.path.abspath(p) for p in new_mirror_paths 
                if p and os.path.abspath(p) != self.primary_db_path
            ]
            self._init_all_dbs()

    def _ensure_schema(self, conn: sqlite3.Connection):
        """Initialise ou met à jour la table files et tous les index haute performance si absents."""
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        except Exception as e:
            logger.error("Erreur initialisation du schéma SQLite", str(e))

    def _open_connection(self, db_path: str) -> sqlite3.Connection:
        """Ouvre une connexion SQLite avec configuration haute performance pour des centaines de milliers de fichiers."""
        parent_dir = os.path.dirname(db_path)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception:
                pass

        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA cache_size=-64000;")     # 64 Mo de cache RAM dédié
            conn.execute("PRAGMA mmap_size=268435456;")   # 256 Mo memory-mapped I/O
            conn.execute("PRAGMA temp_store=MEMORY;")
        except Exception:
            pass
        return conn

    def _init_all_dbs(self):
        """Initialise le schéma, les index haute performance et active le mode WAL sur la base principale et les miroirs."""
        try:
            conn = self._open_connection(self.primary_db_path)
            try:
                self._ensure_schema(conn)
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Impossible d'initialiser la base principale ({self.primary_db_path})", str(e))

        for mirror_path in self.mirror_db_paths:
            try:
                conn = self._open_connection(mirror_path)
                try:
                    self._ensure_schema(conn)
                finally:
                    conn.close()
            except Exception as e:
                logger.warning(f"Miroir inaccessible ({mirror_path})", str(e))

    def _resolve_target_and_rel(self, full_path: str) -> Tuple[str, str]:
        """Déduit l'ID de cible et le chemin relatif à partir d'un chemin absolu."""
        norm_p = os.path.normcase(os.path.abspath(full_path))
        best_target = None
        best_len = -1
        for t in self.targets:
            norm_t = os.path.normcase(os.path.abspath(t.path))
            if norm_p == norm_t:
                return t.id, "."
            prefix = norm_t if norm_t.endswith(os.sep) else norm_t + os.sep
            if norm_p.startswith(prefix) and len(norm_t) > best_len:
                best_target = t
                best_len = len(norm_t)

        if best_target:
            try:
                rel = os.path.relpath(full_path, best_target.path)
                return best_target.id, rel
            except ValueError:
                pass

        return "unknown", full_path

    def _ensure_target_and_rel(self, record: FileRecord) -> Tuple[str, str]:
        """S'assure que target_id et rel_path sont valides sur le FileRecord."""
        if record.target_id and record.rel_path:
            return record.target_id, record.rel_path
        if record.path:
            t_id, r_path = self._resolve_target_and_rel(record.path)
            record.target_id = t_id
            record.rel_path = r_path
            return t_id, r_path
        return "unknown", record.rel_path or ""

    def get_target_metadata_fast(self, target_id: str) -> Dict[str, Tuple[int, float, str]]:
        """Récupère en un SELECT ultra-rapide les métadonnées (rel_path -> size, mtime, last_checked) d'une cible."""
        metadata: Dict[str, Tuple[int, float, str]] = {}
        with self._lock:
            try:
                conn = self._open_connection(self.primary_db_path)
                try:
                    cursor = conn.execute(
                        "SELECT rel_path, size, mtime, last_checked_date FROM files WHERE target_id = ?;",
                        (target_id,)
                    )
                    for row in cursor:
                        metadata[row[0]] = (row[1], row[2], row[3] or "")
                finally:
                    conn.close()
            except Exception as e:
                logger.error(f"Erreur get_target_metadata_fast ({target_id})", str(e))
        return metadata

    def upsert_batch(self, records: List[FileRecord]):
        """Écrit un lot d'enregistrements en simultané dans la base principale ET tous les miroirs."""
        if not records:
            return

        query = """
        INSERT INTO files (target_id, rel_path, size, mtime, hash_value, hash_algo, last_checked_date, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(target_id, rel_path) DO UPDATE SET
            size=excluded.size,
            mtime=excluded.mtime,
            hash_value=excluded.hash_value,
            hash_algo=excluded.hash_algo,
            last_checked_date=excluded.last_checked_date,
            status=excluded.status,
            error_message=excluded.error_message;
        """

        params = []
        for r in records:
            t_id, r_path = self._ensure_target_and_rel(r)
            params.append((
                t_id,
                r_path,
                r.size,
                r.mtime,
                r.hash_value,
                r.hash_algo,
                r.last_checked_date,
                r.status.value if isinstance(r.status, FileStatus) else str(r.status),
                r.error_message
            ))

        with self._lock:
            try:
                conn = self._open_connection(self.primary_db_path)
                try:
                    conn.executemany(query, params)
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                logger.error("Échec d'écriture sur la base principale", str(e))

            for mirror_path in self.mirror_db_paths:
                try:
                    conn = self._open_connection(mirror_path)
                    try:
                        conn.executemany(query, params)
                        conn.commit()
                    finally:
                        conn.close()
                except Exception as e:
                    logger.warning(f"Échec écriture miroir ({mirror_path})", str(e))

    def get_record(self, target_id_or_path: str, rel_path: Optional[str] = None) -> Optional[FileRecord]:
        """Récupère l'état enregistré d'un fichier par (target_id, rel_path) ou par chemin absolu."""
        if rel_path is not None:
            t_id = target_id_or_path
            r_path = rel_path
        else:
            t_id, r_path = self._resolve_target_and_rel(target_id_or_path)

        with self._lock:
            try:
                conn = self._open_connection(self.primary_db_path)
                try:
                    cursor = conn.execute(
                        "SELECT * FROM files WHERE target_id = ? AND rel_path = ?;",
                        (t_id, r_path)
                    )
                    row = cursor.fetchone()
                    if row:
                        return self._row_to_record(row)
                finally:
                    conn.close()
            except Exception as e:
                logger.debug(f"Erreur get_record ({t_id}, {r_path}): {e}")
        return None

    def get_all_records(
        self,
        status_filter: Optional[str] = None,
        search_term: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[FileRecord]:
        results = []
        conditions = []
        params = []

        if status_filter and status_filter.upper() not in ("TOUS", "ALL"):
            conditions.append("status = ?")
            params.append(status_filter)

        if search_term:
            term_clean = search_term.lower()
            matching_tids = [t.id for t in self.targets if term_clean in t.path.lower() or term_clean in t.alias.lower()]
            if matching_tids:
                placeholders = ",".join("?" for _ in matching_tids)
                conditions.append(f"(rel_path LIKE ? OR target_id IN ({placeholders}))")
                params.append(f"%{search_term}%")
                params.extend(matching_tids)
            else:
                conditions.append("rel_path LIKE ?")
                params.append(f"%{search_term}%")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM files {where_clause} ORDER BY last_checked_date DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self._lock:
            try:
                conn = self._open_connection(self.primary_db_path)
                try:
                    cursor = conn.execute(query, params)
                    for row in cursor.fetchall():
                        results.append(self._row_to_record(row))
                finally:
                    conn.close()
            except Exception as e:
                logger.error("Erreur consultation base", str(e))

        return results

    def get_duplicate_records(self, target_ids: Optional[List[str]] = None) -> List[FileRecord]:
        """Récupère tous les fichiers ayant une taille et un hash en commun avec au moins un autre fichier.
        Si target_ids est spécifié ou si des cibles sont configurées dans l'instance,
        seules les cibles actives sont prises en compte pour la détection et l'affichage des doublons.
        """
        if target_ids is None and self.targets:
            target_ids = [t.id for t in self.targets if t.enabled]

        if target_ids is not None:
            clean_ids = list(dict.fromkeys(tid for tid in target_ids if tid))
            if not clean_ids:
                return []

            placeholders = ",".join("?" for _ in clean_ids)
            query = f"""
            SELECT f.target_id, f.rel_path, f.size, f.mtime, f.hash_value, f.hash_algo, f.last_checked_date, f.status, f.error_message
            FROM files f
            INNER JOIN (
                SELECT hash_value, size, hash_algo
                FROM files
                WHERE size > 0 AND hash_value != '' AND status NOT IN ('MISSING', 'ERROR', 'LOCKED')
                  AND target_id IN ({placeholders})
                GROUP BY hash_value, size, hash_algo
                HAVING COUNT(*) > 1
            ) d ON f.hash_value = d.hash_value AND f.size = d.size AND f.hash_algo = d.hash_algo
            WHERE f.status NOT IN ('MISSING', 'ERROR', 'LOCKED')
              AND f.target_id IN ({placeholders})
            ORDER BY f.size DESC, f.hash_value;
            """
            params = clean_ids + clean_ids
        else:
            query = """
            SELECT f.target_id, f.rel_path, f.size, f.mtime, f.hash_value, f.hash_algo, f.last_checked_date, f.status, f.error_message
            FROM files f
            INNER JOIN (
                SELECT hash_value, size, hash_algo
                FROM files
                WHERE size > 0 AND hash_value != '' AND status NOT IN ('MISSING', 'ERROR', 'LOCKED')
                GROUP BY hash_value, size, hash_algo
                HAVING COUNT(*) > 1
            ) d ON f.hash_value = d.hash_value AND f.size = d.size AND f.hash_algo = d.hash_algo
            WHERE f.status NOT IN ('MISSING', 'ERROR', 'LOCKED')
            ORDER BY f.size DESC, f.hash_value;
            """
            params = []

        results = []
        with self._lock:
            try:
                conn = self._open_connection(self.primary_db_path)
                try:
                    cursor = conn.execute(query, params)
                    for row in cursor.fetchall():
                        results.append(self._row_to_record(row))
                finally:
                    conn.close()
            except Exception as e:
                logger.error("Erreur récupération doublons", str(e))
        return results

    def delete_record(self, record_or_target_id: Any, rel_path: Optional[str] = None) -> bool:
        """Supprime un fichier de la base principale et de tous les miroirs."""
        if isinstance(record_or_target_id, FileRecord):
            target_id = record_or_target_id.target_id
            r_path = record_or_target_id.rel_path
        elif rel_path is not None:
            target_id = str(record_or_target_id)
            r_path = str(rel_path)
        else:
            path_str = str(record_or_target_id)
            target_id, r_path = self._resolve_target_and_rel(path_str)

        success = False
        with self._lock:
            try:
                conn = self._open_connection(self.primary_db_path)
                try:
                    conn.execute("DELETE FROM files WHERE target_id = ? AND rel_path = ?;", (target_id, r_path))
                    conn.commit()
                    success = True
                finally:
                    conn.close()
            except Exception as e:
                logger.error("Erreur suppression de record sur base principale", str(e))

            for m in self.mirror_db_paths:
                try:
                    c = self._open_connection(m)
                    try:
                        c.execute("DELETE FROM files WHERE target_id = ? AND rel_path = ?;", (target_id, r_path))
                        c.commit()
                    finally:
                        c.close()
                except Exception:
                    pass
        return success

    def delete_target_records(self, target_id: str) -> int:
        """Supprime tous les fichiers d'une cible de la base principale et de tous ses miroirs."""
        deleted = 0
        with self._lock:
            try:
                conn = self._open_connection(self.primary_db_path)
                try:
                    cursor = conn.execute("DELETE FROM files WHERE target_id = ?;", (target_id,))
                    deleted = cursor.rowcount
                    conn.commit()
                    logger.info(f"Purge cible {target_id} : {deleted} enregistrements supprimés.")
                finally:
                    conn.close()
            except Exception as e:
                logger.error(f"Erreur purge cible {target_id} sur base principale", str(e))

            for m in self.mirror_db_paths:
                try:
                    c = self._open_connection(m)
                    try:
                        c.execute("DELETE FROM files WHERE target_id = ?;", (target_id,))
                        c.commit()
                    finally:
                        c.close()
                except Exception:
                    pass

        # Optimisation immédiate de la base SQLite et des index après suppression de cible
        try:
            self.optimize_database()
            logger.info("Base SQLite", f"Optimisation effectuée suite à la suppression de la cible {target_id}.")
        except Exception as e:
            logger.debug(f"Erreur optimisation SQLite après suppression cible: {e}")

        return deleted

    def delete_records_batch(self, target_id: str, rel_paths: List[str]) -> int:
        """Supprime un lot de chemins relatifs d'une cible de la base principale et de tous les miroirs."""
        if not rel_paths:
            return 0
        total_deleted = 0
        chunk_size = 500

        with self._lock:
            for i in range(0, len(rel_paths), chunk_size):
                chunk = rel_paths[i:i + chunk_size]
                params = [target_id] + chunk
                placeholders = ",".join("?" for _ in chunk)
                query = f"DELETE FROM files WHERE target_id = ? AND rel_path IN ({placeholders});"

                try:
                    conn = self._open_connection(self.primary_db_path)
                    try:
                        cur = conn.execute(query, params)
                        total_deleted += cur.rowcount
                        conn.commit()
                    finally:
                        conn.close()
                except Exception as e:
                    logger.error("Erreur suppression par lot sur base principale", str(e))

                for m in self.mirror_db_paths:
                    try:
                        c = self._open_connection(m)
                        try:
                            c.execute(query, params)
                            c.commit()
                        finally:
                            c.close()
                    except Exception:
                        pass

        return total_deleted

    def optimize_database(self, vacuum: bool = True) -> None:
        """Optimise et compacte les fichiers SQLite (base principale et miroirs) :
        - PRAGMA wal_checkpoint(TRUNCATE) : intègre le journal WAL avant compactage
        - VACUUM : reconstruit la base, défragmente et restitue physiquement l'espace libre au système
        - PRAGMA optimize : met à jour les statistiques de l'optimiseur SQLite pour les index
        - PRAGMA wal_checkpoint(TRUNCATE) : synchronise et tronque le journal WAL à 0 octet
        """
        all_dbs = [self.primary_db_path] + self.mirror_db_paths
        with self._lock:
            for db_path in all_dbs:
                if not os.path.exists(db_path):
                    continue
                try:
                    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
                    try:
                        # 1. Forcer le checkpoint WAL pour intégrer toutes les écritures en attente dans le fichier principal
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

                        # 2. Reconstruire et compacter physiquement la base SQLite si demandé
                        if vacuum:
                            try:
                                conn.execute("VACUUM;")
                            except Exception as ve:
                                logger.warning(f"Avertissement VACUUM sur {os.path.basename(db_path)} : {ve}")

                        # 3. Mettre à jour les statistiques de l'optimiseur de requêtes
                        conn.execute("PRAGMA optimize;")

                        # 4. Tronquer à nouveau le journal WAL à 0 octet
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    finally:
                        conn.close()

                    logger.info("Base SQLite", f"Optimisation et compactage de {os.path.basename(db_path)} terminés.")
                except Exception as e:
                    logger.debug(f"Erreur optimisation base ({db_path}): {e}")

    def stream_all_records(
        self,
        status_filter: Optional[str] = None,
        search_term: Optional[str] = None,
        chunk_size: int = 5000
    ) -> Generator[FileRecord, None, None]:
        conditions = []
        params = []

        if status_filter and status_filter.upper() not in ("TOUS", "ALL"):
            conditions.append("status = ?")
            params.append(status_filter)

        if search_term:
            term_clean = search_term.lower()
            matching_tids = [t.id for t in self.targets if term_clean in t.path.lower() or term_clean in t.alias.lower()]
            if matching_tids:
                placeholders = ",".join("?" for _ in matching_tids)
                conditions.append(f"(rel_path LIKE ? OR target_id IN ({placeholders}))")
                params.append(f"%{search_term}%")
                params.extend(matching_tids)
            else:
                conditions.append("rel_path LIKE ?")
                params.append(f"%{search_term}%")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM files {where_clause};"

        conn = self._open_connection(self.primary_db_path)
        try:
            cursor = conn.execute(query, params)
            while True:
                rows = cursor.fetchmany(chunk_size)
                if not rows:
                    break
                for row in rows:
                    yield self._row_to_record(row)
        finally:
            conn.close()

    def get_total_count(
        self,
        status_filter: Optional[str] = None,
        search_term: Optional[str] = None
    ) -> int:
        conditions = []
        params = []

        if status_filter and status_filter.upper() not in ("TOUS", "ALL"):
            conditions.append("status = ?")
            params.append(status_filter)

        if search_term:
            term_clean = search_term.lower()
            matching_tids = [t.id for t in self.targets if term_clean in t.path.lower() or term_clean in t.alias.lower()]
            if matching_tids:
                placeholders = ",".join("?" for _ in matching_tids)
                conditions.append(f"(rel_path LIKE ? OR target_id IN ({placeholders}))")
                params.append(f"%{search_term}%")
                params.extend(matching_tids)
            else:
                conditions.append("rel_path LIKE ?")
                params.append(f"%{search_term}%")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT COUNT(*) FROM files {where_clause};"

        with self._lock:
            try:
                conn = self._open_connection(self.primary_db_path)
                try:
                    cursor = conn.execute(query, params)
                    row = cursor.fetchone()
                    return row[0] if row else 0
                finally:
                    conn.close()
            except Exception:
                return 0

    def _row_to_record(self, row: sqlite3.Row) -> FileRecord:
        target_id = row["target_id"]
        rel_path = row["rel_path"]
        target = self.target_map.get(target_id)
        if target:
            if rel_path == ".":
                full_path = target.path
            else:
                full_path = os.path.normpath(os.path.join(target.path, rel_path))
        else:
            full_path = rel_path
            for t in self.targets:
                candidate = os.path.normpath(os.path.join(t.path, rel_path))
                if os.path.exists(candidate):
                    full_path = candidate
                    break

        try:
            status = FileStatus(row["status"])
        except ValueError:
            status = FileStatus.ERROR

        return FileRecord(
            target_id=target_id,
            rel_path=rel_path,
            path=full_path,
            size=row["size"],
            mtime=row["mtime"],
            hash_value=row["hash_value"],
            hash_algo=row["hash_algo"],
            last_checked_date=row["last_checked_date"],
            status=status,
            error_message=row["error_message"]
        )
