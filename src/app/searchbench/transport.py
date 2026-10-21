"""Pooled async HTTP, per-request telemetry, and native streamed tool calls."""

import asyncio
import json
import os
import time
from pathlib import Path

from app.searchbench.config import token_cost
from app.searchbench.metrics import normalized_usage


class TokenBudgetExceeded(RuntimeError):
    def __init__(self, requested, remaining):
        super().__init__("Token budget cannot cover the next model request")
        self.requested = requested
        self.remaining = remaining


def request_token_ceiling(payload, max_tokens):
    """Conservative input-byte upper bound plus output allowance and protocol overhead."""
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return len(serialized) + max(0, int(max_tokens)) + 512


class TokenBudget:
    """Shared, crash-safe hard ceiling for inference requests in an experiment."""

    def __init__(self, cap, *, used=0, reported=0, estimated=0, checkpoint=None,
                 recovered_reservations=0, exhausted=False):
        self.cap = int(cap)
        self.used = int(used)
        self.reported = int(reported)
        self.estimated = int(estimated)
        self.reserved = 0
        self.checkpoint = Path(checkpoint) if checkpoint else None
        self.recovered_reservations = int(recovered_reservations)
        self.exhausted = bool(exhausted or self.used >= self.cap)
        self.denials = 0
        self.lock = asyncio.Lock()
        self.next_reservation = 1
        self._reservations = {}

    @classmethod
    def open(cls, cap, checkpoint, *, initial_used=0, initial_reported=0,
             initial_estimated=0):
        path = Path(checkpoint)
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("cap") != int(cap):
                raise ValueError(f"Token cap must stay at {saved.get('cap'):,} for this experiment")
            pending = int(saved.get("reserved", 0))
            # A reservation was saved before its request was sent. If the process
            # disappeared before settlement, conservatively charge the full hold.
            used = int(saved.get("used", 0)) + pending
            estimated = int(saved.get("estimated", 0)) + pending
            budget = cls(cap, used=used, reported=saved.get("reported", 0),
                         estimated=estimated, checkpoint=path,
                         recovered_reservations=int(saved.get("recovered_reservations", 0)) + pending,
                         exhausted=saved.get("exhausted", False))
            budget._persist()
            return budget
        budget = cls(cap, used=initial_used, reported=initial_reported,
                     estimated=initial_estimated, checkpoint=path)
        budget._persist()
        return budget

    @property
    def remaining(self):
        return max(0, self.cap - self.used - self.reserved)

    async def reserve(self, payload, max_tokens):
        amount = request_token_ceiling(payload, max_tokens)
        async with self.lock:
            if self.exhausted or amount > self.remaining:
                self.exhausted = True
                self.denials += 1
                self._persist()
                raise TokenBudgetExceeded(amount, self.remaining)
            key = self.next_reservation
            self.next_reservation += 1
            self._reservations[key] = amount
            self.reserved += amount
            self._persist()
        return {"id": key, "tokens": amount}

    async def settle(self, reservation, usage):
        if reservation is None:
            return {"tokens": 0, "basis": "none"}
        usage = normalized_usage(usage or {})
        async with self.lock:
            amount = self._reservations.pop(reservation["id"], reservation["tokens"])
            self.reserved -= amount
            if usage["total"] is None:
                charge, basis = amount, "conservative_reservation"
                self.estimated += charge
            else:
                charge, basis = usage["total"], "provider_reported"
                self.reported += charge
            self.used += charge
            if charge > amount:
                # This should not occur with the UTF-8 byte upper bound. Stop all
                # future calls if a provider reports usage above the reservation.
                self.exhausted = True
            if self.used >= self.cap:
                self.exhausted = True
            self._persist()
        return {"tokens": charge, "basis": basis}

    def snapshot(self):
        return {"cap": self.cap, "used": self.used, "reported": self.reported,
                "estimated": self.estimated, "reserved": self.reserved,
                "remaining": self.remaining, "exhausted": self.exhausted,
                "denials": self.denials,
                "recovered_reservations": self.recovered_reservations,
                "policy": "Before each inference call reserve UTF-8 request bytes + max output tokens + 512 protocol tokens; reported usage settles to actual, missing usage is charged at the full reservation."}

    def _persist(self):
        if not self.checkpoint:
            return
        self.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.checkpoint.with_suffix(self.checkpoint.suffix + ".next")
        temporary.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")
        for attempt in range(6):
            try:
                temporary.replace(self.checkpoint)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(.1 * (attempt + 1))


class Wire:
    def __init__(self, client, started=None, tavily_credit_usd=None, token_budget=None):
        self.client = client
        self.started = time.perf_counter() if started is None else started
        self.events = []
        self.locks = {}
        self.next_at = {}
        self.tavily_credit_usd = tavily_credit_usd
        self.token_budget = token_budget

    def now(self):
        return time.perf_counter() - self.started

    async def pace(self, lane):
        # DeepSeek has separate 5 QPS quotas for search and fetch. Shared by all runs.
        async with self.locks.setdefault(lane, asyncio.Lock()):
            await asyncio.sleep(max(0, self.next_at.get(lane, 0) - time.perf_counter()))
            self.next_at[lane] = time.perf_counter() + .23

    async def post(self, provider, base, path, key_env, payload):
        if not os.environ.get(key_env):
            raise ValueError(f"Missing {key_env}")
        if provider == "deepseek":
            await self.pace(path)
        event = {"kind": path, "provider": provider, "start_s": self.now(), "request": payload}
        self.events.append(event)
        headers = {"x-api-key" if provider == "exa" else "Authorization":
                   os.environ[key_env] if provider == "exa" else "Bearer " + os.environ[key_env]}
        try:
            response = await self.client.post(base.rstrip("/") + path, headers=headers, json=payload)
            event["status"] = response.status_code
            event["http_version"] = response.http_version
            response.raise_for_status()
            data = response.json()
            event["response"] = data
            event["cost_usd"] = (0.00075 if data.get("results") or data.get("content") else 0.0) if provider == "deepseek" else data.get("costDollars", {}).get("total")
            if provider == "tavily":
                event["credits"] = data.get("usage", {}).get("credits")
                if event["credits"] is not None and self.tavily_credit_usd is not None:
                    event["cost_usd"] = event["credits"] * self.tavily_credit_usd
                    event["cost_basis"] = f"Tavily credits × ${self.tavily_credit_usd:g}; comparison rate, not account invoice"
            return data
        except Exception as error:
            # No raw response bodies, headers, or exception strings in diagnostics.
            event["error"] = type(error).__name__
            raise
        finally:
            event["duration_s"] = self.now() - event["start_s"]

    async def chat(self, model, messages, tools, max_tokens=1400):
        if not os.environ.get(model.key_env):
            raise ValueError(f"Missing {model.key_env}")
        payload = {"model": model.model, "messages": messages, "stream": True,
                   "stream_options": {"include_usage": True}, "max_tokens": max_tokens}
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        payload["temperature"] = .5
        if model.effort:
            payload.update(reasoning_effort=model.effort, temperature=.5)
        if model.provider == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        event = {"kind": "model", "provider": model.provider, "model": model.model,
                 "start_s": self.now(), "usage": {}, "finish_reason": None,
                 "parameters": {k: v for k, v in payload.items() if k not in ("messages", "tools")}}
        self.events.append(event)
        reservation = None
        try:
            if self.token_budget:
                reservation = await self.token_budget.reserve(payload, max_tokens)
                event["budget_reserved_tokens"] = reservation["tokens"]
        except TokenBudgetExceeded as error:
            event["budget_requested_tokens"] = error.requested
            event["budget_remaining_tokens"] = error.remaining
            event["error"] = "TokenBudgetExceeded"
            event["duration_s"] = self.now() - event["start_s"]
            raise
        content, calls = [], {}
        try:
            async with self.client.stream("POST", model.base_url + "/chat/completions", json=payload,
                                          headers={"Authorization": "Bearer " + os.environ[model.key_env]}) as response:
                event["status"] = response.status_code
                event["http_version"] = response.http_version
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                        continue
                    data = json.loads(line[5:])
                    if data.get("error"):
                        raise ValueError("Provider stream error")
                    event["resolved_model"] = data.get("model", event.get("resolved_model"))
                    if data.get("usage"):
                        event["usage"] = data["usage"]
                    for choice in data.get("choices") or []:
                        if choice.get("finish_reason"):
                            event["finish_reason"] = choice["finish_reason"]
                        delta = choice.get("delta") or {}
                        delta_content = delta.get("content")
                        if isinstance(delta_content, list):
                            # Large 4 streams typed thinking blocks alongside text.
                            # Retain token counts, never treat thinking as visible output.
                            delta_content = "".join(p.get("text", "") for p in delta_content if p.get("type") == "text")
                        if delta_content:
                            event.setdefault("first_text_s", self.now())
                            content.append(delta_content)
                        for part in delta.get("tool_calls") or []:
                            event.setdefault("first_tool_s", self.now())
                            call = calls.setdefault(part["index"], {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            if part.get("id"):
                                call["id"] = part["id"]
                            for key in ("name", "arguments"):
                                call["function"][key] += (part.get("function") or {}).get(key) or ""
            message = {"role": "assistant", "content": "".join(content) or None}
            if calls:
                message["tool_calls"] = [calls[i] for i in sorted(calls)]
            event["message"] = message
            if event["finish_reason"] not in ("stop", "tool_calls"):
                event["error_detail"] = "finish_reason=" + str(event["finish_reason"])
                raise ValueError("Incomplete model response")
            return message, event
        except Exception as error:
            event["error"] = type(error).__name__
            raise
        finally:
            event["cost_usd"] = token_cost(model, event["usage"])
            if self.token_budget:
                charge = await self.token_budget.settle(reservation, event["usage"])
                event["budget_charge_tokens"] = charge["tokens"]
                event["budget_charge_basis"] = charge["basis"]
                event["budget_used_after"] = self.token_budget.used
            event["duration_s"] = self.now() - event["start_s"]
