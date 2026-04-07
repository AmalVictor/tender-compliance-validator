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
 
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
 
from config import settings
from database import create_tables
from database_decisions import HumanDecision  # registers table with metadata
from routers import audit, chat, documents, projects, decisions
 

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

# ── CORS (allow Next.js and Streamlit frontends) ──────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url, exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(projects.router, prefix="/api/projects", tags=["Projects"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(audit.router, prefix="/api/audit", tags=["Audit"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(decisions.router, prefix="/api/decisions", tags=["Decisions"])

_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


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
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.APP_ENV == "development",
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    start()