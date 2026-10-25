"""Ordonnanceur multithread avec files dédiées par disque et équilibrage dynamique :
- Une file de priorité dédiée par disque/cible pour éliminer les goulots d'étranglement
- Remplissage maximal des threads disponibles jusqu'à global_max_workers
- Égalisation dynamique de la charge entre disques (ex: 4 disques -> 2/2/2/2, puis 3/3/2, puis 4/4)
- Traitement prioritaire des fichiers nouveaux/modifiés (priorité 0) avant les vérifications
- Synchronisation rigoureuse des vitesses et progression toutes les 0.5s
"""

import os
import time
import threading
from collections import deque
from datetime import datetime
from typing import List, Dict, Callable, Optional, Any, Tuple

from core.models import TargetFolder, FileRecord, FileStatus, ScanStats
from core.hasher import hash_file_stream, to_windows_long_path
from core.database import DatabaseManager
from core.scanner import IntegrityDecider, discover_files_in_target
from core.logger import logger
from core.i18n import tr


STATUS_WAITING = "__STATUS_WAITING__"
STATUS_IDLE = "__STATUS_IDLE__"
STATUS_DONE = "__STATUS_DONE__"
STATUS_STOPPED = "__STATUS_STOPPED__"


class WorkerPool:
    """Gestionnaire de threads de hachage multiqueue avec égalisation dynamique par disque."""

    def __init__(
        self,
        targets: List[TargetFolder],
        db_manager: DatabaseManager,
        global_max_workers: int = 4,
        hash_algorithm: str = "BLAKE2b",
        on_stats_update: Optional[Callable[[ScanStats, Dict[int, Tuple[str, str, float]]], None]] = None,
        on_file_processed: Optional[Callable[[FileRecord], None]] = None,
        config: Optional[Any] = None
    ):
        self.targets = [t for t in targets if t.enabled]
        self.db_manager = db_manager
        self.global_max_workers = max(1, global_max_workers)
        self.hash_algorithm = hash_algorithm
        self.config = config

        # Callbacks UI
        self.on_stats_update = on_stats_update
        self.on_file_processed = on_file_processed

        # Contrôle d'exécution
        self.pause_event = threading.Event()
        self.cancel_event = threading.Event()

        # Dictionnaires et indexation des cibles
        self.target_map: Dict[str, TargetFolder] = {t.path: t for t in self.targets}
        for t in self.targets:
            if t.id:
                self.target_map[t.id] = t
        self.target_indices: Dict[str, int] = {t.path: i for i, t in enumerate(self.targets)}

        # Files de priorité absolue dédiées par disque :
        # - target_new_queues : NOUVEAUX fichiers et MODIFIÉS (traités en priorité absolue)
        # - target_existing_queues : FICHIERS DÉJÀ EN BASE (traités dans un second temps)
        self.target_new_queues: Dict[str, deque] = {
            t.path: deque() for t in self.targets
        }
        self.target_existing_queues: Dict[str, deque] = {
            t.path: deque() for t in self.targets
        }
        self._phase_existing_logged: bool = False

        # Concurrence dynamique et égalisation
        self.target_active_workers: Dict[str, int] = {t.path: 0 for t in self.targets}
        self._scheduler_cond = threading.Condition()
        self._rr_turn = 0

        # Statistiques globales
        self.stats = ScanStats()
        self._stats_lock = threading.RLock()
        self._db_batch: List[FileRecord] = []
        self._db_batch_lock = threading.RLock()

        # Suivi par tâche/worker pour calcul synchronisé toutes les 0.5s
        self.worker_current_file: Dict[int, str] = {i: STATUS_WAITING for i in range(self.global_max_workers)}
        self.worker_current_path: Dict[int, str] = {i: "-" for i in range(self.global_max_workers)}
        self.worker_bytes: Dict[int, int] = {i: 0 for i in range(self.global_max_workers)}
        self.worker_file_progress: Dict[int, Tuple[int, int]] = {i: (0, 0) for i in range(self.global_max_workers)}

        # Threads et suivi de complétion par cible
        self.worker_threads: List[threading.Thread] = []
        self.feeder_threads: List[threading.Thread] = []
        self.target_feeders: Dict[str, threading.Thread] = {}
        self.completed_targets: set = set()
        self.target_processed_count: Dict[str, int] = {t.path: 0 for t in self.targets}
        self._seq_counter = 0
        self._seq_lock = threading.Lock()
        self.scan_mode = "full"  # "full", "simple" ou "update"
        self._targets_to_clean: Dict[str, Tuple[TargetFolder, List[str]]] = {}

    def start_full_scan(self):
        """Lance le scan complet : nouveaux, modifiés et vérification des anciens avec mise à jour DB."""
        self.scan_mode = "full"
        self._start_scan_common(tr("log_start_full_scan"))

    def start_update_scan(self):
        """Lance la mise à jour rapide : traite exclusivement les nouveaux fichiers et les modifiés (File n°1),
        nettoie les fichiers supprimés du disque (avec sécurité 90%), puis optimise la base SQLite."""
        self.scan_mode = "update"
        self._start_scan_common(tr("log_start_update_scan"))

    def start_simple_check(self):
        """Lance le contrôle simple : vérifie uniquement les fichiers supposément identiques sans tester les nouveaux/modifiés et sans toucher à la DB."""
        self.scan_mode = "simple"
        self._start_scan_common(tr("log_start_simple_scan"))

    def _start_scan_common(self, log_msg: str):
        self._reset_state()
        self.stats.is_running = True
        logger.info(log_msg, f"{len(self.targets)} cibles, algo {self.hash_algorithm}")

        self.feeder_threads = []
        self.target_feeders = {}
        for target in self.targets:
            t = threading.Thread(
                target=self._feed_single_target,
                args=(target,),
                daemon=True
            )
            self.feeder_threads.append(t)
            self.target_feeders[target.path] = t
            t.start()

        self._start_workers()

    def pause(self):
        self.pause_event.set()
        self.stats.is_paused = True
        logger.info("Scan suspendu en pause")

    def resume(self):
        self.pause_event.clear()
        self.stats.is_paused = False
        with self._scheduler_cond:
            self._scheduler_cond.notify_all()
        logger.info("Reprise du scan")

    def stop(self):
        """Arrêt propre et immédiat du scan sans bloquer."""
        logger.info(tr("log_scan_stop_requested"), tr("log_scan_cancelling_tasks"))
        self.cancel_event.set()
        self.pause_event.clear()

        # Vider immédiatement toutes les files par disque
        for q in self.target_new_queues.values():
            q.clear()
        for q in self.target_existing_queues.values():
            q.clear()

        with self._scheduler_cond:
            self._scheduler_cond.notify_all()

        with self._stats_lock:
            self.stats.is_running = False
            self.stats.is_paused = False
            self.stats.is_completed = False
            self.stats.is_aborted = True
            self.stats.current_speed_mb_s = 0.0
            self.stats.eta_seconds = None
        self._flush_db_batch()

    def _reset_state(self):
        self.pause_event.clear()
        self.cancel_event.clear()
        self.stats = ScanStats(
            is_running=True,
            current_phase="new_files" if self.scan_mode in ("full", "update") else "existing_files"
        )
        self._targets_to_clean.clear()
        with self._db_batch_lock:
            self._db_batch.clear()
        with self._seq_lock:
            self._seq_counter = 0
        self._rr_turn = 0
        self._phase_existing_logged = False

        # Réinitialisation des files et compteurs par disque
        for q in self.target_new_queues.values():
            q.clear()
        for q in self.target_existing_queues.values():
            q.clear()
        for t_path in self.target_active_workers:
            self.target_active_workers[t_path] = 0

        for i in range(self.global_max_workers):
            self.worker_current_file[i] = STATUS_WAITING
            self.worker_current_path[i] = "-"
            self.worker_bytes[i] = 0
            self.worker_file_progress[i] = (0, 0)

        self.feeder_threads = []
        self.worker_threads = []
        self.target_feeders.clear()
        self.completed_targets.clear()
        self.target_processed_count = {t.path: 0 for t in self.targets}

    def _start_workers(self):
        self.worker_threads = []
        for worker_id in range(self.global_max_workers):
            t = threading.Thread(
                target=self._worker_loop,
                args=(worker_id,),
                daemon=True
            )
            t.start()
            self.worker_threads.append(t)

        threading.Thread(target=self._monitor_loop_synced, daemon=True).start()

    def _find_target_for_file(self, file_path: str) -> Optional[TargetFolder]:
        norm_file = os.path.normcase(os.path.abspath(file_path))
        best_target = None
        best_len = -1
        for target_path, target in self.target_map.items():
            norm_target = os.path.normcase(os.path.abspath(target_path))
            prefix = norm_target if norm_target.endswith(os.sep) else norm_target + os.sep
            if (norm_file == norm_target or norm_file.startswith(prefix)) and len(norm_target) > best_len:
                best_target = target
                best_len = len(norm_target)
        if best_target:
            return best_target
        return self.targets[0] if self.targets else None

    def _feed_single_target(self, target: TargetFolder):
        """Alimente les files dédiées du disque au fil de l'exploration BFS :
        - target_new_queues : fichiers nouveaux ou modifiés (traités immédiatement)
        - target_existing_queues : fichiers déjà archivés en base (traités dans un second temps)
        """
        logger.info(f"Exploration : parcours de la cible {target.path}")
        q_new = self.target_new_queues.get(target.path)
        q_ex = self.target_existing_queues.get(target.path)
        if q_new is None or q_ex is None:
            return

        try:
            target_known = self.db_manager.get_target_metadata_fast(target.id)
        except Exception as e:
            logger.error(f"Erreur chargement index cible {target.alias}", str(e))
            target_known = {}

        ex_patterns = [p.strip() for p in self.config.exclude_patterns.split(",") if p.strip()] if self.config and self.config.exclude_patterns else []
        raw_inc_str = (self.config.include_patterns or "") if self.config else ""
        inc_patterns = [e.strip() for e in raw_inc_str.split(",") if e.strip()]
        min_size = int(self.config.min_file_size_kb) * 1024 if self.config and self.config.min_file_size_kb else 0
        max_size = int(self.config.max_file_size_mb) * 1024 * 1024 if self.config and self.config.max_file_size_mb else 0

        found_rel_paths: set = set()
        existing_tasks_for_target: List[Tuple] = []

        try:
            for file_path in discover_files_in_target(
                target,
                cancel_event=self.cancel_event,
                exclude_patterns=ex_patterns,
                include_patterns=inc_patterns,
                min_size_bytes=min_size,
                max_size_bytes=max_size
            ):
                if self.cancel_event.is_set():
                    break

                try:
                    stat = os.stat(file_path)
                    size = stat.st_size
                    mtime = stat.st_mtime
                except (PermissionError, OSError):
                    size = 0
                    mtime = 0.0

                try:
                    rel_path = os.path.relpath(file_path, target.path)
                except ValueError:
                    rel_path = os.path.basename(file_path)

                found_rel_paths.add(rel_path)

                # Test d'existence instantané en RAM (0 requête SQL par fichier)
                existing_meta = target_known.get(rel_path)
                has_existing = existing_meta is not None

                if self.scan_mode == "simple":
                    # En contrôle simple : ne pas tester les fichiers nouveaux ou modifiés
                    if not has_existing:
                        continue
                    ex_size, ex_mtime, _ = existing_meta
                    if abs(mtime - ex_mtime) > 1.0 or size != ex_size:
                        continue
                    is_new_or_mod = False
                elif self.scan_mode == "update":
                    if not has_existing:
                        is_new_or_mod = True
                    else:
                        ex_size, ex_mtime, _ = existing_meta
                        if abs(mtime - ex_mtime) > 1.0 or size != ex_size:
                            is_new_or_mod = True
                        else:
                            # Fichier existant et inchangé : validé immédiatement sans ré-encodage hash
                            with self._stats_lock:
                                self.stats.total_files_found += 1
                                self.stats.scanned_files += 1
                                self.stats.ok_count += 1
                                self.target_processed_count[target.path] = self.target_processed_count.get(target.path, 0) + 1
                            continue
                else:
                    if not has_existing:
                        is_new_or_mod = True
                    else:
                        ex_size, ex_mtime, _ = existing_meta
                        if abs(mtime - ex_mtime) > 1.0 or size != ex_size:
                            is_new_or_mod = True
                        else:
                            is_new_or_mod = False

                with self._stats_lock:
                    self.stats.total_files_found += 1
                    self.stats.total_bytes_to_scan += size

                with self._seq_lock:
                    self._seq_counter += 1
                    seq = self._seq_counter

                if is_new_or_mod:
                    task_item = (seq, file_path, target, has_existing, rel_path)
                    with self._scheduler_cond:
                        q_new.append(task_item)
                        self._scheduler_cond.notify()
                else:
                    # Règle d'or : trier les fichiers existants par date de dernier contrôle croissante (les plus anciens d'abord)
                    last_chk = existing_meta[2] if (existing_meta and len(existing_meta) >= 3) else ""
                    existing_tasks_for_target.append((last_chk or "", seq, file_path, target, has_existing, rel_path))

            # Une fois l'exploration du disque terminée pour cette cible, trier les fichiers existants
            # par date de dernier contrôle croissante (vide/ancien en premier)
            if existing_tasks_for_target:
                existing_tasks_for_target.sort(key=lambda x: (x[0], x[1]))
                with self._scheduler_cond:
                    for item in existing_tasks_for_target:
                        # item[1:] = (seq, file_path, target, has_existing, rel_path)
                        q_ex.append(item[1:])
                    self._scheduler_cond.notify_all()

        except Exception as e:
            logger.error(f"Erreur exploration {target.path}", str(e))
        finally:
            # Sécurité anti-purge : si >= 90% des fichiers sont manquants, bloquer le nettoyage
            if not self.cancel_event.is_set() and self.scan_mode in ("full", "update"):
                total_known = len(target_known)
                if total_known > 0:
                    missing_rel = set(target_known.keys()) - found_rel_paths
                    missing_count = len(missing_rel)
                    if missing_count > 0:
                        missing_ratio = missing_count / total_known
                        if missing_ratio >= 0.90:
                            msg = tr(
                                "safety_alert_msg",
                                target.alias or target.path,
                                missing_count,
                                total_known,
                                f"{missing_ratio * 100:.1f}"
                            )
                            logger.warning("Safety alert", msg)
                            with self._stats_lock:
                                self.stats.safety_alerts.append(msg)
                        else:
                            self._targets_to_clean[target.id] = (target, list(missing_rel))
                            logger.info(
                                f"Emplacement '{target.alias or target.path}' : "
                                f"{missing_count} fichiers absents du disque programmés pour suppression en base."
                            )

            with self._scheduler_cond:
                self._check_target_completion(target.path)
                self._scheduler_cond.notify_all()

    def _get_next_task(self, worker_id: int) -> Optional[Tuple[TargetFolder, Tuple]]:
        """Sélectionne dynamiquement la prochaine tâche pour maximiser l'utilisation
        globale des threads tout en garantissant que :
        1. TOUS les nouveaux fichiers (et fichiers modifiés) sont scannés et insérés en PRIORITÉ ABSOLUE.
        2. Les fichiers déjà existants en base sont traités dans un second temps (Phase 2),
           uniquement après que tous les nouveaux fichiers ont été découverts et ajoutés à la base.
        3. La charge est équilibrée entre disques actifs (round-robin / charge min).
        """
        while not self.cancel_event.is_set():
            if self.pause_event.is_set():
                time.sleep(0.1)
                continue

            with self._scheduler_cond:
                feeders_alive = any(t.is_alive() for t in self.feeder_threads)

                # =========================================================
                # PHASE 1 : NOUVEAUX FICHIERS ET MODIFIÉS (Priorité Absolue)
                # =========================================================
                if self.scan_mode in ("full", "update"):
                    eligible_new: List[TargetFolder] = []
                    for target in self.targets:
                        t_path = target.path
                        q_new = self.target_new_queues.get(t_path)
                        if not q_new or len(q_new) == 0:
                            continue
                        active = self.target_active_workers.get(t_path, 0)
                        if active < max(1, target.max_workers):
                            eligible_new.append(target)

                    if eligible_new:
                        best_target = min(
                            eligible_new,
                            key=lambda t: (
                                self.target_active_workers.get(t.path, 0),
                                (self.target_indices.get(t.path, 0) - self._rr_turn) % max(1, len(self.targets))
                            )
                        )
                        self._rr_turn = (self.target_indices.get(best_target.path, 0) + 1) % max(1, len(self.targets))
                        self.target_active_workers[best_target.path] = self.target_active_workers.get(best_target.path, 0) + 1
                        try:
                            task_item = self.target_new_queues[best_target.path].popleft()
                            with self._stats_lock:
                                self.stats.current_phase = "new_files"
                            return best_target, task_item
                        except IndexError:
                            self.target_active_workers[best_target.path] = max(0, self.target_active_workers[best_target.path] - 1)
                            continue

                    # S'il reste des nouveaux fichiers en file mais que les workers sont saturés pour ces disques :
                    any_new_remaining = any(len(q) > 0 for q in self.target_new_queues.values())
                    if any_new_remaining:
                        self._scheduler_cond.wait(timeout=0.2)
                        continue

                    # Si l'explorateur est encore en train de parcourir les dossiers à la recherche de nouveaux fichiers :
                    if feeders_alive:
                        self._scheduler_cond.wait(timeout=0.2)
                        continue

                # =========================================================
                # PHASE 2 : FICHIERS DÉJÀ EN BASE (Audit d'intégrité)
                # (Ignoré en mode 'update' qui se contente de la file n°1)
                # =========================================================
                if self.scan_mode != "update":
                    if self.scan_mode == "full" and not self._phase_existing_logged:
                        self._phase_existing_logged = True
                        with self._stats_lock:
                            self.stats.current_phase = "existing_files"
                        logger.info(tr("log_phase_transition"), tr("log_phase_new_finished"))

                    eligible_existing: List[TargetFolder] = []
                    for target in self.targets:
                        t_path = target.path
                        q_ex = self.target_existing_queues.get(t_path)
                        if not q_ex or len(q_ex) == 0:
                            continue
                        active = self.target_active_workers.get(t_path, 0)
                        if active < max(1, target.max_workers):
                            eligible_existing.append(target)

                    if eligible_existing:
                        best_target = min(
                            eligible_existing,
                            key=lambda t: (
                                self.target_active_workers.get(t.path, 0),
                                (self.target_indices.get(t.path, 0) - self._rr_turn) % max(1, len(self.targets))
                            )
                        )
                        self._rr_turn = (self.target_indices.get(best_target.path, 0) + 1) % max(1, len(self.targets))
                        self.target_active_workers[best_target.path] = self.target_active_workers.get(best_target.path, 0) + 1
                        try:
                            task_item = self.target_existing_queues[best_target.path].popleft()
                            with self._stats_lock:
                                self.stats.current_phase = "existing_files"
                            return best_target, task_item
                        except IndexError:
                            self.target_active_workers[best_target.path] = max(0, self.target_active_workers[best_target.path] - 1)
                            continue

                # Vérifier si l'ensemble des tâches est définitivement terminé
                all_new_empty = all(len(q) == 0 for q in self.target_new_queues.values())
                all_ex_empty = (self.scan_mode == "update") or all(len(q) == 0 for q in self.target_existing_queues.values())
                all_workers_idle = all(w == 0 for w in self.target_active_workers.values())

                if not feeders_alive and all_new_empty and all_ex_empty and all_workers_idle:
                    self._scheduler_cond.notify_all()
                    return None

                # Disques temporairement au plafond de workers : attendre réveil
                self._scheduler_cond.wait(timeout=0.2)

        return None

    def _check_target_completion(self, target_path: str):
        """Vérifie et consigne lorsqu'une cible a terminé tous ses fichiers."""
        if target_path in self.completed_targets:
            return

        feeder = self.target_feeders.get(target_path)
        feeder_done = feeder is None or not feeder.is_alive()
        q_new = self.target_new_queues.get(target_path)
        q_ex = self.target_existing_queues.get(target_path)
        if self.scan_mode == "update":
            queues_empty = not q_new or len(q_new) == 0
        else:
            queues_empty = (not q_new or len(q_new) == 0) and (not q_ex or len(q_ex) == 0)
        active = self.target_active_workers.get(target_path, 0)

        if feeder_done and queues_empty and active == 0:
            self.completed_targets.add(target_path)
            target = self.target_map.get(target_path)
            alias = target.alias if target else target_path
            count = self.target_processed_count.get(target_path, 0)
            logger.info(tr("scan_target_finished_title"), tr("scan_target_finished", alias, count))

    def _release_target_slot(self, target_path: str):
        """Libère un slot de worker pour le disque donné et réveille l'ordonnanceur."""
        with self._scheduler_cond:
            if target_path in self.target_active_workers:
                self.target_active_workers[target_path] = max(0, self.target_active_workers[target_path] - 1)
            self._check_target_completion(target_path)
            self._scheduler_cond.notify_all()

    def _worker_loop(self, worker_id: int):
        while not self.cancel_event.is_set():
            if self.pause_event.is_set():
                time.sleep(0.1)
                continue

            task = self._get_next_task(worker_id)
            if task is None:
                break

            target, item = task
            seq, file_path, target, has_existing, rel_path = item

            try:
                self._process_single_file(worker_id, file_path, target, has_existing, rel_path)
            except Exception as e:
                logger.error(f"Exception worker #{worker_id + 1}", str(e))
            finally:
                self._release_target_slot(target.path)
                self.worker_current_file[worker_id] = STATUS_WAITING
                self.worker_current_path[worker_id] = "-"
                self.worker_file_progress[worker_id] = (0, 0)

        self.worker_current_file[worker_id] = STATUS_IDLE
        self.worker_current_path[worker_id] = "-"
        self.worker_file_progress[worker_id] = (0, 0)

    def _process_single_file(self, worker_id: int, file_path: str, target: TargetFolder, has_existing: bool, rel_path: str):
        if self.cancel_event.is_set():
            return

        filename = os.path.basename(file_path)
        folder = os.path.dirname(file_path)
        self.worker_current_file[worker_id] = filename
        self.worker_current_path[worker_id] = folder
        self.worker_file_progress[worker_id] = (0, 0)

        if not os.path.exists(file_path):
            record = FileRecord(
                target_id=target.id,
                rel_path=rel_path,
                path=file_path,
                status=FileStatus.MISSING,
                error_message=tr("err_file_missing_on_disk"),
                last_checked_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            self._record_result(record)
            return

        try:
            stat = os.stat(file_path)
            current_size = stat.st_size
            current_mtime = stat.st_mtime
        except (PermissionError, OSError) as e:
            try:
                stat = os.stat(to_windows_long_path(file_path))
                current_size = stat.st_size
                current_mtime = stat.st_mtime
            except Exception:
                record = FileRecord(
                    target_id=target.id,
                    rel_path=rel_path,
                    path=file_path,
                    status=FileStatus.LOCKED,
                    error_message=f"Impossible de lire les métadonnées : {e}",
                    last_checked_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                self._record_result(record)
                return

        # Évite 1 requête SQL si le fichier est totalement nouveau
        existing_record = self.db_manager.get_record(target.id, rel_path) if has_existing else None
        buffer_size = target.buffer_size_bytes or (2 * 1024 * 1024)

        try:
            def progress_cb(bytes_done, total, speed, chunk_len):
                if chunk_len > 0:
                    with self._stats_lock:
                        self.stats.bytes_scanned += chunk_len
                        self.worker_bytes[worker_id] += chunk_len
                        self.worker_file_progress[worker_id] = (bytes_done, total)

            preserve_atime = getattr(self.config, "preserve_atime", True) if self.config else True

            # Règle d'or : un fichier existant et non modifié conserve son algorithme archivé en base
            # pour vérifier son intégrité sans recalcul inutile.
            # S'il est modifié sur disque ou totalement nouveau, il est haché avec l'algorithme actif.
            is_modified = existing_record is not None and (
                abs(current_mtime - existing_record.mtime) > 1.0 or current_size != existing_record.size
            )
            if existing_record and existing_record.hash_algo and not is_modified:
                algo_to_use = existing_record.hash_algo
            else:
                algo_to_use = self.hash_algorithm

            computed_hash, bytes_read, duration = hash_file_stream(
                file_path=file_path,
                algorithm=algo_to_use,
                buffer_size=buffer_size,
                progress_callback=progress_cb,
                pause_event=self.pause_event,
                cancel_event=self.cancel_event,
                preserve_atime=preserve_atime
            )

            evaluated_record = IntegrityDecider.evaluate_file_integrity(
                file_path=file_path,
                computed_hash=computed_hash,
                hash_algo=algo_to_use,
                existing_record=existing_record,
                current_size=current_size,
                current_mtime=current_mtime,
                target_id=target.id,
                rel_path=rel_path
            )

            with self._stats_lock:
                self.worker_file_progress[worker_id] = (current_size, current_size)

            self._record_result(evaluated_record)

        except InterruptedError:
            return
        except PermissionError as e:
            logger.warning(f"Fichier verrouillé ou accès refusé : {file_path}", str(e))
            record = FileRecord(
                target_id=target.id,
                rel_path=rel_path,
                path=file_path,
                size=current_size,
                mtime=current_mtime,
                status=FileStatus.LOCKED,
                error_message=f"Verrouillé / Accès refusé : {e}",
                last_checked_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            self._record_result(record)
        except OSError as e:
            # Erreur de lecture système, secteur défectueux (ex: WinError 23 CRC error, EIO, etc.)
            logger.error(f"Erreur de lecture système / I/O : {file_path}", str(e))
            record = FileRecord(
                target_id=target.id,
                rel_path=rel_path,
                path=file_path,
                size=current_size,
                mtime=current_mtime,
                status=FileStatus.ERROR,
                error_message=f"Erreur système I/O : {e}",
                last_checked_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            self._record_result(record)
        except Exception as e:
            logger.error(f"Erreur d'I/O imprévue : {file_path}", str(e))
            record = FileRecord(
                target_id=target.id,
                rel_path=rel_path,
                path=file_path,
                size=current_size,
                mtime=current_mtime,
                status=FileStatus.ERROR,
                error_message=f"Erreur : {e}",
                last_checked_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            self._record_result(record)

    def _record_result(self, record: FileRecord):
        with self._stats_lock:
            self.stats.scanned_files += 1
            if record.target_id:
                t = self.target_map.get(record.target_id)
                if t and t.path in self.target_processed_count:
                    self.target_processed_count[t.path] += 1
            elif record.path:
                for tp in self.target_processed_count:
                    if record.path.startswith(tp):
                        self.target_processed_count[tp] += 1
                        break

            if record.status == FileStatus.OK:
                self.stats.ok_count += 1
            elif record.status == FileStatus.MODIFIED:
                self.stats.modified_count += 1
            elif record.status == FileStatus.NEW:
                self.stats.new_count += 1
            elif record.status == FileStatus.CORRUPT:
                self.stats.corrupted_count += 1
            elif record.status == FileStatus.LOCKED:
                self.stats.locked_count += 1
            elif record.status == FileStatus.MISSING:
                self.stats.missing_count += 1
            elif record.status == FileStatus.ERROR:
                self.stats.error_count += 1

        if self.scan_mode != "simple":
            batch_to_write = None
            with self._db_batch_lock:
                self._db_batch.append(record)
                if len(self._db_batch) >= 200:
                    batch_to_write = list(self._db_batch)
                    self._db_batch.clear()

            if batch_to_write:
                self.db_manager.upsert_batch(batch_to_write)

        if self.on_file_processed:
            try:
                self.on_file_processed(record)
            except Exception as e:
                logger.debug(f"Erreur callback on_file_processed: {e}")

    def _flush_db_batch(self):
        if self.scan_mode == "simple":
            return
        batch_to_write = None
        with self._db_batch_lock:
            if self._db_batch:
                batch_to_write = list(self._db_batch)
                self._db_batch.clear()

        if batch_to_write:
            self.db_manager.upsert_batch(batch_to_write)

    def _monitor_loop_synced(self):
        """Calcul rigoureusement synchronisé toutes les 0.5 secondes."""
        start_time = time.perf_counter()
        last_time = start_time
        last_global_bytes = 0
        last_worker_bytes: Dict[int, int] = {i: 0 for i in range(self.global_max_workers)}

        while self.stats.is_running and not self.cancel_event.is_set():
            time.sleep(0.5)

            self._flush_db_batch()

            now = time.perf_counter()
            delta_time = now - last_time
            if delta_time < 0.2:
                continue

            worker_tasks: Dict[int, Tuple[str, str, str, float]] = {}

            with self._stats_lock:
                current_global_bytes = self.stats.bytes_scanned
                delta_global = max(0, current_global_bytes - last_global_bytes)
                self.stats.current_speed_mb_s = (delta_global / (1024 * 1024)) / delta_time
                self.stats.elapsed_time_s = now - start_time

                for wid in range(self.global_max_workers):
                    cur_w_bytes = self.worker_bytes[wid]
                    w_delta = max(0, cur_w_bytes - last_worker_bytes[wid])
                    w_speed = (w_delta / (1024 * 1024)) / delta_time
                    w_file = self.worker_current_file[wid]
                    w_path = self.worker_current_path.get(wid, "-")

                    done_b, total_b = self.worker_file_progress.get(wid, (0, 0))
                    if w_file in (STATUS_WAITING, STATUS_IDLE):
                        progress_str = "-"
                    elif total_b > 0:
                        pct = min(100.0, (done_b / total_b) * 100.0)
                        if total_b >= 1024 * 1024:
                            progress_str = f"{pct:.0f}% ({done_b / (1024*1024):.1f}/{total_b / (1024*1024):.1f} {tr('unit_mb')})"
                        elif total_b >= 1024:
                            progress_str = f"{pct:.0f}% ({done_b / 1024:.0f}/{total_b / 1024:.0f} {tr('unit_kb')})"
                        else:
                            progress_str = f"{pct:.0f}% ({done_b}/{total_b} {tr('unit_b')})"
                    else:
                        progress_str = "100%"

                    worker_tasks[wid] = (w_path, w_file, progress_str, w_speed)
                    last_worker_bytes[wid] = cur_w_bytes

                remaining_bytes = max(0, self.stats.total_bytes_to_scan - current_global_bytes)
                if self.stats.current_speed_mb_s > 0.05 and remaining_bytes > 0:
                    speed_bytes_s = self.stats.current_speed_mb_s * 1024 * 1024
                    self.stats.eta_seconds = remaining_bytes / speed_bytes_s
                else:
                    self.stats.eta_seconds = None

                stats_copy = ScanStats(**self.stats.__dict__)

            last_global_bytes = current_global_bytes
            last_time = now

            if self.on_stats_update:
                self.on_stats_update(stats_copy, worker_tasks)

            feeder_alive = any(t.is_alive() for t in self.feeder_threads)
            all_queues_empty = (
                all(len(q) == 0 for q in self.target_new_queues.values())
                and (self.scan_mode == "update" or all(len(q) == 0 for q in self.target_existing_queues.values()))
            )
            workers_alive = any(t.is_alive() for t in self.worker_threads)
            all_done = (
                not feeder_alive
                and all_queues_empty
                and not workers_alive
            )
            if all_done:
                # 1. Nettoyage sécurisé des fichiers supprimés du disque
                total_cleaned = 0
                if self.scan_mode in ("full", "update") and not self.cancel_event.is_set():
                    for target_id, (target, missing_list) in list(self._targets_to_clean.items()):
                        if missing_list:
                            c = self.db_manager.delete_records_batch(target_id, missing_list)
                            total_cleaned += c
                            logger.info(f"Nettoyage BDD terminé pour '{target.alias or target.path}' : {c} fichiers supprimés purgés.")

                with self._stats_lock:
                    self.stats.is_running = False
                    self.stats.is_completed = True
                    self.stats.is_aborted = self.cancel_event.is_set()
                    self.stats.current_speed_mb_s = 0.0
                    self.stats.eta_seconds = None
                    self.stats.deleted_clean_count = total_cleaned
                    final_stats = ScanStats(**self.stats.__dict__)

                self._flush_db_batch()

                # 2. Optimisation de la base SQLite et des miroirs en fin de scan
                if not self.cancel_event.is_set():
                    try:
                        self.db_manager.optimize_database()
                        logger.info("Base SQLite optimisée avec succès (PRAGMA optimize & wal_checkpoint).")
                    except Exception as e:
                        logger.error("Erreur optimisation SQLite en fin de scan", str(e))

                logger.info(
                    tr("log_scan_finished_title"),
                    tr("log_scan_finished_summary", self.stats.scanned_files, self.stats.corrupted_count, total_cleaned)
                )
                idle_tasks = {
                    wid: ("-", STATUS_DONE, "100%", 0.0)
                    for wid in range(self.global_max_workers)
                }
                if self.on_stats_update:
                    self.on_stats_update(final_stats, idle_tasks)
                break

        # Notification finale si le scan a été arrêté ou interrompu
        if self.cancel_event.is_set() or not self.stats.is_completed:
            with self._stats_lock:
                self.stats.is_running = False
                self.stats.is_completed = False
                self.stats.is_aborted = True
                self.stats.current_speed_mb_s = 0.0
                self.stats.eta_seconds = None
                stopped_stats = ScanStats(**self.stats.__dict__)
            self._flush_db_batch()
            idle_tasks = {
                wid: ("-", STATUS_STOPPED, "-", 0.0)
                for wid in range(self.global_max_workers)
            }
            if self.on_stats_update:
                self.on_stats_update(stopped_stats, idle_tasks)
