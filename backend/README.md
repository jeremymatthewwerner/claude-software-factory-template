# Backend API

A FastAPI-based backend for your Claude Software Factory project.

## Quick Start

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Run development server
uv run uvicorn app.main:app --reload --port 8000

# Open API docs
open http://localhost:8000/docs
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (used by DevOps monitoring) |
| GET | `/api/version` | API version info |
| GET | `/api/hello` | Hello World greeting |
| POST | `/api/hello` | Personalized greeting |

## Development

```bash
# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=app --cov-report=term-missing

# Lint code
uv run ruff check .

# Format code
uv run ruff format .

# Type check
uv run mypy .

# Security audit
uv run pip-audit
```

## Project Structure

```
backend/
├── app/
│   ├── __init__.py    # Package init with version
│   ├── main.py        # FastAPI application
│   └── py.typed       # PEP 561 marker
├── tests/
│   ├── __init__.py
│   ├── conftest.py    # Test fixtures
│   └── test_main.py   # API tests
├── pyproject.toml     # Project config
└── README.md          # This file
```

## Extending the API

1. **Add new endpoints** in `app/main.py` or create new router modules
2. **Add models** using Pydantic for request/response validation
3. **Add tests** in `tests/` - aim for 70%+ coverage
4. **Run quality gates** before committing

Example adding a new router:

```python
# app/routers/items.py
from fastapi import APIRouter

router = APIRouter(prefix="/api/items", tags=["Items"])

@router.get("/")
async def list_items():
    return []

# app/main.py
from app.routers import items
app.include_router(items.router)
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Server port | 8000 |
| `ENVIRONMENT` | dev/staging/production | development |
| `DATABASE_URL` | Database connection string | (none) |

## Deployment

This app is configured to deploy on Railway. See the root README for deployment instructions.
