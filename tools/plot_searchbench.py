"""Plot a saved search experiment; optional matplotlib, no API calls.

    python tools/plot_searchbench.py path/to/searchbench.json
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.searchbench.report import aggregate  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    document = json.loads(args.source.read_text(encoding="utf-8"))
    summaries = sorted(aggregate(document["runs"]), key=lambda s: (s["model"], s["strategy"], s["search"]))
    models = list(dict.fromkeys(s["model"] for s in summaries))
    palette = ["#2563eb", "#7c3aed", "#08916f", "#d97706", "#dc4058", "#526478"]
    colors = {name: palette[i % len(palette)] for i, name in enumerate(models)}
    figure, axes = plt.subplots(1, 3, figsize=(15, max(4.5, len(summaries) * .4 + 1.8)), sharey=True)
    for index, summary in enumerate(summaries):
        mean = summary["mean_s"]
        color = colors[summary["model"]]
        if mean is not None:
            interval = summary["mean_s_ci95_task_bootstrap"]
            axes[0].barh(index, mean, height=.58, color=color, alpha=.85)
            if interval:
                axes[0].errorbar(mean, index, xerr=[[max(0, mean - interval[0])], [max(0, interval[1] - mean)]], fmt="none", ecolor="#243247", capsize=3)
            label_at = max(mean, interval[1]) if interval else mean
            axes[0].text(label_at, index, f"  {mean:.1f}s ({summary['ok']}/{summary['n']})", va="center", fontsize=8)
        else:
            axes[0].text(0, index, f"No completion (0/{summary['n']})", va="center", fontsize=8)
        cost = summary["known_cost_usd"] / summary["n"]
        tokens = summary["known_total_tokens"] / summary["n"] / 1000
        for axis, value, label, complete in (
            (axes[1], cost, f"${cost:.4f}", summary["cost_complete"]),
            (axes[2], tokens, f"{tokens:.1f}k", summary["total_tokens"] is not None),
        ):
            axis.barh(index, value, height=.58, color=color, alpha=.85, hatch=None if complete else "//")
            axis.text(value, index, "  " + ("" if complete else "≥ ") + label, va="center", fontsize=8)
    labels = [f"{s['model']} / {s['strategy']}" for s in summaries]
    axes[0].set_yticks(range(len(labels)), labels)
    axes[0].invert_yaxis()
    for axis, title in zip(axes, ("Successful mean latency (seconds)", "Cost per attempt (estimated USD)", "Model tokens per attempt (thousands)")):
        axis.set_title(title, fontsize=11, pad=14)
        axis.set_xlim(left=0, right=max(axis.get_xlim()[1] * 1.25, .01))
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.tick_params(axis="y", length=0, labelsize=9)
        axis.tick_params(axis="x", labelsize=8)
        axis.xaxis.grid(True, alpha=.15)
        axis.set_axisbelow(True)
    cases = len({r["case"] for r in document["runs"]})
    figure.suptitle(f"Web research pilot · {len(document['runs'])} attempts · {cases} distinct questions", x=.02, ha="left", fontsize=17, weight="bold")
    figure.text(.02, .045, "Latency intervals: 95% task-cluster bootstrap. Costs and tokens include failed attempts; hatched bars are known lower bounds.", fontsize=9, color="#475569")
    figure.text(.02, .015, "Small screening sample; factual correctness is unscored. Provider caches may apply. No Google baseline was measured.", fontsize=9, color="#475569")
    figure.tight_layout(rect=(0, .08, 1, .93))
    for suffix in (".metrics.png", ".metrics.svg"):
        path = args.source.with_suffix(suffix)
        figure.savefig(path, dpi=180, facecolor="white")
        print(path)
    plt.close(figure)


if __name__ == "__main__":
    main()
