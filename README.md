# CodeSage AI

An AI-powered software engineering assistant that understands, documents, reviews, and improves GitHub repositories using AI and static analysis.

🚧 Currently under active development.

## Running locally

There are two ways to run the stack, for two different purposes:

| | Backend | Frontend | Database | Use it for |
|---|---|---|---|---|
| **Native dev** | `uvicorn app.main:app --reload` ([backend/README.md](backend/README.md)) | `npm run dev` ([frontend/README.md](frontend/README.md)) | your own local/Docker Postgres | day-to-day development (hot reload, fast iteration) |
| **Containerized, production-parity** | `docker compose up` (this section) | same | `pgvector/pgvector:pg16` container | verifying the app behaves the way a real deployment will, before M8's actual deployment phase |

The containerized stack is **not** a deployment — there's no CI/CD, managed database, or hosting involved (that's later in M8). It runs the exact same Dockerfiles and `APP_ENV=production` configuration a real deployment would, entirely on your machine, so "does this actually work in production shape" can be answered locally.

### Quick start

```bash
cp .env.example .env
# edit .env: set SECRET_KEY and POSTGRES_PASSWORD (see the comments in .env.example)

docker compose up --build
```

This starts three services on a private Docker network (`codesage-net`):

```
Browser
  │  (only port reachable from outside the network)
  ▼
frontend  :3000   Next.js, standalone build, output: "standalone"
  │  BFF (/api/bff/*) — the only path from browser code to the backend
  ▼
backend   :8000   FastAPI, 2 Uvicorn workers, APP_ENV=production
  ▼
db        :5432   pgvector/pgvector:pg16, persistent named volume
```

The browser only ever talks to `frontend:3000`. `backend:8000` and `db:5432` are bound to `127.0.0.1` on the host (not `0.0.0.0`) purely so you can `curl http://localhost:8000/health` or connect a local `psql`/GUI client while developing — a real deployment would not expose either of those the way this local stack does.

Once the containers are healthy, apply migrations (never run automatically — see below):

```bash
docker compose exec backend alembic upgrade head
```

Then open <http://localhost:3000>, register an account, and connect a repository. `LLM_PROVIDER` and `EMBEDDING_PROVIDER` default to `mock` — the full stack works end-to-end (ingestion, Ask/Explain/Review) with zero API keys and zero cost. Set `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` and the matching `LLM_PROVIDER`/`EMBEDDING_PROVIDER` in `.env` to exercise a real provider instead.

### Required environment variables (`.env`, from `.env.example`)

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | Yes | JWT signing key, 32+ chars. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. A throwaway value is fine locally. |
| `POSTGRES_PASSWORD` | Yes | Password the `db` container creates its role with, and what `backend` connects with. |
| `POSTGRES_DB` / `POSTGRES_USER` | No | Default to `codesage`/`codesage`. |
| `GITHUB_TOKEN` | No | Only needed if you hit GitHub's 60 req/h unauthenticated limit. |
| `EMBEDDING_PROVIDER` / `OPENAI_API_KEY` | No | Default `mock`; set to `openai` + a real key to test real embeddings. |
| `LLM_PROVIDER` / `ANTHROPIC_API_KEY` | No | Default `mock`; set to `anthropic` + a real key to test real answers. |

`docker-compose.yml` itself carries every other setting (`APP_ENV=production`, `DEBUG=false`, `LOG_FORMAT=json`, rate limiting on, etc.) — only secrets and optional provider choices live in `.env`.

> **Note on `${VAR}` substitution:** Docker Compose resolves `${GITHUB_TOKEN}`/`${OPENAI_API_KEY}`/`${ANTHROPIC_API_KEY}` from your **shell's actual environment first**, falling back to `.env` only if a variable isn't exported at all. If your shell already has one of these set for an unrelated reason, it will flow into the container even though you never put it in `.env` — harmless while `LLM_PROVIDER`/`EMBEDDING_PROVIDER` stay `mock` (the key is simply never used), but worth knowing. Run `docker compose config` to see exactly what each service will actually receive.

### Migrations

Migrations are **never** run automatically — `app/main.py`'s startup lifespan only verifies database connectivity and recovers any ingestion interrupted by a prior restart, it does not touch the schema. Apply/inspect migrations explicitly:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```

### Ports exposed on the host

| Port | Service | Reachable from | Purpose |
|---|---|---|---|
| `3000` | frontend | anywhere (all interfaces) | the app itself |
| `127.0.0.1:8000` | backend | localhost only | curl `/health`, run `alembic`, local API testing |
| `127.0.0.1:5432` | db | localhost only | connect a local `psql`/GUI client |

### Persistent data

Database files live in the named Docker volume `db_data` (declared in `docker-compose.yml`), independent of container lifecycle — `docker compose down` keeps it; `docker compose down -v` deletes it. Nothing else in the stack is stateful (the frontend and backend containers hold no data of their own).

### Rebuilding after a code change

`docker compose up --build` rebuilds any service whose Dockerfile or build context changed. During active backend/frontend development, the native (non-Docker) workflows in `backend/README.md`/`frontend/README.md` are faster (hot reload); reach for the containerized stack specifically to verify production-shaped behavior.

## Continuous integration

Every pull request and every push to `main` runs `.github/workflows/ci.yml` — five independent jobs, all in parallel (no job waits on another), so one slow job never blocks the rest:

| Job | What it proves | Blocks merge? |
|---|---|---|
| **frontend** | `npm run typecheck` / `lint` / `test` / `build` — the same commands documented in [frontend/README.md](frontend/README.md) | Yes |
| **backend-unit** | `ruff check` / `ruff format --check` / `mypy` / `pytest` against the fast SQLite path (~420 tests) — the same commands documented in [backend/README.md](backend/README.md) | Yes |
| **backend-postgres** | Migrations and the RAG retrieval layer against a *real* `pgvector/pgvector:pg16` service container — see below | Yes (except the two informational `alembic check` steps — see below) |
| **security-audit** | `npm audit --audit-level=high` (frontend) and `pip-audit` (backend) | `npm audit` yes; `pip-audit` is advisory (see below) |
| **docker-build** | Both M8 Phase 1 Dockerfiles still build (`docker/build-push-action`, `push: false` — nothing is ever published here) | Yes |

**What must pass before merging:** frontend, backend-unit, backend-postgres (its two `alembic check` steps aside), `npm audit`, and docker-build all being green. `pip-audit`'s findings and `alembic check`'s output are visible in every run but don't gate the merge — see the specific reasons below.

### PostgreSQL/pgvector integration testing

The `backend-postgres` job runs against a fresh `pgvector/pgvector:pg16` service container (the same image the Phase 1 `docker-compose.yml` uses) with ephemeral, CI-only credentials — never a real secret. It:

1. Sets `TEST_DATABASE_URL` (and fails the job immediately, with an explicit `::error::`, if that variable is ever unset — this pipeline never silently continues without a real database).
2. Runs `alembic upgrade head` against the empty database, `alembic current` to confirm it landed on `head`, then `alembic downgrade -1` → `alembic upgrade head` to prove the round trip is real and non-destructive.
3. Runs `pytest tests/test_rag_retrieval.py` — the one test file that calls `VectorRetriever`/`KeywordRetriever` directly (not through the HTTP layer), genuinely exercising the real `<=>` pgvector operator and the real `tsv_content @@ plainto_tsquery(...)` full-text search, not the SQLite approximation those retrievers fall back to otherwise. Its last test asserts the session is actually bound to a `postgresql` engine — a regression that silently routed this job back onto SQLite would fail loudly here, not pass quietly.

`tests/test_rag_api.py` is deliberately **not** run in this job: its `TestClient`-based tests hit a documented, pre-existing test-harness limitation against real `asyncpg` (`TestClient`'s background-thread event loop vs. `asyncpg`'s loop-affine connections — a `RuntimeError: ... attached to a different loop`, found and root-caused during M8 Phase 1, and confirmed via a live HTTP smoke test *not* to occur in the real running app, which has exactly one event loop and no thread portal). It's a test-infrastructure gap, not an application bug — fixing it properly means moving those tests to `httpx.AsyncClient`+`ASGITransport`, a good candidate for later work, not something this phase forces through.

**Why `alembic check` doesn't gate the job:** it diffs the live database against what the SQLAlchemy models actually declare (`Base.metadata`), and this schema has two *permanent, deliberate* divergences from that: `code_chunks.tsv_content` and its HNSW/GIN indexes are intentionally unmapped on the `CodeChunk` model (raw-SQL-only, added directly in migration `0004` — see that model's own docstring), and several models' descriptive `comment=` kwargs were never propagated into the migrations as real `COMMENT ON COLUMN` DDL. Neither is a bug in any given PR's migration changes, and "fixing" `alembic check` would mean either remapping `tsv_content` (undoing a deliberate M5 design decision) or rewriting historical migrations purely for cosmetic DDL — exactly the kind of change-migrations-to-force-a-green-result this project avoids. The step still runs and its output stays visible on every PR, so a genuinely *new* divergence beyond this known baseline is still there for a human to notice.

**Why `pip-audit` doesn't gate the job:** unlike `npm audit --audit-level=high`, `pip-audit` has no built-in severity floor as of this writing — it reports every known advisory for every installed package with no way to filter to high-severity-only. Failing the job on it would risk blocking merges on low-severity or dev-tooling-only advisories with no real bearing on this service. It still runs, and its findings are visible in the job log.

### Dependency vulnerability scanning

`npm audit --audit-level=high` (frontend) genuinely gates CI. `pip-audit` (backend) runs advisory-only, for the reason above. Both are dependency-vulnerability scanners specifically — they say nothing about *secrets* accidentally committed to the repo. For that, **enable GitHub's built-in secret scanning** in this repository's Settings → Code security — it's a repo-settings toggle, not something expressible in a workflow file, and this project doesn't (and shouldn't) build a custom secrets-management system in its place.

### CI security posture

- Zero GitHub repository secrets are referenced anywhere in `ci.yml` — every backend job's `SECRET_KEY` is a hardcoded, non-secret CI-only value, and the Postgres job's database credentials are ephemeral, generated fresh by the service container on every run.
- Triggered via `pull_request` (never `pull_request_target`), so a fork PR's `GITHUB_TOKEN` is read-only by default and never gets write access or secret exposure just by opening a PR.
- Top-level `permissions: contents: read` — no job needs to write to the repo, publish a package, or comment on anything.
- No image is ever pushed anywhere by this workflow (`docker-build`'s `push: false`) — that, along with any real deployment, is a later phase.
