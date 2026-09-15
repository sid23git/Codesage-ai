# Production Deployment

**Platforms:** [Render](https://render.com) (backend + frontend, both from the M8 Phase 1 Dockerfiles) + [Neon](https://neon.tech) (managed PostgreSQL + pgvector).

This is a runbook, not automation — M8 Phase 3 could not provision real cloud accounts on your behalf (see the note at the end of this doc), so every step below is something you do by hand, once, in each platform's dashboard. Nothing here requires a paid plan; both platforms' free tiers are sufficient for a portfolio deployment.

**No secret value is ever written to this file or to `render.yaml`.** Every secret below is entered directly into Render's dashboard.

---

## 1. Database — Neon (managed PostgreSQL + pgvector)

1. Sign up at [neon.tech](https://neon.tech) (GitHub OAuth is the fastest path).
2. Create a new project. Pick a region close to wherever you deploy Render's services (e.g. if Render is in Oregon, pick Neon's closest US-West region) — same-region keeps latency low.
3. Neon gives you a connection string immediately, of the form:
   ```
   postgresql://<user>:<password>@<host>/<dbname>?sslmode=require
   ```
   **Use the *pooled* connection string** (Neon's dashboard has a toggle for "Pooled connection" vs "Direct connection") — Render's free tier can spin services down and restart them on incoming traffic, and a pooled endpoint handles that reconnection pattern far better than a direct one.
4. **Convert it to this app's required format.** Two changes, both required:
   - The driver scheme must be `postgresql+asyncpg://`, not the bare `postgresql://` Neon gives you.
   - `?sslmode=require` is `libpq`/psycopg syntax, not what SQLAlchemy's asyncpg dialect expects. Replace it with `?ssl=require`. (If that specific value doesn't connect, asyncpg will usually still negotiate TLS automatically against Neon with the query parameter dropped entirely — try that as a fallback and note whichever actually worked for you here.)

   Result:
   ```
   postgresql+asyncpg://<user>:<password>@<host>/<dbname>?ssl=require
   ```
   This full string is what you'll paste into Render as `DATABASE_URL` in step 2 below.
5. **pgvector is enabled automatically** — migration `0004` (`CREATE EXTENSION IF NOT EXISTS vector;`) runs this the first time `alembic upgrade head` executes against this database (step 4). Neon's default role can create this extension without needing superuser. Verify after migrating:
   ```sql
   SELECT * FROM pg_extension WHERE extname = 'vector';
   ```
6. **No public exposure beyond what Neon requires.** Neon databases are internet-reachable by design (there's no VPC to place a Render service inside otherwise) but require the password in the connection string and enforce TLS (`ssl=require`) — there is no way to reduce this further without Neon's paid private-networking tier, which is unnecessary here. Never put this connection string anywhere but Render's secret env var field.

---

## 2. Backend — Render

### Option A: Blueprint (recommended, fastest)

1. Render dashboard → **New** → **Blueprint** → connect this GitHub repo. Render reads `render.yaml` at the repo root and proposes both `codesage-backend` and `codesage-frontend` as Docker-runtime web services.
2. Render prompts you, once, for every `sync: false` value in the blueprint. Fill in:

   | Variable | Value |
   |---|---|
   | `SECRET_KEY` | Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. A **real, unique** secret — never reuse the local-dev or CI values from earlier phases. |
   | `DATABASE_URL` | The converted Neon connection string from step 1.4 above. |
   | `GITHUB_TOKEN` | See §7 below — create this first if you want real ingestion to work beyond GitHub's 60 req/h unauthenticated limit. |
   | `OPENAI_API_KEY` | Leave blank to keep `EMBEDDING_PROVIDER=mock` (see §8). Fill in only if you're providing a real key. |
   | `ANTHROPIC_API_KEY` | Leave blank to keep `LLM_PROVIDER=mock` (see §8). Fill in only if you're providing a real key. |

3. Deploy. Render builds `backend/Dockerfile`, then `frontend/Dockerfile`.
4. Once the backend service exists, confirm its actual public URL in Render's dashboard (top of the service page). It should match `https://codesage-backend.onrender.com` (Render assigns this deterministically from the `name:` field) — if it doesn't (e.g. the name was taken and Render suffixed it), update `codesage-frontend`'s `BACKEND_URL` env var to match, then redeploy the frontend service.

### Option B: Manual (fallback, if the Blueprint path ever breaks)

Create two **Web Services** by hand, each: **New → Web Service → connect this repo → Runtime: Docker**.

| | Backend | Frontend |
|---|---|---|
| Dockerfile path | `backend/Dockerfile` | `frontend/Dockerfile` |
| Docker build context | `backend` | `frontend` |
| Health check path | `/health` | *(leave default)* |
| Env vars | same table as `render.yaml`'s `codesage-backend` service | same table as `codesage-frontend`, with `BACKEND_URL` set to the backend service's actual URL |

> **Confirmed failure mode if "Docker build context" is left at the repo root:** the build reaches `backend/Dockerfile` (Render finds it fine via "Dockerfile path"), but every `COPY` instruction that references a backend-relative file — `pyproject.toml`, `app`, `alembic`, `alembic.ini` — fails with `"<file>": not found`, because none of those paths exist at the repo root; they only exist under `backend/`. This was reproduced locally byte-for-byte (`docker buildx build -f backend/Dockerfile .` fails with `"/pyproject.toml": not found`; the identical build with context `./backend` succeeds cleanly). If you hit this, the fix is **not** a Dockerfile change — go to the service's **Settings → Build & Deploy** and correct **Docker Build Context Directory** to `backend` (leaving **Dockerfile Path** as `backend/Dockerfile`). Same logic applies to the frontend service with `frontend`.

### Every backend environment variable, and why

| Variable | Value | Secret? |
|---|---|---|
| `APP_NAME` | `codesage-api` | No |
| `APP_ENV` | `production` | No — Phase 0's startup validator refuses `DEBUG=true` combined with this |
| `DEBUG` | `false` | No — **never** `true` in production (exposes `/docs`, echoes SQL, opens CORS) |
| `LOG_LEVEL` | `INFO` | No |
| `LOG_FORMAT` | `json` | No — structured logs for Render's log viewer |
| `SECRET_KEY` | *(generated, 32+ chars)* | **Yes** |
| `DATABASE_URL` | *(Neon pooled DSN, converted)* | **Yes** |
| `DB_STATEMENT_CACHE_SIZE` | `0` | No — required for Neon's pooled endpoint (see §1.3) |
| `REGISTRATION_ENABLED` | `true`, then `false` after you've made your own account | No |
| `RATE_LIMIT_ENABLED` | `true` | No |
| `RATE_LIMIT_AUTH` / `RATE_LIMIT_ASSISTANT` / `RATE_LIMIT_INGEST` | `10/minute` / `20/minute` / `5/minute` | No |
| `GITHUB_TOKEN` | *(fine-grained PAT, see §7)* | **Yes** |
| `EMBEDDING_PROVIDER` | `mock` or `openai` | No |
| `OPENAI_API_KEY` | *(only if `EMBEDDING_PROVIDER=openai`)* | **Yes** |
| `LLM_PROVIDER` | `mock` or `anthropic` | No |
| `LLM_MODEL` | `claude-sonnet-5` | No |
| `ANTHROPIC_API_KEY` | *(only if `LLM_PROVIDER=anthropic`)* | **Yes** |

**The backend never exposes any of this to the frontend or the browser.** The frontend's only knowledge of the backend is `BACKEND_URL` (a public HTTPS URL, not a secret) — no backend env var is ever read by, or forwarded into, the frontend container. See §5 for exactly why that boundary holds.

---

## 3. Migrations — the explicit release step

Render's **Pre-Deploy Command** (a command that runs automatically before each deploy goes live) is the ideal mechanism for this — but it's a **paid-plan feature**, not available on the free tier this deployment uses. So, on the free tier, run it by hand after each deploy that changes the schema:

1. Render dashboard → `codesage-backend` service → **Shell** tab.
2. Run:
   ```bash
   alembic upgrade head
   alembic current
   ```
3. Confirm the output ends on `0005 (head)`.

This intentionally mirrors Phase 0/1: the application's own startup `lifespan` **never** runs migrations itself — it only verifies connectivity and recovers any ingestion interrupted by a restart (§10). Migrations are always a deliberate, separate action, here identical in spirit to `docker compose exec backend alembic upgrade head` from local development.

*(If you later move the backend to a paid Render plan, switch to the Pre-Deploy Command — set it to `alembic upgrade head` in the service's Settings, and this manual step is no longer needed.)*

---

## 4. Frontend — Render

Covered by §2's Blueprint/manual setup above. The frontend has no secrets of its own — `BACKEND_URL`, `SESSION_COOKIE_NAME`, and `SESSION_COOKIE_MAX_AGE_SECONDS` are all plain configuration, not credentials.

---

## 5. HTTPS, cookies, and the browser/JWT boundary

Render terminates TLS for every service automatically (`*.onrender.com` gets a certificate with zero configuration) — both `codesage-backend` and `codesage-frontend` are HTTPS-only from the outside by default.

Because the deployed frontend runs with `NODE_ENV=production`, `lib/server/session.ts`'s cookie gets `Secure: true` automatically (it's conditioned on exactly that env var — see the M7 BFF implementation) — combined with the `HttpOnly` and `SameSite=Lax` flags that are unconditional. **Verify this directly** once deployed:

```bash
curl -sI https://codesage-frontend.onrender.com/api/bff/auth/login \
  -X POST -H "Content-Type: application/json" -d '{"email":"...","password":"..."}' \
  | grep -i set-cookie
```
Expect: `Secure; HttpOnly; SameSite=Lax` all present, and the response body containing no `access_token` field anywhere — the raw JWT never leaves the backend/frontend-server boundary; the browser only ever holds the opaque, httpOnly cookie. `proxy.ts` gates every protected page behind that cookie's mere presence, and the BFF's `/api/bff/*` routes are the *only* thing the browser's own JavaScript ever calls — confirmed in the M7 architecture and unchanged by this deployment.

Also verify: `/docs` and `/redoc` on the backend return 404 (they're conditioned on `DEBUG`, which is `false`), and that CORS stays closed — `curl -I https://codesage-backend.onrender.com/health -H "Origin: https://evil.example"` should carry no `Access-Control-Allow-Origin` header at all.

---

## 6. GitHub token

Create a **fine-grained personal access token** (GitHub → Settings → Developer settings → Fine-grained tokens):

- **Repository access:** "Public Repositories (read-only)" — this app only ever ingests public repositories a user supplies a URL for; it never needs write access or access to private repos.
- **Permissions:** none beyond the default read access that scope implies (no need to grant any of the optional read/write permission toggles — the app only calls GitHub's public REST metadata/tarball endpoints).
- Paste the resulting token into Render's `GITHUB_TOKEN` secret field. This raises the app's GitHub API rate limit from 60 req/h (unauthenticated) to 5,000 req/h.

---

## 7. LLM / embedding providers

**Deploy and verify with mock providers first** (`LLM_PROVIDER=mock`, `EMBEDDING_PROVIDER=mock` — `render.yaml`'s defaults). The entire application — register, ingest, Ask, Explain, Review, conversation history — is fully functional this way, with deterministic mock responses, zero cost, and zero external dependency on Anthropic/OpenAI being reachable.

**If real credentials become available:** set `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY`, and/or `EMBEDDING_PROVIDER=openai` + `OPENAI_API_KEY`, redeploy, and re-run the Ask/Explain/Review portion of the smoke test in §9 against the real providers.

**If real credentials are not available:** ship with mock providers and say so plainly — do not simulate or fabricate what a real-provider response would look like. The mock path is a fully legitimate, intentional part of this architecture (documented since M6), not a workaround.

---

## 8. Live smoke test (run this after every deploy that touches auth, ingestion, or the assistant endpoints)

Against the real deployed frontend URL:

1. Register → land on dashboard.
2. Connect a small public GitHub repository.
3. Trigger ingestion → confirm the request returns promptly (see §10) and the UI polls status until `completed`.
4. Ask a question → Explain a file → Review a snippet — confirm each returns a real response (mock-provider text if using mocks, per §8).
5. Open conversation history → resume a conversation.
6. Log out → confirm the session cookie is cleared and protected routes redirect to `/login`.

Also specifically check:
- **Insufficient evidence:** ask something the ingested repo has no real content to answer — expect the dedicated "not enough evidence" UI state, not a fabricated answer.
- **401:** load a protected page with an expired/absent session — expect a clean redirect to `/login?reason=expired`, not a crash.
- **404:** open a repository/conversation ID that isn't yours or doesn't exist — expect a clean "not found" state.
- **Retryable errors:** if you can trigger one (e.g. temporarily set an invalid `GITHUB_TOKEN`), confirm the retry-eligible `ErrorState` UI appears rather than a raw error.
- **Ownership isolation:** register a second account, confirm it cannot see or reach the first account's repositories/conversations (404, not 403 — matches the anti-enumeration design already in place).

---

## 9. Ingestion: background processing + failure recovery

M8 Phase 0 changed ingestion's *concurrency* handling (a process-wide semaphore capping simultaneous ingestions) and added a *startup recovery sweep* — it did **not** move `POST /ingest` off the request/response path (that was explicitly scoped out during Phase 0 as too large a change; see that phase's own report). So:

- `POST /ingest` **returns once the pipeline finishes** (download → scan → embed → persist), not immediately — for small-to-medium repositories this is typically seconds, for larger ones it can take up to the low tens of seconds.
- The frontend's ingestion status polling (`useLatestIngestion`, exponential backoff 2s→15s) is real and does work correctly — it's just that, on a single request, the *initiating* browser tab mostly sees the terminal state directly in that same response; the polling matters more for a *second* tab/session watching the same repository mid-ingestion, or for picking up the result if the initiating request's connection drops before the response arrives.
- **Stale-ingestion recovery** (added in Phase 0): if the backend process is killed mid-ingestion (a redeploy landing while one is in flight, an OOM, a platform restart), the row is left at `status="ingesting"` with no automatic path back — until the *next* process startup, whose `lifespan` runs `IngestionService.sweep_stale_ingestions()`, marking it `failed` with `"Ingestion was interrupted by a service restart. Please retry."` and flipping the owning repository back to `failed` (never leaving it stuck at `analyzing` forever). This was verified directly against a real Postgres container during Phase 1 (kill mid-ingestion → restart → confirm the sweep).

**To verify this on the real deployment**, either:
- **Safely, without an actual interruption:** confirm the behavior by code inspection + the existing automated test (`TestStaleIngestionSweep` in `backend/tests/test_ingestion_service.py`, already passing in CI) — this is the honest, low-risk option for a shared production environment.
- **With an actual interruption, if you're comfortable doing this on a real (but disposable/test) deployment:** start an ingestion on a large-ish repository, then use Render's dashboard to manually restart the backend service mid-ingestion. After it comes back up, confirm (a) the repository's ingestion history shows a `failed` row with the exact message above, and (b) the UI offers a normal retry path, not a stuck "analyzing forever" state. Only do this against a deployment you're prepared to have briefly disrupted.

---

## 10. CI/CD integration

`.github/workflows/ci.yml` (M8 Phase 2) already runs on every push to `main` and every pull request — frontend, backend-unit, backend-postgres, security-audit, and docker-build, all required to be green. Render's Blueprint deploy is triggered independently, by Render's own GitHub integration watching `main` (configurable per-service in Render's dashboard under **Settings → Auto-Deploy**) — it is **not** wired through GitHub Actions, and this phase does not add tag-based GHCR release automation (explicitly out of scope). In practice: merging to `main` with CI green is what should precede a Render auto-deploy; Render deploying a commit CI hasn't validated is a footgun worth avoiding by keeping branch protection on `main` requiring the CI checks.

---

## 11. Rollback / redeploy

- **Rollback:** Render dashboard → the service → **Events**/**Deploys** tab → pick a prior successful deploy → **Rollback to this deploy**. This redeploys that exact prior image; it does **not** touch the database. If the commit you're rolling back past included a migration, you may need to manually `alembic downgrade <revision>` via the Shell tab first — check `alembic history` before assuming a rollback is purely code-level.
- **Redeploy (same commit):** Render dashboard → **Manual Deploy** → **Deploy latest commit** (or a specific prior commit).
- **Config-only change** (an env var, without a code change): editing an env var in Render's dashboard triggers a redeploy of that service automatically.

---

## 12. Production URLs

*(Fill in once deployed — do not commit real secret values anywhere near these.)*

- Frontend: `https://codesage-frontend.onrender.com` *(or your actual assigned URL)*
- Backend: `https://codesage-backend.onrender.com` *(or your actual assigned URL — verify it matches what the frontend's `BACKEND_URL` points at)*
- Database: Neon project dashboard (no public URL to record — access is via the connection string only, held as a Render secret)

---

## Why this is a runbook and not automation

M8 Phase 3 could not create Render, Neon, or GitHub-token credentials on your behalf — those require an account, and in Render/Neon's case OAuth consent, that only you can grant. This document plus `render.yaml` is everything short of that account-linking step; once the services exist and the env vars above are set, the rest of this doc (migrations, smoke test, rollback) is directly actionable by anyone with dashboard access, including a future session of this assistant once given the resulting URLs to verify against.
