"""Pooled async HTTP, per-request telemetry, and native streamed tool calls."""

import asyncio
import json
import os
import time

from app.searchbench.config import token_cost


class Wire:
    def __init__(self, client, started=None, tavily_credit_usd=None):
        self.client = client
        self.started = time.perf_counter() if started is None else started
        self.events = []
        self.locks = {}
        self.next_at = {}
        self.tavily_credit_usd = tavily_credit_usd

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
            event["duration_s"] = self.now() - event["start_s"]
