from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.db.database import Base, engine

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event handler to ensure database schema exists on startup."""
    # Creates tables on startup if they do not exist.
    # Suitable for Milestone 2 development before schema migrations (Alembic) are introduced.
    Base.metadata.create_all(bind=engine)
    yield
    
app = FastAPI(
    title="ReconAI",
    description="AI-Powered Payment Reconciliation & Exception Investigator",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/")
def read_root() -> dict[str, str]:
    return {
        "message": "ReconAI is running",
        "status": "active",
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
    }