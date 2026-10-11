# Update protocol

## Every change gets a new version

Every change set must increase the app version and update `README.md` before it is committed. This includes features, fixes, documentation, configuration, dependencies, and packaging. Bump once for the complete change set; another change after publishing requires another bump.

Use `MAJOR.MINOR.PATCH`: increase PATCH for compatible corrections, MINOR for new compatible features, and MAJOR for incompatible changes. The next version must be greater than the current tree and every published app release.

Before choosing the version, inspect the remote inventory with `git fetch origin --tags` and `gh release list --repo Berbadov/kriko`. The bump tool checks the current tree; remote release uniqueness is a required publishing check. Do not choose a version already present in either inventory. Creating the new tag and release must fail if either already exists; never force a tag or use `--clobber` to bypass that failure.

```powershell
.venv/Scripts/python.exe tools/bump.py 1.3.1
```

The tool updates `pyproject.toml`, `kriko-gpui/Cargo.toml`, the app entry in `kriko-gpui/Cargo.lock`, and README's version badge and download filenames. Add reader-visible release notes to the README yourself. Update installation instructions when the reader's steps change. Historical benchmark versions remain historical.

## Published versions are immutable

The updater compares the release installer's version with the running app version. A changed file with the same version is not an update. Never replace assets under an existing release, reuse a published version, or move a published tag. Publish corrections under a newer version, including corrections to checksums or packaging.

The release tag, source manifests, installed app metadata, MSI ProductVersion, installer filename, README badge, and download filenames must agree. Name installers `kriko-X.Y.Z-x86_64.msi`; publish `SHA256SUMS.txt` beside them. Keep the MSI UpgradeCode stable so a newer installer replaces the existing installation.

## Build and publish

1. Record the request and its acceptance criteria. Prepare the complete change set, version bump, and README update in a review branch. Preserve unrelated workspace changes.
2. Refresh the build environment's package metadata after bumping: `.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e .`. Run `.venv/Scripts/python.exe tools/bump.py --show --strict`; the tree, README, and installed metadata must agree before freezing.
3. Build from the exact reviewed source using `kriko-gpui/package.ps1`. Follow the project's review and verification rules and record the observed result. Never rename an older installer to simulate a version bump.
4. Generate SHA256 digests from the final downloadable files. `SHA256SUMS.txt` must name each file exactly. Include the MSI, any portable ZIP, catalogs, and their index as applicable. Update `packs.json` URLs to the new release tag when publishing catalogs.
5. Push the review branch and PR. The reader merges to `main`. A release explicitly authorized before merge must identify its exact reviewed source commit and pending PR in its notes; never imply that it is already on `main`.
6. Create a new `vX.Y.Z` tag at that source commit. Prepare a draft release with the versioned assets, checksum manifest, and release notes. Publish it as the latest stable release only after its assets are complete. Do not overwrite an existing release.
7. Observe that the updater offers the release to the preceding installed version and verifies its download against the published manifest. Record installation and `/api/health` version observations when available. Report any remaining verification limits.

Release notes summarize reader-visible changes, installation steps, known limits, and the exact source commit. The release's README must describe the same version.
