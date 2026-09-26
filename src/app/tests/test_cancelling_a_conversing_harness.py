"""ops-2: cancelling a harness research run must complete and never wedge
the single job worker.

`_stream`'s teardown used to `taskkill /T` the child and then block on
`pipe.close()`. On Windows, `taskkill /T` walks the *live* parent-pid chain,
so it misses a descendant whose own parent has already exited — exactly
what a conversing CLI's stdin-reading shim looks like once its parent dies
— and closing a pipe a surviving grandchild still holds blocks forever,
wedging the worker thread and every job queued behind it.

This runs a real subprocess (a stand-in CLI that sleeps, never answering)
so the fix is proven against `subprocess.Popen` and threads, not against a
mock of them. It cannot spawn Windows' own broken-parent-chain shape from
this sandbox, but it does prove the two things this file's own code can
promise everywhere: a cancel completes in bounded time, and the job object
plumbing (`_new_job_object`/`_assign_job`/`_kill_tree`) does not itself
raise or hang on the platform running the suite.
"""

import sys
import time

import pytest

from app.providers import harness as harness_mod
from app.web.jobs import Cancelled


def _sleepy_cli(tmp_path):
    """A CLI that reads nothing, says nothing, and sleeps far past any
    reasonable cancel — the stand-in for a conversing harness that has
    stopped to think and has not yet been asked anything."""
    script = tmp_path / "fake_sleepy_cli.py"
    script.write_text(
        "import sys, time\n"
        "sys.stdin.read()\n"  # blocks until stdin is closed, same as a real CLI mid-turn
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    return harness_mod.Harness(
        "sleepy", "Sleepy CLI", sys.executable, (str(script), "-p"), structured=False,
    )


def test_a_cancelled_stream_completes_in_bounded_time(tmp_path):
    fake = _sleepy_cli(tmp_path)
    researcher = harness_mod.HarnessResearcher(fake, timeout=60.0)

    cancelled_after = {"ticks": 2}

    def check_cancelled():
        cancelled_after["ticks"] -= 1
        if cancelled_after["ticks"] <= 0:
            raise Cancelled()

    researcher.check_cancelled = check_cancelled
    researcher.replies = lambda: []

    started = time.monotonic()
    with pytest.raises(Cancelled):
        researcher._stream([fake.executable, str(tmp_path / "fake_sleepy_cli.py"), "-p"],
                            stdin_read=None, say=None)
    elapsed = time.monotonic() - started
    # A silent tick is 0.5s (`_cancel_tick`) and the cancel fires on the
    # second one, so this should return in a couple of seconds — nothing
    # like the 40-90s wedge the audit observed.
    assert elapsed < 10.0


def test_the_job_object_helpers_never_raise_off_windows(tmp_path):
    """`_new_job_object`/`_assign_job`/`_kill_tree` are exercised on every
    platform this suite runs on (POSIX here), and must be inert rather than
    a source of new failures where there is no Job Object API to call."""
    job = harness_mod.HarnessResearcher._new_job_object()
    if sys.platform != "win32":
        assert job is None

    class _FakeProc:
        pid = 999999
        _handle = None

        def kill(self):
            pass

    harness_mod.HarnessResearcher._assign_job(job, _FakeProc())
    harness_mod.HarnessResearcher._kill_tree(_FakeProc(), job)
