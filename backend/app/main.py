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

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
