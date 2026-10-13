# Update protocol

## Versions move at release, not per change

Change sets land without touching the version or the README. Whoever cuts a
release bumps the version once, with `tools/bump.py`, and writes the
reader-visible notes in the README for everything since the last one. The
strict version check confirms the source versions, README badge and download
filenames, and installed distribution metadata agree.

Use `MAJOR.MINOR.PATCH`: increase PATCH for compatible corrections, MINOR for new compatible features, and MAJOR for incompatible changes. The next version must be greater than the current tree and every published app release.

Before choosing the version, inspect the remote inventory with `git fetch origin --tags` and `gh release list --repo Berbadov/kriko`. The bump tool checks the current tree; remote release uniqueness is a required publishing check. Do not choose a version already present in either inventory. Creating the new tag and release must fail if either already exists; never force a tag or use `--clobber` to bypass that failure.

```powershell
.venv/Scripts/python.exe tools/bump.py 1.3.1
```

The tool updates `pyproject.toml`, `kriko-gpui/Cargo.toml`, the app entry in `kriko-gpui/Cargo.lock`, and README's version badge and download filenames. Add reader-visible release notes to the README yourself. Update installation instructions when the reader's steps change. Historical benchmark versions remain historical.

## Published versions are immutable

The in-app updater currently installs only the Windows x86_64 MSI. It downloads the MSI named by the release and verifies it with the root `SHA256SUMS.txt`. It does not update Windows portable ZIPs or macOS app bundles; those are replaced manually from the matching archive.

The release tag, source manifests, installed app metadata, MSI ProductVersion,
installer filename, README badge, and download filenames must agree. Name the
MSI `kriko-X.Y.Z-x86_64.msi`; keep its `SHA256SUMS.txt` at the release root,
because the updater looks up that exact manifest name. It covers the MSI and
Windows portable ZIP.

The release workflow also publishes macOS packages built natively on both Apple Silicon (`arm64`) and Intel (`x86_64`). Each architecture has a disk image and portable app bundle named `kriko-X.Y.Z-macos-<arch>.dmg` and `kriko-X.Y.Z-macos-<arch>-portable.zip`, with its own `SHA256SUMS-<arch>.txt`. The workflow adds `SHA256SUMS-ALL.txt` as an aggregate over the other release assets. This aggregate supplements the Windows manifest; never replace or rename the root `SHA256SUMS.txt` with it. Keep the MSI UpgradeCode stable so a newer installer replaces the existing installation.

Never replace assets under a published release, reuse a published version, or move a published tag. Publish corrections under a newer version, including corrections to checksums or packaging. Uploading the first assets to a new, unpublished draft is expected. If a draft already exists for the tag, verify its source and complete the same draft rather than creating a competing release; do not clobber or replace already attached binaries. Never use `--clobber` to replace published assets.

## Build and publish

1. Prepare the version bump and README notes for all reader-visible changes
   since the last release in a review branch. Preserve unrelated workspace
   changes. Changes do not bump the version individually; the release does.
2. Refresh the build environment's package metadata after bumping. On Windows
   use `.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e .`;
   on macOS use `uv pip install --python .venv/bin/python --no-deps -e .`.
   Then run `.venv/Scripts/python.exe tools/bump.py --show --strict` on Windows
   or `.venv/bin/python tools/bump.py --show --strict` on macOS; source,
   README, and installed metadata must agree before packaging.
3. Run `tools/gate.sh` on the exact reviewed source and open a PR. The reader
   merges to `main`; use the reviewed, merged source commit for the release.
   If a release is explicitly authorized before merge, identify its exact
   reviewed commit and pending PR in the draft notes and do not imply that it
   is already on `main`.
4. Before creating the immutable tag, hand-dispatch
   `.github/workflows/desktop.yml` on the reviewed source branch/commit. It
   builds Windows x64, packs, and both native macOS architectures. Verify the
   full gate and every target's packaging and smoke results, then download the
   run artifacts. Match the workflow run's source SHA to the intended release
   commit. A branch dispatch produces artifacts, not a release draft. Do not
   claim a native artifact was built or observed unless that architecture's
   native packaging and smoke checks actually ran.
5. Prepare the release files without rebuilding or renaming the verified
   desktop binaries. Regenerate `packs.json` so each `.kpack` URL names the new
   `vX.Y.Z` tag, then verify the URLs. Keep the Windows `SHA256SUMS.txt`
   unchanged and verify the MSI/portable ZIP against it; verify each Mac
   package against its matching `SHA256SUMS-<arch>.txt`. Generate and verify
   `SHA256SUMS-ALL.txt` over the final complete asset set. If any binary
   changes, return to native packaging and repeat its checks before proceeding.

   From the repository root, after placing the verified `.kpack` files in
   `release/`, the index can be regenerated with:

   ```sh
   python packaging/publish_index.py \
     --base-url "https://github.com/Berbadov/kriko/releases/download/vX.Y.Z" \
     --out release/packs.json release/*.kpack
   ```
6. Check whether the tag or a draft release already exists. If neither exists, create `vX.Y.Z` at the exact verified source SHA and create a new draft release. If the same tag already has an unpublished draft, verify that it points to this exact source SHA and complete that draft; do not create a competing release. If the tag points elsewhere or its release is published, stop and use a new version. Upload the verified artifacts, regenerated pack index, packs, and manifests to the draft. Review the source SHA/PR, exact filenames, checksums, release notes, and README before manually publishing it as latest stable. The tag workflow can create a draft itself, but running it on the tag rebuilds the native packages; use the verified branch-run artifacts when following this branch-first process.
7. Never move or force a tag, replace published assets, or reuse a published version. The release job refuses a tag that already has a release. A draft may be completed with missing initial assets, but do not clobber or replace verified binaries already attached; if a binary must change, use a new version. Corrections after publication also require a new version. After publication, observe the Windows updater offer and verify its MSI download against `SHA256SUMS.txt`. Record installation and `/api/health` observations when available. Mac and portable installs are updated manually. Report remaining verification limits.

Release notes summarize reader-visible changes, installation steps, known limits, and the exact source commit. The release's README must describe the same version.
