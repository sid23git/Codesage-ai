# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CodeSage AI is an AI-powered software engineering assistant that understands, documents, reviews, and improves GitHub repositories using AI (RAG-grounded LLM calls) and static analysis. It's a monorepo:

- `backend/` — FastAPI + SQLAlchemy (async) + Alembic + PostgreSQL/pgvector.
- `frontend/` — Next.js 16 (App Router), React 19.
- `docs/` — deployment runbook, database notes, product/roadmap docs.
- `render.yaml` — Render Blueprint for production deployment.
- `docker-compose.yml` — local, production-shaped stack (frontend + backend + `pgvector/pgvector:pg16`), distinct from native dev.

Production runs on Render (backend + frontend, both Docker) + Neon (managed Postgres + pgvector). Full runbook: `docs/deployment/README.md`.

## Commands

### Backend (`backend/`)

```bash
# Setup
python -m venv .venv && .venv\Scripts\activate   # Windows; source .venv/bin/activate elsewhere
pip install -e ".[dev]"
cp .env.example .env   # set SECRET_KEY and DB credentials

# Run
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Lint / format / typecheck (exactly what CI runs)
ruff check app tests
ruff format app tests          # CI uses --check
mypy app

# Test (fast path: isolated in-memory SQLite, ~420 tests, no external services)
pytest
pytest tests/test_auth.py                       # one file
pytest tests/test_auth.py::test_register_user   # one test
pytest -k "ingestion"                           # by name substring

# Migrations (env.py sources the DB URL from app settings, never alembic.ini)
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
alembic current
alembic downgrade -1
```

**Postgres-backed test path:** SQLite can't exercise the two Postgres-only retrieval code paths (real pgvector `<=>` cosine distance, real per-term `tsv_content @@ plainto_tsquery(...)` full-text search) — both silently fall back to a SQLite approximation otherwise (see `app/rag/retrieval/vector.py` / `keyword.py`). Set `TEST_DATABASE_URL` to a real Postgres+pgvector DSN before running `pytest` to make `tests/conftest.py`'s `test_engine` fixture run actual `alembic upgrade head` instead of `Base.metadata.create_all`, then run `pytest tests/test_rag_retrieval.py tests/test_retrieval_quality.py -v` to exercise it for real. This is exactly what CI's `backend-postgres` job does.

### Frontend (`frontend/`)

```bash
npm install
cp .env.local.example .env.local   # set BACKEND_URL if not http://localhost:8000
npm run dev
npm run typecheck    # tsc --noEmit
npm run lint         # eslint
npm test             # vitest run (all)
npx vitest run path/to/file.test.tsx        # one file
npx vitest run -t "test name"               # by name
npm run build
```

Regenerate typed API client after any backend schema change (types are generated from FastAPI's OpenAPI schema, never hand-written):

```bash
cd ../backend && python -c "
import json
from app.main import app
json.dump(app.openapi(), open('../frontend/openapi.json', 'w'), indent=2)
"
cd ../frontend && npm run generate:types
```

### Full stack, production-shaped (`docker compose`)

```bash
cp .env.example .env   # set SECRET_KEY and POSTGRES_PASSWORD
docker compose up --build
docker compose exec backend alembic upgrade head   # migrations are never automatic
```

Frontend on `:3000` is the only port meant to be externally reachable; backend `:8000` and db `:5432` are bound to `127.0.0.1` for local debugging only.

## Architecture

### Backend layering

Routes (`app/api/v1/*.py`) are intentionally thin: auth + request/response translation + mapping domain exceptions to HTTP status codes only. All business logic lives in `app/services/*`. No route handler ever calls `httpx` or raw SQL directly — e.g. the GitHub sync flow is strictly `route (repositories.py) → RepositoryService → GitHubClient (httpx) → GitHub REST API`. All v1 routes are mounted twice — at root and under `/api/v1` — so both prefixes work.

### RAG / ingestion pipeline (the core product feature)

1. `POST /repositories/{id}/ingest` → `IngestionService.trigger_ingestion`: downloads a GitHub tarball (`app/ingestion/archive.py`'s `safe_extract_tarball`, guarded against path traversal/zip bombs), scans and filters files (`app/ingestion/scanner.py`, `filter.py`, `languages.py`) against the `INGESTION_MAX_*` limits in `app/core/config.py`. Concurrency is capped process-wide by `INGESTION_MAX_CONCURRENT` via an `asyncio.Semaphore`, since each ingestion holds a full archive in memory.
2. `RAGService.index_repository` (`app/services/rag_service.py`) runs three phases, deliberately separated: **(1)** `chunk_file` (`app/rag/chunking`) routes each file to a language-aware chunker (Python: AST-based; Markdown: heading-based; JS/TS/Go/Rust/Java/C/C++/C#: generic structural blocks; everything else: a line-based fallback) — outside any DB transaction; **(2)** calls the configured embedding provider (`mock` or `openai`, `app/rag/embeddings`) — also outside any transaction; **(3)** persists new `CodeChunk` rows and atomically deletes the previous ingestion's stale chunks in one bounded transaction. Phases 1–2 never hold a DB connection open across network I/O.
3. Retrieval (`app/rag/retrieval/hybrid.py`'s `fuse()`) combines dense semantic search (`VectorRetriever`, pgvector cosine distance) and lexical search (`KeywordRetriever`, Postgres FTS against the `tsv_content` generated column + GIN index) plus, for broad repository questions only, a bounded set of README/architecture-doc/entry-point chunks (`OverviewRetriever`), via deterministic Linear Score Fusion: `S_final = min(1.0, 0.70·S_sem + 0.30·S_lex + symbol_bonus(0.20) + path_bonus(0.10) + overview_bonus(0.15))`. `S_lex` is IDF-weighted coverage of the query's content terms (each term its own `plainto_tsquery`, OR-ed — not one AND-ed query over the whole question). The path bonus is whole-word only and only applies on top of ≥0.05 content evidence; comment-only chunks and ignore-pattern files (`.gitignore`, `.gitkeep`) are never returned as evidence. All query/chunk heuristics live in `app/rag/retrieval/query_analysis.py`. `LLM_MIN_RELEVANCE_SCORE` defaults to 0.11, calibrated for voyage-code-4's compressed score range — re-benchmark before changing it or the embedding model. Real behavior only shows up against Postgres — see the testing note above.
4. `OrchestrationService` (`app/services/orchestration_service.py`) is the single place wiring retrieval → the token-budgeted `PromptBuilder` (`app/llm/prompt_builder.py`) → a `BaseLLMProvider` (`mock` or `anthropic`, `app/llm/providers`). Its three entry points (`ask`, `explain`, `review`, used by `app/api/v1/assistant.py`) share one private `_run()` so retrieval/prompt/LLM-call/error handling never forks three ways. It's deliberately FastAPI-independent (plain args, dataclass return) for direct unit testing. When no retrieved chunk clears `LLM_MIN_RELEVANCE_SCORE`, it returns a defined "insufficient evidence" result instead of letting the LLM answer ungrounded.
5. `ConversationService` only persists a conversation and its messages once a turn actually completes — a failed `/ask` (LLM timeout, no ingestion yet, etc.) never leaves an orphaned, empty conversation behind.

### Settings & database URL resolution (`app/core/config.py`)

A single `pydantic-settings` `Settings` class, read once via `get_settings()` (`lru_cache`). Supply either a full `DATABASE_URL` (must already be `postgresql+asyncpg://...` — validated, will raise otherwise) or individual `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`; `DATABASE_URL` wins if both are present. `SECRET_KEY` is required (rejects a known placeholder value) and `DEBUG=true` is refused whenever `APP_ENV=production`. `alembic/env.py` reads `get_settings().async_database_url` directly — `alembic.ini`'s own `sqlalchemy.url` is never used, so no credential needs to live there.

### Neon-specific connection quirk (production only)

Neon's connection strings use `?sslmode=require` (and sometimes `&channel_binding=require`), which SQLAlchemy's asyncpg dialect rejects outright (`TypeError: connect() got an unexpected keyword argument 'sslmode'`/`'channel_binding'`). Strip the query string and use `?ssl=require` instead (asyncpg will still negotiate TLS if even that's dropped). Use Neon's **pooled** (`-pooler`) endpoint for the app's own `DATABASE_URL` (Render's free tier suspends/resumes services, and pooling handles that reconnect pattern better) but the **direct** (non-pooled) endpoint for `alembic`, `pg_dump`, or anything needing session-level state — see `docs/deployment/README.md`.

### Frontend BFF pattern

The browser never calls FastAPI directly — only same-origin `/api/bff/*` Next.js Route Handlers, which read an httpOnly session cookie and forward it to the backend as `Authorization: Bearer <token>` (see `frontend/README.md`). This keeps the raw JWT unreachable from client-side JS and makes FastAPI's CORS config irrelevant to this app. `proxy.ts` (Next 16 renamed `middleware.ts` → `proxy.ts`) does a **presence-only** cookie check, never JWT validation — real auth happens on the backend. `lib/api/types.generated.ts` is generated from the backend's OpenAPI schema and must never be hand-edited.

`frontend/CLAUDE.md` pulls in `frontend/AGENTS.md`, an auto-generated note (regenerated by `next dev`, keep it committed) that this Next.js version has breaking API/convention changes from older training data — check `node_modules/next/dist/docs/` before assuming older Next.js behavior when touching frontend code.

### Testing strategy (backend)

`tests/conftest.py` defaults every test to an isolated in-memory SQLite engine — no external services. Setting `TEST_DATABASE_URL` switches the `test_engine` fixture to run real `alembic upgrade head` against a live Postgres+pgvector instance instead of `Base.metadata.create_all`, which is required to reproduce the `tsv_content` generated column and HNSW/GIN indexes (they're raw-SQL-only in migration `0004`, not on the SQLAlchemy model at all).

### CI (`.github/workflows/ci.yml`)

Five independent jobs gate every PR/push to `main`: `frontend`, `backend-unit` (SQLite path), `backend-postgres` (real `pgvector/pgvector:pg16`, runs `alembic upgrade head` → `current` → a downgrade/upgrade round-trip → `tests/test_rag_retrieval.py` against the real engine), `security-audit` (`npm audit --audit-level=high` blocks; `pip-audit` is advisory only — it has no severity-floor flag), and `docker-build` (both Dockerfiles, never pushes an image). `alembic check` runs inside `backend-postgres` but is advisory (`continue-on-error`) because of two permanent, deliberate divergences between the live schema and `Base.metadata` — read that job's inline comments before treating new `alembic check` output as a regression.

### Deployment

Render Blueprint (`render.yaml`) provisions `codesage-backend` and `codesage-frontend`, both Docker runtime. The database is a separately-provisioned Neon project, wired in via the `DATABASE_URL` secret env var — never provisioned by the Blueprint itself. Migrations are a deliberate, manual, separate step on Render's free tier (no Pre-Deploy Command available there) — `alembic upgrade head` is run by hand via the Render Shell tab after any deploy that changes the schema. The app's own startup `lifespan` (`app/main.py`) never runs migrations; it only verifies DB connectivity and recovers any repository ingestion left mid-run by a prior restart, logging a warning (not crashing) if the database is unreachable. Full step-by-step runbook, every env var and why, and the rollback procedure: `docs/deployment/README.md`.
