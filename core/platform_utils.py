"""Utilitaires multi-plateformes (Windows, Linux, macOS) pour RotGuard."""

import os
import sys
import time
import subprocess
from typing import Optional


IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"


def is_running_as_admin() -> bool:
    """Vérifie si le processus possède les privilèges administrateur (root sous Linux/macOS)."""
    if IS_WINDOWS:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    else:
        try:
            return os.geteuid() == 0
        except Exception:
            return False


def request_elevation():
    """Tente de relancer le programme avec des privilèges élevés (UAC sous Windows, pkexec sous Linux).
    
    Compatible à 100% avec les fichiers compilés en .exe (PyInstaller/cx_Freeze) et les scripts Python.
    """
    if is_running_as_admin():
        return

    is_frozen = getattr(sys, "frozen", False)

    if IS_WINDOWS:
        try:
            import ctypes

            if is_frozen:
                # Dans un .exe compilé, sys.executable est le binaire lui-même
                executable = sys.executable
                work_dir = os.path.dirname(os.path.abspath(sys.executable))
                # Transmettre uniquement les arguments CLI supplémentaires, sans réinjecter sys.argv[0]
                cli_args = sys.argv[1:]
                params = subprocess.list2cmdline(cli_args) if cli_args else ""
            else:
                # En mode script Python
                executable = sys.executable
                script_path = os.path.abspath(sys.argv[0])
                work_dir = os.path.dirname(script_path)
                cli_args = [script_path] + sys.argv[1:]
                params = subprocess.list2cmdline(cli_args)

            ret = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                executable,
                params,
                work_dir,
                1
            )
            # Un code retour > 32 indique que le prompt UAC a été accepté et le nouveau processus démarré
            if ret > 32:
                os._exit(0)
        except Exception:
            pass
    elif IS_LINUX:
        if is_frozen:
            args = ["pkexec", sys.executable] + sys.argv[1:]
        else:
            args = ["pkexec", sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]
        try:
            subprocess.Popen(args)
            os._exit(0)
        except Exception:
            pass


def open_in_file_manager(path: str):
    """Ouvre le gestionnaire de fichiers de l'OS (Explorateur Windows, Nautilus/Dolphin sous Linux, Finder sous macOS).
    Sélectionne le fichier dans son dossier s'il existe.
    """
    if not path:
        return

    norm = os.path.normpath(os.path.abspath(path))
    if IS_WINDOWS:
        if os.path.isfile(norm):
            # IMPORTANT : sous Windows, explorer.exe /select attend une chaîne unique avec guillemets autour du chemin
            # Passer une liste ou des guillemets autour de /select provoque l'ouverture de Documents / Ce PC
            subprocess.Popen(f'explorer /select,"{norm}"')
        elif os.path.isdir(norm):
            subprocess.Popen(f'explorer "{norm}"')
        else:
            # Si le fichier physique n'existe plus (ex: manquant/supprimé), ouvrir son dossier parent
            parent = os.path.dirname(norm)
            if os.path.isdir(parent):
                subprocess.Popen(f'explorer "{parent}"')
            else:
                subprocess.Popen(f'explorer /select,"{norm}"')
    elif IS_LINUX:
        # Si c'est un fichier, on ouvre son dossier parent
        target = norm if os.path.isdir(norm) else os.path.dirname(norm)
        if os.path.exists(target):
            try:
                # Essayer d'abord d'ouvrir le dossier
                subprocess.Popen(["xdg-open", target])
            except Exception:
                pass
    elif IS_MACOS:
        if os.path.exists(norm):
            subprocess.Popen(["open", "-R", norm])
        else:
            parent = os.path.dirname(norm)
            if os.path.exists(parent):
                subprocess.Popen(["open", parent])


def suspend_system():
    """Met la machine en veille selon l'OS."""
    if IS_WINDOWS:
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=False)
    elif IS_LINUX:
        subprocess.run(["systemctl", "suspend"], check=False)
    elif IS_MACOS:
        subprocess.run(["pmset", "sleepnow"], check=False)


def poweroff_system():
    """Éteint la machine selon l'OS."""
    if IS_WINDOWS:
        subprocess.run(["shutdown.exe", "/s", "/t", "0"], check=False)
    elif IS_LINUX:
        subprocess.run(["systemctl", "poweroff"], check=False)
    elif IS_MACOS:
        subprocess.run(["shutdown", "-h", "now"], check=False)


def play_completion_sound(has_error: bool = False, parent_widget=None):
    """Joue un signal sonore (1 bip de succès, 3 bips si erreur)."""
    count = 3 if has_error else 1

    for i in range(count):
        played = False
        if IS_WINDOWS:
            try:
                import winsound
                sound_type = winsound.MB_ICONHAND if has_error else winsound.MB_ICONASTERISK
                winsound.MessageBeep(sound_type)
                played = True
            except Exception:
                pass

        if not played and parent_widget is not None:
            try:
                parent_widget.bell()
                played = True
            except Exception:
                pass

        if not played:
            try:
                # Signal sonore terminal / stdout
                sys.stdout.write("\a")
                sys.stdout.flush()
            except Exception:
                pass

        if i < count - 1:
            time.sleep(0.35)


def set_process_cpu_priority(priority: str) -> bool:
    """Modifie la priorité processeur (CPU) du processus courant.
    
    Valeurs supportées : 'low', 'below_normal', 'normal', 'above_normal', 'high'.
    """
    p = (priority or "normal").lower()
    if IS_WINDOWS:
        try:
            import ctypes
            h_proc = ctypes.windll.kernel32.GetCurrentProcess()
            win_cpu_map = {
                "low": 0x00000040,           # IDLE_PRIORITY_CLASS
                "below_normal": 0x00004000,  # BELOW_NORMAL_PRIORITY_CLASS
                "normal": 0x00000020,        # NORMAL_PRIORITY_CLASS
                "above_normal": 0x00008000,  # ABOVE_NORMAL_PRIORITY_CLASS
                "high": 0x00000080           # HIGH_PRIORITY_CLASS
            }
            val = win_cpu_map.get(p, 0x00000020)
            return bool(ctypes.windll.kernel32.SetPriorityClass(h_proc, val))
        except Exception:
            return False
    elif IS_LINUX:
        try:
            nice_map = {
                "low": 15,
                "below_normal": 5,
                "normal": 0,
                "above_normal": -5,
                "high": -10
            }
            val = nice_map.get(p, 0)
            os.setpriority(os.PRIO_PROCESS, 0, val)
            return True
        except Exception:
            return False
    return False


def set_process_io_priority(priority: str) -> bool:
    """Modifie la priorité d'E/S disque (I/O) du processus courant.
    
    Valeurs supportées : 'very_low', 'low', 'normal', 'high'.
    Sur Windows Vista/7/8/10/11 : utilise ProcessIoPriority (33) via ntdll ou kernel32.
    Sur Linux : utilise ionice si disponible.
    """
    p = (priority or "normal").lower()
    if IS_WINDOWS:
        try:
            import ctypes
            h_proc = ctypes.windll.kernel32.GetCurrentProcess()
            win_io_map = {
                "very_low": 0,
                "low": 1,
                "normal": 2,
                "high": 3
            }
            io_val = ctypes.c_ulong(win_io_map.get(p, 2))
            success = False

            # 1. Tenter via SetProcessInformation (Windows 8+)
            if hasattr(ctypes.windll.kernel32, "SetProcessInformation"):
                try:
                    ret = ctypes.windll.kernel32.SetProcessInformation(
                        h_proc,
                        33,  # ProcessInformationClass.ProcessIoPriority
                        ctypes.byref(io_val),
                        ctypes.sizeof(io_val)
                    )
                    if ret:
                        success = True
                except Exception:
                    pass

            # 2. Tenter via ntdll.NtSetInformationProcess (Windows Vista -> 11)
            if not success and hasattr(ctypes.windll.ntdll, "NtSetInformationProcess"):
                try:
                    status = ctypes.windll.ntdll.NtSetInformationProcess(
                        h_proc,
                        33,  # ProcessIoPriority
                        ctypes.byref(io_val),
                        ctypes.sizeof(io_val)
                    )
                    success = (status == 0)
                except Exception:
                    pass

            return success
        except Exception:
            return False
    elif IS_LINUX:
        try:
            pid = str(os.getpid())
            if p == "very_low":
                subprocess.run(["ionice", "-c3", "-p", pid], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif p == "low":
                subprocess.run(["ionice", "-c2", "-n7", "-p", pid], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif p == "normal":
                subprocess.run(["ionice", "-c2", "-n4", "-p", pid], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif p == "high":
                subprocess.run(["ionice", "-c2", "-n0", "-p", pid], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False
    return False


def apply_process_priorities(cpu_priority: str = "normal", io_priority: str = "normal"):
    """Applique simultanément la priorité CPU et la priorité I/O configurées."""
    set_process_cpu_priority(cpu_priority)
    set_process_io_priority(io_priority)


def send_file_to_trash(file_path: str) -> bool:
    """Déplace un fichier vers la Corbeille de l'OS (Recycle Bin / Trash).
    
    Retourne True si le fichier a été déplacé dans la corbeille avec succès, False sinon.
    """
    if not os.path.exists(file_path):
        return True

    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes

            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR),
                    ("fFlags", wintypes.WORD),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", wintypes.LPVOID),
                    ("lpszProgressTitle", wintypes.LPCWSTR),
                ]

            FO_DELETE = 0x0003
            FOF_ALLOWUNDO = 0x0040        # Déplace dans la corbeille
            FOF_NOCONFIRMATION = 0x0010   # Ne redemande pas confirmation Windows
            FOF_SILENT = 0x0004           # Pas d'animation
            FOF_NOERRORUI = 0x0400        # Pas de boîte d'erreur native

            # pFrom doit être doublement terminé par \0
            abs_p = os.path.abspath(file_path)
            double_null_path = abs_p + "\0\0"

            fileop = SHFILEOPSTRUCTW()
            fileop.hwnd = None
            fileop.wFunc = FO_DELETE
            fileop.pFrom = double_null_path
            fileop.pTo = None
            fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
            fileop.fAnyOperationsAborted = False
            fileop.hNameMappings = None
            fileop.lpszProgressTitle = None

            ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
            return (ret == 0 and not fileop.fAnyOperationsAborted)
        except Exception:
            return False
    elif IS_LINUX:
        try:
            res = subprocess.run(["gio", "trash", file_path], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                return True
            res = subprocess.run(["trash-put", file_path], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return (res.returncode == 0)
        except Exception:
            return False
    elif IS_MACOS:
        try:
            cmd = f'tell application "Finder" to delete POSIX file "{file_path}"'
            res = subprocess.run(["osascript", "-e", cmd], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return (res.returncode == 0)
        except Exception:
            return False
    return False


def show_native_notification(title: str, message: str, is_error: bool = False):
    """Affiche une notification système native (Toast Windows 10/11, notify-send sous Linux)."""
    if IS_WINDOWS:
        try:
            clean_title = title.replace("'", "''").replace("\n", " ")
            clean_msg = message.replace("'", "''").replace("\n", " ")
            ps_code = f"""
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName('text')
            $textNodes.Item(0).AppendChild($template.CreateTextNode('{clean_title}')) | Out-Null
            $textNodes.Item(1).AppendChild($template.CreateTextNode('{clean_msg}')) | Out-Null
            $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('RotGuard').Show($toast)
            """
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_code],
                startupinfo=startupinfo,
                creationflags=0x08000000,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass
    elif IS_LINUX:
        try:
            urgency = "critical" if is_error else "normal"
            subprocess.Popen(["notify-send", "-u", urgency, title, message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    elif IS_MACOS:
        try:
            script = f'display notification "{message}" with title "{title}"'
            subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
