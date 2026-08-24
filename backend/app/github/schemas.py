"""Internal Pydantic schemas for GitHub API responses.

These schemas are used exclusively inside the application to represent
data fetched from the GitHub REST API.  They are **never** exposed directly
to external API consumers; the ``RepositoryResponse`` schema (in
``app/schemas/repository``) is the public-facing representation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GitHubRepoData(BaseModel):
    """Parsed metadata from ``GET /repos/{owner}/{repo}``.

    Field names follow the GitHub REST API JSON response keys where possible.
    Snake_case aliases are provided for Pydantic population from GitHub's JSON.
    """

    model_config = ConfigDict(populate_by_name=True)

    github_id: int = Field(alias="id")
    owner_login: str = Field(alias="owner")
    name: str
    full_name: str
    description: str | None = None
    default_branch: str
    language: str | None = None
    stargazers_count: int = 0
    forks_count: int = 0
    open_issues_count: int = 0
    updated_at: datetime | None = None

    @classmethod
    def from_github_json(cls, data: dict[str, object]) -> GitHubRepoData:
        """Construct from a raw GitHub API JSON dict.

        Handles the nested ``owner`` object by extracting ``login`` before
        delegating to normal Pydantic validation.

        Parameters
        ----------
        data:
            Raw JSON dict from the GitHub REST API ``/repos/{owner}/{repo}``
            endpoint.

        Returns
        -------
        GitHubRepoData
            Validated internal representation.
        """
        owner_field = data.get("owner")
        if isinstance(owner_field, dict):
            data = {**data, "owner": owner_field.get("login", "")}

        return cls.model_validate(data)
