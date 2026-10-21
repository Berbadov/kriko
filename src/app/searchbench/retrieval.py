"""Search and provider-side page reading, with run-local coalescing and evidence IDs."""

import asyncio
from urllib.parse import urlsplit, urlunsplit

from app.searchbench.config import SEARCHES


def canonical(url):
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Invalid public source URL")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


class Retrieval:
    def __init__(self, wire, variant, *, count=5, page_chars=6000):
        self.wire, self.variant = wire, variant
        self.provider, self.key_env, self.base, self.mode = SEARCHES[variant]
        self.count, self.page_chars = count, page_chars
        self.sources, self.memo = {}, {}
        self.cache_hits = 0
        self.first_result_s = None

    async def once(self, key, operation):
        if key in self.memo:
            self.cache_hits += 1
        else:
            self.memo[key] = asyncio.create_task(operation())
        return await self.memo[key]

    def remember(self, item, *, fetched=False):
        url = canonical(item["url"])
        source = self.sources.setdefault(url, {"id": f"S{len(self.sources) + 1}", "url": url, "fetched": False, "has_page_content": False})
        source["title"] = str(item.get("title") or source.get("title", ""))
        text = item.get("raw_content") or item.get("text") or item.get("content") or ""
        snippet = item.get("snippet") or "\n".join(item.get("highlights") or []) or item.get("summary") or ""
        if text and (fetched or not source.get("text")):
            source["text"] = str(text)[:self.page_chars]
        source["has_page_content"] |= bool(text) and (fetched or (self.provider == "deepseek" and self.mode == "content"))
        source["snippet"] = str(snippet)[:1000]
        source["fetched"] |= fetched
        return dict(source)

    async def search(self, query):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Search requires a query")
        if self.provider == "deepseek" and len(query) > 128:
            raise ValueError("DeepSeek search query exceeds 128 characters")

        async def operation():
            if self.provider == "deepseek":
                path, payload = "/v1/tools/search", {"query": query, "count": self.count, "need_content": self.mode == "content"}
            elif self.provider == "exa":
                path, payload = "/search", {"query": query, "numResults": self.count, "type": self.mode,
                                             "contents": {"highlights": True}}
            else:
                path, payload = "/search", {"query": query, "max_results": self.count, "search_depth": self.mode,
                                             "include_answer": False, "include_usage": True}
            data = await self.wire.post(self.provider, self.base, path, self.key_env, payload)
            results = []
            for item in data.get("results", []):
                try:
                    results.append(self.remember(item))
                except (ValueError, KeyError):
                    continue
            if results and self.first_result_s is None:
                self.first_result_s = self.wire.now()
            return results
        return await self.once(("search", query.strip().casefold()), operation)

    async def fetch(self, url):
        url = canonical(url)
        if url not in self.sources:
            raise ValueError("Fetch requires a URL returned by search")

        async def operation():
            if self.provider == "deepseek":
                path, payload = "/v1/tools/fetch", {"url": url}
            elif self.provider == "exa":
                path, payload = "/contents", {"ids": [url], "text": {"maxCharacters": self.page_chars}}
            else:
                path, payload = "/extract", {"urls": [url], "extract_depth": "basic", "include_usage": True}
            data = await self.wire.post(self.provider, self.base, path, self.key_env, payload)
            item = data if self.provider == "deepseek" else next(iter(data.get("results", [])), {})
            if not (item.get("content") or item.get("text") or item.get("raw_content")):
                raise ValueError("Page has no readable content")
            return self.remember({**item, "url": url}, fetched=True)
        return await self.once(("fetch", url), operation)
