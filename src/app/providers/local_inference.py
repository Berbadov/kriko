"""A completion socket for a local inference server.

Lives in `app/providers/` with the other sockets, not in the engine, for the
same reason `llm.py` does: the OpenAI-compatible wire protocol says
`"model"` and the domain-free guard bans that word from `kriko/` — a
protocol's vocabulary is the protocol's business, and the split between
engine shape and provider sockets is where that boundary is drawn.

Speaks `/v1/chat/completions`, the surface every serious local engine
exposes, so the plane never learns which binary is behind the port.
"""

import json
import urllib.request


class OpenAICompatSocket:
    """A completion socket for a local inference server.

    Speaks the OpenAI-compatible `/v1/chat/completions` surface that every
    serious local engine exposes, so the plane never learns which binary
    is behind the port. `response_json_schema` is honoured through the
    `json_schema` response-format when the server advertises it — engine-
    level grammar constraint, the strongest guarantee a small socket can
    get — and ignored without complaint when it does not.

    Temperature 0 for extraction: creativity in front of a grounding gate
    buys refusals, not findings.
    """

    def __init__(self, base_url: str, serving_name: str,
                 timeout: float = 120.0,
                 temperature: float = 0.0,
                 context_chars: int = 12000,
                 response_json_schema: str = ""):
        self.base_url = base_url.rstrip("/")
        self.serving_name = serving_name
        self.timeout = timeout
        self.temperature = temperature
        self.context_chars = context_chars
        self._schema = response_json_schema
        self.tokens_used = 0
        self.calls = 0

    def complete(self, prompt: str) -> str:
        body = {
            "model": self.serving_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }
        if self._schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "findings", "schema": self._schema},
            }
        request = urllib.request.Request(
            self.base_url + "/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        self.calls += 1
        try:
            usage = payload.get("usage", {}) or {}
            total = usage.get("total_tokens")
            if isinstance(total, (int, float)):
                self.tokens_used += int(total)
        except (AttributeError, TypeError):
            pass
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message", {}) or {}
        return str(message.get("content", "") or "")
