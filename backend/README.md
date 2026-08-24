# CodeSage AI — Backend

FastAPI service powering the CodeSage AI platform.

## Requirements

- Python 3.12+
- PostgreSQL 15+ (or in-memory SQLite for automated tests)

## Quick start

```bash
# 1. Clone / enter the backend directory
cd backend

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies (with dev extras)
pip install -e ".[dev]"

# 4. Set up environment variables
cp .env.example .env
# Edit .env with your local database credentials and SECRET_KEY

# 5. Run database migrations
alembic upgrade head

# 6. Start the development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at <http://localhost:8000>.
Interactive OpenAPI docs: <http://localhost:8000/docs>

---

## Authentication & Security

CodeSage AI uses JWT-based authentication:
1. Register an account with `POST /auth/register`. Passwords are encrypted using **bcrypt** with salted hashing.
2. Authenticate with `POST /auth/login` to receive a signed **JWT access token** (signed using `HS256` with `SECRET_KEY`).
3. Pass the access token in the `Authorization` header for protected endpoints:
   ```http
   Authorization: Bearer <your_access_token>
   ```
4. Check identity with `GET /auth/me`.

---

## API Endpoints

### System & Health

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | No | Service liveness probe |

### Authentication

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/register` | No | Register a new user |
| `POST` | `/auth/login` | No | Authenticate and obtain JWT token |
| `GET` | `/auth/me` | Bearer | Retrieve authenticated user profile |

### Repositories

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/repositories` | Bearer | Register a repository for the current user |
| `GET` | `/repositories` | Bearer | List repositories owned by the current user |
| `GET` | `/repositories/{id}` | Bearer | Get details of an owned repository |
| `PUT` | `/repositories/{id}` | Bearer | Update metadata of an owned repository |
| `DELETE` | `/repositories/{id}` | Bearer | Delete an owned repository |
| `POST` | `/repositories/{id}/sync` | Bearer | Sync repository metadata from GitHub |

*(Endpoints are also accessible under the `/api/v1` prefix, e.g. `/api/v1/auth/login`).*

---

## GitHub Integration

### Architecture

All GitHub API communication follows a strict layered flow:

```
POST /repositories/{id}/sync
   ↓
API Route (repositories.py)
   ↓  maps HTTP errors
Repository Service (repository_service.py)
   ↓  enforces ownership, parses URL
GitHub Service / Client (github/client.py)
   ↓  httpx.AsyncClient
GitHub REST API (api.github.com)
```

No route handler ever calls `httpx` directly.

### Repository Sync Endpoint

```
POST /repositories/{repository_id}/sync
Authorization: Bearer <token>
```

**Behaviour:**
1. Authenticates the requesting user.
2. Verifies repository ownership (returns 404 if not found or not owned — not 403, to prevent enumeration).
3. Validates the stored `github_url` against the strict parser.
4. Calls `GET https://api.github.com/repos/{owner}/{repo}`.
5. Persists GitHub metadata onto the repository record.
6. Sets `status = "ready"` and `last_synced_at = now(UTC)`.
7. Returns the updated `RepositoryResponse`.

On failure, `status` is set to `"failed"` and an appropriate HTTP error is returned.

### Supported GitHub URL Format

```
https://github.com/<owner>/<repository>
```

Rules enforced by `parse_github_url`:
- Scheme must be **`https`** (not `http`, `git`, `ftp`, etc.)
- Hostname must be **exactly `github.com`** (SSRF protection — no other hosts allowed)
- Exactly **two path segments**: `owner` and `repo`
- Extra path segments (e.g. `/tree/main`) are **rejected**
- `.git` suffix and trailing slashes are stripped automatically

### Metadata Retrieved

After a successful sync, the following fields are populated on the repository:

| Field | Source | Description |
|---|---|---|
| `github_repository_id` | `id` | GitHub's numeric repository ID |
| `github_owner` | `owner.login` | GitHub owner login |
| `name` | `name` | Repository name |
| `full_name` | `full_name` | `owner/repo` |
| `description` | `description` | Repository description |
| `default_branch` | `default_branch` | e.g. `main` |
| `primary_language` | `language` | Primary programming language |
| `stars` | `stargazers_count` | Star count at last sync |
| `forks` | `forks_count` | Fork count at last sync |
| `open_issues` | `open_issues_count` | Open issues count at last sync |
| `github_updated_at` | `updated_at` | GitHub's own updated timestamp |
| `last_synced_at` | *(server)* | Timestamp of the sync operation |

### Error Responses

| Condition | HTTP Status |
|---|---|
| Invalid or non-GitHub URL | 400 Bad Request |
| Repository not found on GitHub | 404 Not Found |
| Repository not owned by requester | 404 Not Found |
| GitHub API rate limit exceeded | 429 Too Many Requests |
| GitHub request timed out | 504 Gateway Timeout |
| GitHub 5xx server error | 502 Bad Gateway |
| Malformed GitHub response | 502 Bad Gateway |
| Unauthenticated request | 401 Unauthorized |

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GITHUB_TOKEN` | *(none)* | Optional GitHub PAT — raises rate limit from 60 to 5 000 req/h. Never hardcode. |
| `GITHUB_REQUEST_TIMEOUT` | `10.0` | Timeout in seconds for GitHub API requests |

### Testing Strategy

- **URL parser tests** (`test_github_url_parser.py`): Pure unit tests, no I/O.
- **Client tests** (`test_github_client.py`): `httpx.AsyncClient` is patched with `unittest.mock` — no real network calls.
- **Sync endpoint tests** (`test_sync.py`): The `GitHubClient` dependency is replaced via `app.dependency_overrides[get_github_client]` — no real network calls. The real in-memory SQLite database and auth stack are exercised.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_NAME` | `codesage-api` | Service identifier |
| `APP_ENV` | `development` | `development`, `staging`, or `production` |
| `DEBUG` | `false` | Enable debug logs and docs |
| `LOG_LEVEL` | `INFO` | Root logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `SECRET_KEY` | *(required)* | 32+ character signing key for JWTs |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | JWT expiration duration in minutes |
| `DATABASE_URL` | *(optional)* | Full async DSN (`postgresql+asyncpg://...`) |
| `DB_HOST` / `DB_PORT` | `localhost:5432` | Granular DB connection host and port |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | `codesage` | DB credentials if `DATABASE_URL` is omitted |
| `GITHUB_TOKEN` | *(none)* | Optional GitHub PAT for increased rate limits |
| `GITHUB_REQUEST_TIMEOUT` | `10.0` | Timeout for GitHub API requests (seconds) |

---

## Development

### Run tests

```bash
pytest tests/ -v
```

### Lint & format

```bash
ruff check app/ tests/
ruff format app/ tests/
```

### Type checking

```bash
mypy app/
```

### Migrations

```bash
# Generate a new migration
alembic revision --autogenerate -m "describe your change"

# Apply migrations
alembic upgrade head

# Preview SQL (offline mode)
alembic upgrade head --sql
```

---

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app factory, lifespan, and route mounting
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── logging.py       # Structured logging configuration
│   │   └── security.py      # bcrypt password hashing and PyJWT token utilities
│   ├── api/
│   │   ├── deps.py          # FastAPI dependencies (get_current_user, get_github_client)
│   │   └── v1/
│   │       ├── router.py    # V1 root router
│   │       ├── health.py    # Health check endpoint
│   │       ├── auth.py      # Authentication endpoints
│   │       └── repositories.py # Repository CRUD + sync endpoints
│   ├── db/
│   │   ├── base.py          # SQLAlchemy DeclarativeBase
│   │   └── session.py       # Async engine & session factory
│   ├── github/
│   │   ├── client.py        # GitHub API HTTP client (httpx-based)
│   │   ├── exceptions.py    # Typed GitHub integration exception hierarchy
│   │   ├── schemas.py       # Internal GitHubRepoData Pydantic model
│   │   └── url_parser.py    # GitHub URL parser & SSRF protection
│   ├── models/
│   │   ├── user.py          # User ORM model
│   │   └── repository.py    # Repository ORM model (with GitHub metadata columns)
│   ├── schemas/
│   │   ├── user.py          # User request/response schemas
│   │   ├── auth.py          # Token schemas
│   │   └── repository.py    # Repository schemas (with GitHub metadata fields)
│   └── services/
│       ├── auth_service.py  # User & authentication business logic
│       └── repository_service.py # Repository business logic, authorization & sync
├── alembic/                 # Database migrations
│   └── versions/
│       ├── 0001_create_users_and_repositories_tables.py
│       └── 0002_add_github_metadata_to_repositories.py
├── tests/                   # Pytest test suite
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_repositories.py
│   ├── test_github_url_parser.py
│   ├── test_github_client.py
│   └── test_sync.py
├── pyproject.toml
└── .env.example
```
