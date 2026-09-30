"""Retrieval-quality regression tests.

Each case here reproduces a behaviour observed in the production retrieval
benchmark against the FashionRAG repository (voyage-code-4 embeddings):

- path-bonus false positives from substring matching ("and" inside
  ``query_expander.py``, "me" inside ``README.md``, "index" inside
  ``indexing/``) and from bare filename coincidences with no content signal;
- comment-only / ignore-pattern chunks surfacing as evidence;
- keyword retrieval returning nothing for natural-language questions because
  ``plainto_tsquery(<whole question>)`` AND-ed every word;
- broad repository questions ("Explain the architecture of this
  repository.") never reaching the README / entry point.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.code_chunk import CodeChunk
from app.models.ingestion import RepositoryIngestion
from app.models.repository import Repository
from app.models.user import User
from app.rag.embeddings.mock import MockEmbeddingProvider
from app.rag.retrieval.hybrid import _compute_score, fuse
from app.rag.retrieval.keyword import KeywordRetriever, idf_weight, weighted_coverage
from app.rag.retrieval.overview import OverviewRetriever
from app.rag.retrieval.query_analysis import (
    is_broad_repository_question,
    is_comment_only,
    is_non_evidence_chunk,
    is_overview_chunk,
    lexical_terms,
    path_match_terms,
    path_matches_query,
)
from app.schemas.rag import CodeSearchRequest
from app.services.rag_service import RAGService

_postgres_only = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="Requires real PostgreSQL FTS (set TEST_DATABASE_URL).",
)


def _chunk(
    chunk_id: int,
    file_path: str,
    *,
    name: str | None = None,
    text_: str = "def placeholder():\n    return compute_value()\n",
    start_line: int = 1,
) -> CodeChunk:
    return CodeChunk(
        id=chunk_id,
        repository_id=1,
        ingestion_id=1,
        file_path=file_path,
        name=name,
        chunk_type="function" if name else "block",
        start_line=start_line,
        end_line=start_line + 5,
        content_hash=f"h{chunk_id}",
        chunk_text=text_,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Path bonus
# ─────────────────────────────────────────────────────────────────────────────


class TestPathBonusWholeWordMatching:
    """Exact false-positive cases from the production benchmark."""

    @pytest.mark.parametrize(
        ("query", "file_path"),
        [
            # "and" was a substring of "expander"
            (
                "How are images discovered and indexed?",
                "src/retrieval/query_expander.py",
            ),
            # "me" was a substring of "readme"
            ("Give me an overview of this repository.", "README.md"),
            # "an" was a substring of "reranker"
            ("Give me an overview of this repository.", "src/retrieval/reranker.py"),
            # "index" is not the whole word "indexing"
            ("How is the FAISS index built?", "src/indexing/__init__.py"),
            # "a" / "is" / "the" are stopwords, never path matches
            ("What is a model?", "data/metadata/val_pairs.csv"),
            # a file extension in the query must not boost every .py file
            ("What does main.py do?", "src/retrieval/search.py"),
        ],
    )
    def test_no_substring_or_stopword_path_match(
        self, query: str, file_path: str
    ) -> None:
        assert path_matches_query(file_path, query) is False

    @pytest.mark.parametrize(
        ("query", "file_path"),
        [
            ("How is the FAISS index built?", "src/indexing/build_index.py"),
            ("What does main.py do?", "main.py"),
            ("How does the reranker score results?", "src/retrieval/reranker.py"),
            ("How are images encoded?", "src/indexing/image_encoder.py"),
            ("Where is the TextRetriever?", "src/retrieval/TextRetriever.java"),
        ],
    )
    def test_whole_word_path_match(self, query: str, file_path: str) -> None:
        assert path_matches_query(file_path, query) is True

    def test_path_match_terms_drop_stopwords_extensions_and_single_chars(
        self,
    ) -> None:
        terms = path_match_terms("Give me an overview of the a main.py file")
        assert terms == {"overview", "main"}

    def test_pure_path_match_without_content_evidence_gets_no_bonus(self) -> None:
        # Production case: _discover_images / __init__.py reached 0.100 from
        # the path bonus alone with ~zero semantic similarity.
        chunk = _chunk(1, "src/indexing/build_index.py", name="_discover_images")
        score, sources = _compute_score(
            sem_score=0.0,
            lex_score=0.0,
            query_lower="how is the faiss index built?",
            chunk=chunk,
        )
        assert score == 0.0
        assert sources == []

    def test_path_bonus_cannot_lift_noise_over_the_evidence_gate(self) -> None:
        gate = Settings.model_fields["LLM_MIN_RELEVANCE_SCORE"].default
        chunk = _chunk(1, "src/indexing/build_index.py", name="_discover_images")
        # Just below the 0.05 content floor: bonus withheld.
        score, _ = _compute_score(
            sem_score=0.07,
            lex_score=0.0,
            query_lower="how is the faiss index built?",
            chunk=chunk,
        )
        assert score == pytest.approx(0.049)
        assert score < gate

    def test_path_bonus_amplifies_existing_content_evidence(self) -> None:
        chunk = _chunk(1, "src/indexing/build_index.py", name="build_index")
        score, _ = _compute_score(
            sem_score=0.30,
            lex_score=0.0,
            query_lower="how is the faiss index built?",
            chunk=chunk,
        )
        assert score == pytest.approx(0.70 * 0.30 + 0.10)


class TestNonEvidenceChunks:
    def test_comment_only_init_is_dropped_even_when_its_directory_matches(
        self,
    ) -> None:
        # Production case: src/retrieval/__init__.py ("# Retrieval module
        # initialization") scored 0.150 for "How does image retrieval work?".
        init_chunk = _chunk(
            1,
            "src/retrieval/__init__.py",
            text_="# Retrieval module initialization\n",
        )
        real = _chunk(2, "src/retrieval/search.py", name="perform_search")
        results = fuse(
            sem_results=[
                {"chunk": init_chunk, "sem_score": 0.071},
                {"chunk": real, "sem_score": 0.33},
            ],
            lex_results=[{"chunk": init_chunk, "lex_score": 0.6}],
            query="How does image retrieval work?",
            top_k=10,
        )
        assert [r.chunk_id for r in results] == [2]

    def test_gitkeep_and_gitignore_are_not_evidence(self) -> None:
        gitkeep = _chunk(1, "data/raw_images/.gitkeep", text_="# Keep directory\n")
        gitignore = _chunk(
            2, ".gitignore", text_="# install dependencies\n*.log\nbuild/\n"
        )
        readme = _chunk(
            3,
            "README.md",
            name="Installation",
            text_="## Installation\nInstall dependencies with pip.",
        )
        results = fuse(
            sem_results=[],
            lex_results=[
                {"chunk": gitkeep, "lex_score": 1.0},
                {"chunk": gitignore, "lex_score": 1.0},
                {"chunk": readme, "lex_score": 1.0},
            ],
            query="What are the project's dependencies?",
            top_k=10,
        )
        assert [r.chunk_id for r in results] == [3]

    def test_query_naming_the_file_keeps_it(self) -> None:
        assert not is_non_evidence_chunk(
            "*.log\nbuild/\n", ".gitignore", "What does the .gitignore exclude?"
        )

    def test_markdown_headings_are_not_comments(self) -> None:
        assert not is_comment_only("# Title\n## Section", "README.md")
        assert is_comment_only("# Keep directory", "indexes/.gitkeep")
        assert is_comment_only("// just a note\n/* and another */", "src/a.ts")
        assert not is_comment_only("# comment\nx = 1", "src/a.py")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Keyword retrieval for natural-language questions
# ─────────────────────────────────────────────────────────────────────────────


class TestLexicalTerms:
    def test_question_scaffolding_is_removed(self) -> None:
        assert lexical_terms("How does image retrieval work?") == [
            "image",
            "retrieval",
        ]
        assert lexical_terms("What are the project's dependencies?") == ["dependencies"]
        assert lexical_terms("Explain the architecture of this repository.") == [
            "architecture"
        ]

    def test_identifiers_and_paths_are_kept_whole(self) -> None:
        assert lexical_terms("verify_token") == ["verify_token"]
        assert lexical_terms("Where is app/core/security.py used?") == [
            "app/core/security.py"
        ]
        assert lexical_terms("What does main.py do?") == ["main.py"]

    def test_all_stopword_query_has_no_terms(self) -> None:
        assert lexical_terms("How does this work?") == []

    def test_idf_prefers_rare_terms(self) -> None:
        assert idf_weight(1, 46) > idf_weight(10, 46) > idf_weight(46, 46) > 0

    def test_weighted_coverage(self) -> None:
        assert weighted_coverage([True, True], [1.0, 3.0]) == 1.0
        assert weighted_coverage([False, True], [1.0, 3.0]) == 0.75
        assert weighted_coverage([], []) == 0.0


async def _seed(
    db: AsyncSession, owner: User, chunks: list[dict[str, object]]
) -> tuple[int, int]:
    repo = Repository(
        owner_id=owner.id,
        name="quality-repo",
        full_name="testuser/quality-repo",
        github_url="https://github.com/testuser/quality-repo",
        status="ready",
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    ingestion = RepositoryIngestion(repository_id=repo.id, status="completed")
    db.add(ingestion)
    await db.commit()
    await db.refresh(ingestion)

    provider = MockEmbeddingProvider()
    for i, spec in enumerate(chunks):
        body = str(spec["text"])
        db.add(
            CodeChunk(
                repository_id=repo.id,
                ingestion_id=ingestion.id,
                file_path=str(spec["path"]),
                language=spec.get("language", "Python"),  # type: ignore[arg-type]
                chunk_type=str(spec.get("type", "function")),
                name=spec.get("name"),  # type: ignore[arg-type]
                start_line=int(spec.get("start", 1)),  # type: ignore[call-overload]
                end_line=int(spec.get("start", 1)) + 10,  # type: ignore[call-overload]
                content_hash=f"q{i}",
                chunk_text=body,
                embedding=(await provider.embed_texts([body]))[0],
            )
        )
    await db.commit()
    return repo.id, ingestion.id


_FASHION_CHUNKS: list[dict[str, object]] = [
    {
        "path": "src/retrieval/text_retriever.py",
        "name": "TextRetriever",
        "type": "class",
        "text": (
            "class TextRetriever:\n"
            '    """Retrieves fashion images from a FAISS index using text '
            'queries."""\n'
        ),
    },
    {
        "path": "src/indexing/image_encoder.py",
        "name": "ImageEncoder",
        "type": "class",
        "text": (
            "class ImageEncoder:\n"
            '    """Encodes fashion images into normalized CLIP embeddings."""\n'
        ),
    },
    {
        "path": "src/utils/logger.py",
        "name": "setup_logger",
        "text": "def setup_logger(name):\n    return logging.getLogger(name)\n",
    },
    {
        "path": "src/auth/tokens.py",
        "name": "verify_token",
        "text": "def verify_token(token):\n    return decode(token)\n",
    },
    {
        "path": "src/auth/signatures.py",
        "name": "verify_signature",
        "text": "def verify_signature(payload):\n    return check(payload)\n",
    },
]


class TestKeywordRetrieverNaturalLanguage:
    """SQLite fast path: same term extraction, weights and coverage."""

    @pytest.mark.asyncio
    async def test_natural_language_question_matches_on_any_content_term(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo_id, ing_id = await _seed(db_session, test_user, _FASHION_CHUNKS)
        results = await KeywordRetriever().search(
            db=db_session,
            query="How does image retrieval work?",
            repository_id=repo_id,
            ingestion_id=ing_id,
            top_k=10,
        )
        by_name = {r["chunk"].name: r["lex_score"] for r in results}
        # The old whole-question match found nothing here: no chunk contains
        # "work". Both chunks below match the content term "image(s)".
        assert "TextRetriever" in by_name
        assert "ImageEncoder" in by_name
        assert "setup_logger" not in by_name
        assert all(0.0 < s <= 1.0 for s in by_name.values())

    @pytest.mark.asyncio
    async def test_exact_symbol_query_ranks_first_with_full_score(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo_id, ing_id = await _seed(db_session, test_user, _FASHION_CHUNKS)
        results = await KeywordRetriever().search(
            db=db_session,
            query="verify_token",
            repository_id=repo_id,
            ingestion_id=ing_id,
            top_k=10,
        )
        assert results[0]["chunk"].name == "verify_token"
        assert results[0]["lex_score"] == 1.0
        # A multi-part identifier is matched whole, not word-by-word.
        assert "verify_signature" not in {r["chunk"].name for r in results}

    @pytest.mark.asyncio
    async def test_absent_vocabulary_keeps_leftover_generic_match_weak(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        # Benchmark negative control: "How are Stripe payment refunds
        # processed?" matched only the generic "processed" and scored full
        # lexical coverage. Terms absent from the repository must still count.
        repo_id, ing_id = await _seed(db_session, test_user, _FASHION_CHUNKS)
        gate = Settings.model_fields["LLM_MIN_RELEVANCE_SCORE"].default
        results = await KeywordRetriever().search(
            db=db_session,
            query="Which stripe refunds need a token?",
            repository_id=repo_id,
            ingestion_id=ing_id,
            top_k=10,
        )
        assert results
        # Lexical evidence alone (weight 0.30) cannot clear the evidence gate.
        assert all(0.30 * r["lex_score"] < gate for r in results)

    @pytest.mark.asyncio
    async def test_stopword_only_query_returns_nothing(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo_id, ing_id = await _seed(db_session, test_user, _FASHION_CHUNKS)
        results = await KeywordRetriever().search(
            db=db_session,
            query="How does this work?",
            repository_id=repo_id,
            ingestion_id=ing_id,
            top_k=10,
        )
        assert results == []


@_postgres_only
class TestKeywordRetrieverPostgres:
    """Real PostgreSQL FTS: old whole-question AND vs new per-term OR."""

    @pytest.mark.asyncio
    async def test_old_plainto_tsquery_misses_what_new_strategy_finds(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo_id, ing_id = await _seed(db_session, test_user, _FASHION_CHUNKS)
        question = "How does image retrieval work?"

        old_hits = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM code_chunks WHERE ingestion_id = :i "
                    "AND tsv_content @@ plainto_tsquery('english', :q)"
                ),
                {"i": ing_id, "q": question},
            )
        ).scalar_one()
        assert old_hits == 0  # 'work' appears nowhere -> AND fails everywhere

        results = await KeywordRetriever().search(
            db=db_session,
            query=question,
            repository_id=repo_id,
            ingestion_id=ing_id,
            top_k=10,
        )
        names = [r["chunk"].name for r in results]
        # TextRetriever contains both 'imag' and 'retriev' stems -> full coverage.
        assert names[0] == "TextRetriever"
        assert results[0]["lex_score"] == pytest.approx(1.0)
        assert "ImageEncoder" in names
        assert "setup_logger" not in names

    @pytest.mark.asyncio
    async def test_identifier_and_path_queries_stay_exact(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo_id, ing_id = await _seed(db_session, test_user, _FASHION_CHUNKS)

        results = await KeywordRetriever().search(
            db=db_session,
            query="verify_token",
            repository_id=repo_id,
            ingestion_id=ing_id,
            top_k=10,
        )
        assert results[0]["chunk"].name == "verify_token"
        assert results[0]["lex_score"] == 1.0
        # 'verify_token' -> 'verifi' & 'token': verify_signature lacks 'token'.
        assert "verify_signature" not in {r["chunk"].name for r in results}

        path_results = await KeywordRetriever().search(
            db=db_session,
            query="src/utils/logger.py",
            repository_id=repo_id,
            ingestion_id=ing_id,
            top_k=10,
        )
        assert [r["chunk"].name for r in path_results] == ["setup_logger"]

    @pytest.mark.asyncio
    async def test_rare_term_outweighs_common_terms(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo_id, ing_id = await _seed(db_session, test_user, _FASHION_CHUNKS)
        results = await KeywordRetriever().search(
            db=db_session,
            query="Which fashion images need a token?",
            repository_id=repo_id,
            ingestion_id=ing_id,
            top_k=10,
        )
        scores = {r["chunk"].name: r["lex_score"] for r in results}
        # 'token' occurs in 1 of 5 chunks; 'fashion' and 'imag' in 2 each. The
        # chunk matching only the rare term earns more than an unweighted
        # 1-of-3 share of the score.
        assert scores["verify_token"] > 1 / 3
        assert scores["TextRetriever"] > scores["verify_token"]

    @pytest.mark.asyncio
    async def test_absent_vocabulary_keeps_leftover_generic_match_weak(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo_id, ing_id = await _seed(db_session, test_user, _FASHION_CHUNKS)
        gate = Settings.model_fields["LLM_MIN_RELEVANCE_SCORE"].default
        results = await KeywordRetriever().search(
            db=db_session,
            query="How are Stripe payment refunds tokenized?",
            repository_id=repo_id,
            ingestion_id=ing_id,
            top_k=10,
        )
        assert all(0.30 * r["lex_score"] < gate for r in results)

    @pytest.mark.asyncio
    async def test_filters_and_isolation_bind_around_the_or_match(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        # Regression: the OR-ed match condition must stay parenthesised, or
        # an exact-name match escapes the repository/ingestion/path filters.
        repo_id, ing_id = await _seed(db_session, test_user, _FASHION_CHUNKS)
        other = RepositoryIngestion(repository_id=repo_id, status="completed")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        db_session.add(
            CodeChunk(
                repository_id=repo_id,
                ingestion_id=other.id,
                file_path="src/auth/tokens.py",
                language="Python",
                chunk_type="function",
                name="verify_token",
                start_line=1,
                end_line=3,
                content_hash="other",
                chunk_text="def verify_token(token):\n    return None\n",
            )
        )
        await db_session.commit()

        results = await KeywordRetriever().search(
            db=db_session,
            query="verify_token",
            repository_id=repo_id,
            ingestion_id=ing_id,
            top_k=10,
        )
        assert [r["chunk"].ingestion_id for r in results] == [ing_id]

        scoped = await KeywordRetriever().search(
            db=db_session,
            query="How does image retrieval work?",
            repository_id=repo_id,
            ingestion_id=ing_id,
            top_k=10,
            file_paths=["src/indexing/"],
        )
        assert scoped
        assert all(r["chunk"].file_path.startswith("src/indexing/") for r in scoped)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Broad repository-level questions
# ─────────────────────────────────────────────────────────────────────────────


class TestBroadQuestionDetection:
    @pytest.mark.parametrize(
        "query",
        [
            "Explain the architecture of this repository.",
            "Give me an overview of this repository.",
            "How is this project structured?",
            "What are the main components?",
            "Explain the architecture of this repository. Identify the main "
            "components, how they interact, and cite the relevant files.",
            "What does this repo do?",
            "Give me a high-level walkthrough",
        ],
    )
    def test_broad(self, query: str) -> None:
        assert is_broad_repository_question(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "How does image retrieval work?",
            "Where is the query encoder implemented?",
            "How is the FAISS index built?",
            "What data structure does the index use?",
            "verify_token",
        ],
    )
    def test_not_broad(self, query: str) -> None:
        assert is_broad_repository_question(query) is False


class TestOverviewChunkSelection:
    @pytest.mark.parametrize(
        ("path", "name", "start", "expected"),
        [
            ("README.md", "FashionRAG: A Modular Retrieval System", 1, True),
            ("README.md", "Architecture", 23, True),
            ("README.md", "Folder Structure", 59, True),
            ("README.md", "Features", 7, True),
            ("README.md", "Installation", 86, False),
            ("README.md", "Author", 209, False),
            ("docs/README.md", "Architecture", 1, False),  # not the root README
            ("docs/architecture.md", "Request flow", 40, True),
            ("main.py", "main", 55, True),
            ("main.py", "demo_encode", 14, False),
            ("src/main.py", "main", 10, True),
            ("a/b/c/main.py", "main", 10, False),
            ("src/retrieval/search.py", "perform_search", 18, False),
        ],
    )
    def test_is_overview_chunk(
        self, path: str, name: str, start: int, expected: bool
    ) -> None:
        assert is_overview_chunk(path, name, start) is expected

    def test_overview_bonus_only_for_broad_questions(self) -> None:
        readme = _chunk(1, "README.md", name="Architecture", start_line=23)
        broad, broad_sources = _compute_score(
            0.0, 0.0, "explain the architecture", readme, broad_query=True
        )
        narrow, narrow_sources = _compute_score(
            0.0, 0.0, "how is the index built", readme, broad_query=False
        )
        assert broad == pytest.approx(0.15)
        assert "overview" in broad_sources
        assert narrow == 0.0
        assert "overview" not in narrow_sources


_OVERVIEW_REPO_FILES = {
    "README.md": (
        "# Widget Service\n\nA small service that renders widgets.\n\n"
        "## Architecture\n\nRequests enter through main.py, which dispatches to "
        "the renderer and the cache.\n\n"
        "## Installation\n\nRun pip install.\n"
    ),
    "main.py": (
        "import sys\n\n\ndef main():\n    dispatch(sys.argv)\n\n\n"
        "def helper():\n    return 1\n"
    ),
    "renderer.py": ("def render_widget(widget):\n    return template.format(widget)\n"),
}


async def _index_files(
    db: AsyncSession, owner: User, tmp_path: Path, files: dict[str, str]
) -> tuple[int, int]:
    repo = Repository(
        owner_id=owner.id,
        name="overview-repo",
        full_name="testuser/overview-repo",
        github_url="https://github.com/testuser/overview-repo",
        status="ready",
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    ingestion = RepositoryIngestion(repository_id=repo.id, status="completed")
    db.add(ingestion)
    await db.commit()
    await db.refresh(ingestion)
    for filename, content in files.items():
        (tmp_path / filename).write_text(content, encoding="utf-8")
    await RAGService.index_repository(
        db=db,
        repository_id=repo.id,
        ingestion_id=ingestion.id,
        source_root=tmp_path,
        embedding_provider=MockEmbeddingProvider(),
    )
    return repo.id, ingestion.id


class TestBroadQuestionRetrieval:
    """End-to-end through RAGService.search (the Ask/Explain/Review path)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "question",
        [
            "Explain the architecture of this repository.",
            "Give me an overview of this repository.",
            "How is this project structured?",
            "What are the main components?",
        ],
    )
    async def test_broad_question_retrieves_readme_and_entry_point(
        self,
        db_session: AsyncSession,
        test_user: User,
        tmp_path: Path,
        question: str,
    ) -> None:
        repo_id, _ = await _index_files(
            db_session, test_user, tmp_path, _OVERVIEW_REPO_FILES
        )
        results, _ = await RAGService.search(
            db=db_session,
            request=CodeSearchRequest(query=question, top_k=10),
            repository_id=repo_id,
            owner_id=test_user.id,
            embedding_provider=MockEmbeddingProvider(),
        )
        gate = Settings.model_fields["LLM_MIN_RELEVANCE_SCORE"].default
        evidence = {(r.file_path, r.name) for r in results if r.score >= gate}
        assert ("README.md", "Architecture") in evidence
        assert ("README.md", "Widget Service") in evidence
        assert ("main.py", "main") in evidence
        # Non-overview sections/functions get no structural boost.
        boosted = {
            (r.file_path, r.name) for r in results if "overview" in r.retrieval_sources
        }
        assert ("README.md", "Installation") not in boosted
        assert ("main.py", "helper") not in boosted

    @pytest.mark.asyncio
    async def test_specific_question_gets_no_overview_candidates(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        repo_id, _ = await _index_files(
            db_session, test_user, tmp_path, _OVERVIEW_REPO_FILES
        )
        results, _ = await RAGService.search(
            db=db_session,
            request=CodeSearchRequest(query="How is a widget rendered?", top_k=10),
            repository_id=repo_id,
            owner_id=test_user.id,
            embedding_provider=MockEmbeddingProvider(),
        )
        assert all("overview" not in r.retrieval_sources for r in results)

    @pytest.mark.asyncio
    async def test_path_scoped_search_skips_overview(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        repo_id, _ = await _index_files(
            db_session, test_user, tmp_path, _OVERVIEW_REPO_FILES
        )
        results, _ = await RAGService.search(
            db=db_session,
            request=CodeSearchRequest(
                query="Explain the architecture of this repository.",
                top_k=10,
                file_paths=["renderer.py"],
            ),
            repository_id=repo_id,
            owner_id=test_user.id,
            embedding_provider=MockEmbeddingProvider(),
        )
        assert all(r.file_path == "renderer.py" for r in results)

    @pytest.mark.asyncio
    async def test_overview_retriever_is_bounded_and_ordered(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        repo_id, ing_id = await _index_files(
            db_session, test_user, tmp_path, _OVERVIEW_REPO_FILES
        )
        results = await OverviewRetriever().search(
            db=db_session, repository_id=repo_id, ingestion_id=ing_id, limit=2
        )
        assert len(results) == 2
        assert all(r["chunk"].file_path == "README.md" for r in results)
        assert all(r["sem_score"] == 0.0 for r in results)  # no query vector
