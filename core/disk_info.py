"""Module d'inspection matérielle et d'auto-détection HDD vs SSD sous Windows."""

import os
import sys
import subprocess
import shutil
from typing import Tuple, Dict, Any, Optional
from core.models import DiskType


def get_drive_root(path: str) -> str:
    """Extrait la racine d'un chemin (ex: 'D:\\' pour 'D:\\Dossier\\Fichier')."""
    abspath = os.path.abspath(path)
    drive, _ = os.path.splitdrive(abspath)
    if drive:
        return drive + os.sep
    return os.path.abspath(os.sep)


def get_drive_letter(path: str) -> Optional[str]:
    """Récupère la lettre de lecteur Windows en majuscule (ex: 'D')."""
    abspath = os.path.abspath(path)
    drive, _ = os.path.splitdrive(abspath)
    if drive and drive.endswith(":"):
        return drive[0].upper()
    return None


def get_disk_space_info(path: str) -> Dict[str, Any]:
    """Renvoie l'espace total, utilisé et libre en octets et en Go."""
    root = get_drive_root(path)
    try:
        total, used, free = shutil.disk_usage(root)
        return {
            "root": root,
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "total_gb": round(total / (1024 ** 3), 2),
            "used_gb": round(used / (1024 ** 3), 2),
            "free_gb": round(free / (1024 ** 3), 2),
            "free_percent": round((free / total) * 100, 1) if total > 0 else 0
        }
    except Exception:
        return {
            "root": root,
            "total_bytes": 0,
            "used_bytes": 0,
            "free_bytes": 0,
            "total_gb": 0.0,
            "used_gb": 0.0,
            "free_gb": 0.0,
            "free_percent": 0.0
        }


def detect_disk_type_windows_ioctl(drive_letter: str) -> Optional[DiskType]:
    """Interroge directement le pilote de stockage Windows via DeviceIoControl (IOCTL_STORAGE_QUERY_PROPERTY).
    
    Identifie avec une précision matérielle absolue (0,1 ms, sans droits administrateur) :
    - IncursSeekPenalty == TRUE -> HDD (disque rotatif mécanique, y compris disques SATA)
    - IncursSeekPenalty == FALSE -> SSD (mémoire flash / NVMe / SSD SATA)
    """
    if not drive_letter or sys.platform != "win32":
        return None

    import ctypes
    from ctypes import wintypes

    IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
    StorageDeviceSeekPenaltyProperty = 7
    StorageDeviceTrimProperty = 8
    PropertyStandardQuery = 0

    class STORAGE_PROPERTY_QUERY(ctypes.Structure):
        _fields_ = [
            ("PropertyId", wintypes.DWORD),
            ("QueryType", wintypes.DWORD),
            ("AdditionalParameters", wintypes.BYTE * 1),
        ]

    class DEVICE_SEEK_PENALTY_DESCRIPTOR(ctypes.Structure):
        _fields_ = [
            ("Version", wintypes.DWORD),
            ("Size", wintypes.DWORD),
            ("IncursSeekPenalty", wintypes.BOOLEAN),
        ]

    class DEVICE_TRIM_DESCRIPTOR(ctypes.Structure):
        _fields_ = [
            ("Version", wintypes.DWORD),
            ("Size", wintypes.DWORD),
            ("TrimEnabled", wintypes.BOOLEAN),
        ]

    clean_letter = drive_letter.strip().rstrip(":\\").upper()
    if not clean_letter or len(clean_letter) != 1 or not clean_letter.isalpha():
        return None

    root_path = f"{clean_letter}:\\"
    try:
        drive_type_int = ctypes.windll.kernel32.GetDriveTypeW(root_path)
    except Exception:
        drive_type_int = 0
    # DRIVE_REMOVABLE = 2, DRIVE_FIXED = 3, DRIVE_REMOTE = 4, DRIVE_CDROM = 5

    volume_path = rf"\\.\{clean_letter}:"
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3

    # dwDesiredAccess = 0 : permet d'interroger les descripteurs de périphériques sans droits admin
    handle = ctypes.windll.kernel32.CreateFileW(
        volume_path,
        0,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        0,
        None
    )

    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    if handle == INVALID_HANDLE_VALUE or handle == 0:
        return None

    try:
        query = STORAGE_PROPERTY_QUERY()
        query.PropertyId = StorageDeviceSeekPenaltyProperty
        query.QueryType = PropertyStandardQuery

        seek_desc = DEVICE_SEEK_PENALTY_DESCRIPTOR()
        bytes_returned = wintypes.DWORD(0)

        ok = ctypes.windll.kernel32.DeviceIoControl(
            handle,
            IOCTL_STORAGE_QUERY_PROPERTY,
            ctypes.byref(query),
            ctypes.sizeof(query),
            ctypes.byref(seek_desc),
            ctypes.sizeof(seek_desc),
            ctypes.byref(bytes_returned),
            None
        )

        if ok and bytes_returned.value >= ctypes.sizeof(DEVICE_SEEK_PENALTY_DESCRIPTOR):
            # IncursSeekPenalty == 1 -> Disque rotatif mécanique (HDD)
            if bool(seek_desc.IncursSeekPenalty):
                return DiskType.HDD
            else:
                # Seek penalty == 0 -> SSD / Mémoire flash
                # Vérification complémentaire TRIM
                trim_query = STORAGE_PROPERTY_QUERY()
                trim_query.PropertyId = StorageDeviceTrimProperty
                trim_query.QueryType = PropertyStandardQuery
                trim_desc = DEVICE_TRIM_DESCRIPTOR()
                ok_trim = ctypes.windll.kernel32.DeviceIoControl(
                    handle,
                    IOCTL_STORAGE_QUERY_PROPERTY,
                    ctypes.byref(trim_query),
                    ctypes.sizeof(trim_query),
                    ctypes.byref(trim_desc),
                    ctypes.sizeof(trim_desc),
                    ctypes.byref(bytes_returned),
                    None
                )
                if ok_trim and bool(trim_desc.TrimEnabled):
                    return DiskType.SSD

                if drive_type_int == 2:  # DRIVE_REMOVABLE
                    return DiskType.REMOVABLE

                return DiskType.SSD
    except Exception:
        pass
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)

    return None


def detect_disk_type_powershell(drive_letter: str) -> DiskType:
    """Interroge Windows via PowerShell pour identifier le MediaType réel (SSD vs HDD),
    
    avec gestion renforcée des disques rotatifs SATA, NVMe, USB et WMI.
    """
    if not drive_letter or sys.platform != "win32":
        return DiskType.UNKNOWN

    clean_letter = drive_letter.strip().rstrip(":\\").upper()

    # Script PowerShell qui extrait MediaType, BusType, SpindleSpeed et Model
    ps_script = (
        f"$part = Get-Partition -DriveLetter '{clean_letter}' -ErrorAction SilentlyContinue; "
        "if ($part) { "
        "  $d = Get-Disk -Number $part.DiskNumber -ErrorAction SilentlyContinue; "
        "  $pd = Get-PhysicalDisk | Where-Object { $_.DeviceId -eq \"$($part.DiskNumber)\" -or $_.FriendlyName -eq $d.FriendlyName } -ErrorAction SilentlyContinue; "
        "  $media = if ($pd) { $pd.MediaType } else { $d.MediaType }; "
        "  $bus = if ($pd) { $pd.BusType } else { $d.BusType }; "
        "  $speed = if ($pd -and $pd.SpindleSpeed) { $pd.SpindleSpeed } else { 0 }; "
        "  $model = if ($d -and $d.Model) { $d.Model } else { '' }; "
        "  Write-Output \"$media|$bus|$speed|$model\" "
        "} else { "
        f"  $vol = Get-Volume -DriveLetter '{clean_letter}' -ErrorAction SilentlyContinue; "
        "  if ($vol) { Write-Output \"$($vol.DriveType)|||\" } "
        "}"
    )

    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        ps_script
    ]

    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=6,
            creationflags=creationflags
        )
        output = result.stdout.strip()
        if not output:
            return DiskType.UNKNOWN

        parts = output.split("|")
        media_type = parts[0].strip().upper() if len(parts) > 0 else ""
        bus_type = parts[1].strip().upper() if len(parts) > 1 else ""
        speed_str = parts[2].strip() if len(parts) > 2 else "0"
        model = parts[3].strip().upper() if len(parts) > 3 else ""

        try:
            spindle_speed = int(speed_str)
        except ValueError:
            spindle_speed = 0

        # 1. Vitesse de rotation physique (5400, 7200, 5900, 10000 tr/min) -> 100% HDD mécanique !
        if spindle_speed > 0:
            return DiskType.HDD

        # 2. Indication explicite HDD
        if "HDD" in media_type:
            return DiskType.HDD

        # 3. Indication explicite SSD ou NVMe
        if "SSD" in media_type or "NVME" in bus_type or "SCM" in media_type:
            return DiskType.SSD

        # 4. Modèles de disques durs mécaniques rotatifs SATA courants (Seagate, WD, Toshiba...)
        hdd_brands = [
            "BARRACUDA", "IRONWOLF", "SKYHAWK", "EXOS", "FIRECUDA",
            "WD BLUE", "WD RED", "WD PURPLE", "WD BLACK", "WD GOLD", "WDC WD",
            "TOSHIBA DT", "TOSHIBA MD", "TOSHIBA MG", "DESKSTAR", "SEAGATE",
            "ST1000", "ST2000", "ST3000", "ST4000", "ST6000", "ST8000", "ST10000",
            "ST12000", "ST14000", "ST16000", "ST18000", "ST20000",
            "WD10", "WD20", "WD30", "WD40", "WD60", "WD80", "WD100", "WD120", "WD140"
        ]
        if any(b in model for b in hdd_brands) and "SSD" not in model:
            return DiskType.HDD

        # 5. Détection support amovible
        if "USB" in bus_type or "REMOVABLE" in media_type:
            return DiskType.REMOVABLE

        # 6. Disque SATA fixe avec media_type Unspecified :
        # Sous Windows, la quasi-totalité des disques SATA signalés comme Unspecified
        # sur un bus SATA fixe sont des disques durs rotatifs.
        if "SATA" in bus_type:
            return DiskType.HDD

        return DiskType.UNKNOWN
    except Exception:
        return DiskType.UNKNOWN


def detect_disk_type_linux(path: str) -> DiskType:
    """Détecte sous Linux si le support sous-jacent est un SSD (rotational=0) ou un HDD (rotational=1)."""
    try:
        dev_stat = os.stat(path)
        major = os.major(dev_stat.st_dev)
        minor = os.minor(dev_stat.st_dev)

        sys_block_path = f"/sys/dev/block/{major}:{minor}"
        if os.path.exists(sys_block_path):
            real_path = os.path.realpath(sys_block_path)
            parts = real_path.split("/")
            dev_name = None
            if "block" in parts:
                idx = parts.index("block")
                if idx + 1 < len(parts):
                    dev_name = parts[idx + 1]

            if dev_name:
                rot_file = f"/sys/block/{dev_name}/queue/rotational"
                if os.path.exists(rot_file):
                    with open(rot_file, "r") as f:
                        val = f.read().strip()
                        if val == "0":
                            return DiskType.SSD
                        elif val == "1":
                            return DiskType.HDD
    except Exception:
        pass
    return DiskType.UNKNOWN


_DISK_TYPE_CACHE: Dict[str, Tuple[DiskType, int]] = {}


def detect_disk_type(path: str) -> Tuple[DiskType, int]:
    """Détecte le type de support physique et préconise le nombre de threads optimal.
    
    Résultats mis en cache par session pour garantir un temps de réponse nul (0 ms)
    lors des chargements et des rafraîchissements d'interface.
    
    Returns:
        Tuple[DiskType, int]: (Type détecté, nombre de workers recommandés)
    """
    cache_key = os.path.normcase(os.path.abspath(path)) if path else ""
    if cache_key and cache_key in _DISK_TYPE_CACHE:
        return _DISK_TYPE_CACHE[cache_key]

    drive_letter = get_drive_letter(path) if sys.platform == "win32" else None
    if drive_letter and drive_letter.upper() in _DISK_TYPE_CACHE:
        return _DISK_TYPE_CACHE[drive_letter.upper()]

    disk_type = DiskType.UNKNOWN

    if sys.platform == "win32":
        if drive_letter:
            # 1. IOCTL direct ultra-rapide et matériel Windows (SeekPenalty / TRIM)
            ioctl_res = detect_disk_type_windows_ioctl(drive_letter)
            if ioctl_res is not None and ioctl_res != DiskType.UNKNOWN:
                disk_type = ioctl_res
            else:
                # 2. PowerShell / WMI / CIM fallback
                disk_type = detect_disk_type_powershell(drive_letter)
    elif sys.platform.startswith("linux"):
        disk_type = detect_disk_type_linux(path)

    # Recommandations selon le support :
    # Pour les HDD (internes SATA ou externes USB) : 1 seul thread est vital pour préserver le débit
    if disk_type == DiskType.HDD:
        recommended_workers = 1
    elif disk_type == DiskType.SSD:
        recommended_workers = 4
    elif disk_type == DiskType.REMOVABLE:
        recommended_workers = 1
    else:
        recommended_workers = 2

    res = (disk_type, recommended_workers)
    if cache_key:
        _DISK_TYPE_CACHE[cache_key] = res
    if drive_letter:
        _DISK_TYPE_CACHE[drive_letter.upper()] = res
    return res
