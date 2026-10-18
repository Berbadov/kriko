"""Does the installer install, and does it remove what it installed?

    python packaging/smoke_installer.py kriko-ui/builds/kriko-<v>-x86_64-setup.exe

The installer is the one thing a reader runs that no other check runs. This
runs it without a prompt (`/S`) into a scratch folder (`/D=`), looks at what it
wrote, runs the uninstaller it left (`/S` again), and looks at what remains.

What it asserts:

* the three programs and the licence are in the folder, because the app looks
  for its engine beside `kriko.exe` and the engine looks for OpenSERP beside
  itself;
* an uninstaller is there;
* after the uninstall, the programs are gone.

Per-user and quiet, but not free of side effects: the installer writes the
current user's Start-menu and uninstall entries, and those have one name per
machine. So this refuses to run where a Kriko is already installed, rather
than replace the reader's copy with a scratch one and then remove it.
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROGRAMS = ("kriko.exe", "kriko-sidecar.exe", "OpenSERP.exe")
LICENCE = "OpenSERP-LICENSE.txt"


def already_installed() -> str:
    """The folder of an installed Kriko, or the empty string."""
    local = os.environ.get("LOCALAPPDATA", "")
    for candidate in (Path(local) / "Kriko", Path(local) / "Programs" / "Kriko"):
        if (candidate / "kriko.exe").exists():
            return str(candidate)
    try:
        import winreg
    except ImportError:
        return ""
    base = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as root:
            for index in range(winreg.QueryInfoKey(root)[0]):
                name = winreg.EnumKey(root, index)
                if name.lower().endswith("kriko"):
                    return f"HKCU\\{base}\\{name}"
    except OSError:
        return ""
    return ""


def stop_ours(folder: Path) -> None:
    """End anything running out of the scratch folder, and only that."""
    for name in PROGRAMS:
        subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Get-Process -Name {Path(name).stem} -ErrorAction SilentlyContinue "
                f"| Where-Object {{ $_.Path -like '{folder}*' }} "
                "| ForEach-Object { taskkill /F /T /PID $_.Id | Out-Null }",
            ],
            capture_output=True,
            timeout=60,
        )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    setup = Path(argv[1]).resolve()
    if not setup.exists():
        print(f"no such installer: {setup}")
        return 1
    if sys.platform != "win32":
        print("the installer is a Windows program; nothing to run here")
        return 1
    found = already_installed()
    if found:
        print(
            f"Kriko is already installed ({found}). This check would replace it "
            "with a scratch copy and remove that, so it does not run here."
        )
        return 1

    scratch = Path(tempfile.mkdtemp(prefix="kriko-install-smoke-"))
    target = scratch / "Kriko"
    try:
        # `/D=` has to be last, and unquoted: it is NSIS's own argument syntax.
        done = subprocess.run(
            f'"{setup}" /S /D={target}', timeout=600, shell=False
        )
        if done.returncode != 0:
            print(f"the installer exited with {done.returncode}")
            return 1
        missing = [n for n in (*PROGRAMS, LICENCE) if not (target / n).exists()]
        if missing:
            print(f"installed, but {missing} are not in {target}")
            return 1
        uninstaller = target / "uninstall.exe"
        if not uninstaller.exists():
            print(f"no uninstall.exe in {target}")
            return 1
        print(f"installed: {sorted(p.name for p in target.iterdir())}")

        stop_ours(target)
        done = subprocess.run(f'"{uninstaller}" /S', timeout=600, shell=False)
        if done.returncode != 0:
            print(f"the uninstaller exited with {done.returncode}")
            return 1
        # The uninstaller copies itself out and deletes the folder as it exits.
        for _ in range(30):
            left = [n for n in PROGRAMS if (target / n).exists()]
            if not left:
                break
            time.sleep(1)
        if left:
            print(f"the uninstaller left {left} behind")
            return 1
        print("uninstalled: the programs are gone")
        return 0
    finally:
        stop_ours(scratch)
        subprocess.run(
            ["cmd", "/c", "rmdir", "/s", "/q", str(scratch)], capture_output=True
        )


if __name__ == "__main__":
    sys.exit(main(sys.argv))
