"""Keep inherited engine/MCP pipes in a Windows GUI-subsystem executable.

The windowed bootloader avoids allocating a console even when another agent
starts Kriko's MCP server without CREATE_NO_WINDOW. Python leaves its standard
streams unset in this mode, so reconnect the handles supplied by the parent.
No console is allocated, attached, or hidden after it has already appeared.
"""

import os
import sys

if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    ]
    kernel.DuplicateHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    process = kernel.GetCurrentProcess()

    for name, number, mode, flags in (
        ("stdin", -10, "r", os.O_RDONLY),
        ("stdout", -11, "w", os.O_WRONLY),
        ("stderr", -12, "w", os.O_WRONLY),
    ):
        if getattr(sys, name) is not None:
            continue
        handle = kernel.GetStdHandle(number & 0xFFFFFFFF)
        duplicate = wintypes.HANDLE()
        stream = None
        if handle not in (None, ctypes.c_void_p(-1).value) and kernel.DuplicateHandle(
            process, handle, process, ctypes.byref(duplicate), 0, False, 2,
        ):
            try:
                fd = msvcrt.open_osfhandle(duplicate.value, flags | os.O_BINARY)
            except OSError:
                kernel.CloseHandle(duplicate)
            else:
                stream = os.fdopen(fd, mode, buffering=1, encoding="utf-8", errors="replace")
        if stream is None:
            stream = open(os.devnull, mode, encoding="utf-8")
        setattr(sys, name, stream)
        setattr(sys, f"__{name}__", stream)
