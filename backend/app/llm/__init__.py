"""LLM orchestration subsystem for CodeSage AI.

Provides a provider-agnostic abstraction over chat/completion LLMs
(Anthropic, and later OpenAI/Gemini) used to generate answers grounded in
Milestone 5 RAG retrieval evidence.

Milestone 6 Phase 1 scope (providers):
    - Provider-agnostic LLM interface (BaseLLMProvider, LLMMessage, LLMResponse)
    - Deterministic MockLLMProvider for tests / offline development
    - AnthropicProvider adapter (Claude Sonnet 5 by default)
    - Provider-agnostic exception hierarchy (timeout, rate limit,
      provider/API failure, invalid configuration)

Milestone 6 Phase 2 scope (prompt/context construction):
    - Dependency-free, deterministic token estimation and a generic
      priority-ordered budget-fitting mechanism (context_budget.py)
    - Evidence selection (relevance threshold, dedup, deterministic
      ordering), citation formatting, and bounded prompt assembly
      (prompt_builder.py)
    - The RAG -> LLM orchestration itself lives in
      app.services.orchestration_service, one layer up, so it can also
      depend on RAGService without app.llm depending on the service layer.

Explicitly NOT in scope yet:
    - Conversation/message persistence (Phase 3)
    - API endpoints (Phase 3)
    - Streaming, rate limiting, usage metering, GitHub write-back
"""
