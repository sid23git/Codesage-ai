"""Tests for repository CRUD operations and cross-user authorization boundaries."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.user import User


class TestRepositoryCreate:
    """Test suite for POST /repositories."""

    def test_create_repository_authenticated(
        self, client: TestClient, test_user: User, auth_headers: dict[str, str]
    ) -> None:
        """Authenticated user can create a repository."""
        payload = {
            "name": "Codesage-ai",
            "github_url": "https://github.com/sid23git/Codesage-ai",
            "description": "AI-powered engineering assistant",
            "primary_language": "Python",
        }
        response = client.post("/repositories", json=payload, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Codesage-ai"
        assert data["full_name"] == "sid23git/Codesage-ai"
        assert data["github_url"] == "https://github.com/sid23git/Codesage-ai"
        assert data["owner_id"] == test_user.id
        assert data["status"] == "pending"
        assert "id" in data

    def test_create_repository_unauthenticated_rejected(
        self, client: TestClient
    ) -> None:
        """Unauthenticated request to create repository should return 401."""
        payload = {
            "name": "my-repo",
            "github_url": "https://github.com/example/my-repo",
        }
        response = client.post("/repositories", json=payload)
        assert response.status_code == 401

    def test_create_repository_duplicate_url_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Attempting to add the same repository URL twice for one user returns 409."""
        payload = {
            "name": "duplicate-repo",
            "github_url": "https://github.com/example/duplicate-repo",
        }
        resp1 = client.post("/repositories", json=payload, headers=auth_headers)
        assert resp1.status_code == 201

        resp2 = client.post("/repositories", json=payload, headers=auth_headers)
        assert resp2.status_code == 409

    def test_create_repository_invalid_url_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Malformed GitHub URL should return 422."""
        payload = {
            "name": "invalid-repo",
            "github_url": "ftp://not-http-url",
        }
        response = client.post("/repositories", json=payload, headers=auth_headers)
        assert response.status_code == 422


class TestRepositoryList:
    """Test suite for GET /repositories."""

    def test_list_repositories_isolated_to_owner(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
    ) -> None:
        """User A sees only their own repositories, not User B's."""
        # User A creates repo 1
        client.post(
            "/repositories",
            json={
                "name": "repo-a",
                "github_url": "https://github.com/user-a/repo-a",
            },
            headers=auth_headers,
        )

        # User B creates repo 2
        client.post(
            "/repositories",
            json={
                "name": "repo-b",
                "github_url": "https://github.com/user-b/repo-b",
            },
            headers=other_auth_headers,
        )

        # User A lists repos
        resp_a = client.get("/repositories", headers=auth_headers)
        assert resp_a.status_code == 200
        repos_a = resp_a.json()
        assert len(repos_a) == 1
        assert repos_a[0]["name"] == "repo-a"

        # User B lists repos
        resp_b = client.get("/repositories", headers=other_auth_headers)
        assert resp_b.status_code == 200
        repos_b = resp_b.json()
        assert len(repos_b) == 1
        assert repos_b[0]["name"] == "repo-b"

    def test_list_repositories_unauthenticated(self, client: TestClient) -> None:
        """Unauthenticated GET /repositories should return 401."""
        response = client.get("/repositories")
        assert response.status_code == 401


class TestRepositoryGetAndAuthorization:
    """Test suite for GET /repositories/{id} and ownership boundaries."""

    def test_get_owned_repository(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Owner can retrieve their own repository by ID."""
        create_resp = client.post(
            "/repositories",
            json={
                "name": "my-cool-repo",
                "github_url": "https://github.com/user/my-cool-repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        get_resp = client.get(f"/repositories/{repo_id}", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "my-cool-repo"

    def test_cannot_get_other_user_repository(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
    ) -> None:
        """User B requesting User A's repository by ID receives 404 (not 403)."""
        create_resp = client.post(
            "/repositories",
            json={
                "name": "private-repo",
                "github_url": "https://github.com/user-a/private-repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        # User B tries to view User A's repo
        get_resp = client.get(f"/repositories/{repo_id}", headers=other_auth_headers)
        assert get_resp.status_code == 404
        assert get_resp.json()["detail"] == "Repository not found"


class TestRepositoryUpdate:
    """Test suite for PUT /repositories/{id}."""

    def test_update_owned_repository(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Owner can update repository metadata and status."""
        create_resp = client.post(
            "/repositories",
            json={
                "name": "updatable-repo",
                "github_url": "https://github.com/user/updatable-repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        update_resp = client.put(
            f"/repositories/{repo_id}",
            json={
                "name": "renamed-repo",
                "description": "New description",
                "status": "ready",
            },
            headers=auth_headers,
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["name"] == "renamed-repo"
        assert data["description"] == "New description"
        assert data["status"] == "ready"

    def test_cannot_update_other_user_repository(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
    ) -> None:
        """User B cannot update User A's repository (returns 404)."""
        create_resp = client.post(
            "/repositories",
            json={
                "name": "target-repo",
                "github_url": "https://github.com/user-a/target-repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        update_resp = client.put(
            f"/repositories/{repo_id}",
            json={"name": "hacked-name"},
            headers=other_auth_headers,
        )
        assert update_resp.status_code == 404


class TestRepositoryDelete:
    """Test suite for DELETE /repositories/{id}."""

    def test_delete_owned_repository(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Owner can delete their repository."""
        create_resp = client.post(
            "/repositories",
            json={
                "name": "to-delete",
                "github_url": "https://github.com/user/to-delete",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        delete_resp = client.delete(f"/repositories/{repo_id}", headers=auth_headers)
        assert delete_resp.status_code == 204

        # Confirm it is no longer retrievable
        get_resp = client.get(f"/repositories/{repo_id}", headers=auth_headers)
        assert get_resp.status_code == 404

    def test_cannot_delete_other_user_repository(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
    ) -> None:
        """User B cannot delete User A's repository (returns 404)."""
        create_resp = client.post(
            "/repositories",
            json={
                "name": "protected-repo",
                "github_url": "https://github.com/user-a/protected-repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        delete_resp = client.delete(
            f"/repositories/{repo_id}", headers=other_auth_headers
        )
        assert delete_resp.status_code == 404

        # Verify repo still exists for User A
        get_resp = client.get(f"/repositories/{repo_id}", headers=auth_headers)
        assert get_resp.status_code == 200
