"""Downloading a model through Ollama, with its own progress and its own errors.

Ollama is the one runtime that takes a download over HTTP: `POST /api/pull`
streams newline-delimited JSON, one line per step, and says `{"error": ...}`
when it cannot. This module relays that stream into a job's progress and
nothing else. It knows no model name, size or catalogue: the model is the
reader's to name, and the size is whatever Ollama reports for it.

A download is many layers, each with its own `total` and `completed`; the job
shows the sum, so the bar moves forward as a whole instead of restarting for
every layer.
"""

import json
import re
import time
import urllib.error
import urllib.request

from app import prefs
from app.providers import local_discovery as discovery

#: Ollama names a model `name[:tag]`, with an optional `namespace/` and host.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-:/@]{0,199}$")

#: A line may be minutes apart on a slow link while one layer downloads.
STREAM_TIMEOUT = 120.0

#: How often the job row is rewritten, so a fast link does not write a
#: thousand rows a second.
REPORT_EVERY = 0.4

PROBE_TIMEOUT = 3.0


def valid_name(model: str) -> bool:
    return bool(_NAME.match(model or ""))


def ollama_base(app_state_path=None) -> str:
    """Where Ollama answers, or "" when nothing there says it is Ollama."""
    from app import localplane

    mine = localplane.stored(app_state_path)
    for server in discovery.discover(mine[prefs.LOCAL_URL]):
        if server["name"] == "Ollama" and server["up"]:
            return str(server["url"])
    return ""


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB"


def pull(base: str, model: str, progress, *, opener=urllib.request.urlopen) -> dict:
    """Stream `model` down through the Ollama at `base`.

    Raises `RuntimeError` with Ollama's own words when it refuses, and
    `Cancelled` (through `progress.check`) when the reader stops it; closing
    the stream is what tells Ollama to stop sending.
    """
    request = urllib.request.Request(
        base.rstrip("/") + "/api/pull",
        data=json.dumps({"model": model, "stream": True}).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    layers: dict[str, tuple[float, float]] = {}
    last_report = 0.0
    status = "starting"
    shown = 0.0
    progress.set(0.0, f"asking Ollama for {model}")
    try:
        response = opener(request, timeout=STREAM_TIMEOUT)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_error_text(exc.read()) or f"Ollama answered HTTP {exc.code}") from exc
    except OSError as exc:
        raise RuntimeError(f"Ollama did not answer at {base}: {exc}") from exc
    try:
        for raw in response:
            progress.check()
            try:
                line = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if not isinstance(line, dict):
                continue
            if line.get("error"):
                raise RuntimeError(str(line["error"]))
            said = str(line.get("status") or "")
            if said and said != status:
                status = said
                progress.log(said if not said.startswith("pulling ") or "digest" not in line
                             else "pulling a layer")
            digest, total, done = line.get("digest"), line.get("total"), line.get("completed")
            if digest and isinstance(total, (int, float)) and total > 0:
                layers[str(digest)] = (float(done or 0), float(total))
            if said == "success":
                break
            now = time.monotonic()
            if layers and now - last_report >= REPORT_EVERY:
                last_report = now
                got = sum(c for c, _ in layers.values())
                size = sum(t for _, t in layers.values())
                # Ollama names layers as it reaches them, so the known total
                # grows; the bar waits for it rather than stepping back.
                shown = max(shown, min(got / size, 0.99))
                progress.set(shown, f"{_gb(got)} of {_gb(size)}")
        else:
            raise RuntimeError("Ollama closed the download before it finished.")
    except OSError as exc:
        raise RuntimeError(f"The download from Ollama broke off: {exc}") from exc
    finally:
        close = getattr(response, "close", None)
        if close:
            close()
    size = sum(t for _, t in layers.values())
    progress.set(1.0, f"{model} is ready")
    return {"model": model, "runtime": "ollama", "bytes": int(size)}


def installed(base: str, *, opener=urllib.request.urlopen) -> list[dict]:
    """What the Ollama at `base` holds, with the sizes it reports.

    Ollama's own `GET /api/tags`, passed through: name, bytes on disk,
    parameter count and quantisation exactly as it says them, and a field it
    leaves out is `None`. Sizing a model against the GPU needs the bytes, and
    the bytes are Ollama's to know.
    """
    try:
        with opener(base.rstrip("/") + "/api/tags", timeout=PROBE_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
    except (OSError, ValueError):
        return []
    out = []
    for row in (body.get("models") if isinstance(body, dict) else None) or []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        details = row.get("details")
        if not isinstance(details, dict):
            details = {}
        size = row.get("size")
        out.append({
            "name": str(row["name"]),
            "size_bytes": size if isinstance(size, int) and not isinstance(size, bool) else None,
            "params": details.get("parameter_size") or None,
            "quant": details.get("quantization_level") or None,
            "family": details.get("family") or None,
        })
    return out


def _error_text(body: bytes) -> str:
    try:
        said = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return body.decode("utf-8", "replace").strip()[:300]
    if isinstance(said, dict):
        return str(said.get("error") or "")
    return ""
