import os
import sys

WINDOWS = sys.platform == "win32"


class TermSession:
    def __init__(self):
        self.proc = None

    def start(self, cols: int = 80, rows: int = 24) -> None:
        if self.proc is not None and self.alive():
            return
        home = os.path.expanduser("~")
        if WINDOWS:
            import winpty

            shell = os.environ.get("COMSPEC", "powershell.exe")
            self.proc = winpty.PtyProcess.spawn(
                shell, cwd=home, dimensions=(rows, cols)
            )
        else:
            import ptyprocess

            shell = os.environ.get("SHELL", "/bin/sh")
            self.proc = ptyprocess.PtyProcess.spawn(
                [shell], cwd=home, dimensions=(rows, cols)
            )

    def alive(self) -> bool:
        return self.proc is not None and self.proc.isalive()

    def read(self, n: int = 65536) -> str:
        data = self.proc.read(n)
        return data.decode("utf-8", "replace") if isinstance(data, bytes) else data

    def write(self, data: str) -> None:
        self.proc.write(data if WINDOWS else data.encode("utf-8"))

    def resize(self, cols: int, rows: int) -> None:
        self.proc.setwinsize(rows, cols)

    def close(self) -> None:
        if self.proc is not None:
            try:
                self.proc.close(force=True)
            except Exception:
                pass
            self.proc = None


SESSION = TermSession()
