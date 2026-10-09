"""Windows launch options for background helpers with no visible console."""

import subprocess


def hidden_startup():
    """Also suppress a window when a launcher creates its own console."""
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info
