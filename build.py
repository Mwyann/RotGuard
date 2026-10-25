"""Script autonome de compilation de RotGuard en exécutable Windows (.exe) via PyInstaller."""

import os
import sys
import subprocess


def main():
    print("=" * 60)
    print("      RotGuard — Compilation en Exécutable Autonome (.exe)")
    print("=" * 60)
    print(f"Interpréteur Python : {sys.executable}")
    print(f"Version Python      : {sys.version.split()[0]}")
    print()

    # 1. Vérification de la présence de PyInstaller
    print("[1/3] Vérification de PyInstaller...")
    try:
        import PyInstaller
        print(f"      PyInstaller détecté (version {PyInstaller.__version__}).")
    except ImportError:
        print("      PyInstaller non détecté. Installation automatique en cours via pip...")
        try:
            res = subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=False)
            if res.returncode != 0:
                print("      Nouvelle tentative avec l'option --user...")
                res = subprocess.run([sys.executable, "-m", "pip", "install", "--user", "pyinstaller"], check=False)
            if res.returncode != 0:
                print("\n[ERREUR] Impossible d'installer PyInstaller via pip.")
                print("Veuillez installer PyInstaller manuellement avec :")
                print(f"  {sys.executable} -m pip install pyinstaller")
                sys.exit(1)
        except Exception as e:
            print(f"\n[ERREUR] Échec du lancement de pip : {e}")
            sys.exit(1)

    # 2. Compilation avec PyInstaller
    print("\n[2/3] Compilation de RotGuard avec icône officielle...")
    ico_path = os.path.join("assets", "rotguard.ico")
    assets_sep = f"assets{os.pathsep}assets"

    build_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onefile",
        "--clean",
        "--name",
        "RotGuard",
        "--add-data",
        assets_sep,
        "main.py"
    ]

    if os.path.exists(ico_path):
        build_cmd.insert(-1, "--icon")
        build_cmd.insert(-1, ico_path)

    print(f"      Commande : {' '.join(build_cmd)}")
    result = subprocess.run(build_cmd)

    # 3. Résultat
    print("\n[3/3] Bilan de la compilation...")
    exe_path = os.path.join("dist", "RotGuard.exe")
    if result.returncode == 0 and os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print("=" * 60)
        print("  [SUCCÈS] Exécutable généré avec succès !")
        print(f"  Emplacement : {os.path.abspath(exe_path)}")
        print(f"  Taille      : {size_mb:.2f} Mo")
        print("=" * 60)
        print("\nVous pouvez lancer directement dist\\RotGuard.exe sans Python.")
    else:
        print("=" * 60)
        print("  [ERREUR] La compilation a échoué.")
        print(f"  Code de retour : {result.returncode}")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
