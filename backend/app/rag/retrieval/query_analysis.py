"""Deterministic query/chunk analysis shared by the lexical and fusion stages.

Everything here is plain, dependency-free string logic so that every
retrieval decision it drives can be explained and unit-tested in isolation:

- ``lexical_terms`` -- the content-bearing terms of a query, for keyword
  retrieval (stopwords and question scaffolding removed; identifiers and
  paths such as ``verify_token`` or ``app/core/security.py`` kept whole).
- ``path_match_terms`` / ``path_words`` -- whole-word tokens used by the
  path bonus, so a query word only matches a *complete* path component
  (``index`` matches ``build_index.py`` but not ``indexing/``, and ``and``
  never matches ``query_expander.py``).
- ``is_broad_repository_question`` / ``is_overview_chunk`` -- a small,
  rule-based detector for repository-level questions ("Explain the
  architecture of this repository.") and the structural chunks (root README
  sections, architecture docs, entry points) that answer them.
- ``is_non_evidence_chunk`` -- identifies chunks that can never be cited
  as evidence for a question: source chunks containing nothing but comments
  (``# Keep directory``, a one-line ``__init__.py`` comment) and
  ignore-pattern files (``.gitignore`` and friends), unless the query names
  that file explicitly.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# ── Stopwords ────────────────────────────────────────────────────────────────
# Common English function words plus question scaffolding that appears in
# almost every question about a codebase ("how does this repository work",
# "where is X implemented") and therefore carries no retrieval signal. Kept
# deliberately small and explicit rather than pulled from a library so the
# exact behaviour is visible and testable.
# fmt: off
STOPWORDS: frozenset[str] = frozenset(
    {
        # articles / pronouns / determiners
        "a", "an", "the", "this", "that", "these", "those", "it", "its",
        "i", "me", "my", "we", "our", "you", "your", "they", "them", "their",
        "there", "here", "some", "any", "all", "each", "every",
        # prepositions / conjunctions
        "of", "in", "on", "at", "to", "for", "from", "with", "without", "by",
        "into", "onto", "about", "as", "and", "or", "but", "not", "no", "if",
        "then", "than", "so", "via", "between", "within", "across", "through",
        # auxiliaries / question words
        "is", "are", "was", "were", "be", "been", "being", "am",
        "do", "does", "did", "done", "doing", "has", "have", "had",
        "can", "could", "should", "would", "will", "shall", "may", "might",
        "must", "how", "what", "where", "when", "why", "which", "who", "whom",
        # imperative / scaffolding verbs
        "explain", "describe", "show", "tell", "give", "list", "find", "get",
        "please", "help", "understand", "know", "want", "need", "mean",
        "use", "used", "uses", "using", "work", "works", "working",
        "implement", "implemented", "implements", "happen", "happens",
        "perform", "performs", "performed", "handle", "handled", "become",
        "becomes", "take", "takes", "make", "makes", "identify", "cite",
        # generic nouns that describe the question's subject, not its topic
        "repository", "repositories", "repo", "project", "codebase", "code",
        "application", "app", "file", "files", "function", "functions",
        "class", "classes", "method", "methods", "module", "modules",
        "relevant", "part", "parts", "thing", "things", "way", "ways",
        "one", "ones", "also", "just", "only", "like", "such", "other",
    }
)
# fmt: on

# File-extension tokens never earn a path bonus on their own ("main.py" in a
# query must not boost every ``.py`` file).
# fmt: off
_EXTENSION_WORDS: frozenset[str] = frozenset(
    {
        "py", "pyi", "js", "jsx", "ts", "tsx", "mjs", "cjs", "md", "mdx",
        "rst", "txt", "json", "yml", "yaml", "toml", "ini", "cfg", "go", "rs",
        "java", "kt", "c", "h", "cc", "cpp", "hpp", "cs", "rb", "php", "html",
        "css", "scss", "sh", "sql", "ipynb", "lock",
    }
)
# fmt: on

_WORD_RE = re.compile(r"[a-z0-9]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# Punctuation stripped from the ends of a whitespace-delimited query token.
_EDGE_PUNCT = "?!,;:\"'`()[]{}<>*"


def _normalise_word(word: str) -> str:
    """Lowercase + minimal plural folding (``images`` -> ``image``)."""
    word = word.lower()
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _is_stopword(token: str) -> bool:
    token = token.lower()
    if token.endswith("'s"):
        token = token[:-2]
    return token in STOPWORDS


def lexical_terms(query: str) -> list[str]:
    """Return the query's content-bearing terms for keyword retrieval.

    Splits on whitespace only, so identifiers and paths survive intact
    (``verify_token``, ``app/core/security.py``) and are later matched by
    PostgreSQL's own parser exactly as the indexed text was. Surrounding
    punctuation and a sentence-final ``.`` are stripped; stopwords are
    dropped; order is preserved and duplicates removed.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for raw in query.split():
        token = raw.strip(_EDGE_PUNCT).rstrip(".").strip(_EDGE_PUNCT)
        if not token or not any(ch.isalnum() for ch in token):
            continue
        if _is_stopword(token):
            continue
        key = token.lower()
        if key not in seen:
            seen.add(key)
            terms.append(token)
    return terms


def _split_words(text: str) -> list[str]:
    return _WORD_RE.findall(_CAMEL_RE.sub(" ", text).lower())


def path_words(file_path: str) -> set[str]:
    """Whole-word components of *file_path* (split on ``/ . _ -`` and camelCase)."""
    return {_normalise_word(w) for w in _split_words(file_path)}


def path_match_terms(query: str) -> set[str]:
    """Query words eligible for the path bonus (no stopwords/extensions/1-char)."""
    return {
        _normalise_word(w)
        for w in _split_words(query)
        if len(w) >= 2 and w not in STOPWORDS and w not in _EXTENSION_WORDS
    }


def path_matches_query(file_path: str, query: str) -> bool:
    """True if any eligible query word equals a whole component of *file_path*."""
    terms = path_match_terms(query)
    return bool(terms) and not terms.isdisjoint(path_words(file_path))


# ── Broad repository-level questions ─────────────────────────────────────────

_BROAD_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"\barchitecture\b",
        r"\boverview\b",
        r"\bhigh[- ]level\b",
        r"\bbig picture\b",
        r"\bwalk me through\b",
        r"\b(main|key|major|core|primary) "
        r"(components?|modules?|parts|pieces|building blocks)\b",
        r"\bwhat (does|is) (this|the) "
        r"(repo|repository|project|codebase|application|app)\b",
    )
)
_STRUCTURE_RE = re.compile(
    r"\b(structure|structured|organi[sz]ed|organi[sz]ation|layout|laid out)\b"
)
_REPO_NOUN_RE = re.compile(
    r"\b(repo|repository|project|codebase|code base|application|app|system)\b"
)


def is_broad_repository_question(query: str) -> bool:
    """Deterministically detect a repository-level (overview/architecture) question.

    Matches explicit overview vocabulary ("architecture", "overview",
    "high-level", "main components", "what does this repo ...") or a
    structure word *together with* a repository noun ("How is this project
    structured?") -- so "What data structure does the index use?" is not
    treated as broad.
    """
    q = query.lower()
    if any(p.search(q) for p in _BROAD_PATTERNS):
        return True
    return bool(_STRUCTURE_RE.search(q) and _REPO_NOUN_RE.search(q))


_OVERVIEW_HEADING_RE = re.compile(
    r"\b(overview|architecture|design|structure|components?|modules?|"
    r"introduction|intro|about|summary|how it works|pipeline|features?)\b"
)
_OVERVIEW_DOC_STEMS: frozenset[str] = frozenset(
    {"architecture", "overview", "design", "structure"}
)
# fmt: off
ENTRY_POINT_FILES: frozenset[str] = frozenset(
    {
        "main.py", "__main__.py", "app.py", "manage.py", "cli.py", "server.py",
        "run.py", "wsgi.py", "asgi.py", "index.js", "index.ts", "main.js",
        "main.ts", "server.js", "server.ts", "app.js", "app.ts", "main.go",
        "main.rs", "lib.rs", "program.cs", "main.java", "main.kt", "main.c",
        "main.cpp",
    }
)
# fmt: on
_ENTRY_POINT_SYMBOLS: frozenset[str] = frozenset(
    {"main", "__main__", "cli", "run", "create_app", "app", "program"}
)


def is_overview_chunk(file_path: str, name: str | None, start_line: int) -> bool:
    """True for chunks that describe a repository as a whole.

    - a root-level README's introduction (its first section) or any section
      whose heading names an overview topic (Architecture, Features,
      Folder Structure, ...);
    - any chunk of an architecture/overview/design document;
    - the entry-point symbol (``main``, ``create_app``, ...) or module
      header of an entry-point file at the repository root or one level
      down (``main.py``, ``src/index.ts``).
    """
    path = PurePosixPath(file_path.lower())
    depth = len(path.parts) - 1
    heading = (name or "").lower()

    if path.name.startswith("readme") and depth == 0:
        return start_line <= 1 or bool(_OVERVIEW_HEADING_RE.search(heading))

    if path.suffix in {".md", ".mdx", ".rst", ".txt"} and (
        path.stem in _OVERVIEW_DOC_STEMS
        or any(stem in path.stem for stem in ("architecture", "overview"))
    ):
        return True

    if path.name in ENTRY_POINT_FILES and depth <= 1:
        return heading in _ENTRY_POINT_SYMBOLS or (name is None and start_line <= 1)

    return False


# ── Comment-only chunks ──────────────────────────────────────────────────────

_DOC_SUFFIXES: frozenset[str] = frozenset({".md", ".mdx", ".rst", ".txt", ".ipynb"})
_COMMENT_PREFIXES: tuple[str, ...] = ("#", "//", "--", ";", "/*", "*", "<!--", "%")


def is_comment_only(chunk_text: str, file_path: str) -> bool:
    """True if a non-documentation chunk contains only comment lines.

    Such chunks (``# Keep directory`` in a ``.gitkeep``, ``# Retrieval module
    initialization`` in an ``__init__.py``) contain no code and no prose to
    cite, but share vocabulary with real questions -- the benchmark showed
    them surfacing purely through lexical/path coincidences. Documentation
    files are exempt: a Markdown line starting with ``#`` is a heading.
    """
    if PurePosixPath(file_path.lower()).suffix in _DOC_SUFFIXES:
        return False
    lines = [line.strip() for line in chunk_text.splitlines() if line.strip()]
    return bool(lines) and all(line.startswith(_COMMENT_PREFIXES) for line in lines)


# Files that only list path/glob patterns. Their comments and patterns share
# vocabulary with real questions ("dependencies", "logs", "build") but they
# never describe how the project works.
# fmt: off
_IGNORE_PATTERN_FILES: frozenset[str] = frozenset(
    {
        ".gitignore", ".dockerignore", ".npmignore", ".gitattributes",
        ".eslintignore", ".prettierignore", ".gitkeep", ".keep",
    }
)
# fmt: on


def is_non_evidence_chunk(chunk_text: str, file_path: str, query: str) -> bool:
    """True if a chunk should never be returned as evidence for *query*.

    Covers comment-only source chunks and ignore-pattern files. A query that
    names the file itself ("what does the .gitignore exclude?") keeps it --
    naming only its directory ("retrieval" for ``src/retrieval/__init__.py``)
    does not.
    """
    file_name = PurePosixPath(file_path).name
    if path_matches_query(file_name, query):
        return False
    if PurePosixPath(file_path.lower()).name in _IGNORE_PATTERN_FILES:
        return True
    return is_comment_only(chunk_text, file_path)
