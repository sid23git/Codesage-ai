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

*(Endpoints are also accessible under the `/api/v1` prefix, e.g. `/api/v1/auth/login`).*

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
│   │   ├── deps.py          # FastAPI dependencies (get_current_user)
│   │   └── v1/
│   │       ├── router.py    # V1 root router
│   │       ├── health.py    # Health check endpoint
│   │       ├── auth.py      # Authentication endpoints
│   │       └── repositories.py # Repository CRUD endpoints
│   ├── db/
│   │   ├── base.py          # SQLAlchemy DeclarativeBase
│   │   └── session.py       # Async engine & session factory
│   ├── models/
│   │   ├── user.py          # User ORM model
│   │   └── repository.py    # Repository ORM model
│   ├── schemas/
│   │   ├── user.py          # User request/response schemas
│   │   ├── auth.py          # Token schemas
│   │   └── repository.py    # Repository schemas
│   └── services/
│       ├── auth_service.py  # User & authentication business logic
│       └── repository_service.py # Repository business logic & authorization
├── alembic/                 # Database migrations
│   └── versions/
├── tests/                   # Pytest test suite
├── pyproject.toml
└── .env.example
```
