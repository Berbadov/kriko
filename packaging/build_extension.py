"""Build the unsigned Firefox add-on from the shared browser extension.

    python packaging/build_extension.py --output reports/kriko-firefox.xpi

For a permanent Firefox install, submit the XPI for Mozilla signing. This
command does not upload anything or alter browser signature requirements.
"""
import argparse
from pathlib import Path
import tempfile

from app import extension


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = extension.source_dir()
    if source is None:
        parser.error("The extension source is missing")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".kriko-firefox-", dir=args.output.parent) as scratch:
        staged = Path(scratch) / "extension"
        extension.stage(source, staged, "firefox")
        extension.package(staged, args.output)
    print(f"Unsigned Firefox add-on: {args.output.resolve()}")


if __name__ == "__main__":
    main()
