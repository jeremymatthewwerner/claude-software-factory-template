"""
Software Factory Backend API

A simple FastAPI application that demonstrates the structure expected by
the Claude Software Factory. This serves as a starting point for your
backend development.

Endpoints:
- GET /health - Health check for monitoring
- GET /api/version - API version info
- GET /api/hello - Hello World endpoint
- POST /api/hello - Personalized greeting
"""

import math
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import __version__

# Create FastAPI app
app = FastAPI(
    title="Software Factory API",
    description="Backend API powered by Claude Software Factory",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Local frontend dev
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- Exception handlers -----


def _replace_non_finite(value: Any) -> Any:
    """Recursively replace non-finite floats (``NaN``/``inf``/``-inf``) with strings.

    Python's ``json`` parser accepts the non-standard JSON tokens ``NaN``,
    ``Infinity`` and ``-Infinity`` (RFC 8259 forbids them). When such a token
    reaches a request body, Pydantic rejects the resulting non-finite ``float``,
    but the rejected value is then echoed back inside the 422 ``detail[].input``
    field — and ``JSONResponse`` serializes with ``allow_nan=False``, so encoding
    the non-finite float raises and the request 500s. Converting these values to
    their ``repr`` string (``"nan"``/``"inf"``/``"-inf"``) makes the payload
    JSON-encodable so the client gets a clean 422 instead of a server crash.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _replace_non_finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_non_finite(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return a clean 422 for invalid request bodies — never a 500.

    Delegates to FastAPI's default handler so the response is byte-identical for
    the overwhelmingly common case. The default handler only fails when the
    offending input contains a non-finite float (``NaN``/``Infinity``), which it
    cannot JSON-encode; in that case we rebuild the same payload with those
    values sanitized so the client still receives a well-formed 422.
    """
    try:
        return await request_validation_exception_handler(request, exc)
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"detail": _replace_non_finite(jsonable_encoder(exc.errors()))},
        )


# ----- Models -----


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    timestamp: str


class VersionResponse(BaseModel):
    """Version information response."""

    version: str
    name: str
    environment: str


class HelloRequest(BaseModel):
    """Request model for personalized greeting."""

    name: str


class HelloResponse(BaseModel):
    """Response model for greeting."""

    message: str
    timestamp: str


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: str


# ----- Endpoints -----


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> dict[str, Any]:
    """
    Health check endpoint.

    Used by:
    - DevOps Agent for production monitoring (every 5 minutes)
    - Load balancers for health checks
    - CI/CD for deployment verification
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/api/version", response_model=VersionResponse, tags=["System"])
async def get_version() -> dict[str, Any]:
    """
    Get API version information.

    Returns the current version of the API, useful for:
    - Deployment verification
    - Client compatibility checks
    - Debugging production issues
    """
    return {
        "version": __version__,
        "name": "software-factory-api",
        "environment": "development",  # TODO: Read from environment variable
    }


@app.get("/api/hello", response_model=HelloResponse, tags=["Hello World"])
async def hello_world() -> dict[str, Any]:
    """
    Simple Hello World endpoint.

    This is a basic example endpoint. Replace with your actual API logic.
    """
    return {
        "message": "Hello, World! Welcome to your Software Factory.",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.post("/api/hello", response_model=HelloResponse, tags=["Hello World"])
async def hello_name(request: HelloRequest) -> dict[str, Any]:
    """
    Personalized greeting endpoint.

    Args:
        request: Contains the name to greet

    Returns:
        A personalized greeting message
    """
    return {
        "message": f"Hello, {request.name}! Welcome to your Software Factory.",
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ----- Example: Additional endpoints you might add -----
#
# @app.post("/api/auth/register")
# async def register(user: UserCreate) -> Token:
#     """Register a new user."""
#     ...
#
# @app.get("/api/items")
# async def list_items() -> list[Item]:
#     """List all items."""
#     ...
#
# See FastAPI docs: https://fastapi.tiangolo.com/
