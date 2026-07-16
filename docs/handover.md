# Kriko Project Handover Specification

> **HISTORICAL — predates the part-centric "Lego" system.** Kept for context only;
> the described pipeline (verify_agent/review_tool flow) is not how Kriko works today.
> Current entry points: `README.md`, `docs/USAGE.md`, `backlog.md`.

This document summarizes the exact state of Kriko, what works, what has been built, and how to resume development in the future.

---

## 1. Project Overview

Kriko is a Chrome Extension + FastAPI backend designed to surface variant- and mileage-specific used car reliability risks on **Sahibinden.com**, warning buyers about issues *before* they book a standard pre-purchase inspection.

---

## 2. System Architecture

Kriko operates on two isolated planes that hand off data via version-controlled YAML files:

```
┌─────────────────────────────────────────────────────────────────┐
│  KNOWLEDGE PLANE  (Offline, developer-run, LLM-powered)        │
│                                                                 │
│  1. discover.py      → Search YouTube transcripts & web pages   │
│  2. process.py       → Extract candidates via Mistral & Qwen    │
│  3. verify_agent.py  → Automated Exa search corroboration       │
│  4. review_tool.py   → Interactive CLI console for vetting      │
│                            │                                    │
│                            ▼                                    │
│                backend/data/claims/*.yaml                       │
└────────────────────────────┬────────────────────────────────────┘
                             │  sync.py (via Docker exec)
┌────────────────────────────▼────────────────────────────────────┐
│  SERVING PLANE  (Runtime, Docker, <10ms latency, $0 LLM cost)   │
│                                                                 │
│  PostgreSQL ← sync.py                                           │
│       │                                                         │
│  FastAPI /analyze  → matches listing context → returns JSON      │
│       ▲                                                         │
│  Chrome extension (renders overlay cards on Sahibinden)         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. What is Complete & Functional

We have built a fully functional end-to-end framework:

### A. The Serving Plane (FastAPI + Extension)
* **Metadata Scraper** (`extension_ui/content.js`): Scrapes classified attributes (make, model, year, transmission, fuel, displacement) and translates Turkish values to English.
* **API Server** (`backend/api/main.py`): Receives listings, matches them to engine variants, applies context-aware filters, and resolves claims.
* **Variant Matcher** (`backend/core/matcher.py`): Canonicalizes search inputs and matches them to configurations.
* **Contextual Resolver** (`backend/core/resolver.py`): Supports mileage-gating, age-gating, and maintenance-interval checks (plumbing is fully implemented).

### B. The Knowledge Plane (Offline Pipeline)
* **Interactive Source Curation** (`knowledge/discover.py`): A terminal UI to search, preview transcripts, and queue URLs/videos for ingestion.
* **Extraction & Dedup Pipeline** (`knowledge/process.py`): Extracts Candidate Claims using `qwen-2.5-72b` and deduplicates them using Jaccard word overlap.
* **LLM-as-a-Judge Gates** (`knowledge/judge.py`): Includes strict checks for variant matching, support validation, and filtering out generic issues.
* **Automated Verification Agent** (`knowledge/verify_agent.py`): Uses the Exa API to search for corroborating posts, runs LLM gates on new pages, and auto-promotes claims.
* **Interactive CLI Vetting** (`knowledge/review_tool.py`): A CLI to review, edit, and approve/reject claims.

---

## 4. Current Dataset Status (Renault Megane 4)

After running the **Offline Verification Agent**, the Renault Megane 4 dataset stands at:
* **Verified Claims** (served to users as *Confirmed*): **18**
* **Review Claims** (queued for review): **7**
* **Held Claims** (low corroboration): **2**
* **Rejected Claims** (tombstoned noise): **93**

---

## 5. How to Run & Start the Project

### Start Serving Plane (Docker)
```bash
# Start Postgres & FastAPI
docker compose -f deploy/docker-compose.yml up -d

# Check API health
curl http://127.0.0.1:8000/health
```

### Install Knowledge Plane Dependencies
```bash
uv pip install -r knowledge/requirements.txt
export OPENROUTER_API_KEY="sk-or-v1-..."
export MISTRAL_API_KEY="..."
export EXA_API_KEY="..."
```

### Run Automated Ingestion & Verification
```bash
# 1. Discover and stage new sources
python3 -m knowledge.discover "megane 4 arıza" --make renault --model megane --gen 4

# 2. Process and extract candidates
python3 -m knowledge.process renault megane 4

# 3. Auto-verify staged claims via web search
python3 -m knowledge.verify_agent renault megane 4
```

### Manually Crate Claims (Interactive CLI)
```bash
python3 knowledge/review_tool.py --status review
```

---

## 6. Next Steps for Resuming Development

If you decide to pick this project up later, here is the order of priority:
1. **Implement UI badges for Mileage and Maintenance**:
   * Integrate the resolved strength states (`due` and `due_stated` from `resolver.py`) into the Chrome Extension's UI cards.
2. **Onboard a Second Model (Scaling)**:
   * Create `backend/data/variants/toyota_corolla_e210.yaml`.
   * Run `python3 -m knowledge.auto toyota corolla e210` to test the automated web search and extraction pipeline end-to-end on a new car model.
3. **Enhance In-Memory/Database Caching**:
   * Add Redis or in-memory caching to FastAPI endpoints to reduce PostgreSQL load under traffic.
