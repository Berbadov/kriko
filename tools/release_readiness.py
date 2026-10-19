"""Verify observed release journeys against the exact source being published.

Print --fingerprint after code changes, then record observations in the release
evidence file. An absent/skipped check cannot authorize stable publication.
"""

import argparse
import hashlib
import json
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOURNEYS = ("fresh_install", "portable_start", "setup", "sourced_answer", "follow_up",
            "compare", "stop", "reconnect", "upgrade_retains_data")


def fingerprint(root: Path = ROOT) -> str:
    listed = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root)
    paths = sorted(set(path.decode("utf-8") for path in listed.split(b"\0") if path))
    digest = hashlib.sha256()
    for name in paths:
        if name.startswith(("docs/releases/", "artifacts/", "release/")):
            continue
        path = root / name
        if path.is_file():
            digest.update(name.encode("utf-8") + b"\0" + path.read_bytes())
    return digest.hexdigest()


def problems(evidence: dict, version: str, source_fingerprint: str) -> list[str]:
    if not isinstance(evidence, dict):
        return ["Release evidence must be a JSON object."]
    errors = []
    if evidence.get("version") != version:
        errors.append("Evidence does not name this release version.")
    if evidence.get("source_fingerprint") != source_fingerprint:
        errors.append("Evidence does not describe the current source fingerprint.")
    if evidence.get("platform") != "windows-x86_64":
        errors.append("The shipping Windows platform was not observed.")
    journeys = evidence.get("journeys")
    if not isinstance(journeys, dict):
        journeys = {}
    for name in JOURNEYS:
        check = journeys.get(name) or {}
        if not isinstance(check, dict):
            check = {}
        if check.get("status") != "passed" or not check.get("observed_at") or not check.get("evidence"):
            errors.append(f"Missing successful observation: {name}.")
    providers = evidence.get("providers") or {}
    if not isinstance(providers, dict) or not providers:
        errors.append("No real provider/model observations were recorded.")
        providers = {}
    for name, observation in providers.items():
        if (not isinstance(observation, dict) or observation.get("status") != "passed" or not observation.get("model")
                or not observation.get("version") or not observation.get("report")):
            errors.append(f"Provider observation is incomplete: {name}.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fingerprint", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    current = fingerprint()
    if args.fingerprint:
        print(current)
        return 0
    if args.evidence is None:
        parser.error("Provide --evidence or request --fingerprint.")
    try:
        evidence = json.loads(args.evidence.read_text("utf-8"))
        version = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
        errors = problems(evidence, version, current)
    except (OSError, ValueError, TypeError) as error:
        errors = [f"Release evidence is unavailable: {error}"]
    if errors:
        print("Release verification incomplete:\n" + "\n".join(errors))
        return 1
    print("The required release journeys have matching observations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
