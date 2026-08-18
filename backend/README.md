# CodeSage AI — Backend

FastAPI service powering the CodeSage AI platform.

## Requirements

- Python 3.12+
- PostgreSQL 15+

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
# Edit .env with your local database credentials

# 5. Run database migrations
alembic upgrade head

# 6. Start the development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at <http://localhost:8000>.
Interactive docs: <http://localhost:8000/docs>

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health check |

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

### Create a new migration

```bash
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

## Project structure

```
backend/
├── app/
│   ├── main.py          # FastAPI application factory
│   ├── core/
│   │   ├── config.py    # Settings (pydantic-settings)
│   │   └── logging.py   # Logging configuration
│   ├── api/
│   │   └── v1/
│   │       ├── router.py
│   │       └── health.py
│   ├── db/
│   │   ├── base.py      # SQLAlchemy declarative base
│   │   └── session.py   # Async engine & session factory
│   ├── models/          # SQLAlchemy ORM models (future)
│   ├── schemas/         # Pydantic request/response schemas (future)
│   └── services/        # Business logic layer (future)
├── alembic/             # Database migrations
├── tests/
├── pyproject.toml
└── .env.example
```
