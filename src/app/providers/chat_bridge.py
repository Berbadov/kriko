"""Your own chat as the researcher: for a reader with no agent, key or local model.

Most people use a model as a chat in a browser tab, free or on a plan, and
have no coding agent, no API key and no machine for a local model. For them
every research door ended at "Product drafts need an agent". Yet the chat they
already use can search the web and answer in a minute, which is all a quick
look asks for.

So this researcher asks nobody. It hands the quick look's instructions to the
reader (the job's partial result carries them, for the panel to show with a
Copy button) and waits for them to paste the chat's answer back (`POST
/api/jobs/{id}/say`, read through `progress.replies()`).

**A pasted answer is trusted for nothing.** Before it is parsed, every page it
cites is fetched here, on the reader's machine, and `quicklook.parse` keeps a
risk only when its quote is in the page as fetched. A chat that invented a
source, or misquoted one, loses that line; a page that cannot be read
(paywalled, scripted, down) loses it too. That is a stricter bar than a coding
agent's answer gets, because the chat's search is the one we cannot see.
"""

from __future__ import annotations

import time

from app import factcheck

#: How long a quick look waits for the reader to come back with the answer.
WAIT_SECONDS = 30 * 60

#: Between looks for a pasted answer.
POLL_SECONDS = 1.0

#: Pages read per answer: a quick look cites a handful, and a pasted reply is
#: not allowed to turn the reader's machine into a crawler.
MAX_PAGES = 15

#: Said after the instructions, for a chat rather than an agent.
CHAT_TAIL = """
## For a chat

Search the web for this before you answer. Reply with only the ```json block
above, nothing before or after it. Copy each `quote` exactly as it appears on
the page at `url`: the answer is checked against those pages, and any line
whose quote is not on its page is dropped.
"""


class ChatNotAnswered(RuntimeError):
    code = "chat_not_answered"


def cited_urls(reply: str) -> list[str]:
    """Every page the pasted answer cites, first seen first, at most MAX_PAGES."""
    from app.packauthor import _payload  # the fence reader every door uses
    from app.quicklook import closed

    found = _payload(reply)
    if isinstance(found, dict) and "risks" not in found and "specs" not in found:
        found = closed(reply) or found
    if not isinstance(found, dict):
        return []
    urls: list[str] = []
    for item in [*(found.get("risks") or []), *(found.get("specs") or [])]:
        if not isinstance(item, dict):
            continue
        supplied = item.get("sources")
        refs: list = supplied if isinstance(supplied, list) else []
        for ref in [item, *refs]:
            url = str(ref.get("url") or "").strip() if isinstance(ref, dict) else ""
            if url.startswith(("http://", "https://")) and url not in urls:
                urls.append(url)
    return urls[:MAX_PAGES]


class ChatBridge:
    """A researcher whose model is the reader's own chat, relayed by hand."""

    name = "chat"
    cost_basis = "own_chat"

    def __init__(self, progress, *, fetch=None, wait_seconds: float = WAIT_SECONDS,
                 poll_seconds: float = POLL_SECONDS, sleep=time.sleep, clock=time.monotonic):
        self.progress = progress
        self._fetch = fetch or (lambda url: factcheck.fetch(url))
        self._wait = wait_seconds
        self._poll = poll_seconds
        self._sleep = sleep
        self._clock = clock
        #: url -> page text as fetched here; `quicklook.parse` checks quotes in it.
        self.sources: dict[str, str] = {}
        self.on_action = progress.log
        self.check_cancelled = progress.check

    def ask(self, prompt: str) -> str:
        question = prompt.rstrip() + "\n" + CHAT_TAIL
        self.progress.partial({"chat_prompt": question})
        self.progress.set(0.2, "Waiting for your chat's answer")
        self.progress.log("waiting: copy the question into a chat that can search "
                          "the web, then paste its answer here")
        deadline = self._clock() + self._wait
        said: list[str] = []
        while not said:
            self.progress.check()
            said = [one for one in self.progress.replies() if one.strip()]
            if said:
                break
            if self._clock() >= deadline:
                raise ChatNotAnswered(
                    "No answer was pasted in time. Start the quick look again "
                    "when you have your chat's answer.")
            self._sleep(self._poll)
        reply = "\n".join(said)
        self.progress.set(0.6, "Checking the answer against its pages")
        urls = cited_urls(reply)
        if not urls:
            self.progress.log("the answer cites no pages, so nothing in it can be kept")
        for url in urls:
            self.progress.check()
            text, error = self._fetch(url)
            if text:
                self.sources[url] = text
                self.progress.log(f"read: {url}")
            else:
                self.progress.log(f"could not check {url}: {error or 'not readable text'}")
        return reply
