# Stable release acceptance

Run `tools/gate.sh` on the shipping Windows environment, with the Rust cache and
all dependencies installed. Desktop TypeScript, UI behavior, lint, extension and
site tests are required alongside Python, wheel and Rust checks. A skipped check
is incomplete and exits nonzero. Mobile is a separate prototype; changes there
also require `tools/gate.sh mobile` and device observation.

Build the installer and portable ZIP using the documented packaging recipe.
Observe these journeys on the packaged app, using a fresh profile and a profile
from the preceding release:

1. Install without administrator rights and start the portable build separately.
2. Use **More → Set up Kriko**, choose an agent and verify its connection.
3. Install a release catalog and stage/load the browser extension.
4. Ask for exact product options under a budget, with source links. Open the
   quotations, correct the variant, and confirm the correction survives a long chat.
5. Ask a detailed follow-up and compare two links and two saved checks. Inspect
   specifications, units, assumptions and coverage.
6. Include one unreadable source; confirm research finds an alternative or reports
   a precise unresolved gap. A tool request or an offer to begin is not completion.
7. Stop a Product and Compare question while working. Preserve the partial answer.
8. Disconnect/reconnect and retry an uncertain Chat send. Confirm one logical job
   and one reader message, without example data appearing as research.
9. Upgrade the preceding release and retain chats, catalogs and settings. Export a
   snapshot, stage its restore, restart and check restored data and draft contents.

Run conversational scenarios for each provider/version intended to be supported:

```bash
python -m app.conversationbench --agent codex
python -m app.conversationbench --agent codex --run --out codex-conversations.json
```

The first command prints a plan. `--run` sends real requests and may incur provider
charges. CLI IDs, local, and API agent IDs use the same scenarios; unavailable
agents are reported separately and do not pass. Deterministic checks supplement
human assessment of usefulness and source support.

Record results under `docs/releases/<version>.json`. After implementation is
final, obtain its identity with `python tools/release_readiness.py --fingerprint`.
The JSON must contain `version`, `source_fingerprint`, `platform` set to
`windows-x86_64`, and `journeys` with these keys:

`fresh_install`, `portable_start`, `setup`, `sourced_answer`, `follow_up`, `compare`,
`stop`, `reconnect`, `upgrade_retains_data`.

Each journey records `status: "passed"`, `observed_at`, and `evidence` describing
the result or pointing to its capture. `providers` records each observed agent
with `status`, `model`, `version` (CLI/provider version), and `report`. Keep API
keys, personal product listings and other sensitive account data out of reports.

The publication workflow validates this file. Missing observations remain a
release blocker; compiling the app or running scripted providers cannot fill them.
