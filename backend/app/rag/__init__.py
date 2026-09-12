"""RAG (Retrieval-Augmented Generation) subsystem for CodeSage AI.

Provides code-aware chunking, embedding generation, vector storage,
and hybrid retrieval for repository search.

Milestone 5 scope:
    - Semantic retrieval (pgvector cosine distance)
    - Keyword / exact symbol retrieval (PostgreSQL FTS)
    - Hybrid ranking via deterministic Linear Score Fusion
    - Repository and ingestion-level isolation

Explicitly NOT in scope for Milestone 5:
    - LLM answer generation / chat
    - Code call-graph or import-graph construction
    - Graph-based ranking
"""
