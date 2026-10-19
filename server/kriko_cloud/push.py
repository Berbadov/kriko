"""Telling a phone. ntfy takes a plain POST to a topic only the paired devices can derive."""

from __future__ import annotations

import logging
import re
import urllib.request

log = logging.getLogger(__name__)

TOPIC = re.compile(r"^kriko-[0-9a-f]{32}$")


def send(base: str, topic: str, title: str, message: str) -> bool:
    """Push one message. `False` (and a log line, never a raise) when it could not go."""
    if not TOPIC.match(topic or "") or not base:
        return False
    headers = {"Title": title.encode("utf-8", "replace").decode("latin-1", "replace"), "Priority": "default",
               "Tags": "chart_with_downwards_trend"}
    request = urllib.request.Request(f"{base.rstrip('/')}/{topic}", data=message.encode("utf-8"),
                                     headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10):  # noqa: S310 - the operator's own ntfy
            return True
    except Exception:  # noqa: BLE001 - a failed push must not stop the sweep
        log.warning("could not push to ntfy", exc_info=True)
        return False
