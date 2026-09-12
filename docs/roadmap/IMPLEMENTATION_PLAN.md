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
- **Phase 4+ (Planned)**: code review/explanation endpoints reusing this
  same orchestration foundation; GitHub PR write-back as its own later
  sub-effort.

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
