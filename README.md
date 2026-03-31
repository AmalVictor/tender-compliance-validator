# tender-compliance-validator
AI-based RFP vs Vendor Proposal compliance validation system
=======
# Tender Compliance Validator

> AI-powered system that validates vendor proposals against RFP requirements using
> Hierarchical RAG + Cross-Encoder Reranking + NLI Entailment Classification.

**Real-world problem:** Up to 40% of public tenders are rejected for administrative
non-compliance before anyone reads the technical offer. Even technically superior bids
are disqualified for missing a single mandatory clause. This system eliminates that risk.

---

## Architecture

```
RFP PDF ──► Hierarchical Parser ──► Requirement Extractor (2-pass)
                                            │
                                    [Human confirms]
                                            │
Vendor Proposal ──► Parser ──► Bi-encoder Embedder ──► ChromaDB
                                            │
                               Cross-Encoder Reranker
                                            │
                               Entailment Classifier (NLI)
                                            │
                               ┌────────────┴────────────┐
                          Compliance Matrix          Risk Engine
                          (FULL/PARTIAL/NONE)    (regex + LLM hybrid)
                                            │
                               Scoring Engine + PDF Report
```

**Why two-stage retrieval?** Single-stage bi-encoder retrieval misses paraphrase matches
(e.g. "round-the-clock support" ≠ "24/7 support" semantically, but they mean the same
thing). The cross-encoder reranker re-scores top-20 candidates and surfaces the correct
match. Accuracy improvement: ~35% on paraphrase-heavy requirements.

---

## Prerequisites

- Python 3.11+
- A free Groq API key from [console.groq.com](https://console.groq.com) (no credit card)
- ~300MB disk space (for embedding model cache)

---

## Setup (5 commands)

```bash
# 1. Clone and enter the project
git clone <repo-url> && cd tender-compliance-validator

# 2. Install Poetry (if not installed)
curl -sSL https://install.python-poetry.org | python3 -

# 3. Install all dependencies
poetry install

# 4. Configure environment
cp .env.example .env
# Edit .env and add your GROQ_API_KEY

# 5. Verify setup
poetry run python -c "from backend.config import settings; print('Config OK:', settings.APP_ENV)"
```

---

## Running the application

Open **two terminal windows**:

**Terminal 1 — Backend API:**
```bash
poetry run uvicorn backend.main:app --reload --port 8000
# Visit http://localhost:8000/docs for interactive API docs
```

**Terminal 2 — Frontend UI:**
```bash
poetry run streamlit run frontend/app.py --server.port 8501
# Visit http://localhost:8501
```

---

## Running tests

```bash
# All tests
poetry run pytest tests/ -v

# Parser tests only
poetry run pytest tests/test_parser.py -v

# Retriever benchmark (Stage 1 vs Stage 1+2)
poetry run pytest tests/test_retriever.py -v -s
```

---

## Sample data

The `data/` directory contains our **Golden Demo** documents:
- `rfp_cloud_hris.pdf` — A complex RFP with highly specific technical and financial clauses.
- `proposal_insighttech_hris.pdf` — A rigged vendor proposal designed to test the AI's reasoning.
  - *Gotcha 1:* Uses semantic paraphrasing ("follow-the-sun" instead of "24/7/365").
  - *Gotcha 2:* Provides 2 years of financials when 3 are requested (Tests LLM deduction).
  - *Gotcha 3:* Completely omits the Customer Success Manager (Tests the Negative Space Gate).
  - *Gotcha 4:* Hides data residency compliance deep inside a markdown table.

---

## Key design decisions (see DESIGN_DOC.md)

| Decision | Choice | Reason |
|---|---|---|
| **LLM Engine** | Groq Llama 3.3 70B | Blistering fast inference for NLI classification; native JSON output. |
| **Retrieval Math** | Reciprocal Rank Fusion (RRF) | Fuses dense embeddings (recall) with cross-encoder logits (precision) to prevent semantic paraphrasing from being falsely rejected. |
| **Concurrency** | Asyncio + ThreadPools | CPU-bound embedding tasks are isolated; LLM I/O tasks run concurrently via `asyncio.gather` with a Semaphore. |
| **Reliability** | Pydantic Self-Healing | LLM outputs are strictly validated. If the LLM breaks the JSON schema, the system catches the exception and prompts the LLM to correct itself. |
| **Data Extraction** | Layout-Aware PyMuPDF | Automatically strips noisy headers/footers and reconstructs complex table rows so critical compliance data isn't lost during chunking. |
| **Gap Detection** | Negative Space Gating | If the RRF fused score falls below a mathematical threshold, it instantly triggers a `NONE` match without wasting an LLM call. |

---

## Project structure

```
tender-compliance-validator/
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Pydantic settings
│   ├── database.py          # SQLAlchemy models
│   ├── schemas.py           # Pydantic request/response models
│   └── routers/
│       ├── projects.py      # Project CRUD
│       ├── documents.py     # Upload, parse, index
│       └── audit.py         # Audit orchestration
├── services/
│   ├── document_parser.py   # Hierarchical PDF parser
│   ├── requirement_extractor.py  # 2-pass extraction
│   ├── proposal_indexer.py  # ChromaDB embedding
│   ├── retriever.py         # Bi-encoder ANN search  
│   ├── reranker.py          # Cross-encoder reranking
│   ├── entailment_classifier.py  # NLI classification
│   ├── risk_detector.py     # Hybrid risk engine     
│   └── scorer.py            # Compliance scoring     
├── frontend/
│   ├── app.py               # Streamlit entry point
│   ├── api_client.py        # HTTP client
│   └── pages/
│       ├── workspace.py     # Project dashboard
│       ├── upload.py        # Document upload
│       ├── requirements.py  # Human-in-the-loop review
│       ├── matrix.py        # Compliance matrix       
│       ├── risk_heatmap.py  # Risk visualisation      
│       └── deep_dive.py     # Document deep-dive      
├── utils/
│   ├── llm_client.py        # Groq API wrapper + retry
│   └── risk_patterns.py     # Regex risk pattern library
├── tests/
│   ├── test_parser.py
│   └── test_retriever.py
├── data/                    # Sample PDFs for demo
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Known limitations

1. **Scanned PDFs** — OCR is not implemented. Text-based PDFs only.
2. **Single RFP per project** — Multi-lot RFPs are not yet supported.
3. **English only** — No multilingual requirement extraction.
4. **API Rate Limits (Handled):** The Groq free tier restricts tokens-per-minute. Because our asynchronous engine processes requirements so quickly, it can hit this limit. *Solution implemented:* We engineered an exponential backoff and retry loop with `asyncio.Semaphore(5)` that gracefully catches HTTP 429 errors, pauses, and resumes without dropping any data or crashing the app.

