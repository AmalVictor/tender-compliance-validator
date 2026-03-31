"""
main.py
-------
FastAPI application entry point.
Wires together all routers, startup/shutdown events, and middleware.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.database import create_tables
from backend.routers import audit, documents, projects

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logger.info("Starting Tender Compliance Validator API...")

    # Ensure directories exist
    for directory in [settings.UPLOAD_DIR, settings.CHROMA_PERSIST_DIR, settings.HF_HOME]:
        Path(directory).mkdir(parents=True, exist_ok=True)
        logger.debug("Directory ready: %s", directory)

    # Create database tables
    await create_tables()
    logger.info("Database tables ready.")

    # Pre-warm the embedding model in background (avoids cold start on first request)
    # We do this lazily — the first indexing call will load it
    logger.info("API ready. Visit http://localhost:8000/docs for Swagger UI.")

    yield

    # Shutdown
    logger.info("Shutting down...")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Tender Compliance Validator",
    description=(
        "AI-powered system for validating vendor proposals against RFP requirements. "
        "Uses hierarchical RAG + cross-encoder reranking + NLI entailment."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (allow Streamlit frontend) ──────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url, exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(projects.router, prefix="/api/projects", tags=["Projects"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(audit.router, prefix="/api/audit", tags=["Audit"])


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "env": settings.APP_ENV,
        "groq_key_set": bool(settings.GROQ_API_KEY),
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def start():
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.APP_ENV == "development",
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    start()