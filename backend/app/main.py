from fastapi import FastAPI

app = FastAPI(
    title="ReconAI",
    description="AI-Powered Payment Reconciliation & Exception Investigator",
    version="0.1.0",
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