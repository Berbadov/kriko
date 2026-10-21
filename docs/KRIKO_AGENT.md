# Kriko Agent

Kriko Agent is the app's fixed hosted research stack: Mercury 2.5 plans and
writes the answer; DeepSeek Search and Fetch supply web evidence. It appears
under **Settings → Agents** after both provider keys are available.

Set these keys in **Settings → Research** or the ~/.kriko/env file:

    MERCURY_API_KEY=...
    DEEPSEEK_API_KEY=...

The key values stay in the application process. Mercury receives the research
brief and its supplied evidence; DeepSeek receives search queries and URLs from
its own search results. Kriko Agent is pinned to Mercury 2.5 so a saved
per-agent model preference cannot silently change the benchmarked stack.

The agent requests page content with each DeepSeek search. It fetches a result
URL only when the inline text is missing or insufficient. Duplicate search and
fetch requests are coalesced during a research turn; independent tool calls run
with a four-request concurrency bound. Search and Fetch use 0.21-second
per-process pacing to stay below DeepSeek's documented 5-QPS per-account
limit. Failed and empty DeepSeek responses are not counted as billable calls.

Successful search results are cached in `~/.kriko/cache/kriko-agent.sqlite3`:
searches for 15 minutes and fetched pages for one hour, with at most 500 cache
entries. Cache hits appear in the run log and do not incur another DeepSeek
retrieval charge. The cache contains result text and URLs but no API keys; delete
that SQLite file to clear it.

Mercury's conversation context is capped at 48,000 serialized characters, and
the incoming brief is clipped to 16,000 characters if needed. Tool output is
trimmed to fit while keeping source URLs and result metadata first. The full
retrieved text remains in the run's grounding data, up to 8,000 characters per
URL.

Settings → Research has two Kriko Agent controls. **Thoroughness** sets the
search-call ceiling (3 at Low, 5 at the default midpoint, 8 at High) and the
result count per search (2, 4, and 5 respectively). **Validation sensitivity**
requires quotes of 8–20 characters; at 80% and above it also requires an exact
case-sensitive quote from the returned source. Higher settings ask Mercury to
seek independent corroboration for consequential details.

Run token and cost reporting uses Mercury's reported input/output usage and
the model catalogue's Mercury 2.5 rates. DeepSeek is estimated at $0.00075 per
successful search or fetch request. If Mercury omits token usage, Kriko marks
the total unknown instead of reporting a partial amount as the full cost.

The APIs and their current request/billing rules are documented by
[Inception](https://docs.inceptionlabs.ai/) and the
[DeepSeek Search and Fetch guide](https://api-docs.deepseek.com/guides/search/).
