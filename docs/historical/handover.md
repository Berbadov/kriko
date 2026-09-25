> TL;DR (archived 2026-09-25): Handover snapshot of the pre-Lego Kriko (extension + FastAPI,
knowledge/serving planes via YAML). Serving plane (scraper, API, matcher, resolver) and knowledge
plane (discover, process, judge gates, verify_agent, review_tool) functional; Megane 4 at
18 verified / 7 review / 2 held / 93 rejected. Run commands and resume priorities below.

# Kriko Project Handover Specification

> **HISTORICAL — predates the part-centric "Lego" system.** Kept for context only;
> the described pipeline (verify_agent/review_tool flow) is not how Kriko works today.
> Current entry points: `README.md`, `docs/USAGE.md`, `backlog.md`.

State of Kriko: what works, what was built, how to resume.

---

## 1. Project Overview

Chrome Extension + FastAPI backend surfacing variant- and mileage-specific used-car reliability risks on **Sahibinden.com**, *before* the standard pre-purchase inspection.

---

## 2. System Architecture

Two isolated planes handing off via version-controlled YAML:

```
KNOWLEDGE PLANE (offline, LLM): discover.py → process.py → verify_agent.py →
  review_tool.py → backend/data/claims/*.yaml
SERVING PLANE (Docker, <10ms, $0 LLM): sync.py → PostgreSQL → FastAPI /analyze
  → Chrome extension overlay on Sahibinden
```

(Full ASCII diagram — see git history.)

---

## 3. What is Complete & Functional

### A. The Serving Plane (FastAPI + Extension)

Metadata scraper (`extension_ui/content.js`, TR→EN attributes); API server (`backend/api/main.py`, context-aware claim resolution); variant matcher (`backend/core/matcher.py`); contextual resolver (`backend/core/resolver.py`, mileage/age/maintenance-interval plumbing implemented).

### B. The Knowledge Plane (Offline Pipeline)

Interactive source curation (`knowledge/discover.py`); extraction + Jaccard dedup (`knowledge/process.py`, `qwen-2.5-72b`); LLM-as-judge gates (`knowledge/judge.py`: variant, support, generic); Exa auto-verification (`knowledge/verify_agent.py`); interactive vetting CLI (`knowledge/review_tool.py`).

---

## 4. Current Dataset Status (Renault Megane 4)

Post-verification-agent: **18 Verified** (served as *Confirmed*) / **7 Review** / **2 Held** / **93 Rejected** (tombstoned noise).

---

## 5. How to Run & Start the Project

### Start Serving Plane (Docker)

```bash
docker compose -f deploy/docker-compose.yml up -d
curl http://127.0.0.1:8000/health
```

### Install Knowledge Plane Dependencies

```bash
uv pip install -r knowledge/requirements.txt
export OPENROUTER_API_KEY="sk-or-v1-..." MISTRAL_API_KEY="..." EXA_API_KEY="..."
```

### Run Automated Ingestion & Verification

```bash
python3 -m knowledge.discover "megane 4 arıza" --make renault --model megane --gen 4
python3 -m knowledge.process renault megane 4
python3 -m knowledge.verify_agent renault megane 4
```

### Manually Crate Claims (Interactive CLI)

```bash
python3 knowledge/review_tool.py --status review
```

---

## 6. Next Steps for Resuming Development

1. **Mileage/maintenance UI badges** — surface resolver's `due`/`due_stated` states in extension cards.
2. **Second model (scaling)** — `backend/data/variants/toyota_corolla_e210.yaml`, then `python3 -m knowledge.auto toyota corolla e210`.
3. **Caching** — Redis/in-memory FastAPI caching to cut PostgreSQL load.
