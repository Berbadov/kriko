"""The computer Kriko runs on: GPU, memory, processor, installed runtimes.

Read-only. `app/machine.py` asks the machine and caches the answer for a
minute; a field the machine did not report is `null`, never an estimate.
"""

from fastapi import APIRouter

from app import machine

router = APIRouter(prefix="/api", tags=["machine"])


@router.get("/machine")
def read_machine(fresh: bool = False) -> dict:
    return machine.read(fresh=fresh)
