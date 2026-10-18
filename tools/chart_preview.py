"""Rasterise the model-benchmark SVGs with headless Chrome, for eyeballing only.

Not part of the app: the charts ship as SVG and the report embeds them. This
exists because a chart has to be *looked at* before it is trusted, and there is
no way to see an SVG through a text tool.

    python tools/chart_preview.py benchmarks/modelbench-2026-10-18.json
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def browser() -> str:
    for path in CANDIDATES:
        if Path(path).exists():
            return path
    found = shutil.which("chrome") or shutil.which("msedge") or shutil.which("chromium")
    if not found:
        raise SystemExit("no Chrome or Edge found to rasterise with")
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    source = Path(argv[0]).resolve()
    out = (Path(argv[1]) if len(argv) > 1 else source.parent / "preview").resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        raise SystemExit(f"no such report: {source}")
    # Both paths are made absolute before they reach the browser. A relative
    # `--screenshot` is resolved against Chrome's own working directory and a
    # relative SVG would become `file:///chartcheck/…` — the root of the drive,
    # which is not the file, and the browser then writes nothing at all.

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from app.modelbench import charts  # noqa: E402

    document = json.loads(source.read_text(encoding="utf-8"))
    chrome = browser()
    profile = tempfile.mkdtemp(prefix="chart-preview-")
    failures = []
    try:
        for name, markup in charts.render(document).items():
            svg = out / f"{name}.svg"
            svg.write_text(markup, encoding="utf-8")
            png = out / f"{name}.png"
            # Cleared first so a browser that fails to write cannot leave the
            # previous render in place looking like a fresh one. That happened:
            # a stale picture was read as the new one and a whole review pass
            # was spent on a chart that had not changed.
            png.unlink(missing_ok=True)
            size = _size(markup)
            # The window is the SVG plus a little air, and the scale factor is
            # pinned: Chrome otherwise honours the display's DPI and a chart
            # captured at 125% is a chart with its right edge cut off.
            #
            # `stdout`/`stderr` are DEVNULL rather than captured, because a
            # captured child needs a pipe and a sandboxed run may refuse to make
            # one — which fails the browser launch, silently, with `check=False`.
            subprocess.run(
                [chrome, "--headless", "--disable-gpu", "--no-sandbox",
                 "--hide-scrollbars", "--force-device-scale-factor=1",
                 f"--user-data-dir={profile}",
                 f"--window-size={size[0] + 20},{size[1] + 20}",
                 f"--screenshot={png}", f"file:///{svg.as_posix()}"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if png.exists() and png.stat().st_size > 0:
                print(f"  {name:<14} {png}")
            else:
                failures.append(name)
                print(f"  {name:<14} NOT RENDERED — run the browser by hand")
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    return 1 if failures else 0


def _size(markup: str) -> tuple[int, int]:
    head = markup[:400]
    width = int(head.split('width="')[1].split('"')[0])
    height = int(head.split('height="')[1].split('"')[0])
    return width, height


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
