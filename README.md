# TenderAI — Tender Compliance Validator

> **AI-powered procurement intelligence that reads every clause so your legal team doesn't have to.**

![Next.js](https://img.shields.io/badge/Next.js-16-black?style=flat-square&logo=next.js)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?style=flat-square&logo=typescript)
![PostgreSQL](https://img.shields.io/badge/SQLite%2FPostgreSQL-async-336791?style=flat-square&logo=postgresql)
![ChromaDB](https://img.shields.io/badge/ChromaDB-0.5-FF6B35?style=flat-square)
![Groq](https://img.shields.io/badge/Groq-Llama%203.3%2070B-F55036?style=flat-square)

---

## Elevator Pitch

TenderAI transforms a process that takes procurement attorneys days into a sub-minute AI audit. Upload an RFP and competing vendor proposals — TenderAI extracts every contractual obligation, cross-references each one against every proposal with a two-stage retrieval and LLM entailment pipeline, detects hidden legal and financial risks in vendor language, and delivers a colour-coded compliance matrix plus a fully-formatted PDF audit report that is ready to present to a board. It doesn't just surface what vendors said — it reasons about whether what they said actually satisfies what was required, flagging future-tense "we plan to comply" commitments as misses, not wins.

---

## The Problem

In enterprise procurement, Request for Proposal (RFP) documents are often 100+ pages of dense legal, technical, and financial requirements. 

Evaluating competing vendor bids against these RFPs is a manual nightmare:
* **High Failure Rates:** ~40% of bids are rejected for basic administrative non-compliance.
* **Extreme Bottlenecks:** Legal and procurement teams spend weeks manually cross-referencing clauses, delaying critical infrastructure projects.
* **Quadratic Complexity:** Tracking 5 vendors against 200 requirements creates 1,000 unique compliance checks, making human error near-certain.

---

## The Solution

TenderAI implements a full, end-to-end compliance intelligence pipeline:

1. **Document Ingestion** — PDFs are uploaded via a drag-and-drop interface. PyMuPDF extracts text blocks with spatial metadata (page number, bounding boxes, font size, bold flags). A patched sentence-continuation merger re-assembles clauses split across PDF layout blocks. An OCR fallback via Tesseract handles scanned pages. Tables are extracted and serialised row-by-row.

2. **Requirement Extraction (Two-Pass)** — The RFP is processed by a heuristic regex filter (obligation keywords: *shall*, *must*, *is required to*, etc.) that eliminates ~80% of body text without any LLM call. Surviving candidates are batch-classified by `llama-3.1-8b-instant` to produce a normalised intent statement, category (Technical / Legal / Financial / Administrative), criticality (Mandatory / Recommended / Informational), and a clause reference.

3. **Human-in-the-Loop Confirmation** — Every extracted requirement is stored with `is_confirmed=False`. Reviewers inspect, edit, or delete rows in the Requirements Review panel before any audit runs. Only confirmed requirements proceed. This gate makes the AI assistant, not decision-maker.

4. **Vector Indexing** — Each vendor proposal is chunked and embedded using `all-MiniLM-L6-v2` (sentence-transformers, local, zero cost per call) and stored in a per-`(project_id, document_id)` ChromaDB collection. Technical terms (ISO standards, SLAs, financial values) are extracted and stored as metadata for keyword-aware retrieval.

5. **Hybrid Retrieval + Cross-Encoder Reranking** — For every confirmed requirement, Stage 1 runs BM25 sparse retrieval and dense vector ANN search in parallel, fusing results with Reciprocal Rank Fusion (RRF). Stage 2 scores every `(requirement, passage)` pair jointly using `cross-encoder/ms-marco-MiniLM-L-6-v2`, which catches paraphrase matches that bi-encoders miss. A calibrated logistic fusion converts raw scores to a probability. Pairs below a minimum threshold are classified `NONE` without any LLM call — saving ~80% of token spend on clearly missing requirements.

6. **LLM Entailment Classification** — The top reranked passages are sent to `llama-3.3-70b-versatile` (Groq) with a strict typed prompt. The model must classify each pair as `FULL / PARTIAL / NONE / AMBIGUOUS` with an evidence quote, section reference, and explanation. A **temporal commitment guard** (regex + LLM rule) ensures "we intend to obtain ISO 27001 by Q4" is classified `NONE`, not `PARTIAL`. Pydantic v2 validates every LLM response; failed validations trigger up to 2 retry cycles with error context appended to the prompt.

7. **Risk Detection** — A hybrid engine scans proposal text for 15+ risk patterns across six categories: liability caps, scope creep language, price change clauses, obligation-weakening phrases, exit clauses, and vague commitments. Every regex hit is passed to the LLM for contextual confirmation and severity assessment (Low / Medium / High / Critical).

8. **Compliance Scoring** — A weighted formula scores each vendor: Mandatory+FULL=1.0, Mandatory+PARTIAL=0.5, Mandatory+AMBIGUOUS=0.3, Mandatory+NONE=0.0. Risk findings add a separate `risk_score` (Critical=4×, High=3×, Medium=2×, Low=1×). Traffic-light colours (green/amber/red) are computed from combined thresholds.

9. **Report Generation** — A multi-section PDF is generated with ReportLab: cover page with vendor score cards, executive summary with AI award recommendation, colour-coded compliance matrix, per-vendor scorecards with gap lists, risk findings sorted by severity, administrative eligibility checklist results, a timestamped human decision trail, and a verbatim evidence appendix.

---

## Key Features

| Feature | Description |
|---|---|
| **Two-Pass Requirement Extraction** | Heuristic regex pre-filter (instant, free) + LLM batch classification produces normalised, categorised, clause-referenced requirements |
| **Human-in-the-Loop Gate** | Requirements are locked behind a human confirmation step before any audit runs; individual edit/delete/confirm per row |
| **Hybrid BM25 + Vector Retrieval** | RRF fusion of sparse and dense ranking catches both exact-match technical terms and semantic paraphrases |
| **Cross-Encoder Reranking** | `ms-marco-MiniLM-L-6-v2` scores query-passage pairs jointly; ~35% improvement on paraphrase-heavy requirements |
| **Temporal Commitment Guard** | Regex + LLM rule detects future-tense compliance promises ("we plan to…", "upon award") and forces NONE classification |
| **Multi-Vendor Compliance Matrix** | Full requirement × vendor grid with status, confidence score, evidence quote, and section reference per cell |
| **Risk Heatmap** | Per-vendor risk severity cells across 5 contract risk dimensions for instant visual risk assessment |
| **Administrative Eligibility Check** | Deterministic scan for 9 required documents (tax clearance, BEE certificate, company registration, etc.) — no LLM needed |
| **Human Decision Trail** | Accept / Annotate / Override on any AI verdict; full timestamped log included in the exported PDF as a legally-defensible audit trail |
| **Multi-Vendor RAG Chatbot** | Intent-classified (`ANALYTICAL / COMPARE / SINGLE_VENDOR / GENERAL`) chat grounded on structured audit results and live vector retrieval from all vendors simultaneously |
| **Streaming Chat (SSE)** | Token-by-token streaming response via Server-Sent Events for real-time chat UX |
| **Traceability PDF Viewer** | Click any evidence find in the compliance matrix to jump directly to the highlighted passage in the original vendor PDF |
| **PDF Export** | 9-section professional audit report with cover page, matrix, scorecards, decision trail, evidence appendix, and methodology note — generated with ReportLab in ~2 seconds |
| **LLM Response Cache** | SHA-256 prompt hash → SQLite cache deduplicates identical LLM calls across re-runs |
| **OCR Fallback** | Pages with fewer than 50 text characters are rasterised and processed by Tesseract |

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Next.js 16 Frontend                          │
│  Projects · Workspace · Requirements Review · Compliance Matrix      │
│  Risk Heatmap · Deep Dive · Chatbot · PDF Traceability Viewer        │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ HTTP / SSE   localhost:3000 → :8000
┌────────────────────────────▼─────────────────────────────────────────┐
│                      FastAPI 0.115 Backend                           │
│                                                                      │
│  /api/projects  /api/documents  /api/audit  /api/chat  /api/decisions│
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                    Service Layer                               │  │
│  │  DocumentParser → RequirementExtractor → ProposalIndexer      │  │
│  │  Reranker → EntailmentClassifier → RiskDetector               │  │
│  │  AuditOrchestrator → ComplianceScorer → ReportGenerator       │  │
│  └───────────┬─────────────────────────────┬──────────────────────┘  │
│              │                             │                         │
│  ┌───────────▼───────────┐   ┌─────────────▼──────────────────────┐  │
│  │   SQLite (aiosqlite)  │   │  ChromaDB (persistent vector store) │  │
│  │  Projects · Documents │   │  per-(project, document) collection │  │
│  │  Requirements · Matches   │  all-MiniLM-L6-v2 embeddings        │  │
│  │  RiskFindings         │   │  BM25 + cosine + RRF fusion         │  │
│  │  HumanDecisions       │   └─────────────────────────────────────┘  │
│  └───────────────────────┘                                            │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │          Groq Cloud (llama-3.3-70b-versatile / llama-3.1-8b)    │ │
│  │  Requirement classification · Entailment · Risk evaluation      │ │
│  │  Chat grounding · LLM cache (SQLite SHA-256 hash)               │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

The frontend is a full Next.js 16 SPA with React Context for project state, a centralised typed API client, and CSS modules for component styling. The backend is an async FastAPI application with SQLAlchemy 2.0 async ORM, on-startup table creation, and a global exception handler. All LLM calls are gated behind a 3-slot async semaphore to avoid Groq rate limiting.

---

## Tech Stack

### Frontend
| | Technology |
|---|---|
| Framework | Next.js 16 (App Router) |
| Language | TypeScript 5 |
| PDF Viewer | `pdfjs-dist` 4.4 with bounding-box highlight overlay |
| HTTP Client | Native `fetch` with typed wrapper + `axios` |
| State | React Context (`ProjectContext`, `ToastContext`) |
| Styling | Vanilla CSS Modules + global design system |
| Streaming | Browser `EventSource` / SSE for chat |

### Backend
| | Technology |
|---|---|
| Framework | FastAPI 0.115 + Uvicorn |
| Language | Python 3.11 |
| ORM | SQLAlchemy 2.0 async (`aiosqlite`) |
| PDF Parsing | PyMuPDF (`fitz`) |
| OCR | Tesseract via `pytesseract` |
| Validation | Pydantic v2 |
| Config | `pydantic-settings` + `.env` |
| Report | ReportLab 4 |

### AI & ML
| | Technology |
|---|---|
| LLM Provider | Groq API |
| Smart Model | `llama-3.3-70b-versatile` (entailment, risk, chat) |
| Fast Model | `llama-3.1-8b-instant` (bulk requirement extraction) |
| Bi-Encoder | `sentence-transformers/all-MiniLM-L6-v2` (local) |
| Cross-Encoder | `cross-encoder/ms-marco-MiniLM-L-6-v2` (local) |
| Sparse Retrieval | BM25 via `rank-bm25` |
| Fusion | Reciprocal Rank Fusion (RRF) |

### Database & Vector Store
| | Technology |
|---|---|
| Relational DB | SQLite (async, via `aiosqlite`) |
| Vector Store | ChromaDB 0.5 (persistent, local) |
| LLM Cache | SQLite (SHA-256 prompt hash keyed) |

### DevTools
| | Technology |
|---|---|
| Package Manager | Poetry (backend) / npm (frontend) |
| Code Quality | Ruff + Black (Python), TypeScript strict mode |
| Testing | pytest + pytest-asyncio |

---

## How It Works — Step by Step

### 1. Create a Project
Navigate to the Projects page and click **New Project**. Enter the project name, optional tender reference number, contract value, client department, and submission due date. The project card tracks document count, requirement count, and audit status at a glance.

### 2. Upload the RFP
Inside the project Workspace, upload a PDF of the Request for Proposal as an `RFP` document type. The backend immediately parses it with PyMuPDF, extracting text blocks with page numbers and bounding boxes. Page/word counts are displayed in the workspace card.

### 3. Extract Requirements
Click **Extract Requirements**. The two-pass engine scans the RFP: first, a regex filter isolates obligation clauses; then, `llama-3.1-8b-instant` batch-classifies each candidate into category, criticality, clause reference, and a normalised intent statement. All extracted requirements arrive as unconfirmed rows.

### 4. Review and Confirm Requirements
Open the **Requirements Review** tab. Read each extracted requirement, edit the normalised intent if the AI misread the intent, adjust the category or criticality, and mark requirements as confirmed. Use **Confirm All** for bulk approval. Only confirmed requirements are used in the audit.

### 5. Upload Vendor Proposals
Back in the Workspace, upload one or more vendor proposal PDFs as `PROPOSAL` documents with a vendor name. Each proposal is parsed, chunked, embedded with `all-MiniLM-L6-v2`, and stored in its own ChromaDB collection. An administrative eligibility scan checks for 9 common required documents (tax clearance, VAT registration, BEE certificate, etc.) immediately on upload.

### 6. Run the Audit
Click **Run Audit** from the workspace or Dashboard. The `AuditOrchestrator` processes every `(requirement × vendor)` pair concurrently:
- Stage 1: Hybrid BM25 + dense vector retrieval returns top-20 candidate passages
- Stage 2: Cross-encoder reranks to top-5; logistic fusion computes a fused probability
- Below-threshold pairs are classified `NONE` without an LLM call
- Above-threshold pairs are classified by `llama-3.3-70b-versatile`
- Risk scanning runs concurrently on each proposal

Results are saved to the database and the project is marked `audit_complete`.

### 7. Explore the Compliance Matrix
The **Compliance Matrix** tab shows a full requirement × vendor grid. Every cell displays the compliance status (`FULL` / `PARTIAL` / `NONE` / `AMBIGUOUS`), confidence score, and evidence quote. Clicking a cell opens the **Deep Dive** panel with the full evidence passage, LLM explanation, and vendor document ID for traceability.

### 8. Investigate Risks
The **Risk Heatmap** maps every vendor against five risk dimensions (Liability Cap, Price/Scope, Obligations, IP/Data, Exit Terms) with severity colour coding. Clicking a cell navigates directly to the **Deep Dive** tab filtered to that vendor's risks, each showing the matched phrase, LLM-confirmed impact explanation, and source location.

### 9. Accept / Annotate / Override AI Verdicts
In the **Deep Dive** tab, reviewers can Accept (confirm the AI got it right), Annotate (add a note without changing the verdict), or Override (change the verdict to a different status with a mandatory justification note). Every action is timestamped, attributed to a reviewer name, and stored immutably in the `human_decisions` table.

### 10. Chat with Your Documents
The **TenderAI Chatbot** allows free-form questions grounded on the full audit: "Which vendor presents the highest liability risk?", "Compare all vendors on data security requirements", "Does Vendor B address the 24/7 uptime SLA?". The system classifies query intent (`ANALYTICAL / COMPARE / SINGLE_VENDOR / GENERAL`), retrieves from all indexed proposals simultaneously, and builds a structured system prompt combining the full audit summary table and raw evidence passages. Responses stream token-by-token via SSE with numbered citations traceable to source passages.

### 11. Export the PDF Audit Report
Click **Download Report** from the Dashboard. A 9-section PDF is generated: Cover Page → Executive Summary (with AI award recommendation) → Compliance Matrix → Vendor Scorecards → Risk Findings → Admin Eligibility → Human Decision Trail → Evidence Appendix → Methodology Note. The report is production-ready and marked CONFIDENTIAL.

---

## Setup Instructions

### Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- [Poetry](https://python-poetry.org/docs/#installation)
- A [Groq API Key](https://console.groq.com/) (free tier is sufficient for testing)
- Tesseract OCR (optional — required only for scanned PDFs)
  - Windows: download the installer from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
  - Ubuntu: `sudo apt install tesseract-ocr`
  - macOS: `brew install tesseract`

---

### Backend Setup

```bash
# 1. Clone the repository
git clone https://github.com/your-org/tender-compliance.git
cd tender-compliance

# 2. Install Python dependencies
poetry install

# 3. Create the environment file
cp .env.example .env
# Then edit .env and add your GROQ_API_KEY

# 4. Run the FastAPI server
poetry run start-backend
# Or directly:
poetry run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Database tables are created automatically on first startup. No migration tool is required.

The API is available at `http://localhost:8000` and the interactive Swagger UI at `http://localhost:8000/docs`.

---

### Frontend Setup

```bash
# From the repository root
cd frontend

# 1. Install dependencies
npm install

# 2. Create the frontend environment file
echo "NEXT_PUBLIC_API_URL=http://localhost:8000/api" > .env.local

# 3. Start the development server
npm run dev
```

The frontend is available at `http://localhost:3000`.

---

### Running Both Together

Open two terminals:

```bash
# Terminal 1 — Backend
poetry run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend
cd frontend && npm run dev
```

Then open `http://localhost:3000`.

---

## Environment Variables

### Backend (`.env` in project root)

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | **Yes** | — | Groq Cloud API key for LLM inference |
| `GEMINI_API_KEY` | No | `null` | Reserved; not used in current pipeline |
| `SMART_MODEL` | No | `llama-3.3-70b-versatile` | Groq model for entailment, risk, and chat |
| `FAST_MODEL` | No | `llama-3.1-8b-instant` | Groq model for bulk requirement extraction |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///./tender_compliance.db` | SQLAlchemy async DB URL |
| `CHROMA_PERSIST_DIR` | No | `./chroma_db` | Directory for ChromaDB on-disk persistence |
| `HF_HOME` | No | `./model_cache` | Cache directory for Hugging Face models |
| `APP_ENV` | No | `development` | Controls SQL echo and reload mode |
| `LOG_LEVEL` | No | `INFO` | Python logging level |
| `UPLOAD_DIR` | No | `./uploads` | Directory for uploaded PDF files |
| `MAX_FILE_SIZE_MB` | No | `50` | Maximum upload size in megabytes |
| `BATCH_SIZE` | No | `10` | LLM batch size for requirement extraction |
| `MAX_RETRIES` | No | `3` | LLM retry attempts on validation failure |
| `RATE_LIMIT_SLEEP` | No | `0.5` | Seconds to sleep between LLM API calls |
| `TOP_K_RETRIEVAL` | No | `20` | Candidate passages returned by Stage 1 retrieval |
| `TOP_K_RERANK` | No | `5` | Top passages passed to the entailment LLM |
| `PROBABILITY_NONE_THRESHOLD` | No | `0.05` | Minimum fused probability to trigger LLM call |
| `CHAT_LLM_TEMPERATURE` | No | `0.0` | Temperature for chatbot LLM calls |
| `CHAT_MAX_TOKENS` | No | `800` | Max tokens per chatbot response |
| `ANONYMIZED_TELEMETRY` | No | `false` | Disables ChromaDB anonymous telemetry |

### Frontend (`.env.local` in `frontend/`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | No | `http://localhost:8000/api` | Base URL for all FastAPI backend calls |

---

## API Overview

All endpoints are prefixed with `/api`. Full interactive documentation is available at `/docs` (Swagger UI) and `/redoc`.

| Router | Prefix | Description |
|---|---|---|
| **Projects** | `/api/projects` | CRUD for tender review projects; includes document and requirement counts per project |
| **Documents** | `/api/documents` | Upload, parse, and index PDF documents (RFP and proposals); requirement extraction trigger; bulk-confirm; admin eligibility check results; inline PDF file serving |
| **Audit** | `/api/audit` | Pipeline status polling; run full audit; retrieve structured results (compliance matrix, risk findings, vendor scores); export PDF audit report |
| **Chat** | `/api/chat` | Multi-vendor RAG chat (non-streaming JSON and SSE streaming); intent classification; citation-grounded responses with audit context |
| **Decisions** | `/api/decisions` | Record Accept / Annotate / Override decisions on individual match verdicts; retrieve decision history per match and per project |
| **Health** | `/health` | Liveness check; returns `{"status": "ok"}` with environment and API key status |

---


## Project Structure

```
tender-compliance/
│
├── backend/                        # FastAPI application
│   ├── main.py                     # App factory, router wiring, startup events
│   ├── config.py                   # Centralised settings (pydantic-settings)
│   ├── database.py                 # SQLAlchemy 2.0 async ORM models and enums
│   ├── database_decisions.py       # HumanDecision table (Accept/Annotate/Override)
│   ├── schemas.py                  # Pydantic v2 request/response schemas
│   └── routers/
│       ├── projects.py             # Project CRUD endpoints
│       ├── documents.py            # Upload, parse, index, requirements endpoints
│       ├── audit.py                # Audit run, results, PDF export endpoints
│       ├── chat.py                 # Multi-vendor RAG chat + SSE streaming
│       └── decisions.py            # Human decision recording and retrieval
│
├── services/                       # Core AI/ML pipeline services
│   ├── document_parser.py          # Hierarchical PDF parser (PyMuPDF + OCR)
│   ├── requirement_extractor.py    # Two-pass extraction + admin eligibility check
│   ├── proposal_indexer.py         # ChromaDB indexing + hybrid BM25+vector retrieval
│   ├── reranker.py                 # Cross-encoder Stage 2 reranking with logistic fusion
│   ├── entailment_classifier.py    # LLM entailment (FULL/PARTIAL/NONE/AMBIGUOUS)
│   ├── risk_detector.py            # Hybrid regex + LLM risk detection engine
│   ├── audit_orchestrator.py       # Full pipeline orchestration per project
│   ├── scorer.py                   # Weighted compliance and risk scoring
│   └── report_generator.py         # 9-section ReportLab PDF generation
│
├── utils/
│   ├── llm_client.py               # Groq API wrappers (sync/async/streaming + cache)
│   └── risk_patterns.py            # 15+ regex risk pattern definitions
│
├── frontend/                       # Next.js 16 frontend
│   ├── app/
│   │   ├── layout.tsx              # Root layout with ToastContext
│   │   ├── page.tsx                # Login / home entry page
│   │   ├── projects/               # Projects list page
│   │   │   └── ProjectsClient.tsx  # Project cards, create modal
│   │   └── dashboard/[projectId]/  # Per-project dashboard
│   │       └── DashboardClient.tsx # Tab orchestration, audit status, summary KPIs
│   ├── components/
│   │   ├── Workspace.tsx           # Document upload and pipeline status manager
│   │   ├── RequirementsReview.tsx  # Editable requirements table with confirm/delete
│   │   ├── ComplianceMatrix.tsx    # Requirement × vendor compliance grid
│   │   ├── RiskHeatmap.tsx         # Vendor × risk-type severity heatmap
│   │   ├── DeepDive.tsx            # Per-match evidence inspector + decision buttons
│   │   ├── Chatbot.tsx             # Multi-vendor RAG chat with streaming
│   │   ├── TracePdfViewerContent.tsx  # PDF.js viewer with bounding-box highlights
│   │   ├── Sidebar.tsx             # Navigation sidebar
│   │   ├── TopNav.tsx              # Top navigation bar
│   │   └── StatusBadge.tsx         # Compliance status pill component
│   ├── lib/
│   │   ├── api.ts                  # Full typed FastAPI client + data transformers
│   │   └── chat-stream.ts          # SSE streaming client for chat
│   ├── context/
│   │   ├── ProjectContext.tsx      # Global project state provider
│   │   └── ToastContext.tsx        # Global toast notification system
│   └── types/index.ts              # Shared TypeScript types mirroring backend schemas
│
├── pyproject.toml                  # Poetry dependencies and scripts
├── .env                            # Environment variables (not committed)
└── chroma_db/                      # ChromaDB persistent vector storage
```

--- 

## Future Production Architecture
While this prototype successfully demonstrates the core AI reasoning and traceability engine, a production deployment would require the following architectural upgrades:

* **Authentication & RBAC:** Implement OAuth2/NextAuth to secure the backend API routes and scope projects to specific organizational tenants.
* **Asynchronous Task Queues:** Move the `audit_orchestrator.py` LLM classification loop from FastAPI background tasks to a dedicated Celery/Redis queue for horizontal scaling under heavy load.
* **Optimized File Ingestion:** Stream large PDF uploads directly to an S3 bucket via presigned URLs instead of buffering them in FastAPI's memory.
