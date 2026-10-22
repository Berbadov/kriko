#!/usr/bin/env python3
"""Bake the free trial bundle into this build.

A stranger who installs Kriko has no keys and no password. This writes the
bundle that lets them ask a few Kriko Agent questions on the owner's keys —
`sharekeys.TRIAL_QUESTIONS`, counted in `shared.json` on their own machine — and
then stops and says what to do next.

The bundle carries real keys and is a credential, so it is written beside the
sharekeys module, which is gitignored, and it is *not* the owner's personal
key if they would rather it were not:

    # the keys this computer has saved (Settings → Research, or ~/.kriko/env)
    python tools/make_trial_access.py

    # or a pair made for the purpose, with a spend limit set at the provider
    python tools/make_trial_access.py --mercury sk-... --deepseek sk-...

The app-side count is a courtesy and a reader who clears their own state starts
it again. The protection that holds is the limit the owner puts on the trial
key at the provider, and rotating it per release: make a new pair, cap it,
bake it, and retire the old one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app import keys, sharekeys  # noqa: E402 — after the path is set up


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mercury", default="", help="the trial Mercury key (default: the saved one)")
    parser.add_argument("--deepseek", default="", help="the trial DeepSeek key (default: the saved one)")
    parser.add_argument("--questions", type=int, default=sharekeys.TRIAL_QUESTIONS,
                        help=f"how many questions the trial allows (default {sharekeys.TRIAL_QUESTIONS})")
    parser.add_argument("--clear", action="store_true", help="remove the bundle: no trial in this build")
    args = parser.parse_args(argv)

    if not sharekeys.bound():
        print("This build has no share pepper. Run tools/make_share_pepper.py first:",
              file=sys.stderr)
        print("a bundle baked without one would open in any other build.", file=sys.stderr)
        return 2

    if args.clear:
        sharekeys.TRIAL_FILE.unlink(missing_ok=True)
        print(f"removed {sharekeys.TRIAL_FILE}: this build offers no trial.")
        return 0
    values: dict[str, str] = {}
    for name, given in (("mercury", args.mercury), ("deepseek", args.deepseek)):
        if given.strip():
            values[name] = given.strip()
        else:
            try:
                values[name] = keys.require(name)
            except Exception as error:  # noqa: BLE001 — the reader's next step, not a crash
                print(f"No {name} key: {error}", file=sys.stderr)
                return 2
    limit = max(1, int(args.questions))
    try:
        bundle = sharekeys.make_trial(values, questions=limit)
    except sharekeys.ShareError as error:
        print(str(error), file=sys.stderr)
        return 2
    sharekeys.write_trial(bundle)
    print(f"wrote {sharekeys.TRIAL_FILE} ({limit} questions per installation)")
    print("Set a spend limit on these keys at the provider before publishing the build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
