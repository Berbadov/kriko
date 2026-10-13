"""Runtime-reported device use and settings supported by that runtime.

A GPU found on the computer is not evidence that inference uses it. Ollama
reports loaded model and VRAM bytes; other compatible servers may not report
device use, so they remain unknown and their loader settings stay external.
"""
import json
import urllib.request

from app import prefs


def options(mine: dict) -> dict:
    out = {}
    device = mine.get(prefs.LOCAL_DEVICE, "")
    layers = mine.get(prefs.LOCAL_GPU_LAYERS, "")
    if device == "cpu":
        out["num_gpu"] = 0
    elif device == "gpu":
        out["num_gpu"] = -1
    if device != "cpu" and layers:
        try:
            value = int(layers)
            if -1 <= value <= 999:
                out["num_gpu"] = value
        except ValueError:
            pass
    try:
        context = int(mine.get(prefs.LOCAL_CONTEXT) or 0)
        if 512 <= context <= 131072:
            out["num_ctx"] = context
    except ValueError:
        pass
    return out


def _model_key(value: object) -> str:
    """Ollama may report a default tag that the selected name leaves implicit."""
    name = str(value or "").strip().casefold()
    for prefix in ("registry.ollama.ai/library/", "registry.ollama.ai/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.removesuffix(":latest")


def inspect(url: str, runtime: str, model: str, mine: dict) -> dict:
    if runtime == "configured" and url:
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/api/version", timeout=2) as response:
                payload = json.load(response)
            if isinstance(payload, dict) and isinstance(payload.get("version"), str):
                runtime = "Ollama"
        except (OSError, ValueError, TypeError):
            pass
    requested_device = mine.get(prefs.LOCAL_DEVICE, "") or "auto"
    out = {"device": "unknown", "model": model, "runtime": runtime,
           "loaded": False, "requested_device": requested_device,
           "requested_gpu_layers": mine.get(prefs.LOCAL_GPU_LAYERS, "") or "runtime default",
           "device_source": "",
           "supported": runtime == "Ollama", "requested": options(mine), "settings": mine,
           "memory_bytes": None, "vram_bytes": None, "context_tokens": None,
           "reason": "The runtime has not reported device use.",
           "settings_help": (
               "Ollama applies device, GPU layers and context to the next request. "
               "Changing these can reload the model. GPU is a request; check the "
               "reported device after a run. Memory allocation is managed by Ollama."
               if runtime == "Ollama" else
               "Set GPU offload and context in your runtime's model loader, then "
               "reload the model. This server does not expose these controls to Kriko.")}
    if runtime != "Ollama" or not url or not model:
        return out
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/ps", timeout=2) as response:
            payload = json.load(response)
        for row in payload.get("models", []):
            if not isinstance(row, dict) or _model_key(model) not in {
                    _model_key(row.get("name")), _model_key(row.get("model"))}:
                continue
            out["loaded"] = True
            size, vram = row.get("size"), row.get("size_vram")
            if isinstance(size, int) and size > 0 and isinstance(vram, int) and vram >= 0:
                actual = "cpu" if vram == 0 else "gpu" if vram >= size else "mixed"
                out.update(memory_bytes=size, vram_bytes=vram,
                           device=actual, device_source="Ollama /api/ps",
                           gpu_offload_percent=min(100, round(vram * 100 / size)))
                if actual == "cpu" and requested_device == "gpu":
                    out["reason"] = (
                        "Ollama reports CPU use for this loaded model despite the GPU request. "
                        "Check Ollama's GPU backend, driver and available memory, then refresh."
                    )
                elif actual == "mixed":
                    out["reason"] = (
                        f"Ollama reports mixed CPU/GPU use ({out['gpu_offload_percent']}% of "
                        "the model allocation is in VRAM). Check available VRAM if you expected "
                        "full GPU offload."
                    )
                elif actual == "cpu":
                    out["reason"] = "Ollama reports CPU use for this loaded model."
                else:
                    out["reason"] = "Ollama reports GPU allocation for this loaded model."
            else:
                out["reason"] = (
                    "Ollama reports the model loaded but did not report its VRAM allocation."
                )
            context = row.get("context_length")
            if isinstance(context, int) and not isinstance(context, bool) and context > 0:
                out["context_tokens"] = context
            break
        else:
            out["reason"] = "The model is not loaded. Run it, then refresh to see its device."
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return out
