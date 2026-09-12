# CodeSage AI — Implementation Plan

This document outlines the phased roadmap and technical implementation plan for building CodeSage AI, an AI-powered software engineering assistant that analyzes, reviews, and improves GitHub repositories.

---

## Architecture Overview & Technology Choices

- **Language / Runtime:** Python 3.12+
- **Web Framework:** FastAPI
- **Data Validation & Settings:** Pydantic v2 & `pydantic-settings`
- **Database ORM:** SQLAlchemy 2.0 (asyncio)
- **Database Driver:** `asyncpg` (PostgreSQL)
- **Database Migrations:** Alembic
- **Testing:** `pytest`, `pytest-asyncio`, `httpx`
- **Code Quality & Linting:** `ruff` (formatting and linting), `mypy` (strict static typing)

---

## Milestone Roadmap

### Milestone 1: Backend Foundation (Completed)
**Goal:** Establish a production-grade backend service skeleton with complete configuration, database abstractions, migration tooling, health check endpoint, test infrastructure, and linting/typing standards.

### Milestone 2: User Authentication & Tenant Management (Completed)
**Goal:** Implement user identity, registration, JWT authentication, and organization/workspace management.

### Milestone 3: GitHub Integration & Webhook Handling (Completed)
**Goal:** Connect GitHub App / OAuth for repository synchronization and PR webhook ingestion.

### Milestone 4: Repository Ingestion & Static Analysis Pipeline (Completed)
**Goal:** Parse repository AST, extract symbols, dependency graphs, and code metrics.

---

### Milestone 5: Vector Store & Codebase RAG Pipeline (Completed)
**Goal:** Embed code chunks and symbols into vector storage to enable semantic code search and context retrieval.

#### Architecture Details (Approved):
- **Vector Store**: PostgreSQL + `pgvector`
- **Embedding Dimension**: Fixed at 1536 (OpenAI standard)
- **Code-Aware Chunking**:
  - Python AST parsing for functions and classes.
  - Structural parsing for JS/TS/Go/Rust.
  - Markdown header parsing.
  - Fallback sliding-window line chunking.
- **Retrieval Engine**:
  - Semantic Retrieval (Cosine distance via pgvector)
  - Keyword / Exact Retrieval (PostgreSQL FTS & symbol match)
  - Hybrid Ranker (Deterministic Linear Score Fusion)
- **Database Model**: `code_chunks` table with `embedding vector(1536)` and `tsv_content`
- **Isolation**: Strict repository-level isolation via query filters.

---

### Milestone 6: LLM Orchestration & Code Review Engine (Current)
**Goal:** Implement prompt orchestration, automated PR reviews, documentation generation, and architectural suggestions.
- LLM abstraction layer (Anthropic Claude first; OpenAI/Gemini pluggable later)
- Automated code review / explanation over indexed repository code and
  user-provided code/diffs (GitHub PR comment publishing deferred)
- Multi-turn conversational repo assistant, persisted per user/repository
- Structured, evidence-grounded output — never answers from unsupported
  general knowledge when repository evidence is insufficient

#### Architecture Details (Approved):
- **RAG boundary**: M6 calls `RAGService.search()` exclusively; no direct
  access to `CodeChunk`, pgvector, or retrieval internals. M5 retrieval
  contracts are unchanged.
- **Conversation persistence**: PostgreSQL-backed `Conversation`/`Message`
  models, owned by user and scoped by repository, using soft (non-FK)
  evidence references so history survives repository re-indexing.
- **Context budget**: configurable hard token ceiling
  (`LLM_CONTEXT_TOKEN_BUDGET`) enforced by the prompt builder, plus a
  minimum relevance threshold (`LLM_MIN_RELEVANCE_SCORE`) below which the
  assistant returns a defined insufficient-evidence response instead of
  generating an answer.
- **Streaming, rate limiting/usage metering, and GitHub write-back** are
  explicitly deferred (streaming to M7, cost/observability controls to M8).
- **Call-graph/import-graph ranking** remains out of scope, as decided in M5.

#### Implementation Phases:
- **Phase 1 (Completed): LLM Provider Layer** — provider-agnostic
  `BaseLLMProvider` interface (`app/llm/providers/base.py`), deterministic
  `MockLLMProvider` for tests, `AnthropicProvider` adapter (Claude Sonnet 5
  default) with SDK-exception-to-domain-exception translation, a
  `get_llm_provider()` factory, provider-agnostic `LLMError` hierarchy
  (`app/llm/exceptions.py`), and matching `Settings`/DI wiring
  (`LLM_PROVIDER`, `LLM_MODEL`, `ANTHROPIC_API_KEY`,
  `LLM_REQUEST_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`,
  `LLM_CONTEXT_TOKEN_BUDGET`, `LLM_MAX_HISTORY_MESSAGES`,
  `LLM_MIN_RELEVANCE_SCORE`, `get_llm_provider()` dependency in
  `app/api/deps.py`). No orchestration, prompt construction, persistence,
  or API endpoints yet — those are later phases.
- **Phase 2 (Completed): Prompt/Context Construction + Orchestration** —
  `app/llm/context_budget.py` (dependency-free, deterministic token
  estimation — ~4 chars/token heuristic — plus a generic priority-ordered
  `TokenBudget.fit_greedy()` mechanism); `app/llm/prompt_builder.py`
  (`select_evidence()` — relevance filtering against
  `LLM_MIN_RELEVANCE_SCORE`, dedup by chunk id, deterministic score-desc
  ordering — and `PromptBuilder.build()`, which formats citation-labeled
  evidence blocks, enforces `LLM_CONTEXT_TOKEN_BUDGET` as a hard ceiling,
  truncates history to `LLM_MAX_HISTORY_MESSAGES` and drops it oldest-first
  under budget pressure, and raises `InsufficientEvidenceError` /
  `LLMContextError` for the two "cannot proceed" conditions);
  `app/services/orchestration_service.py::OrchestrationService.ask()` —
  calls `RAGService.search()` as a black box (hybrid mode, no direct
  `CodeChunk`/pgvector access), builds a bounded prompt via
  `PromptBuilder`, calls `BaseLLMProvider.complete()`, and normalizes the
  result into a plain `AssistantAnswer` dataclass
  (`status: "answered" | "insufficient_evidence"`, `answer`, `evidence`,
  `model`, `ingestion_id`, `input_tokens`, `output_tokens`). No completed
  ingestion → `RepositoryNotIndexedError`; insufficient evidence → an
  `AssistantAnswer` with `status="insufficient_evidence"` and the LLM is
  never called; provider timeout/rate-limit/failure/configuration errors
  propagate as Phase 1's own `LLMError` subclasses, unmodified. Still no
  conversation persistence or API endpoints — the service accepts an
  optional in-memory `history: list[LLMMessage]` parameter so persistence
  can be added in Phase 3 without redesigning this flow.
- **Phase 3 (Completed): Conversation Persistence + Assistant API** —
  `Conversation`/`Message` models (`app/models/conversation.py`,
  migration `0005`), user-owned and repository-scoped, with `Message`
  storing a **soft (non-FK) JSON evidence snapshot**
  (`chunk_id`, `file_path`, `start_line`/`end_line`, `language`, `name`,
  `score`, a bounded text `snippet`) so historical citations remain
  readable after a repository is re-indexed and its `code_chunks` rows
  are replaced. `ConversationService` owns creation, ownership/scope
  verification, chronological history loading (capped at
  `LLM_MAX_HISTORY_MESSAGES`), and `record_turn()` — the single place
  that persists a turn, in one short bounded transaction, appending both
  messages to the conversation so a brand-new conversation and its first
  two messages are only ever written together, atomically, once the LLM
  call has actually succeeded (a failed turn — timeout, rate limit, no
  ingestion, oversized context — leaves nothing persisted, not even an
  empty conversation shell). New endpoints in `app/api/v1/assistant.py`:
  `POST /repositories/{id}/ask` (creates or continues a conversation,
  returns `answer`/`evidence`/`model`/token usage/`conversation_id`;
  insufficient-evidence is a normal 200 response, still persisted, never
  an unsupported answer), `GET /repositories/{id}/conversations` (list,
  most-recently-active first), `GET
  /repositories/{id}/conversations/{conversation_id}` (full chronological
  history). Every endpoint verifies repository ownership first, then
  (where applicable) that the conversation belongs to both the
  authenticated user and the requested repository. No DB transaction is
  held open across the RAG/embedding/LLM calls — an explicit commit
  closes out any transaction opened by the pre-flight reads before
  `OrchestrationService.ask()` runs, mirroring the pattern already
  established in `rag_service.py`/`ingestion_service.py`.
- **Phase 4 (Completed): Code Explanation + Code Review** — extends the
  Phase 2/3 foundation with two new task types, sharing all retrieval,
  budgeting, and orchestration logic; nothing in M5 or the Phase 1/2
  provider abstraction changed.
  - **Shared prompting** (`app/llm/prompt_templates.py`): the one place
    that owns task-specific system instructions (ask/explain/review, each
    distinct but sharing the same hallucination-control rules) and
    per-request question/query builders. No provider-specific code lives
    here. `PromptBuilder` gained two small, backward-compatible
    extensions to support this: a `system_instructions` constructor
    parameter (defaults to the original ask instructions) and a
    `require_evidence` flag on `build()` (defaults to `True`, preserving
    ask/explain's existing strict behavior).
  - **`OrchestrationService`** gained a shared private `_run()` helper
    used by `ask()` (unchanged signature/behavior), new `explain()`, and
    new `review()` — no duplicated RAG/prompt/LLM-calling logic across
    task types.
  - **`POST /repositories/{id}/explain`**: targets a `file_path` (+
    optional `start_line`/`end_line`/`symbol`/`question`), scopes
    retrieval to that file via `CodeSearchRequest.file_paths`, and
    requires qualifying evidence exactly like `/ask` — an unfound
    target returns the same defined insufficient-evidence result, never
    a fabricated explanation.
  - **`POST /repositories/{id}/review`**: targets repository code
    (`file_path`/`symbol`/line range) and/or up to 20,000 characters of
    user-provided code/diff (untrusted input, clearly labeled as such in
    the prompt and never treated as if already indexed), for a
    `focus` of general/bugs/security/maintainability/performance/style.
    When reviewing user-provided code, repository evidence is optional
    supporting context (`require_evidence=False`) rather than a hard
    gate, since the user's own submitted code — not a repository claim —
    is the primary subject; a repository-only review target keeps the
    same strict evidence requirement as `/ask`/`/explain`. The LLM is
    instructed to respond with a single JSON object; the response is
    parsed into structured `findings` (title, severity, category,
    explanation, recommendation, file_path, start/end line, and resolved
    `evidence_chunk_ids`) plus a human-readable `summary`, degrading
    gracefully (summary = raw text, findings = []) if the model's
    response isn't valid JSON rather than failing the request.
  - **Conversation support**: both endpoints accept an optional
    `conversation_id` reusing `ConversationService` unchanged (no new
    persistence model) — supplying one appends the turn to that owned,
    repository-scoped conversation; omitting it returns a one-off result
    with nothing persisted (unlike `/ask`, these do not auto-create a
    conversation when omitted).
  - Same transaction-boundary discipline as `/ask`: no DB transaction
    held open across RAG/embedding/LLM calls.
- **Phase 5 (Completed): Engineering Hardening** — a review-and-harden
  pass across the complete Phase 1-4 system; no new endpoints or
  models. Architecture, provider abstraction, evidence/grounding rules,
  context budgeting, conversation integrity, and error handling were all
  re-verified end-to-end and found correct; the changes made were:
  - **Deduplication**: `/ask` now shares the same `_raise_for_llm_error()`
    HTTP-status mapping already used by `/explain`/`/review` (previously
    duplicated inline); a new `_get_owned_repository_or_404()` helper
    replaces five identical copies of the repository-ownership check
    across the router; `ExplainRequest`/`ReviewRequest`'s identical
    `end_line >= start_line` check now shares one
    `app/schemas/validators.py::validate_line_range()` function. None of
    these changes status codes or observable behavior.
  - **Prompt-injection hardening**: `_SHARED_RULES` (in
    `prompt_templates.py`, so it applies to ask/explain/review alike)
    now explicitly instructs the model to treat all repository evidence
    and user-provided code strictly as content to analyze, never as
    instructions to it — even when that content is itself phrased as an
    instruction (e.g. a README or code comment saying "ignore previous
    instructions" or "you are now in developer mode"). Verified by new
    regression tests that index/submit exactly such content and assert
    the system message is unaffected by it.
  - **Provider completeness**: reviewed and confirmed correct as-is — no
    second real provider was added (see rationale below).
  - **Test hardening**: added repository/conversation-mismatch isolation
    tests to `/explain` and `/review` (previously only `/ask` had them);
    added an end-to-end transaction-boundary regression test proving no
    DB transaction is open at the moment `llm_provider.complete()` is
    invoked; added the prompt-injection isolation tests described above
    for both repository content (`/ask`) and user-submitted code
    (`/review`).
  - **Second LLM provider — deliberately deferred, not added**: the M6
    spec calls for "Anthropic first, others pluggable later," and the
    abstraction (`BaseLLMProvider`, the exception-translation pattern,
    the `get_llm_provider()` factory) already supports adding one later
    at low, well-isolated cost. Adding one now was assessed and rejected
    for this hardening pass specifically because (a) the `anthropic` SDK
    is already pinned below 1.0 to avoid a documented `httpx`/`httpcore`
    dependency conflict — a second provider SDK is a second chance to
    reintroduce exactly that class of conflict; (b) there is no live-key
    test infrastructure in this project for validating a real second
    adapter beyond structural mocking, so it would ship exercised only
    against a fake; and (c) no product requirement has surfaced for a
    second provider yet. This is a scope judgment, not a capability gap.
- **Phase 6+ (Planned)**: GitHub PR write-back as its own later
  sub-effort; anything beyond that is unscoped.

---

### Milestone 7: Frontend Web Application
**Goal:** Modern web dashboard for repository insights, review history, interactive chat, and workspace settings.
- Next.js / React frontend
- Clean dark-mode UI with Tailwind CSS and glassmorphism styling
- Real-time SSE/WebSocket stream for analysis and chat
- Interactive repository graph and diff viewer

---

### Milestone 8: Deployment, CI/CD & Observability
**Goal:** Production containerization, deployment pipelines, Prometheus/OpenTelemetry metrics, and error tracking.
- Dockerfile and Docker Compose configurations
- GitHub Actions CI/CD workflows
- OpenTelemetry tracing and structured logging
- Production readiness and load testing
