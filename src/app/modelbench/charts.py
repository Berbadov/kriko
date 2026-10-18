"""The graphs, drawn from the same rows the report prints.

Five pictures, each answering one question a table answers slowly:

* `tradeoff` — **which model should the phone use.** Tokens per run against the
  share of what it claimed that the documents did not support, with the bubble
  sized by how many facts it actually found. The whole decision in one frame:
  down and to the left is good, and the two candidates at the frontier are
  visibly an order of magnitude apart on cost.
* `quality` — a five-by-five matrix of the quality rates, because a single
  "score" would hide that one model's problem is abstention and another's is
  invention. A matrix rather than five bars per model: three-pixel bars stacked
  six deep read as one block, which is worse than no chart.
* `tokens` — where the tokens went, in and out, with the harness's whole-session
  figure drawn as the different kind of number it is.
* `dimensions` — *where* each model fails. The aggregate says how much; this says
  which kind of reading it cannot do.
* `fabrication` — what kind of fabrication. An unsupported claim, a quotation
  that is not in the page it names, and a figure under the wrong name have
  different remedies.

**Hand-drawn SVG, not matplotlib.** Three reasons, each concrete. The desktop
build carries its dependencies and a plotting library is a large one to add for
five pictures. A chart that cannot be regenerated from a saved run goes stale
the moment a rate is corrected, and `rerender` already rebuilds the report from
its JSON — so these are rebuilt with it. And SVG is text: it differs in a
review, it stays crisp on a HiDPI screen, and it carries a
`prefers-color-scheme` rule so one file reads correctly on a light and a dark
page.

Every number here comes from the document `report.py` already writes. Nothing is
recomputed, so a graph cannot disagree with the table beside it.
"""

import math
import xml.sax.saxutils as sax

#: Series colours, in the order candidates appear. A blue/amber/violet set
#: rather than red/green, because "which of these two is worse" is exactly the
#: question the pictures are for and the most common colour blindness is
#: red-green.
SERIES = ("#2563eb", "#d97706", "#7c3aed", "#0d9488", "#be185d", "#4d7c0f",
          "#0369a1", "#a16207")

#: The chart page's own styles. `prefers-color-scheme` is honoured because a
#: README is read on both, and a black-on-white chart on a dark page is a
#: rectangle of glare. The SVG is loaded as an image, so the query applies to
#: the reader's page rather than to GitHub's chrome.
_STYLE = """
  :root {
    --ink: #0f172a; --ink-soft: #475569; --ink-faint: #94a3b8;
    --rule: #cbd5e1; --grid: #eef2f7; --track: #eef2f7; --panel: #ffffff;
    --good: #0f766e; --warn: #b45309; --bad: #b91c1c;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --ink: #e6edf6; --ink-soft: #9fb0c4; --ink-faint: #64748b;
      --rule: #334155; --grid: #1c2430; --track: #1c2430; --panel: #0d1117;
      --good: #2dd4bf; --warn: #fbbf24; --bad: #f87171;
    }
  }
  text { font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto,
         Helvetica, Arial, sans-serif; fill: var(--ink); }
"""

#: Rough advance width per character as a fraction of the font size, for a UI
#: sans-serif. Used only to lay a label *near* a mark and to keep two labels
#: from colliding; real alignment is left to `text-anchor`, which the renderer
#: does exactly. An estimate is right for the first job and wrong for the second.
_CHAR = 0.56
MIN_RADIUS = 5.0
MAX_RADIUS = 26.0


def esc(value) -> str:
    """Text, safe to put in an SVG document."""
    return sax.escape(str(value), {'"': "&quot;", "'": "&apos;"})


def short_name(candidate_id: str) -> str:
    """`harness:mistral-vibe@glm-5-3` → `glm-5-3 (CLI)`.

    A chart label has room for a name, not for a routing instruction. The *kind*
    is kept, because it is the difference between a model that could sit on a
    phone and a process that needs a laptop, and the redundant parts are dropped.
    """
    text = str(candidate_id or "")
    kind, _, rest = text.partition(":")
    if kind == "harness":
        _, _, model = rest.rpartition("@")
        return f"{model or rest} (CLI)"
    return rest or text


def _pct(value, places: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.{places}f}%"


def _num(value) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}"


def _text_width(text: str, size: float) -> float:
    return len(str(text)) * size * _CHAR


def wrap(label: str, width: int) -> list[str]:
    """`"sold-product-vs-host"` → `["sold product", "vs host"]`.

    Column headings in the grid are one word short of colliding, and rotating
    them to fit costs a reader more than it saves. Two short lines stay
    horizontal and stay readable.
    """
    words: list[str] = []
    for chunk in str(label).replace("_", "-").split("-"):
        if chunk:
            words.append(chunk)
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [str(label)]


def wrap_text(text: str, width: int = 104) -> list[str]:
    """Word-wrap prose to a character budget, for the note under a chart.

    Kept separate from `wrap`, which breaks labels on their hyphens. Prose has
    no hyphens to break on, so the first version of this left every footnote as
    one long line running off the right edge of the picture.
    """
    lines: list[str] = []
    current = ""
    for word in str(text).split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def nice_step(span: float, target: int = 4) -> float:
    """A round number near `span / target`, from 1, 2, 2.5 or 5 times a decade.

    Because an axis labelled 2,020 · 4,041 · 6,061 · 8,081 is an axis nobody
    reads: the ticks are an artefact of the data instead of a scale, and a
    reader has to divide to use them.
    """
    if span <= 0:
        return 1.0
    rough = span / max(1, target)
    decade = 10.0 ** math.floor(math.log10(rough))
    for multiple in (1.0, 2.0, 2.5, 5.0, 10.0):
        if rough <= multiple * decade:
            return multiple * decade
    return 10.0 * decade


def _ladder(value: float, *, up: bool) -> float:
    """The nearest 1/2/5 × 10ⁿ step at or beyond `value`."""
    if value <= 0:
        return 1.0
    decade = 10.0 ** math.floor(math.log10(value))
    best = decade
    for multiple in (1.0, 2.0, 5.0, 10.0):
        candidate = multiple * decade
        if up and candidate >= value:
            return candidate
        if not up and candidate <= value:
            best = candidate
    return 10.0 * decade if up else best


def nice_log_bounds(low: float, high: float) -> tuple[float, float]:
    """The tightest 1/2/5 ladder that contains both values, with a little air.

    The first version of this snapped outward to whole decades, which on a
    dataset spanning 862 to 8,081 produced an axis of 100 to 100,000 — 60% of
    the plot empty and both interesting models crammed into one corner. A log
    axis still has to be *scaled to its data*.
    """
    return _ladder(low * 0.92, up=False), _ladder(high * 1.08, up=True)


class Svg:
    """An SVG document, built by appending strings.

    Small on purpose: five charts need rectangles, lines, circles and text, and
    a general-purpose drawing library is the dependency this module exists to
    avoid.
    """

    def __init__(self, width: int, height: int, title: str, about: str = ""):
        self.width = width
        self.height = height
        self.title = title
        self.about = about
        self.parts: list[str] = []

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def rect(self, x, y, w, h, *, fill="none", stroke="none", width=1,
             opacity=1.0, radius=0, dash="") -> None:
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(0.0, w):.1f}" '
            f'height="{max(0.0, h):.1f}" rx="{radius}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{width}" opacity="{opacity}"{extra}/>'
        )

    def line(self, x1, y1, x2, y2, *, stroke="var(--rule)", width=1,
             opacity=1.0, dash="") -> None:
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{stroke}" stroke-width="{width}" opacity="{opacity}"{extra}/>'
        )

    def circle(self, cx, cy, r, *, fill="none", stroke="none", width=1,
               opacity=1.0, dash="") -> None:
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{max(0.0, r):.1f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{width}" '
            f'opacity="{opacity}"{extra}/>'
        )

    def text(self, x, y, body, *, size=12, weight=400, anchor="start",
             fill="var(--ink)", opacity=1.0) -> None:
        # An empty string is not a label. Emitting one leaves dead markup that a
        # reader cannot account for and a test cannot distinguish from a label
        # whose value went missing.
        if not str(body).strip():
            return
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'opacity="{opacity}">{esc(body)}</text>'
        )

    def lines(self, x, y, body: str, *, size=12, weight=400, anchor="start",
              fill="var(--ink-soft)", leading=1.25) -> None:
        """Several lines of text, on one baseline grid."""
        for index, line in enumerate(str(body).split("\n")):
            self.text(x, y + index * size * leading, line, size=size,
                      weight=weight, anchor=anchor, fill=fill)

    def render(self) -> str:
        """The whole document, with a title and a description for a screen reader.

        `role="img"`, a `<title>` and a `<desc>` are not decoration: a chart is
        the only thing in this report that carries a finding with no words beside
        it, and a picture with no accessible name is a finding half the readers
        cannot get at all.
        """
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'height="{self.height}" viewBox="0 0 {self.width} {self.height}" '
            f'role="img" aria-labelledby="chart-title">'
            f'<title id="chart-title">{esc(self.title)}</title>'
            f"<desc>{esc(self.about or self.title)}</desc>"
            f"<style>{_STYLE}</style>"
            f'<rect width="{self.width}" height="{self.height}" fill="var(--panel)"/>'
            + "".join(self.parts)
            + "</svg>\n"
        )

    def write(self, path) -> None:
        from pathlib import Path

        Path(path).write_text(self.render(), encoding="utf-8")


def _measured(candidates: list[dict]) -> list[dict]:
    """Candidates with a counted token figure, in document order."""
    return [one for one in candidates if one.get("tokens_total_mean") is not None]


def _frame(svg: Svg, document: dict) -> None:
    """The heading every chart shares: what it measured, and of what."""
    shape = document.get("set") or {}
    version = ""
    for one in shape.get("sets") or []:
        version = f"{one.get('set_id', '')} {one.get('set_version', '')}".strip()
    svg.text(24, 30, svg.title, size=15, weight=600)
    svg.text(24, 49, svg.about, size=12, fill="var(--ink-soft)")
    svg.text(svg.width - 24, 30, version, size=11, anchor="end",
             fill="var(--ink-faint)")
    svg.text(svg.width - 24, 49,
             f"{shape.get('case_count', 0)} cases · {shape.get('runs', 0)} runs",
             size=11, anchor="end", fill="var(--ink-faint)")


def tradeoff(document: dict) -> Svg:
    """Cost against fabrication, sized by what was found. The decision chart."""
    candidates = _measured(document.get("candidates") or [])
    svg = Svg(900, 540, "Cost against fabrication",
              "Tokens per run against the share of claims the documents did not "
              "support. Bubble area is expected facts found; the bar is the 95% interval.")
    _frame(svg, document)
    left, right, top, bottom = 78.0, 210.0, 86.0, 104.0
    plot_w = svg.width - left - right
    plot_h = svg.height - top - bottom

    points = [one for one in candidates if one.get("hallucination_rate") is not None]
    skipped = [one for one in candidates if one.get("hallucination_rate") is None]
    if not points:
        svg.text(left, top + plot_h / 2, "No candidate produced a scoreable claim.",
                 size=13, fill="var(--ink-soft)")
        return svg

    costs = [float(one["tokens_total_mean"]) for one in points]
    low, high = nice_log_bounds(min(costs), max(costs))
    log_low, log_high = math.log10(low), math.log10(high)

    def x_of(cost: float) -> float:
        return left + (math.log10(cost) - log_low) / (log_high - log_low) * plot_w

    def y_of(rate: float) -> float:
        return top + (1.0 - rate) * plot_h

    # A 1/2/5 ladder, because the axis is logarithmic and equal spacing would
    # tell a reader that 1,000→2,000 is the same step as 8,000→9,000.
    decade = 10.0 ** math.floor(log_low)
    while decade <= high * 1.0001:
        for multiple in (1, 2, 5):
            value = decade * multiple
            if low <= value <= high:
                x = x_of(value)
                svg.line(x, top, x, top + plot_h, stroke="var(--grid)")
                svg.text(x, top + plot_h + 18, _num(value), size=10,
                         anchor="middle", fill="var(--ink-faint)")
        decade *= 10
    for share in (0, .25, .5, .75, 1.0):
        y = y_of(share)
        svg.line(left, y, left + plot_w, y, stroke="var(--grid)")
        svg.text(left - 10, y + 4, _pct(share), size=10, anchor="end",
                 fill="var(--ink-faint)")
    svg.line(left, top + plot_h, left + plot_w, top + plot_h, stroke="var(--rule)")
    svg.line(left, top, left, top + plot_h, stroke="var(--rule)")
    svg.text(left - 10, top - 10, "invented", size=11, anchor="end",
             fill="var(--ink-soft)")
    svg.text(left + plot_w / 2, top + plot_h + 38, "tokens per run (log scale)",
             size=11, anchor="middle", fill="var(--ink-soft)")

    # The corner worth wanting, in the corner it belongs to. Down and to the
    # left is cheap and honest, and naming it saves the reader from working out
    # which way each axis points.
    svg.rect(left + 8, top + plot_h - 30, 150, 22, fill="var(--good)",
             opacity=0.12, radius=5)
    svg.text(left + 18, top + plot_h - 15, "cheap and honest", size=11,
             weight=600, fill="var(--good)")

    biggest = max(1, max((int(one.get("found") or 0) for one in points), default=1))
    placed: list[tuple[float, float, float]] = []
    for index, one in enumerate(sorted(points, key=lambda o: float(o["tokens_total_mean"]))):
        colour = SERIES[index % len(SERIES)]
        x = x_of(float(one["tokens_total_mean"]))
        y = y_of(float(one["hallucination_rate"]))
        radius = MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * math.sqrt(
            max(1, int(one.get("found") or 0)) / biggest)
        interval = one.get("hallucination_interval")
        if interval:
            svg.line(x, y_of(interval[0]), x, y_of(interval[1]),
                     stroke=colour, width=2, opacity=0.35)
            for edge in interval:
                svg.line(x - 5, y_of(edge), x + 5, y_of(edge),
                         stroke=colour, width=2, opacity=0.35)
        svg.circle(x, y, radius, fill=colour, opacity=0.20)
        svg.circle(x, y, radius, stroke=colour, width=2)
        label = short_name(one["candidate"])
        # The label goes where there is room: right of the bubble normally, and
        # left of it when the bubble is close enough to the edge that the text
        # would leave the plot.
        size = 11.0
        width = _text_width(label, size)
        to_the_right = x + radius + 8 + width <= left + plot_w
        anchor = "start" if to_the_right else "end"
        tx = x + radius + 6 if to_the_right else x - radius - 6
        box = ((tx, tx + width) if to_the_right else (tx - width, tx))
        lane = y - radius - 2
        while any(abs(lane - other[2]) < 13 and box[0] < other[1] and box[1] > other[0]
                  for other in placed):
            lane += 13
        svg.text(tx, max(top + 10, lane), label, size=size, weight=600,
                 anchor=anchor, fill=colour)
        placed.append((box[0], box[1], lane))

    foot = svg.height - 56
    if skipped:
        for line in wrap_text(
            "Not plotted — produced no claims to score, so it has no fabrication "
            "rate: " + ", ".join(short_name(one["candidate"]) for one in skipped)
        ):
            svg.text(left, foot, line, size=11, fill="var(--warn)")
            foot += 15
    svg.text(left, foot,
             "Bubble area is expected facts found. Down and left is better.",
             size=11, fill="var(--ink-faint)")
    return svg


def quality(document: dict) -> Svg:
    """A model-by-measure matrix of the five rates.

    A matrix rather than five bars stacked per model. The stack was the first
    version and it failed on the page: five bars four pixels tall, five pixels
    apart, are one grey block with a legend a reader has to keep re-reading.
    Five cells across with the number written in each is read in one pass.
    """
    candidates = document.get("candidates") or []
    metrics = (
        ("Correct facts", "recall", "var(--good)", "more is better"),
        ("Hallucinated", "hallucination_rate", "var(--bad)", "less is better"),
        ("Specs found", "spec_recall", "var(--good)", "more is better"),
        ("Wrong specs", "spec_error_rate", "var(--bad)", "less is better"),
        ("Abstained", "abstention_accuracy", "var(--good)", "more is better"),
    )
    row_h = 44.0
    top = 116.0
    height = int(top + row_h * max(1, len(candidates)) + 88)
    svg = Svg(900, height, "Quality by model",
              "Pooled rates over every run. A dash means there was nothing to "
              "divide by — not a zero.")
    _frame(svg, document)
    left, right = 158.0, 24.0
    cell_w = (svg.width - left - right) / len(metrics)
    half = cell_w / 2 - 18

    for column, (label, _key, _colour, _sense) in enumerate(metrics):
        cx = left + column * cell_w + cell_w / 2
        for index, line in enumerate(wrap(label, 11)):
            svg.text(cx, 88 + index * 13, line, size=10, anchor="middle",
                     weight=600, fill="var(--ink-soft)")
    svg.text(left - 14, 88, "pooled rate", size=10, anchor="end",
             fill="var(--ink-faint)")

    for row, one in enumerate(candidates):
        y = top + row * row_h
        svg.text(left - 14, y + 26, short_name(one["candidate"]), size=11.5,
                 weight=600, anchor="end")
        if row:
            svg.line(left - 8, y - 6, svg.width - right, y - 6, stroke="var(--grid)")
        for column, (_label, key, colour, _sense) in enumerate(metrics):
            cx = left + column * cell_w + cell_w / 2
            value = one.get(key)
            if value is None:
                svg.text(cx, y + 19, "—", size=13, anchor="middle",
                         fill="var(--ink-faint)")
                svg.rect(cx - half, y + 26, half * 2, 9, fill="var(--track)",
                         radius=4.5)
                continue
            svg.text(cx, y + 19, _pct(value), size=13, weight=600,
                     anchor="middle", fill=colour)
            svg.rect(cx - half, y + 26, half * 2, 9, fill="var(--track)", radius=4.5)
            svg.rect(cx - half, y + 26, max(3.0, half * 2 * float(value)), 9,
                     fill=colour, opacity=0.85, radius=4.5)

    base = top + row_h * len(candidates) + 22
    svg.text(left - 14, base, "read it as", size=10, anchor="end",
             fill="var(--ink-faint)")
    x = left
    for label, _key, colour, sense in (metrics[0], metrics[1]):
        svg.rect(x, base - 9, 10, 10, fill=colour, opacity=0.85, radius=2)
        svg.text(x + 15, base, f"{label} — {sense}", size=11,
                 fill="var(--ink-soft)")
        x += 24 + _text_width(f"{label} — {sense}", 11)
    svg.lines(left, base + 22, "\n".join(wrap_text(
        "Correct facts is expected facts found. Hallucinated is claimed and "
        "unsupported, of what was claimed. Abstained is an empty answer where "
        "the corpus holds none.", 116)), size=11, fill="var(--ink-faint)")
    return svg


def tokens(document: dict) -> Svg:
    """Where the tokens went, in and out, and what a correct answer cost."""
    candidates = document.get("candidates") or []
    top = 104.0
    row_h = 34.0
    svg = Svg(900, int(top + row_h * max(1, len(candidates)) + 62), "Token cost",
              "Mean tokens per run, split where the transport reported a split, "
              "and the tokens each expected fact found cost.")
    _frame(svg, document)
    left, right = 158.0, 262.0
    plot_w = svg.width - left - right
    counted = [one for one in candidates if one.get("tokens_total_mean") is not None]
    biggest = max((float(one["tokens_total_mean"]) for one in counted), default=1.0)
    step = nice_step(biggest)
    ticks = 0
    while ticks * step <= biggest * 1.02:
        x = left + plot_w * (ticks * step / biggest)
        svg.line(x, 84, x, top + row_h * len(candidates) - 8, stroke="var(--grid)")
        svg.text(x, 76, _num(ticks * step), size=10, anchor="middle",
                 fill="var(--ink-faint)")
        ticks += 1
    scale = plot_w / biggest
    for row, one in enumerate(candidates):
        y = top + row * row_h
        svg.text(left - 14, y + 12, short_name(one["candidate"]), size=11.5,
                 weight=600, anchor="end")
        total = one.get("tokens_total_mean")
        if total is None:
            svg.text(left + 4, y + 12, "— not counted", size=10,
                     fill="var(--ink-faint)")
            continue
        inside = one.get("tokens_in_mean")
        outside = one.get("tokens_out_mean")
        if inside is not None and outside is not None:
            svg.rect(left, y, float(inside) * scale, 16, fill="#2563eb",
                     opacity=0.85, radius=3)
            svg.rect(left + float(inside) * scale, y, float(outside) * scale, 16,
                     fill="#7c3aed", opacity=0.85, radius=3)
            svg.text(left + float(total) * scale + 8, y + 13, _num(total),
                     size=11, fill="var(--ink-soft)")
        else:
            # No split was reported. Outlined and named, so it is never read as
            # the same kind of number as the filled ones beside it.
            svg.rect(left, y, float(total) * scale, 16, fill="var(--warn)",
                     opacity=0.22, radius=3)
            svg.rect(left, y, float(total) * scale, 16, stroke="var(--warn)",
                     width=1.5, dash="4 3", radius=3)
            # "(session)" and not "whole session": the value has to clear the
            # per-correct-fact column, and a label that reaches it makes two
            # different numbers look like one.
            svg.text(left + float(total) * scale + 8, y + 13,
                     f"{_num(total)} (session)", size=11, fill="var(--warn)")
        per_fact = one.get("tokens_per_fact")
        svg.text(svg.width - 24, y + 13,
                 f"{_num(per_fact)} per correct fact" if per_fact is not None
                 else "— no fact to price",
                 size=11, anchor="end", fill="var(--ink-soft)")
    base = top + row_h * len(candidates) + 20
    svg.rect(left, base - 10, 12, 11, fill="#2563eb", opacity=0.85, radius=2)
    svg.text(left + 18, base, "sent", size=11, fill="var(--ink-soft)")
    svg.rect(left + 74, base - 10, 12, 11, fill="#7c3aed", opacity=0.85, radius=2)
    svg.text(left + 92, base, "returned", size=11, fill="var(--ink-soft)")
    svg.rect(left + 190, base - 10, 12, 11, stroke="var(--warn)", width=1.5,
             dash="4 3", radius=2)
    svg.text(left + 208, base,
             "a whole session — its system prompt and tools, not a split figure",
             size=11, fill="var(--warn)")
    return svg


def dimensions(document: dict) -> Svg:
    """The grid: how much each model invented, case dimension by dimension."""
    rows = document.get("by_dimension") or []
    candidates = [one["candidate"] for one in document.get("candidates") or []]
    order: list[str] = []
    for one in rows:
        if one["dimension"] not in order:
            order.append(one["dimension"])
    cell_h = 30.0
    top = 116.0
    height = int(top + cell_h * max(1, len(candidates)) + 62)
    svg = Svg(900, height, "Where each model fails",
              "Share of claimed items the documents did not support, by the "
              "dimension the case was built to test. A dash means it claimed "
              "nothing there.")
    _frame(svg, document)
    if not rows or not order:
        svg.text(24, 100, "No per-dimension rows were recorded.", size=13,
                 fill="var(--ink-soft)")
        return svg
    left, right = 158.0, 24.0
    cell_w = (svg.width - left - right) / len(order)
    for column, dimension in enumerate(order):
        cx = left + column * cell_w + cell_w / 2
        for index, line in enumerate(wrap(dimension, 11)):
            svg.text(cx, 88 + index * 13, line, size=10, anchor="middle",
                     fill="var(--ink-soft)")
    for row, candidate in enumerate(candidates):
        y = top + row * cell_h
        svg.text(left - 14, y + cell_h / 2 + 4, short_name(candidate), size=11.5,
                 weight=600, anchor="end")
        for column, dimension in enumerate(order):
            found = next((one for one in rows
                          if one["candidate"] == candidate
                          and one["dimension"] == dimension), None)
            x = left + column * cell_w
            if found is None or found.get("hallucination_rate") is None:
                # Nothing was claimed, so there is no rate. Pale with a dash —
                # never green, which would read as a clean sheet.
                svg.rect(x + 1.5, y + 1.5, cell_w - 3, cell_h - 3,
                         fill="var(--track)", radius=4)
                svg.text(x + cell_w / 2, y + cell_h / 2 + 4, "—", size=11,
                         anchor="middle", fill="var(--ink-faint)")
                continue
            value = float(found["hallucination_rate"])
            svg.rect(x + 1.5, y + 1.5, cell_w - 3, cell_h - 3, fill="var(--bad)",
                     opacity=0.10 + 0.75 * value, radius=4)
            svg.text(x + cell_w / 2, y + cell_h / 2 + 4, _pct(value), size=10,
                     anchor="middle", weight=600,
                     fill="#ffffff" if value > 0.6 else "var(--ink)")
    base = top + cell_h * len(candidates) + 22
    svg.text(left - 14, base, "shaded by", size=10, anchor="end",
             fill="var(--ink-faint)")
    svg.lines(left, base, "\n".join(wrap_text(
        "the share of claimed items the documents did not support — darker is "
        "worse. A dash means the model claimed nothing for that case, which is "
        "not the same as being right.", 116)), size=11, fill="var(--ink-faint)")
    return svg


def fabrication(document: dict) -> Svg:
    """What kind of fabrication, in counts, because the remedies differ."""
    candidates = document.get("candidates") or []
    top = 110.0
    row_h = 34.0
    svg = Svg(900, int(top + row_h * max(1, len(candidates)) + 64),
              "What kind of fabrication",
              "Counts, not rates: an unsupported claim, a quotation that is not "
              "in the page it names, and a figure under the wrong name.")
    _frame(svg, document)
    left, right = 158.0, 60.0
    plot_w = svg.width - left - right
    kinds = (
        ("claims not supported", "fabricated", "#b91c1c"),
        ("of which a bad quote", "unsupported_quotes", "#7c3aed"),
        ("wrong specifications", "specs_wrong", "#b45309"),
    )
    biggest = max([1] + [int(one.get(key) or 0) for one in candidates
                         for _label, key, _colour in kinds])
    step = nice_step(biggest)
    ticks = 0
    while ticks * step <= biggest * 1.02:
        x = left + plot_w * (ticks * step / biggest)
        svg.line(x, 88, x, top + row_h * len(candidates) - 6, stroke="var(--grid)")
        svg.text(x, 80, _num(ticks * step), size=10, anchor="middle",
                 fill="var(--ink-faint)")
        ticks += 1
    scale = plot_w / biggest
    for row, one in enumerate(candidates):
        y = top + row * row_h
        svg.text(left - 14, y + 15, short_name(one["candidate"]), size=11.5,
                 weight=600, anchor="end")
        for index, (_label, key, colour) in enumerate(kinds):
            value = int(one.get(key) or 0)
            bar_y = y + index * 6.4
            if not value:
                continue
            width = scale * value
            svg.rect(left, bar_y, width, 5.4, fill=colour, opacity=0.9, radius=2.5)
            svg.text(left + width + 6, bar_y + 5, str(value), size=10,
                     fill="var(--ink-faint)")
    base = top + row_h * len(candidates) + 18
    x = left
    for label, _key, colour in kinds:
        svg.rect(x, base - 10, 12, 11, fill=colour, opacity=0.9, radius=2)
        svg.text(x + 18, base, label, size=11, fill="var(--ink-soft)")
        x += 28 + _text_width(label, 11)
    svg.text(left, base + 22,
             "A model with many claims and no bad quotes is over-reaching; one "
             "with bad quotes is not reading. Different faults, different fixes.",
             size=11, fill="var(--ink-faint)")
    return svg


#: Every chart, by the name its file is given. A dict rather than a list so a
#: caller can render one, and so the set is discoverable from a test.
ALL = {
    "tradeoff": tradeoff,
    "quality": quality,
    "tokens": tokens,
    "dimensions": dimensions,
    "fabrication": fabrication,
}


def render(document: dict, *, only=None) -> dict:
    """`{name: svg text}` for every chart this document supports."""
    wanted = [only] if isinstance(only, str) else list(only or ALL)
    return {name: ALL[name](document).render() for name in wanted if name in ALL}


def write(directory, stem: str, document: dict) -> dict:
    """Write every chart beside the report. Returns `{name: path}`."""
    from pathlib import Path

    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, markup in render(document).items():
        target = out / f"{stem}-{name}.svg"
        target.write_text(markup, encoding="utf-8")
        paths[name] = str(target)
    return paths
