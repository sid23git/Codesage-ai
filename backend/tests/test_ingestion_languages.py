"""Unit tests for programming and markup language detection."""

from __future__ import annotations

import pytest

from app.ingestion.languages import detect_language


@pytest.mark.parametrize(
    ("path", "expected_language"),
    [
        # Python
        ("main.py", "Python"),
        ("src/utils.pyi", "Python"),
        ("SCRIPT.PY", "Python"),
        # JavaScript / TypeScript
        ("app.js", "JavaScript"),
        ("component.jsx", "JavaScript"),
        ("server.mjs", "JavaScript"),
        ("index.ts", "TypeScript"),
        ("view.tsx", "TypeScript"),
        # Systems languages
        ("main.c", "C"),
        ("header.h", "C"),
        ("solver.cpp", "C++"),
        ("solver.hpp", "C++"),
        ("main.go", "Go"),
        ("lib.rs", "Rust"),
        ("App.java", "Java"),
        ("Program.cs", "C#"),
        # Data / Markup / Styling
        ("schema.sql", "SQL"),
        ("index.html", "HTML"),
        ("style.css", "CSS"),
        ("style.scss", "CSS"),
        ("README.md", "Markdown"),
        ("config.yaml", "YAML"),
        ("settings.yml", "YAML"),
        ("package.json", "JSON"),
        ("pyproject.toml", "TOML"),
        ("manifest.xml", "XML"),
        # Shell
        ("deploy.sh", "Shell"),
        ("setup.bash", "Shell"),
        # Special filenames
        ("Dockerfile", "Dockerfile"),
        ("dockerfile", "Dockerfile"),
        ("Dockerfile.dev", "Dockerfile"),
        ("Dockerfile.production", "Dockerfile"),
        ("Makefile", "Makefile"),
        ("makefile", "Makefile"),
        ("CMakeLists.txt", "CMake"),
        ("Gemfile", "Ruby"),
    ],
)
def test_detect_language_known(path: str, expected_language: str) -> None:
    assert detect_language(path) == expected_language


@pytest.mark.parametrize(
    "path",
    [
        "unknown.xyz",
        "file.unknownext",
        "binary.dat",
        "noextensionfile",
        "somedir/subfile",
    ],
)
def test_detect_language_unknown(path: str) -> None:
    assert detect_language(path) is None
