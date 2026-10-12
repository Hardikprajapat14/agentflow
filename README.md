# AgentFlow - Autonomous AI Workforce & Workflow Automation Platform

Describe a business task in plain English. AgentFlow **plans** it, **selects tools**, **executes** them, **validates**
the results, asks for **human approval** before sensitive actions, and produces a grounded **report** - while you watch
every step (status, timestamps, duration, input, output, errors) in real time.

```
Natural Language -> Planning -> Tool Selection -> Execution -> Validation -> Human Approval -> Final Result
```

**100% free to run**: Groq free-tier LLM, local ONNX embeddings (no API), PostgreSQL + pgvector, Redis, DuckDuckGo search
(no key). The only credential you need is a free Groq API key.

## Quick start (Docker, ~5 minutes)

```bash
cp .env.example .env
# 1. Create a free key (no credit card): https://console.groq.com/keys  -> paste into LLM_API_KEY
# 2. Set JWT_SECRET:  python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up --build
```

Open **http://localhost:3000** (API docs: http://localhost:8000/api/docs). Then:

1. Register an account.
2. **Documents** -> upload `sample_data/sales_data.csv` and `sample_data/company_sales_policy.pdf` (optionally `sample_customers.csv`).
3. **New Workflow** -> use Example 1 -> *Run workflow*.
4. Watch the timeline. At *Report Generation* the workflow pauses for **approval** -> Approve -> read/download the report (PDF/Markdown).

The sample data has planted facts you can verify: West drops ~27% and South ~15% in the latest month, and Central has a
spike in March 2026 (flagged by the Isolation Forest). The policy says >10% drops trigger a review and >25% are critical.

## Architecture

```
React (Vite/TS/Tailwind/Recharts) --nginx--> FastAPI --enqueue--> Redis --> Celery worker
                                               |                               |
                                               +------- PostgreSQL + pgvector -+
```

| Stage | Component | What it does |
|---|---|---|
| Planning | `agents/planner.py` | LLM (JSON mode) -> validated `Plan` (pydantic); unknown tools dropped, sensitive tools forced to need approval, one self-repair retry |
| Tool selection + args | `agents/executor.py` | Native **LLM function calling** (forced `tool_choice`) generates arguments from the objective + dataset schemas; falls back to auto-detected defaults if the LLM is unavailable |
| Tools | `tools/builtin.py` | `read_document`, `analyze_data` (pandas), `ml_analysis` (IsolationForest + trend forecast), `create_chart`, `rag_search` (pgvector), `web_search`, `send_email` (approval-gated) |
| Validation | `agents/validator.py` | Deterministic output checks per step + LLM **fact-check** of the report against tool evidence (auto-rewrite once if claims are unsupported) |
| Human-in-the-loop | executor + `routers/workflows.py` | Execution pauses (`awaiting_approval`), state persisted; approve -> worker resumes from the next pending step; reject -> workflow stops |
| Report | `services/report.py`, `services/pdf.py` | Markdown + PDF (ReportLab, with charts). If the LLM is down, a deterministic report is produced instead |
| RAG | `rag/` | Paragraph-aware chunking, local embeddings (fastembed `bge-small-en-v1.5`, 384-d), pgvector HNSW cosine search, per-user isolation |
| Monitoring | `usePolling` hook | UI polls the workflow every 1.5 s while it is active; audit log tab shows every event |

Every workflow always contains: **AI Planning -> (planned tool steps) -> Result Validation -> Report Generation**.

### Resilience
- LLM 429/5xx: retry with backoff, then automatic fallback to `LLM_FALLBACK_MODEL`.
- A failed non-critical step (e.g. web search offline) is recorded and the workflow continues; the report states the limitation.
- Worker crash: interrupted `running` steps are reset and resumed. Redis down: clear 503 error.
- Missing API key / SMTP / unreadable file: actionable error messages shown in the step.

### Security
bcrypt (SHA-256 pre-hash, no 72-byte truncation), JWT, per-user data isolation on every query, upload allow-list +
size limit + sanitized names, auth rate limiting, security headers, production guard against the default `JWT_SECRET`,
sensitive tools always gated by approval.

## API (all under `/api`, Bearer JWT except auth)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register`, `/auth/login`, `/auth/logout` | Authentication |
| GET | `/auth/me` | Current user |
| POST/GET/DELETE | `/documents`, `/documents/{id}` | Upload (async indexing), list, delete |
| POST/GET | `/workflows` | Create+run, list |
| GET/DELETE | `/workflows/{id}` | Detail with steps, approvals, result |
| GET | `/workflows/{id}/audit` | Audit trail |
| GET | `/workflows/{id}/report.pdf` / `.md` | Download report |
| GET | `/approvals?status=pending` | Pending approvals |
| POST | `/approvals/{id}/resolve` | `{ "approve": true, "note": "..." }` |
| GET | `/health` | DB / Redis / LLM-config status |

## Local development (without Docker for the app)

```bash
# infra only
docker compose up db redis -d

# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env            # set LLM_API_KEY, JWT_SECRET; UPLOAD_DIR=./data/uploads REPORT_DIR=./data/reports
alembic upgrade head
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app.celery_app worker -l INFO      # second terminal
# (no Redis? set CELERY_EAGER=true and skip the worker - runs jobs in a thread, dev only)

# frontend
cd frontend && npm install && npm run dev                        # http://localhost:5173
```

## Tests

```bash
cd backend && alembic upgrade head && pytest -q
```
20 tests: security, chunking/embeddings, column detection, ML (checks the planted anomalies are found), validator,
LLM client (retries, fallback model, function calling, JSON repair), and **end-to-end API flows against real Postgres +
pgvector** (auth, isolation, upload validation, plan -> execute -> approval -> PDF report, rejection, LLM outage).
The LLM provider is replaced by a test double in tests only; everything else is real. CI (`.github/workflows/ci.yml`)
runs backend tests, the frontend build and the Docker build.

## Configuration notes

- **Different free LLM**: change `LLM_BASE_URL` / `LLM_MODEL` (OpenRouter free models, Gemini OpenAI-compat endpoint, or fully
  offline Ollama - examples in `.env.example`). Needs a model that supports JSON mode and tool calling.
- **Groq free limits**: the free tier is rate limited (per-minute tokens). AgentFlow keeps prompts small and falls back to
  the 8B model; a full workflow uses roughly 5-8 LLM calls.
- **Embeddings**: `EMBEDDING_BACKEND=hashing` is a lightweight lexical fallback (used in tests). Changing the embedding
  dimension requires changing `EMBEDDING_DIM` *before* running migrations.
- **Email tool**: set `SMTP_*`; it only runs after you approve it. Ask e.g. "...and email the findings to a@b.com".
- Plotly (listed in the brief) is not used: charts are Recharts in the UI and ReportLab in the PDF - no extra weight.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Workflow fails at planning: "LLM_API_KEY is not configured" | Put your Groq key in `.env`, `docker compose up -d --force-recreate backend worker` |
| "Rate limited after retries" | Wait a minute, or set `LLM_MODEL=llama-3.1-8b-instant` |
| Document stuck in *processing* | `docker compose logs worker` (first run may download the embedding model) |
| 503 when starting a workflow | Redis/worker not running: `docker compose ps` |

## Project layout

```
backend/app/{agents,tools,rag,ml,services,routers,models,schemas,workers,security,utils}  alembic/  tests/
frontend/src/{pages,components,layouts,hooks,services,types,utils}
sample_data/   docker-compose.yml   .env.example   .github/workflows/ci.yml
```
