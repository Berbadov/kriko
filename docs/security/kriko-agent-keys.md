# Kriko Agent credential review — 2026-10-22

Kriko Agent is an experimental preview combining Mercury 3 with DeepSeek
Search and Fetch. It uses credentials supplied on the reader's computer.
No shared Kriko account is included in the downloads.

## Published 0.3.0 audit

The four current local provider credentials (Mercury, DeepSeek, Exa and Tavily)
were compared without printing their values against:

- 9,702 Git blobs reachable from remote branches and tags;
- all nine 0.3.0 release assets, checked against GitHub's uploaded SHA-256 hashes;
- 2,070 decompressed archive members;
- 2,407 decompressed frozen Python modules, including compiled constants.

The comparison covered UTF-8, UTF-16 little-endian and base64 representations.
There were **no matches**. The running installed engine reported these keys as
coming from the environment. Its local database contained no recorded key-test
operations. These observations support that the current credentials were not
committed or bundled in 0.3.0. They do not audit previously rotated credentials,
unavailable provider logs or every possible external disclosure.

## Key-test routing correction

The Mercury **Test** action in 0.3.0 incorrectly used the configured
OpenAI-compatible endpoint and its model. That could transmit a Mercury key to
that endpoint if this action was used. Actual Kriko Agent chat calls use
Inception's endpoint for Mercury and DeepSeek's endpoint for retrieval.

The patch routes the key test directly to Inception with the Mercury model
(then 2.5, now 3), ignoring unrelated OpenAI-compatible configuration. A
regression test verifies the destination, model, authorization header and
absence of credentials from the response, using a dummy credential and mocked
transport. The duplicate DeepSeek key entry is also removed.

Anyone who used **Test** for Mercury in an affected build should replace that
Mercury credential through their provider account. This recommendation concerns
the misdirected test request, not evidence of public credentials in the release.
