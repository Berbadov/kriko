"""YouTube mechanic video transcripts via yt-dlp.

No API key required — yt-dlp fetches auto-generated subtitles directly.
Call get_transcript(video_id) to fetch and normalize a single video.
CuratedSource (sources/curated.py) is the entry point for batch use.
"""

import logging
import re

from packs.cars.pipeline.sources.base import Document

log = logging.getLogger(__name__)


def get_transcript(video_id: str) -> str | None:
    """Download and normalize the auto-generated transcript for a YouTube video.

    Tries Turkish first, falls back to English. Returns clean prose text
    (timestamps and duplicate cue lines stripped). Returns None if no
    transcript is available or yt-dlp fails.
    """
    try:
        import yt_dlp  # imported here so the rest of the module loads without it
    except ImportError:
        log.error("yt-dlp not installed — run: pip install yt-dlp")
        return None

    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {
        "skip_download": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["tr", "en"],
        "subtitlesformat": "vtt",
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            subs = info.get("requested_subtitles") or {}
            for lang in ("tr", "en"):
                if lang not in subs:
                    continue
                sub_url = subs[lang].get("url")
                if not sub_url:
                    continue
                raw = ydl.urlopen(sub_url).read().decode("utf-8", errors="replace")
                text = _normalize_vtt(raw)
                if text:
                    log.debug("Fetched %s transcript for %s (%d chars)", lang, video_id, len(text))
                    return text
    except Exception as exc:
        log.warning("yt-dlp failed for %s: %s", video_id, exc)

    return None


def _normalize_vtt(vtt: str) -> str:
    """Strip VTT metadata and timestamps; deduplicate overlapping cue lines."""
    lines = []
    seen: set[str] = set()
    for line in vtt.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip VTT header and metadata lines
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "REGION")):
            continue
        # Skip timestamp lines (00:00:01.500 --> 00:00:03.200 or 00:01.500 --> 00:03.200)
        if re.match(r"[\d:]+\.[\d]+ --> [\d:]+\.[\d]+", line):
            continue
        # Skip cue identifiers (pure integers or "auto:...")
        if re.match(r"^\d+$", line) or line.startswith("auto:"):
            continue
        # Collapse duplicates from overlapping rolling-window cues
        if line not in seen:
            seen.add(line)
            lines.append(line)

    return " ".join(lines)


class YouTubeSource:
    """Kept for interface compatibility — use CuratedSource for batch fetching."""

    def fetch_video(self, video_id: str, channel: str = "YouTube") -> Document | None:
        text = get_transcript(video_id)
        if not text:
            return None
        return Document(
            text=text[:8000],
            url=f"https://www.youtube.com/watch?v={video_id}",
            site_or_channel=channel,
        )
