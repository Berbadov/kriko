# Decontamination and Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository read the way the code already behaves — a category-free knowledge engine with cars as pack #1 — and make it installable.

**Architecture:** Seven tasks. Tasks 1–3 are structural (packaging, docs, README) and land first so the prose written later describes the final layout. Task 4 extends the domain-free gate to prose and **fails**, producing the exact offence list. Tasks 5–6 fix that prose until it passes. Task 7 moves the engine's own test fixtures off cars so the suite proves generality instead of asserting it. The dependency fan is not touched at any point.

**Tech Stack:** Python 3.14, pytest, `ast` + `tokenize` (comments are *not* in the AST), tomllib/pyproject, SQLite, FastAPI, PyYAML.

**Spec:** `docs/superpowers/specs/2026-08-30-decontamination-and-packaging-design.md`

## Global Constraints

- **Run tests with the repo venv and this exact invocation:**

  ```bash
  .venv/bin/python -m pytest -o addopts="" -q
  ```

  **Baseline: 605 passed, ~26s.** The `-o addopts=""` is required — `pytest.ini` already sets `-q`, so a plain `pytest -q` passes `-q` twice and pytest suppresses the `N passed` summary line entirely. A bare `python` does not exist on this machine.
- **The dependency fan does not change.** `app/` → `kriko/` ← `packs/`. `kriko/` imports none of the others. Enforced by `app/pipeline/tests/test_repo_invariants.py`; never weaken that test.
- **No behaviour changes anywhere in this plan.** Every task is packaging, prose, or test fixtures. An executable change inside a prose task's diff is a review finding.
- **`packs/` stays at the repository root.** It is content shipped as a `.kpack` file, not library code. Only `kriko/` and `app/` move under `src/`.
- **Commit message must end with:** `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- **Do not merge to main.** Committing and pushing to `feat/knowledge-engine-pivot` is authorised.
- **Baseline commit:** `d3cbe6f`. Branch `feat/knowledge-engine-pivot`, already pushed and tracking `origin`.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, Python floor, runtime deps, optional `pipeline` extra |

**Moved:**

| From | To |
|---|---|
| `kriko/` | `src/kriko/` |
| `app/` | `src/app/` |
| `docs/overhaul_plan.md` | `docs/historical/overhaul_plan.md` |
| `docs/claim_relevance_plan.md` | `docs/historical/claim_relevance_plan.md` |
| `docs/pipeline_postmortem.md` | `docs/historical/pipeline_postmortem.md` |

**Substantially rewritten:**

| File | Change |
|---|---|
| `README.md` | 247 lines → ~120, for a reader who has never seen the project |
| `kriko/tests/test_core_is_domain_free.py` | Gate extended to docstrings and comments; its own docstring's reasoning inverted |
| `packs/cars/pipeline/requirements.txt` | Rewritten against reality, or deleted |

---

### Task 1: `src/` layout and `pyproject.toml`

**Files:**
- Create: `pyproject.toml`
- Move: `kriko/` → `src/kriko/`, `app/` → `src/app/`
- Modify: `pytest.ini`, `.github/workflows/ci.yml`
- Modify (one extra `.parent` each): `app/pipeline/panel.py:32`, `app/pipeline/remediate.py:39`, `app/pipeline/tests/test_repo_invariants.py:12`, `kriko/tests/test_pack_contract.py:14`

**Interfaces:**
- Produces: import paths **unchanged** — `kriko.*` and `app.*` still resolve identically once the package is installed or `src/` is on the path. Every later task depends on this.

- [ ] **Step 1: Record the baseline and the entry points that must still work**

```bash
.venv/bin/python -m pytest -o addopts="" -q | tail -1
for m in app.cli app.mcp_server app.web packs.cars.build packs.cars.coverage; do
  printf "%-24s " "$m"
  .venv/bin/python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$m') else 1)" \
    && echo OK || echo GONE
done
```

Expected: `605 passed`, and every module `OK`. Write both outputs down — Step 8 compares against them.

- [ ] **Step 2: Move the two packages**

```bash
mkdir -p src
git mv kriko src/kriko
git mv app src/app
```

Use `git mv` so the moves record as renames and the diff stays readable.

- [ ] **Step 3: Write `pyproject.toml`**

The runtime dependencies are what `src/kriko/` and `src/app/` actually import — verify this yourself rather than trusting the list:

```bash
grep -rhoE "^(import|from) [a-z_]+" --include='*.py' src/kriko src/app \
  | awk '{print $2}' | sort -u
```

Anything in that output which is not stdlib and not `kriko`/`app`/`packs` is a runtime dependency. Expected: `fastapi`, `mcp`, `pydantic`, `yaml` (the distribution is `pyyaml`), plus `uvicorn` which `app/web/__main__.py` invokes.

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "kriko"
version = "0.1.0"
description = "A local-first, open knowledge engine for manufactured products"
readme = "README.md"
requires-python = ">=3.14"
license = { text = "MIT" }

dependencies = [
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "pydantic>=2.0",
    "pyyaml>=6.0.1",
    "mcp>=1.0,<2.0",
]

[project.optional-dependencies]
# Building knowledge, not reading it. None of this is needed to install a
# pack and answer a question; all of it is needed to research one.
pipeline = [
    "httpx>=0.27.0",
    "selectolax>=0.3.21",
    "mistralai>=1.0.0",
    "langextract>=1.6.0",
    "yt-dlp>=2024.1.1",
    "trafilatura>=1.9.0",
    "textual>=0.60.0",
    "exa-py>=2.14.0",
    "anthropic",
]
dev = ["pytest>=8.0.0"]

[tool.setuptools.packages.find]
where = ["src"]
include = ["kriko*", "app*"]
```

Check the `license` field against the repository's actual licence before writing it — if there is no `LICENSE` file, ask rather than asserting MIT.

- [ ] **Step 4: Fix the four path computations that walk past the package root**

Each gained one directory level. Read each line, confirm what it is trying to reach, and add exactly one `.parent` (or increment the `parents[N]` index by one):

| file | before | after |
|---|---|---|
| `src/app/pipeline/panel.py:32` | `Path(__file__).resolve().parent.parent.parent` | one more `.parent` |
| `src/app/pipeline/remediate.py:39` | `Path(__file__).resolve().parent.parent.parent` | one more `.parent` |
| `src/app/pipeline/tests/test_repo_invariants.py:12` | `.parent` × 4 | `.parent` × 5 |
| `src/kriko/tests/test_pack_contract.py:14` | `parents[2]` | `parents[3]` |

**Verify each by printing it, not by reasoning about it:**

```bash
.venv/bin/python -c "
from pathlib import Path
for f in ['src/app/pipeline/panel.py','src/app/pipeline/remediate.py',
          'src/app/pipeline/tests/test_repo_invariants.py',
          'src/kriko/tests/test_pack_contract.py']:
    print(f)
"
```

then for each, import the module (or run its test) and confirm the computed root contains `packs/` and `README.md`. A wrong root imports cleanly and fails later on a path that does not exist — that is the failure mode this step exists to prevent.

- [ ] **Step 5: Update `pytest.ini`**

`testpaths = kriko packs app` becomes:

```ini
testpaths = src/kriko src/app packs
```

Keep the existing comment explaining why the paths are named explicitly; it is still true and still important.

- [ ] **Step 6: Update CI**

In `.github/workflows/ci.yml`, the Python job installs dependencies around line 28 and runs `python -m pytest` at line 39. Replace the dependency install with an editable install of the project plus its dev extra:

```yaml
              run: |
                  python -m pip install --upgrade pip
                  pip install -e ".[dev,pipeline]"
```

Read the surrounding YAML before editing and match its indentation exactly — this file uses an unusual indent width.

- [ ] **Step 7: Install into a clean environment and confirm the packaging is real**

```bash
.venv/bin/pip install -e . 2>&1 | tail -3
.venv/bin/python -c "import kriko, app; print('kriko:', kriko.__file__); print('app:', app.__file__)"
```

Expected: both resolve under `src/`. If `pip install -e .` fails, the `packages.find` configuration is wrong — fix it here rather than working around it.

- [ ] **Step 8: Run every entry point and the full suite**

```bash
for m in app.cli app.mcp_server packs.cars.build packs.cars.coverage; do
  printf "%-24s " "$m"
  .venv/bin/python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$m') else 1)" \
    && echo OK || echo GONE
done
.venv/bin/python -m pytest -o addopts="" -q | tail -1
```

Expected: every module `OK`, and **605 passed** — identical to Step 1. A drop means a path computation is wrong; find it before committing.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -F - <<'EOF'
build: src/ layout and a pyproject, so Kriko can be installed

kriko/ and app/ move under src/; packs/ deliberately does not. A pack is
content — authored as a directory, shipped as one .kpack file, per
docs/PACK_CONTRACT.md — not library code, and putting it under src/ would
claim it is part of the installable distribution.

Keeping packs/ at the root is also what makes this cheap: of the eleven
path computations that walk up to the repository root, seven live inside
packs/ and stay correct untouched. The four that broke each needed one
more .parent, and each was verified by printing the resolved root rather
than by reasoning about the arithmetic.

pyproject splits the dependencies by what they are for: reading knowledge
needs fastapi, uvicorn, pydantic, pyyaml and mcp; building it needs the
extraction and scraping stack, which is now an optional `pipeline` extra.
Installing Kriko to answer a question no longer pulls yt-dlp.

The dependency fan is untouched. 605 passed, unchanged.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: `docs/` says which documents are current

**Files:**
- Move: `docs/overhaul_plan.md`, `docs/claim_relevance_plan.md`, `docs/pipeline_postmortem.md` → `docs/historical/`
- Modify: whichever live documents reference them (found in Step 1)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable. Task 3's README doc-table depends on the final locations.

- [ ] **Step 1: Find every reference before moving anything**

```bash
for d in overhaul_plan claim_relevance_plan pipeline_postmortem design_flaws; do
  echo "--- $d"
  grep -rn "$d" --include='*.md' . | grep -v node_modules | grep -v "^./docs/historical/"
done
```

Write down each hit. Expect roughly two live references each for the first three, and about four for `design_flaws`.

- [ ] **Step 2: Move the three pre-pivot documents**

```bash
git mv docs/overhaul_plan.md docs/historical/overhaul_plan.md
git mv docs/claim_relevance_plan.md docs/historical/claim_relevance_plan.md
git mv docs/pipeline_postmortem.md docs/historical/pipeline_postmortem.md
```

**`docs/design_flaws.md` stays.** It was last touched 2026-08-21, is referenced by four live documents, and backs open backlog item B13. Moving it would break a live reference and mislabel current work as history.

- [ ] **Step 3: Repoint every reference from Step 1**

Update each to `docs/historical/<name>.md`, and where the surrounding sentence implies the document is current, say it is historical. `docs/historical/` already carries a blanket warning ("Historical context only; don't follow their instructions") — a reference from a live document should not contradict that.

- [ ] **Step 4: Confirm nothing points at the old paths**

```bash
grep -rn "docs/overhaul_plan\|docs/claim_relevance_plan\|docs/pipeline_postmortem" \
  --include='*.md' . | grep -v node_modules | grep -v docs/historical/ | grep -v docs/superpowers/
```

Expected: no output. Hits inside `docs/superpowers/` are archival planning records and are left alone.

- [ ] **Step 5: Run the suite and commit**

```bash
.venv/bin/python -m pytest -o addopts="" -q | tail -1
git add -A
git commit -F - <<'EOF'
docs: move the pre-pivot planning documents into historical/

overhaul_plan.md, claim_relevance_plan.md and pipeline_postmortem.md were
last touched on 2026-06-29 — before the pivot that made Kriko a
category-free engine — and sat in docs/ beside current documents with
nothing marking them stale. A reader had no way to tell which described
the system they were looking at.

docs/historical/ exists for exactly this and already carries the warning.
design_flaws.md stays: it is referenced by four live documents and backs
open backlog item B13.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: `README.md` for someone who has never seen this project

**Files:**
- Rewrite: `README.md`

**Interfaces:**
- Consumes: the final layout from Task 1, the final doc locations from Task 2.
- Produces: nothing importable.

- [ ] **Step 1: Get a real example of the product's output**

The current README describes the idea and never shows it. Build and install the cars pack, then run a lookup and capture what actually comes back:

```bash
.venv/bin/python -m app.cli build packs/cars
.venv/bin/python -m app.cli packs
```

Then run a lookup for a real variant — read `.venv/bin/python -m app.cli --help` for the exact syntax rather than guessing it. Capture the genuine output. **Do not invent a plausible-looking example**; a fabricated sample in a README is the most damaging kind of false documentation, because a new reader measures the product against it.

If the lookup path cannot be driven from the CLI, say so in your report and use the smallest real thing you can produce instead.

- [ ] **Step 2: Write the new README**

Target ~120 lines. Structure:

1. **What it is** — the one question Kriko answers, and that it runs locally. Keep the existing opening paragraphs; they are good and correctly framed.
2. **What it looks like** — the real output from Step 1, in a fenced block. This is the section the current README lacks entirely.
3. **Install and run** — `pip install -e ".[pipeline]"`, build a pack, ask it something, start the dashboard, load the extension. Fewest commands that actually work; verify each one.
4. **What a pack is** — two short paragraphs, the two shipped packs (`cars`, `drill`), linking `docs/PACK_CONTRACT.md`.
5. **Where to go next** — a short table: `docs/ARCHITECTURE.md` to read the code, `CLAUDE.md` for principles, `CONTRIBUTING.md` to contribute, `backlog.md` for status.

**Delete** the `Design principles` section — link to `CLAUDE.md` instead of duplicating it. **Delete** the `File layout` block entirely; `docs/ARCHITECTURE.md` carries a verified package table, and the current block lists `kriko/` twice.

Keep the `Supported cars (TR market)` table — it is concrete, true, and tells a reader whether Kriko is useful to them today.

- [ ] **Step 3: Verify every command and path in the new README**

```bash
.venv/bin/python - <<'PATHS'
import pathlib, re
doc = pathlib.Path("README.md").read_text()
paths = set(re.findall(r'`((?:src|kriko|app|packs|docs|extension)/[\w./-]+)`', doc))
missing = [p for p in sorted(paths) if not pathlib.Path(p.rstrip('/')).exists()]
print("MISSING:", missing or "none")
PATHS
```

Expected: `MISSING: none`. Then run every command block in the README yourself. A command that does not work is worse than an omitted one.

- [ ] **Step 4: Run the suite and commit**

```bash
.venv/bin/python -m pytest -o addopts="" -q | tail -1
git add README.md
git commit -F - <<'EOF'
docs: a README for someone who has never seen this project

247 lines written for a reader who already knew the project, including a
File layout block that listed kriko/ twice — a copy-paste error in the
section a newcomer trusts most.

The rewrite shows the product before explaining it: a real ranked claim
for a real listing, which the old README never did. Design principles
became a link to CLAUDE.md rather than a second copy, and the file layout
became a link to docs/ARCHITECTURE.md, which already carries a package
table whose paths and line anchors are verified.

Every command and path in it was run or resolved.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: Extend the domain-free gate to prose — and watch it fail

**Files:**
- Modify: `src/kriko/tests/test_core_is_domain_free.py`

**Interfaces:**
- Produces: `ALLOWED_PROSE: dict[str, set[str]]` — filename → the banned terms that file may legitimately use in prose. Task 5 populates it; nothing else consumes it.

**This task deliberately ends with a failing test.** The failure output *is* the deliverable: it is the exact, complete list of prose offences Task 5 must fix. Do not fix any prose in this task.

- [ ] **Step 1: Read the existing test and note what you are reversing**

Its module docstring currently says:

> Prose is deliberately exempt: the docstrings in this package explain themselves by reference to the car code they replaced, and that history is worth keeping.

That was a considered decision, and this task reverses it. `test_the_guard_actually_catches_something` also asserts that a docstring does **not** trip the gate. Both must change, or the test will contradict itself.

- [ ] **Step 2: Understand why comments need a different mechanism**

Python's `ast` module **discards comments entirely** — they are not nodes and no AST walk can reach them. Docstrings are `ast.Constant` nodes and the existing `_docstring_nodes()` already identifies them. Comments require `tokenize`:

```python
import io
import tokenize


def _comments(path: Path) -> list[tuple[int, str]]:
    """Every comment in a file, as (lineno, text). ast discards comments."""
    src = path.read_text(encoding="utf-8")
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            out.append((tok.start[0], tok.string))
    return out
```

- [ ] **Step 3: Add the prose scan and the allowlist**

Add to the module, near `ALLOWED_EXACT`:

```python
# Prose in the engine may not explain a generic mechanism through one
# category's vocabulary — a reader writing a pack for dishwashers should not
# find every explanation phrased in gearboxes. A category example is allowed
# where it genuinely clarifies a rule, and each one is named here so that the
# exception is a visible decision rather than an oversight.
#
# filename -> the banned terms that file may use in prose.
ALLOWED_PROSE: dict[str, set[str]] = {}
```

Then a scanner that reports docstrings and comments separately from executable positions:

```python
def _prose_offences(path: Path) -> list[str]:
    """Banned vocabulary in docstrings and comments, minus the allowlist."""
    permitted = ALLOWED_PROSE.get(path.name, set())
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []

    for node in ast.walk(tree):
        if not (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                  ast.AsyncFunctionDef))):
            continue
        text = ast.get_docstring(node)
        if not text:
            continue
        hits = sorted({w for w in _split_identifier(text) if w in BANNED} - permitted)
        if hits:
            found.append(f"{path.name}:{node.lineno}: docstring contains {hits}")

    for lineno, text in _comments(path):
        hits = sorted({w for w in _split_identifier(text) if w in BANNED} - permitted)
        if hits:
            found.append(f"{path.name}:{lineno}: comment contains {hits}")

    return found
```

Note `_split_identifier` already lowercases and splits on word boundaries, so it works on prose as well as identifiers.

- [ ] **Step 4: Add the gate test**

```python
def test_the_engine_does_not_explain_itself_in_one_category():
    """The code is category-free; the prose must be too.

    A reader arriving to write a pack for a product Kriko has never seen
    should not find every explanation phrased in another category's terms.
    That reader cannot run the AST check — they just read, and believe what
    they read.
    """
    offences = []
    for path in sorted(CORE.rglob("*.py")):
        if "/tests/" in path.as_posix() or "__pycache__" in path.as_posix():
            continue
        offences.extend(_prose_offences(path))

    assert offences == [], (
        "kriko/ explains itself in one product category:\n  "
        + "\n  ".join(offences)
        + "\n\nState the generic rule first. A category example may follow "
          "where it genuinely clarifies — add it to ALLOWED_PROSE so the "
          "exception is a decision someone made on purpose."
    )
```

- [ ] **Step 5: Invert the two places that assert prose is exempt**

Rewrite the module docstring's last paragraph to say prose is now checked and why. In `test_the_guard_actually_catches_something`, the line

```python
        # ...and the docstring did not trip it.
        assert not any("A docstring may mention" in o for o in offences)
```

asserts the old behaviour. `_offences()` still legitimately exempts docstrings — the new `_prose_offences()` is what catches them — so this assertion stays **true** for `_offences`. Keep it, and add a companion assertion that `_prose_offences` *does* catch the same docstring, so both halves are pinned.

- [ ] **Step 6: Run it and capture the failure — this is the deliverable**

```bash
.venv/bin/python -m pytest -o addopts="" \
  src/kriko/tests/test_core_is_domain_free.py::test_the_engine_does_not_explain_itself_in_one_category \
  -v 2>&1 | tee /tmp/prose-offences.txt | tail -40
```

Expected: **FAIL**, listing roughly 23 offences across `lookup/`, `adapters.py`, `research/`, `text/`. Save that full list into your report — Task 5 works from it.

- [ ] **Step 7: Commit the failing gate**

Commit it red, deliberately, so the offence list is in the history rather than only in a scratch file:

```bash
git add src/kriko/tests/test_core_is_domain_free.py
git commit -F - <<'EOF'
test(gates): the domain-free guard now reads the prose too, and it fails

The AST check has always exempted prose, on the reasoning that the
docstrings explain themselves by reference to the car code they replaced.
That was a considered decision and this reverses it: the repository is now
public, and a reader arriving to write a pack for a product Kriko has
never seen cannot run the AST check. They read, and believe what they read
— and what they currently read is gearboxes and mileage explaining every
generic mechanism.

Comments need tokenize rather than ast, which discards them entirely.
Docstrings come from ast.get_docstring, which the existing scanner already
identifies in order to skip them.

Committed failing on purpose: the ~23 offences it lists are the work item,
and belong in the history rather than in a scratch file. ALLOWED_PROSE is
empty here and is populated by the commit that fixes them, so every
surviving example is a decision someone made on purpose.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 5: Decontaminate the engine's prose

**Files:**
- Modify: every file named in Task 4's offence list — expected to include `src/kriko/lookup/__init__.py`, `lookup/match.py`, `lookup/conditions.py`, `lookup/query.py`, `adapters.py`, `research/__init__.py`, `text/title_sim.py`
- Modify: `src/kriko/tests/test_core_is_domain_free.py` (populate `ALLOWED_PROSE`)

**Interfaces:**
- Consumes: `ALLOWED_PROSE` from Task 4.
- Produces: a green `test_the_engine_does_not_explain_itself_in_one_category`.

- [ ] **Step 1: Repair the mangled docstring first**

`src/kriko/lookup/__init__.py:6` currently reads:

> together held 876 lines of car packs.cars.pipeline. Nothing here knows what a car is; the

That is a `sed` rewrite from an earlier rename, mangled and unreviewed, in the docstring of the engine's central module. It is broken text, not a style preference. Read the surrounding docstring, work out what it was trying to say, and write a sentence that is true of the code as it stands now.

- [ ] **Step 2: Rewrite each offending comment and docstring**

The rule: **state the generic mechanism first.** A category example may follow when it genuinely clarifies, and then it goes in `ALLOWED_PROSE`.

Worked example — `lookup/conditions.py:3` currently says:

> One evaluator replaces every gate the old serving path hard-coded: mileage windows, maintenance intervals, and the five car-specific compatibility checks that lived...

The generic statement is: one evaluator handles every condition a pack declares — usage thresholds, time windows, and configuration compatibility — returning met, unmet or unknown. That is what the code does for any category. Write that.

Judgement calls you should make, not ask about:
- `adapters.py`'s "148.000 km" thousand-separator example **earns its place** — it illustrates a real parsing hazard that is hard to convey abstractly. Keep it, frame it as one instance of locale-dependent number formatting, and add `adapters.py` to `ALLOWED_PROSE`.
- `lookup/conditions.py:16`'s "if an ad does not state the mileage" illustrates the unknown-versus-false distinction, which is genuinely clearer with a concrete case. Either generalise it (a listing that omits a usage figure) or allowlist it — your call, but say which you chose and why.

- [ ] **Step 3: Populate `ALLOWED_PROSE` with what you kept**

```python
ALLOWED_PROSE: dict[str, set[str]] = {
    # Locale-dependent number formatting is hard to convey abstractly; the
    # "148.000 km" case is a real hazard this module exists to handle.
    "adapters.py": {"mileage"},
}
```

Each entry needs a comment saying why that example earns its exception. An entry without a reason is how an allowlist becomes a way of silencing the test.

- [ ] **Step 4: Run the gate**

```bash
.venv/bin/python -m pytest -o addopts="" \
  src/kriko/tests/test_core_is_domain_free.py -v
```

Expected: PASS, both the executable check and the prose check.

- [ ] **Step 5: Confirm you changed no code**

```bash
git diff --stat
git diff -U0 | grep -E "^\+" | grep -vE "^\+\+\+" | grep -vE "^\+\s*(#|\"\"\"|'''|$)" | head -20
```

The second command shows added lines that are **not** comments or docstrings. Expected: only the `ALLOWED_PROSE` entries in the test file. Anything else in `src/kriko/` is a behaviour change inside a prose task — revert it.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/python -m pytest -o addopts="" -q | tail -1
```

Expected: **605 passed**, plus the new prose test.

```bash
git add -A
git commit -F - <<'EOF'
docs(engine): the engine stops explaining itself in one category

Twenty-three comments and docstrings in kriko/ explained generic
mechanisms exclusively through cars — "the five car-specific
compatibility checks", "dropping the car entirely served nothing", "every
car-specific thing the old pipeline hard-coded". The code was already
category-free and enforced as such; the prose said the opposite, and prose
is what a new contributor believes.

lookup/__init__.py's opening docstring was worse than car-shaped: it read
"together held 876 lines of car packs.cars.pipeline", a mangled sed
rewrite from an earlier rename sitting in the engine's central module.

Each explanation now states the generic rule first. Three category
examples survive because they genuinely clarify a hazard that is hard to
convey abstractly, and each is named in ALLOWED_PROSE with its reason, so
the exception is a decision rather than an oversight.

Comments and docstrings only — verified no non-prose line changed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 6: Remove the archaeology, repo-wide

**Files:**
- Modify: the ~50 sites found in Step 1, across `src/kriko/`, `src/app/`, `packs/`
- Rewrite or delete: `packs/cars/pipeline/requirements.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable.

- [ ] **Step 1: Find every instance**

```bash
grep -rniE "the old (pipeline|code|serving|path|system)|used to (live|be|hard-code)|before the pivot|legacy" \
  --include='*.py' src packs | grep -v __pycache__ | tee /tmp/archaeology.txt | wc -l
```

Expected: roughly 50. Include test files this time — the phrasing is equally unhelpful there.

- [ ] **Step 2: Decide each one individually**

Three outcomes, and most are the first:

1. **Delete** — the sentence explains nothing without the deleted code. Most fall here.
2. **Rewrite** — the sentence explains a current behaviour but dates it. Say what the code does now.
3. **Keep as one `# History:` line** — the sentence explains a *non-obvious constraint* that only makes sense given what came before. Compress the narrative to the constraint.

The test for keeping: would a reader who has never seen the old code be confused by the current code without this note? If no, delete it.

- [ ] **Step 3: Hold `app/` to the engine's bar, with one exception**

`src/app/` has 12 car references. `src/app/pipeline/` **drives the cars pipeline and imports `packs.cars.pipeline` by design** — naming cars where it genuinely describes that work is correct and stays. What goes is prose that explains a **generic** interface through cars alone. `app/web/routers/` and `app/mcp_server.py` serve any pack and should read that way.

- [ ] **Step 4: Fix `packs/cars/pipeline/requirements.txt`**

It currently instructs the reader to `pip install -r knowledge/requirements.txt` — a path deleted two passes ago — and annotates dependencies with `ops/hub/web.py`, `ops/mcp/server.py`, `knowledge/extract.py`, `forums.py`, `specialists.py`, none of which exist. It is a *functional* file: people run it.

Task 1 moved these dependencies into `pyproject.toml`'s `pipeline` extra. Decide:

- **Delete it**, if `pip install -e ".[pipeline]"` fully replaces it. Then grep for references to the file and update them.
- **Keep it**, if something (CI, a script, a doc) still needs a plain requirements file. Then rewrite every comment against the current tree.

Say which you chose and why in your report. Verify by grepping for `requirements.txt` across the repo before deciding.

- [ ] **Step 5: Confirm no code changed**

```bash
git diff -U0 | grep -E "^\+" | grep -vE "^\+\+\+" \
  | grep -vE "^\+\s*(#|\"\"\"|'''|$)" | head -20
```

Expected: only `requirements.txt` or `pyproject.toml` lines. Anything else is a behaviour change in a prose task.

- [ ] **Step 6: Run the suite and commit**

```bash
.venv/bin/python -m pytest -o addopts="" -q | tail -1
git add -A
git commit -F - <<'EOF'
docs: delete the archaeology

Fifty references to "the old pipeline", "used to live", "before the pivot"
and "legacy" across production code. Each was meaningful to whoever moved
the code and means nothing to a stranger; together they date the tree
rather than explaining it.

Most are deleted outright. A few survive compressed to a single
"# History:" line, kept only where a reader who never saw the old code
would otherwise be confused by the current code.

packs/cars/pipeline/requirements.txt was the worst case because it is
functional rather than decorative: it told the reader to install
knowledge/requirements.txt, deleted two passes ago, and annotated its
dependencies with five modules that no longer exist.

app/pipeline/ keeps its car references — it drives the cars pipeline and
imports packs.cars.pipeline by design. What went is prose that explained a
generic interface through cars alone.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 7: The engine's tests prove generality with a second category

**Files:**
- Modify: `src/kriko/tests/test_ids.py`, `test_adapters.py`, `test_research.py`, `test_packstore.py`, and any other `src/kriko/tests/` file the Step 1 scan names

**Interfaces:**
- Consumes: `packs/drill/`'s vocabulary as the second category.
- Produces: nothing importable.

**Fixtures change; assertions do not.** If a test's *assertion* has to change to accommodate a new fixture, that test was coupled to car semantics and you should **report it rather than edit it** — that is a finding about the engine, not a fixture problem.

- [ ] **Step 1: Find the car fixtures**

```bash
grep -rniE "\b(megane|golf|clio|renault|volkswagen|dsg|tdi|tsi|dci|k9k|ea888|dq200|gearbox|mileage)\b" \
  src/kriko/tests/*.py | grep -v __pycache__
```

Expected: about 14 hits across four files, ten of them in `test_ids.py`.

- [ ] **Step 2: Read what `packs/drill/` actually offers**

```bash
cat packs/drill/pack.toml
head -40 packs/drill/data/subjects.yaml
head -30 packs/drill/vocabulary/terms.yaml
```

The drill pack is the deliberate car-shape falsifier: no engine, no fuel, no displacement, wearing out in charge cycles instead of kilometres. Use its real vocabulary — brand, model line, battery platform, charge cycles — rather than inventing terms.

- [ ] **Step 3: Convert the fixtures, file by file, running each after**

Start with `test_ids.py`, which has the most. Identity hashing is precisely where the "same product" question lives, so it benefits most from a non-car example.

After each file:

```bash
.venv/bin/python -m pytest -o addopts="" src/kriko/tests/test_ids.py -v
```

Expected: PASS with the same assertions. If an assertion needs changing, stop and record why.

- [ ] **Step 4: Use two categories where the test is about crossing between them**

Cross-pack union and identity-collision tests should use **two distinct categories**, not one renamed. A test proving two packs' rows merge correctly is far stronger when the packs describe different kinds of object — that is the actual claim being made.

- [ ] **Step 5: Confirm the engine's tests no longer lean on cars**

```bash
grep -rniE "\b(megane|golf|clio|renault|volkswagen|dsg|tdi|tsi|dci|k9k|ea888|dq200)\b" \
  src/kriko/tests/*.py | grep -v __pycache__
```

Expected: no output, or only occurrences inside a test that is *deliberately* about two categories and says so.

Note `packs/cars/tests/` and `packs/cars/pipeline/tests/` keep their car fixtures — they test the cars pack, where cars are the subject. Do not touch them.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/python -m pytest -o addopts="" -q | tail -1
```

Expected: **605 passed** plus the prose test from Task 4 — no test lost.

```bash
git add -A
git commit -F - <<'EOF'
test(engine): the engine's own tests stop proving generality with cars

kriko/'s suite exists to demonstrate that the engine works for any product
category, and it demonstrated that using Renaults and Volkswagens
exclusively — ten car references in test_ids.py alone. That is an
assertion dressed as a proof: a suite that only ever sees one category
cannot fail when the engine learns that category's shape.

The fixtures move to packs/drill/'s vocabulary, which exists as the
car-shape falsifier: no engine, no fuel, no displacement, wearing out in
charge cycles rather than kilometres. Tests about crossing between packs
now use two genuinely different categories, because that is the claim they
are making.

Fixtures changed; assertions did not.

packs/cars/tests/ keeps its car fixtures — it tests the cars pack, where
cars are the subject.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 7: Push the branch**

```bash
git push
```

The branch already tracks `origin/feat/knowledge-engine-pivot`. Pushing is authorised; merging to `main` is not.
