"""Record brief Windows process launches without needing to read window titles.

Run while reproducing a console flash: python tools/trace_processes.py
Only executable names, process IDs and ancestry are recorded, never commands.
"""

import argparse
import ctypes
import json
import os
import time
from ctypes import wintypes
from pathlib import Path


class ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("usage", wintypes.DWORD),
        ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
        ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
        ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
        ("flags", wintypes.DWORD), ("name", wintypes.WCHAR * 260),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--output", type=Path, default=Path("process-starts.jsonl"))
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("this trace requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    def snapshot():
        handle = kernel.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = ProcessEntry()
            entry.size = ctypes.sizeof(entry)
            rows = {}
            ok = kernel.Process32FirstW(handle, ctypes.byref(entry))
            while ok:
                rows[entry.pid] = (entry.name, entry.parent)
                ok = kernel.Process32NextW(handle, ctypes.byref(entry))
            return rows
        finally:
            kernel.CloseHandle(handle)

    previous = snapshot()
    parents = dict(previous)
    count = 0
    deadline = time.monotonic() + args.seconds
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Recording for {args.seconds:g}s to {args.output.resolve()}", flush=True)
    # Polling works without administrator rights; WMI ProcessStartTrace does
    # not. This can miss processes shorter than a snapshot, so an empty trace
    # is not proof that no process started.
    with args.output.open("w", encoding="utf-8") as output:
        while time.monotonic() < deadline:
            current = snapshot()
            parents.update(current)
            for pid in current.keys() - previous.keys():
                name, parent = current[pid]
                chain = []
                cursor = pid
                seen = set()
                while cursor in parents and cursor not in seen:
                    seen.add(cursor)
                    ancestor, ancestor_parent = parents[cursor]
                    chain.append(ancestor)
                    cursor = ancestor_parent
                row = {"time": time.time(), "name": name, "pid": pid,
                       "parent": parent, "ancestry": chain}
                output.write(json.dumps(row) + "\n")
                output.flush()
                count += 1
                if any(item.lower().startswith("kriko") for item in chain):
                    print(" -> ".join(reversed(chain)), flush=True)
            previous = current
            time.sleep(.002)
    print(f"Captured {count} process starts.", flush=True)


if __name__ == "__main__":
    main()
