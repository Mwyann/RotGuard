"""Module d'exportation des données de RotGuard vers CSV et formats de checksums."""

import os
import csv
import time
from typing import Optional, Tuple
from datetime import datetime
from core.database import DatabaseManager
from core.logger import logger
from core.i18n import tr


def export_to_csv(
    db_manager: DatabaseManager,
    output_path: str,
    status_filter: Optional[str] = None,
    search_term: Optional[str] = None
) -> Tuple[int, float]:
    """Exporte les enregistrements de la base de données vers un fichier CSV.
    
    Utilise le streaming par curseur (stream_all_records) pour ne jamais saturer la RAM,
    même avec plusieurs centaines de milliers d'entrées.
    """
    start_time = time.perf_counter()
    count = 0

    parent = os.path.dirname(output_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    headers = [
        tr("csv_col_path"),
        tr("csv_col_size"),
        tr("csv_col_mtime"),
        tr("csv_col_algo"),
        tr("csv_col_hash"),
        tr("csv_col_last_check"),
        tr("csv_col_status"),
        tr("csv_col_error"),
    ]

    try:
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(headers)

            for r in db_manager.stream_all_records(status_filter=status_filter, search_term=search_term):
                mtime_str = ""
                if r.mtime > 0:
                    try:
                        mtime_str = datetime.fromtimestamp(r.mtime).strftime("%Y-%m-%d %H:%M:%S")
                    except (OSError, ValueError, OverflowError):
                        mtime_str = ""
                status_val = r.status.value if hasattr(r.status, "value") else str(r.status)
                writer.writerow([
                    r.path,
                    r.size,
                    mtime_str,
                    r.hash_algo,
                    r.hash_value,
                    r.last_checked_date or "",
                    status_val,
                    r.error_message or ""
                ])
                count += 1

        duration = max(time.perf_counter() - start_time, 0.001)
        logger.info(f"Export CSV réussi ({count} fichiers)", output_path)
        return count, duration
    except Exception as e:
        logger.error(f"Échec de l'export CSV : {output_path}", str(e))
        raise


def export_to_checksum_file(
    db_manager: DatabaseManager,
    output_path: str,
    status_filter: Optional[str] = None
) -> Tuple[int, float]:
    """Exporte au format standard d'empreintes (compatible md5sum/sha1sum/b2sum) en streaming."""
    start_time = time.perf_counter()
    count = 0

    parent = os.path.dirname(output_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            for r in db_manager.stream_all_records(status_filter=status_filter):
                if r.hash_value:
                    f.write(f"{r.hash_value}  {r.path}\n")
                    count += 1

        duration = max(time.perf_counter() - start_time, 0.001)
        logger.info(f"Export Checksum réussi ({count} empreintes)", output_path)
        return count, duration
    except Exception as e:
        logger.error(f"Échec de l'export Checksum : {output_path}", str(e))
        raise
