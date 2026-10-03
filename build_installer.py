"""
build_installer.py – One-command build script to package Ratnodadhi into an installable Windows .exe.

Steps performed:
1. Ensures PyInstaller is installed.
2. Runs PyInstaller with ratnodadhi.spec to build the application into dist/Ratnodadhi/.
3. Detects Inno Setup Compiler (iscc.exe) and compiles installer.iss into dist-installer/Ratnodadhi-Setup-v6.0.exe.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str], desc: str) -> None:
    print(f"\n==> {desc}...")
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"ERROR: {desc} failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def find_inno_setup_compiler() -> str | None:
    """Check PATH, common Program Files install paths, and Windows Registry for ISCC.exe."""
    iscc = shutil.which("iscc")
    if iscc:
        return iscc

    common_paths = [
        # Check Inno Setup 7 first
        Path(os.environ.get("LocalAppData", "")) / "Programs" / "Inno Setup 7" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Inno Setup 7" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 7" / "ISCC.exe",
        Path("C:/Inno Setup 7/ISCC.exe"),
        # Check Inno Setup 6
        Path(os.environ.get("LocalAppData", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path("C:/Inno Setup 6/ISCC.exe"),
    ]
    for p in common_paths:
        if p.exists():
            return str(p)

    # Search Windows Registry for Inno Setup installation directory
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for subkey in (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 7_is1",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 7_is1",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 5_is1",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 5_is1",
            ):
                try:
                    with winreg.OpenKey(root, subkey) as key:
                        install_dir, _ = winreg.QueryValueEx(key, "InstallLocation")
                        candidate = Path(install_dir) / "ISCC.exe"
                        if candidate.exists():
                            return str(candidate)
                except OSError:
                    pass
    except Exception:
        pass

    return None


def main() -> None:
    root_dir = Path(__file__).parent.resolve()
    os.chdir(root_dir)

    installer_only = "--installer-only" in sys.argv

    print("=" * 60)
    print("  Ratnodadhi (BookLib) Windows Installer Builder")
    print("=" * 60)

    dist_app = root_dir / "dist" / "Ratnodadhi" / "Ratnodadhi.exe"

    if installer_only and dist_app.exists():
        print(f"\n[INFO] Skipping PyInstaller (--installer-only specified).")
        print(f"Using existing application bundle at: {dist_app.parent}")
    else:
        # 1. Check / Install PyInstaller
        try:
            import PyInstaller
            print(f"PyInstaller {PyInstaller.__version__} is available.")
        except ImportError:
            print("PyInstaller not found. Installing PyInstaller...")
            run_cmd([sys.executable, "-m", "pip", "install", "pyinstaller"], "Installing PyInstaller")

        # 2. Build application with PyInstaller
        spec_file = root_dir / "ratnodadhi.spec"
        if not spec_file.exists():
            print(f"ERROR: Specification file '{spec_file}' not found.")
            sys.exit(1)

        run_cmd([sys.executable, "-m", "PyInstaller", "--noconfirm", "ratnodadhi.spec"], "Building Ratnodadhi executable bundle")

        if not dist_app.exists():
            print(f"ERROR: Expected build output '{dist_app}' was not created.")
            sys.exit(1)

        print(f"\n[SUCCESS] Standalone application built successfully at:")
        print(f"  {dist_app.parent}")

    # 3. Compile Windows Installer with Inno Setup
    iscc_path = find_inno_setup_compiler()
    if iscc_path:
        print(f"\nFound Inno Setup Compiler at: {iscc_path}")
        run_cmd([iscc_path, str(root_dir / "installer.iss")], "Compiling Inno Setup installer")
        installer_out = root_dir / "dist-installer"
        print("\n" + "=" * 60)
        print("  *** INSTALLER BUILD COMPLETE! ***")
        print("=" * 60)
        print(f"Installable .exe is located in:\n  {installer_out}")
        print("\nDistribution notes:")
        print("  - Users can run this installer to perform a clean installation.")
        print("  - To issue updates, simply increment MyAppVersion in 'installer.iss' and rebuild.")
        print("  - Running the new installer on an existing machine will seamlessly update the files")
        print("    and preserve all user databases, covers, and settings.")
    else:
        print("\n" + "=" * 60)
        print("  NOTICE: Inno Setup Compiler (ISCC.exe) not detected.")
        print("=" * 60)
        print("Your application executable bundle is ready in:")
        print(f"  {dist_app.parent}")
        print("\nTo compile the installable Setup.exe:")
        print("1. Install Inno Setup (free & open source):")
        print("   - Via Winget:  winget install JRSoftware.InnoSetup")
        print("   - Or download: https://jrsoftware.org/isdl.php")
        print("2. Re-run this builder:  python build_installer.py --installer-only")
        print("   OR right-click 'installer.iss' in Windows Explorer and choose 'Compile'.")
        print("\nThe resulting installer will be in 'dist-installer/'.")


if __name__ == "__main__":
    main()
