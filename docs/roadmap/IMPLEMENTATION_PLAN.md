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

### Milestone 5: Vector Store & Codebase RAG Pipeline (Current)
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

### Milestone 6: LLM Orchestration & Code Review Engine
**Goal:** Implement prompt orchestration, automated PR reviews, documentation generation, and architectural suggestions.
- LLM abstraction layer (Anthropic Claude, OpenAI, Google Gemini)
- Automated PR review pipeline (diff analysis, style, security, bug risk scoring)
- Multi-turn conversational repo assistant
- Structured markdown output & GitHub PR review comments publishing

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
