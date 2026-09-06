"""
ReconAI - Main FastAPI Application Entrypoint.

Serves backend health APIs, reconciliation dashboard endpoints, and the UI frontend.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.dashboard import router as dashboard_router
from app.db.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Ensures database schema exists on application startup."""
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="ReconAI",
    description="AI-Powered Payment Reconciliation & Exception Investigator",
    version="0.10.0",
    lifespan=lifespan,
)

# Register API routers
app.include_router(dashboard_router)

# Mount static directory for dashboard UI assets
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
def read_root():
    """Serve the dashboard SPA if static index.html exists, else return API status."""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "message": "ReconAI is running",
        "status": "active",
        "dashboard_api": "/api/dashboard/summary",
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
    }