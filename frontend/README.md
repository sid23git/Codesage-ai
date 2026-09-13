# CodeSage AI — Frontend

Next.js (App Router) frontend for CodeSage AI, an AI-powered software
engineering assistant. See `docs/roadmap/IMPLEMENTATION_PLAN.md` (Milestone 7)
and the approved plan at the repo-level `.claude/plans/warm-questing-bachman.md`
for the full architecture rationale.

## Architecture in one paragraph

The browser **never** calls the FastAPI backend directly — it only calls
same-origin `/api/bff/*` Route Handlers. Those Route Handlers are a thin
**backend-for-frontend (BFF)**: they read an httpOnly session cookie,
attach it to the backend request as `Authorization: Bearer <token>`, and
forward everything else unchanged. This means:

- The raw JWT is never readable by client-side JavaScript (mitigates XSS
  token theft).
- FastAPI's CORS configuration is irrelevant to this app — server-to-server
  calls aren't subject to browser CORS at all.
- Local dev uses the exact same BFF flow as production — there is no
  separate "call FastAPI directly" dev path.

## Getting started

```bash
npm install
cp .env.local.example .env.local   # then edit BACKEND_URL if needed
npm run dev
```

The backend must be running (default `http://localhost:8000`) for anything
past the landing page to work.

## Regenerating API types

Frontend TypeScript types are generated from the backend's own OpenAPI
schema — never hand-duplicated. To refresh them after a backend schema
change:

```bash
# with the backend importable from ../backend (no server needed):
cd ../backend && python -c "
import json
from app.main import app
json.dump(app.openapi(), open('../frontend/openapi.json', 'w'), indent=2)
"
cd ../frontend && npm run generate:types
```

(Or, with a running backend: `curl http://localhost:8000/openapi.json -o openapi.json`.)

## Key directories

- `app/(auth)/` — login/register pages (public)
- `app/(app)/` — authenticated pages, wrapped in the app shell (sidebar + top bar)
- `app/api/bff/` — the BFF: `auth/{login,register,logout}` are special-cased
  (they translate the token into a cookie); everything else goes through
  the generic `[...path]` proxy
- `proxy.ts` — route-protection gate (Next 16 renamed `middleware.ts` →
  `proxy.ts`); a **presence-only** cookie check, never JWT validation
- `lib/api/` — typed client, one module per backend router (`auth.ts`,
  `repositories.ts`, `assistant.ts`), plus `types.generated.ts`
  (generated, do not edit) and `types.ts` (thin name aliases)
- `lib/server/` — server-only code (cookie helpers, the FastAPI fetch
  helper) — never imported from client components
- `lib/query/` — TanStack Query client + query-key factories (all server
  state lives here, not in a global store)
- `components/states/` — `LoadingState`/`EmptyState`/`ErrorState`/
  `InsufficientEvidenceNotice`, used across every data-fetching screen

## Deferred (not in scope for M7)

SSE/WebSocket streaming, interactive repository/call-graph visualization,
GitHub PR write-back, Docker/CI-CD, production observability. See the
plan document for why.

## Notes from the M7 Phase 6 hardening pass

A final polish/QA/accessibility/security pass audited the whole app as
one product (no new routes or features). Two items are worth recording
so they aren't rediscovered or "fixed" blindly later:

- **Shiki bundle stays on the full bundle (`import { codeToHtml } from
  "shiki"`), by measured choice, not oversight.** The audit confirmed the
  registry/engine overhead is a single ~280KB chunk, code-split to only
  the routes that render a code block (Ask/Explain/Review/Conversations),
  and that individual language grammars are still lazy-loaded per
  language on first use, not bundled eagerly. Switching to Shiki's
  fine-grained bundle (`shiki/core` + an explicit language loader) or the
  WASM-free JS regex engine would shrink that further, but would (a)
  require rewriting the `vi.mock("shiki", ...)` mocks in every test file
  that renders a code block, and (b) trade tokenization correctness
  (oniguruma vs. the ~95%-compatible JS engine) for a size win on an
  asset that's already deferred and cached after first use. Given the
  existing lazy/scoped behavior, that trade wasn't judged worth making.
- **`CardTitle` (`components/ui/card.tsx`) renders an `<h2>`, not a
  `<div>`.** This was a real gap: every Card section (Repository,
  Ingestion, review findings, etc.) was invisible to screen-reader
  heading navigation. Every page that has its own page-level `<h1>` gets
  a correct `h1 > h2` outline from this; the login/register screens have
  no separate page `<h1>` (the card title doubles as the page's only
  heading), so their outline starts at `h2` -- an accepted minor gap, not
  a skipped level.
- Every `/repositories/[id]/**` page now renders a "Repository not
  found" empty state for a non-numeric `id` in the URL. Previously a
  malformed URL (e.g. `/repositories/abc`) silently disabled every query
  on the page (by design, to avoid a NaN-built API call) and fell
  through every loading/error guard, rendering nothing at all.
