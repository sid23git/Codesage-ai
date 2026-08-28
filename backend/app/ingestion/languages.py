"""Programming and markup language detection based on extension and filename mapping."""

from __future__ import annotations

import os
from pathlib import Path

# Mapping of lowercase file extensions (with dot) to canonical language names
EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    # Python
    ".py": "Python",
    ".pyi": "Python",
    ".pyw": "Python",
    # JavaScript / TypeScript ecosystem
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    # Systems & Compiled Languages
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".hxx": "C++",
    ".c++": "C++",
    ".h++": "C++",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".cs": "C#",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sc": "Scala",
    ".dart": "Dart",
    ".lua": "Lua",
    ".rb": "Ruby",
    ".php": "PHP",
    ".phtml": "PHP",
    ".r": "R",
    ".rmd": "R",
    # Shell / Scripting
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".fish": "Shell",
    ".ps1": "PowerShell",
    ".bat": "Batch",
    ".cmd": "Batch",
    # Data / Query / Web Markup & Styling
    ".sql": "SQL",
    ".html": "HTML",
    ".htm": "HTML",
    ".xhtml": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".sass": "CSS",
    ".less": "CSS",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".mdown": "Markdown",
    ".mkd": "Markdown",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".jsonc": "JSON",
    ".json5": "JSON",
    ".toml": "TOML",
    ".xml": "XML",
    ".svg": "XML",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
    ".proto": "Protocol Buffers",
}

# Special filename mappings (matched case-insensitively)
SPECIAL_FILENAME_MAP: dict[str, str] = {
    "dockerfile": "Dockerfile",
    "containerfile": "Dockerfile",
    "makefile": "Makefile",
    "gnumakefile": "Makefile",
    "cmakelists.txt": "CMake",
    "gemfile": "Ruby",
    "rakefile": "Ruby",
    "vagrantfile": "Ruby",
    "procfile": "Procfile",
    "jenkinsfile": "Groovy",
}


def detect_language(file_path: str | Path) -> str | None:
    """Detect programming or markup language for a given file path.

    Parameters
    ----------
    file_path:
        Relative or absolute file path or filename.

    Returns
    -------
    str | None
        Canonical language name (e.g. ``"Python"``, ``"TypeScript"``) or ``None``
        if the language could not be recognized.
    """
    path_obj = Path(file_path)
    filename = path_obj.name.lower()

    # 1. Check special filename mappings (e.g., 'Dockerfile', 'Makefile')
    if filename in SPECIAL_FILENAME_MAP:
        return SPECIAL_FILENAME_MAP[filename]

    # Handle prefixed Dockerfiles (e.g., Dockerfile.dev, Dockerfile.prod)
    if filename.startswith("dockerfile.") or filename.startswith("containerfile."):
        return "Dockerfile"

    # 2. Check extension mappings
    ext = os.path.splitext(filename)[1].lower()
    if ext in EXTENSION_LANGUAGE_MAP:
        return EXTENSION_LANGUAGE_MAP[ext]

    return None
