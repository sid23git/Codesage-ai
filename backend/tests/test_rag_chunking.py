"""Tests for code-aware chunking engine."""

from __future__ import annotations

from app.rag.chunking import (
    FallbackChunker,
    MarkdownChunker,
    PythonAstChunker,
    RawChunk,
    StructuralBlockChunker,
    chunk_file,
)


class TestRawChunk:
    """Test RawChunk dataclass and hashing."""

    def test_content_hash_deterministic(self) -> None:
        chunk1 = RawChunk(
            file_path="foo.py",
            start_line=1,
            end_line=5,
            language="Python",
            chunk_type="function",
            name="bar",
            chunk_text="def bar():\n    return 42",
        )
        chunk2 = RawChunk(
            file_path="other.py",
            start_line=10,
            end_line=15,
            language="Python",
            chunk_type="function",
            name="bar",
            chunk_text="  def bar():\n    return 42  ",
        )
        assert chunk1.content_hash == chunk2.content_hash
        assert len(chunk1.content_hash) == 64


class TestPythonAstChunker:
    """Test Python AST chunking."""

    def test_chunks_functions_and_classes(self) -> None:
        code = (
            "import os\n\n"
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n\n"
            "async def fetch_data():\n"
            "    return {'status': 'ok'}\n\n"
            "class Calculator:\n"
            "    def multiply(self, x, y):\n"
            "        return x * y\n"
        )
        chunker = PythonAstChunker()
        chunks = chunker.chunk("calc.py", "Python", code)

        assert len(chunks) == 3
        assert chunks[0].name == "add"
        assert chunks[0].chunk_type == "function"
        assert chunks[0].start_line == 3
        assert "def add" in chunks[0].chunk_text

        assert chunks[1].name == "fetch_data"
        assert chunks[1].chunk_type == "function"
        assert chunks[1].start_line == 6

        assert chunks[2].name == "Calculator"
        assert chunks[2].chunk_type == "class"
        assert chunks[2].start_line == 9

    def test_syntax_error_falls_back(self) -> None:
        malformed_code = "def broken(\n  invalid syntax :::"
        chunker = PythonAstChunker()
        chunks = chunker.chunk("broken.py", "Python", malformed_code)

        assert len(chunks) >= 1
        assert chunks[0].chunk_type == "block"

    def test_no_functions_or_classes_falls_back(self) -> None:
        flat_code = "x = 1\ny = 2\nz = x + y\n"
        chunker = PythonAstChunker()
        chunks = chunker.chunk("flat.py", "Python", flat_code)

        assert len(chunks) == 1
        assert chunks[0].chunk_type == "block"


class TestStructuralBlockChunker:
    """Test structural block chunking for polyglot code."""

    def test_chunks_typescript(self) -> None:
        code = (
            "export interface User {\n"
            "  id: number;\n"
            "  name: string;\n"
            "}\n\n"
            "export class UserService {\n"
            "  getUser() {\n"
            "    return null;\n"
            "  }\n"
            "}\n\n"
            "export async function login() {\n"
            "  return true;\n"
            "}\n"
        )
        chunker = StructuralBlockChunker()
        chunks = chunker.chunk("user.ts", "TypeScript", code)

        assert len(chunks) >= 2
        names = [c.name for c in chunks]
        assert "User" in names or "UserService" in names

    def test_chunks_go(self) -> None:
        code = (
            "package main\n\n"
            "type Server struct {\n"
            "    port int\n"
            "}\n\n"
            "func StartServer() error {\n"
            "    return nil\n"
            "}\n"
        )
        chunker = StructuralBlockChunker()
        chunks = chunker.chunk("server.go", "Go", code)

        assert len(chunks) >= 1
        names = [c.name for c in chunks]
        assert "Server" in names or "StartServer" in names


class TestMarkdownChunker:
    """Test Markdown section chunking."""

    def test_chunks_by_headers(self) -> None:
        doc = (
            "# Introduction\n\n"
            "Welcome to CodeSage AI.\n\n"
            "## Architecture\n\n"
            "Here is the architecture overview.\n\n"
            "### Database\n\n"
            "PostgreSQL + pgvector is used.\n"
        )
        chunker = MarkdownChunker()
        chunks = chunker.chunk("README.md", "Markdown", doc)

        assert len(chunks) == 3
        assert chunks[0].name == "Introduction"
        assert chunks[0].chunk_type == "doc_section"
        assert chunks[1].name == "Architecture"
        assert chunks[2].name == "Database"


class TestFallbackChunker:
    """Test fallback sliding-window line chunker."""

    def test_sliding_window(self) -> None:
        lines = [f"line {i}" for i in range(1, 101)]
        text = "\n".join(lines)

        chunker = FallbackChunker(chunk_lines=40, overlap_lines=10)
        chunks = chunker.chunk("data.txt", None, text)

        assert len(chunks) == 3
        assert chunks[0].start_line == 1
        assert chunks[0].end_line == 40
        assert chunks[1].start_line == 31
        assert chunks[1].end_line == 70
        assert chunks[2].start_line == 61
        assert chunks[2].end_line == 100

    def test_empty_text_returns_empty(self) -> None:
        chunker = FallbackChunker()
        chunks = chunker.chunk("empty.txt", None, "")
        assert chunks == []


class TestChunkFileRouter:
    """Test top-level chunk_file router."""

    def test_routes_to_python(self) -> None:
        code = "def foo(): pass"
        chunks = chunk_file("test.py", "Python", code)
        assert len(chunks) == 1
        assert chunks[0].name == "foo"

    def test_routes_to_markdown(self) -> None:
        doc = "# Title\nContent"
        chunks = chunk_file("doc.md", "Markdown", doc)
        assert len(chunks) == 1
        assert chunks[0].name == "Title"

    def test_empty_string_returns_empty(self) -> None:
        chunks = chunk_file("test.py", "Python", "   \n\n  ")
        assert chunks == []
