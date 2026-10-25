"""Moteur de hachage unifié pour RotGuard.

Prend en charge CRC32, MD5, SHA-1, SHA-256, SHA-512, BLAKE2b et SpookyHash V2.
Lecture par streaming avec tampons configurables, rapport de progression en temps réel
par bloc et gestion robuste des interruptions.
"""

import os
import time
import zlib
import hashlib
import threading
from typing import Callable, Optional, Tuple, Any

from core.spookyhash import SpookyHashV2


SUPPORTED_ALGORITHMS = [
    "BLAKE2b",    # Recommandé : C ultra-rapide natif, 512-bit
    "CRC32",      # Rapide, historique
    "MD5",        # Standard 128-bit
    "SHA-1",      # Standard 160-bit
    "SHA-256",    # Sécurisé standard
    "SHA-512",    # Sécurisé 512-bit
    "SpookyHash"  # 128-bit non cryptographique
]


class CRC32Hasher:
    """Wrapper pour zlib.crc32 afin d'offrir une API similaire à hashlib."""
    def __init__(self):
        self._val = 0

    def update(self, data: bytes):
        self._val = zlib.crc32(data, self._val)

    def hexdigest(self) -> str:
        return f"{self._val & 0xFFFFFFFF:08x}"


def get_hasher_instance(algo_name: str) -> Any:
    """Instancie l'objet de hachage selon le nom de l'algorithme."""
    algo = algo_name.upper().replace("-", "")

    if algo == "CRC32":
        return CRC32Hasher()
    elif algo == "MD5":
        return hashlib.md5()
    elif algo == "SHA1":
        return hashlib.sha1()
    elif algo == "SHA256":
        return hashlib.sha256()
    elif algo == "SHA512":
        return hashlib.sha512()
    elif algo == "BLAKE2B":
        return hashlib.blake2b()
    elif "SPOOKY" in algo:
        return SpookyHashV2()
    else:
        return hashlib.blake2b()


def to_windows_long_path(path: str) -> str:
    """Préfixe un chemin Windows avec \\?\\ pour dépasser la limite MAX_PATH (260 caractères)
    et désactiver la normalisation Win32 restrictive (permettant les noms avec points multiples, etc.).
    """
    if os.name != "nt":
        return path
    abs_path = os.path.abspath(path)
    if abs_path.startswith("\\\\?\\"):
        return abs_path
    if abs_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + abs_path[2:]
    return "\\\\?\\" + abs_path


def hash_file_stream(
    file_path: str,
    algorithm: str = "BLAKE2b",
    buffer_size: int = 2 * 1024 * 1024,
    progress_callback: Optional[Callable[[int, int, float, int], None]] = None,
    pause_event: Optional[threading.Event] = None,
    cancel_event: Optional[threading.Event] = None,
    preserve_atime: bool = True
) -> Tuple[str, int, float]:
    """Calcule l'empreinte d'un fichier avec lecture par blocs et gestion des pauses/annulations.
    
    Args:
        file_path: Chemin absolu du fichier à hacher.
        algorithm: Algorithme choisi ('BLAKE2b', 'CRC32', 'MD5', 'SHA-1', etc.).
        buffer_size: Taille du tampon de lecture en octets (ex: 2 Mo = 2097152).
        progress_callback: Callback optionnel (octets_lus_total_fichier, taille_totale, vitesse_instantanee_Mo_s, delta_octets_bloc).
        pause_event: Événement threading de pause (si actif, la lecture s'endort).
        cancel_event: Événement threading d'annulation (si actif, la fonction s'interrompt).
        preserve_atime: Si True, préserve et restaure l'horodatage de dernier accès (atime) original.
        
    Returns:
        Tuple[str, int, float]: (Hash hexadécimal, nombre d'octets lus, durée en secondes).
    """
    if not os.path.isfile(file_path):
        long_p = to_windows_long_path(file_path)
        if not os.path.isfile(long_p):
            raise FileNotFoundError(f"Fichier introuvable : {file_path}")

    # Mémorisation des horodatages originaux pour restauration furtive de l'atime
    orig_atime = None
    orig_mtime = None
    target_p = file_path
    if preserve_atime:
        try:
            st = os.stat(file_path)
            orig_atime, orig_mtime = st.st_atime, st.st_mtime
        except Exception:
            try:
                target_p = to_windows_long_path(file_path)
                st = os.stat(target_p)
                orig_atime, orig_mtime = st.st_atime, st.st_mtime
            except Exception:
                pass

    try:
        total_size = os.path.getsize(file_path)
    except OSError:
        total_size = os.path.getsize(to_windows_long_path(file_path))

    hasher = get_hasher_instance(algorithm)

    bytes_read = 0
    start_time = time.perf_counter()
    last_callback_time = start_time
    last_callback_bytes = 0

    if total_size == 0:
        duration = max(time.perf_counter() - start_time, 0.0001)
        if progress_callback:
            progress_callback(0, 0, 0.0, 0)
        return hasher.hexdigest(), 0, duration

    # Tente d'abord l'ouverture directe, puis repli sur le chemin préfixé \\?\ si nécessaire
    opened_long = False
    try:
        f = open(file_path, "rb")
    except OSError:
        f = open(to_windows_long_path(file_path), "rb")
        opened_long = True

    try:
        with f:
            while True:
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("Calcul interrompu par l'utilisateur.")

                if pause_event and pause_event.is_set():
                    while pause_event.is_set():
                        if cancel_event and cancel_event.is_set():
                            raise InterruptedError("Calcul interrompu pendant la pause.")
                        time.sleep(0.1)

                chunk = f.read(buffer_size)
                if not chunk:
                    break

                chunk_len = len(chunk)
                hasher.update(chunk)
                bytes_read += chunk_len

                # Notification immédiate de progression par bloc lu (permettant la mise à jour de vitesse en temps réel)
                now = time.perf_counter()
                delta_time = now - last_callback_time
                if progress_callback:
                    delta_bytes = bytes_read - last_callback_bytes
                    speed_mb_s = (delta_bytes / (1024 * 1024)) / delta_time if delta_time > 0 else 0.0
                    progress_callback(bytes_read, total_size, speed_mb_s, chunk_len)
                    last_callback_time = now
                    last_callback_bytes = bytes_read
    finally:
        # Restauration furtive de l'access time (atime) original
        if preserve_atime and orig_atime is not None and orig_mtime is not None:
            restore_p = to_windows_long_path(file_path) if opened_long else file_path
            try:
                os.utime(restore_p, (orig_atime, orig_mtime))
            except Exception:
                try:
                    os.utime(to_windows_long_path(file_path), (orig_atime, orig_mtime))
                except Exception:
                    pass

    duration = max(time.perf_counter() - start_time, 0.0001)
    final_hash = hasher.hexdigest()
    return final_hash, bytes_read, duration
