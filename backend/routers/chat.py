"""
chat.py
"""
from __future__ import annotations
import asyncio, json, logging
from typing import Annotated, Any, AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from config import settings
from schemas import ChatMessage
from services.proposal_indexer import ProposalIndexer
from utils.llm_client import acall_smart_messages, acall_smart_messages_stream

logger = logging.getLogger(__name__)
router = APIRouter()

CHAT_TOP_K_PER_VENDOR = 4
CHAT_TOP_K_FINAL      = 8
MAX_EVIDENCE_CHARS    = 600


def get_proposal_indexer() -> ProposalIndexer:
    return ProposalIndexer()


# ── Schemas ───────────────────────────────────────────────────────────────────



class MultiVendorChatRequest(BaseModel):
    project_id: int
    document_ids: list[int] = Field(default_factory=list)
    document_id: int | None = None
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    
    audit_summary: str | None = Field(default=None)


class RichChatCitation(BaseModel):
    citation_index: int
    vendor_name: str
    vendor_document_id: int
    section_title: str | None = None
    page_number: int | None = None
    text: str


class MultiVendorChatResponse(BaseModel):
    reply: str
    citations: list[RichChatCitation] = Field(default_factory=list)
    vendors_searched: list[str] = Field(default_factory=list)


# ── Intent classification ─────────────────────────────────────────────────────

_COMPARE_KEYWORDS = {
    "compare","comparison","versus","vs","vs.","better","best",
    "which vendor","all vendors","across vendors","side by side",
    "rank","ranking","recommend","recommendation","winner",
    "highest","lowest","strongest","weakest",
}

_ANALYTICAL_KEYWORDS = {
    "risk profile","lowest risk","highest risk","risk score",
    "compliance score","most compliant","least compliant",
    "critical risk","failed requirement","mandatory requirement",
    "which vendor should","award recommendation","recommend awarding",
    "compliance rate","pass rate","failed","disqualif",
}

def classify_intent(message: str, vendor_names: list[str] | None = None) -> str:
    """Returns ANALYTICAL | COMPARE | SINGLE_VENDOR | GENERAL."""
    lower = message.lower()
    if any(kw in lower for kw in _ANALYTICAL_KEYWORDS):
        return "ANALYTICAL"
    if any(kw in lower for kw in _COMPARE_KEYWORDS):
        return "COMPARE"
    if vendor_names:
        for name in vendor_names:
            for word in name.lower().split():
                if len(word) >= 4 and word in lower:
                    return "SINGLE_VENDOR"
    return "GENERAL"


# ── Vendor discovery ──────────────────────────────────────────────────────────

def _resolve_document_ids(request: MultiVendorChatRequest, indexer: ProposalIndexer) -> list[tuple[int, str]]:
    from services.proposal_indexer import collection_name
    ids = list(request.document_ids)
    if not ids and request.document_id:
        ids = [request.document_id]
    if ids:
        result = []
        for doc_id in ids:
            cname = collection_name(request.project_id, doc_id)
            try:
                coll = indexer.client.get_collection(cname)
                meta = coll.get(limit=1, include=["metadatas"])
                vendor_name = (meta.get("metadatas") or [{}])[0].get("vendor_name") or f"Vendor {doc_id}"
            except Exception as e:
                logger.warning("Could not fetch collection for doc_id=%s: %s", doc_id, e)
                vendor_name = f"Vendor {doc_id}"
            result.append((doc_id, vendor_name))
        return result
    prefix = f"proj{request.project_id}_doc"
    result = []
    try:
        for coll_obj in indexer.client.list_collections():
            name = coll_obj.name if hasattr(coll_obj, "name") else str(coll_obj)
            if name.startswith(prefix):
                doc_id_str = name[len(prefix):]
                if doc_id_str.isdigit():
                    doc_id = int(doc_id_str)
                    try:
                        coll = indexer.client.get_collection(name)
                        meta = coll.get(limit=1, include=["metadatas"])
                        vendor_name = (meta.get("metadatas") or [{}])[0].get("vendor_name") or f"Vendor {doc_id}"
                        result.append((doc_id, vendor_name))
                    except Exception as e:
                        logger.warning("Could not retrieve metadata for %s: %s", name, e)
    except Exception as e:
        logger.error("Could not list collections: %s", e)
    return result


# ── Retrieval ─────────────────────────────────────────────────────────────────

async def _retrieve_for_vendor(indexer, query, project_id, doc_id, vendor_name, top_k):
    loop = asyncio.get_event_loop()
    try:
        chunks = await loop.run_in_executor(
            None,
            lambda: indexer.retrieve_hybrid(query_text=query, project_id=project_id, document_id=doc_id, top_k=top_k),
        )
    except ValueError:
        logger.warning("Collection not found for doc_id=%s, skipping.", doc_id)
        return []
    for chunk in chunks:
        chunk["vendor_name"] = vendor_name
        chunk["vendor_document_id"] = doc_id
    return chunks


async def retrieve_multi_vendor(indexer, query, project_id, vendor_docs, top_k_per_vendor=CHAT_TOP_K_PER_VENDOR, top_k_final=CHAT_TOP_K_FINAL):
    tasks = [_retrieve_for_vendor(indexer, query, project_id, doc_id, vname, top_k_per_vendor) for doc_id, vname in vendor_docs]
    per_vendor = await asyncio.gather(*tasks)
    all_chunks = [c for chunks in per_vendor for c in chunks]
    all_chunks.sort(key=lambda x: float(x.get("retrieval_rrf", 0.0)), reverse=True)
    seen: set[int] = set(); top: list = []; rest: list = []
    for c in all_chunks:
        vid = c["vendor_document_id"]
        (top if vid not in seen else rest).append(c)
        seen.add(vid)
    return (top + rest)[:top_k_final]




# ── Prompt construction ───────────────────────────────────────────────────────

def _build_system_prompt(vendor_sections: dict, intent: str, audit_summary: str | None = None) -> str:
    # Section 1: audit results
    if audit_summary:
        audit_block = f"## STRUCTURED AUDIT RESULTS\n{audit_summary}"
    else:
        audit_block = (
            "## STRUCTURED AUDIT RESULTS\n"
            "Warning: No structured audit results were provided. "
            "Answer risk/compliance questions from raw evidence only."
        )

    # Section 2: raw evidence
    evidence_lines = ["## VENDOR EVIDENCE (raw proposal passages)"]
    citation_counter = 1
    for vendor_name, chunks in vendor_sections.items():
        evidence_lines.append(f"\n### {vendor_name}\n")
        for chunk in chunks:
            title = chunk.get("section_title") or "Unknown section"
            page  = chunk.get("page_number", "?")
            text  = chunk["text"][:MAX_EVIDENCE_CHARS]
            evidence_lines.append(f"[Citation {citation_counter}] (Section: {title}, Page {page})\n{text}\n")
            chunk["_citation_index"] = citation_counter
            citation_counter += 1
    evidence_block = "\n".join(evidence_lines)

    intent_instruction = {
        "ANALYTICAL": "Answer PRIMARILY from the STRUCTURED AUDIT RESULTS table. Do NOT derive compliance conclusions from raw passages.",
        "COMPARE": "Lead with audit table scores and risk counts, then support with evidence citations using a markdown table. Never attribute evidence from one vendor to another.",
        "SINGLE_VENDOR": "Focus on the specific vendor's audit row and their evidence sections.",
        "GENERAL": "Use audit results as primary source and evidence as secondary support.",
    }.get(intent, "Use audit results as primary source and evidence as support.")

    return f"""You are 'TenderAI', an expert procurement and legal assistant.

QUERY INTENT: {intent}
INSTRUCTIONS: {intent_instruction}

RULES:
1. Use STRUCTURED AUDIT RESULTS as the primary source for compliance/risk conclusions.
2. Use VENDOR EVIDENCE as supporting context and for direct quotes only.
3. Always attribute claims to specific vendors by name.
4. Use [Citation N] markers when drawing on evidence passages.
5. If the answer is not findable, say: "I cannot find the answer to this in the provided documents."
6. For comparisons, use a markdown table.
7. Respond with a single JSON object: {{"reply": "<your markdown answer>"}}

---
{audit_block}
---
{evidence_block}
"""


# ── Core RAG pipeline ─────────────────────────────────────────────────────────

async def _run_rag(request: MultiVendorChatRequest, indexer: ProposalIndexer):
    vendor_docs = _resolve_document_ids(request, indexer)
    if not vendor_docs:
        raise HTTPException(status_code=400, detail="No indexed vendor documents found for this project.")

    vendor_names = [v for _, v in vendor_docs]
    intent       = classify_intent(request.message, vendor_names=vendor_names)
    logger.info("TenderAI chat: project=%s intent=%s vendors=%s q=%s",
                request.project_id, intent, vendor_names, request.message[:120])

    all_chunks = await retrieve_multi_vendor(indexer, request.message, request.project_id, vendor_docs)

    if not all_chunks and not request.audit_summary:
        return ("I cannot find relevant information in the indexed proposals for your question.", [], vendor_names)

    vendor_sections: dict[str, list[dict]] = {}
    for chunk in all_chunks:
        vendor_sections.setdefault(chunk["vendor_name"], []).append(chunk)

    system_prompt = _build_system_prompt(vendor_sections, intent, audit_summary=request.audit_summary or None)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in request.history[-6:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": request.message})

    try:
        raw = await acall_smart_messages(
            messages,
            max_tokens=settings.CHAT_MAX_TOKENS,
            temperature=settings.CHAT_LLM_TEMPERATURE,
            skip_cache=True,
        )
    except Exception as e:
        logger.exception("TenderAI LLM call failed: %s", e)
        raise HTTPException(status_code=502, detail="The language model could not complete this request.") from e

    reply_text = (raw.get("reply") or "").strip() if isinstance(raw, dict) else ""
    if not reply_text:
        reply_text = "I could not produce a structured answer. Please try again."

    citations = [
        RichChatCitation(
            citation_index=chunk["_citation_index"],
            vendor_name=chunk["vendor_name"],
            vendor_document_id=chunk["vendor_document_id"],
            section_title=chunk.get("section_title") or None,
            page_number=int(chunk["page_number"]) if chunk.get("page_number") else None,
            text=chunk["text"][:300],
        )
        for chunk in all_chunks if chunk.get("_citation_index") is not None
    ]
    return reply_text, citations, vendor_names


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=MultiVendorChatResponse)
async def chat_endpoint(request: MultiVendorChatRequest, indexer: Annotated[ProposalIndexer, Depends(get_proposal_indexer)]):
    try:
        if not request.message or not request.message.strip():
            raise HTTPException(status_code=400, detail="message field cannot be empty.")
        reply, citations, vendors = await _run_rag(request, indexer)
        return MultiVendorChatResponse(reply=reply, citations=citations, vendors_searched=vendors)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Chat API error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _stream_rag(request: MultiVendorChatRequest, indexer: ProposalIndexer) -> AsyncGenerator[str, None]:
    try:
        vendor_docs = _resolve_document_ids(request, indexer)
        if not vendor_docs:
            yield _sse({"type": "error", "message": "No indexed vendor documents found."})
            return
        vendor_names = [v for _, v in vendor_docs]
        yield _sse({"type": "vendors", "vendors": vendor_names})
        intent     = classify_intent(request.message, vendor_names=vendor_names)
        all_chunks = await retrieve_multi_vendor(indexer, request.message, request.project_id, vendor_docs)
        vendor_sections: dict[str, list[dict]] = {}
        for chunk in (all_chunks or []):
            vendor_sections.setdefault(chunk["vendor_name"], []).append(chunk)
        if not all_chunks and not request.audit_summary:
            yield _sse({"type": "token", "token": "I cannot find relevant information in the proposals."})
            yield _sse({"type": "done"}); return
        system_prompt = _build_system_prompt(vendor_sections, intent, audit_summary=request.audit_summary or None)
        messages = [{"role": "system", "content": system_prompt}]
        for msg in request.history[-6:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": request.message})
        accumulated = ""
        try:
            async for token in acall_smart_messages_stream(messages, max_tokens=settings.CHAT_MAX_TOKENS, temperature=settings.CHAT_LLM_TEMPERATURE):
                accumulated += token; yield _sse({"type": "token", "token": token})
        except NotImplementedError:
            raw = await acall_smart_messages(messages, max_tokens=settings.CHAT_MAX_TOKENS, temperature=settings.CHAT_LLM_TEMPERATURE)
            reply_text = (raw.get("reply") or "") if isinstance(raw, dict) else ""
            if reply_text.startswith("{"):
                try: reply_text = json.loads(reply_text).get("reply", reply_text)
                except Exception: pass
            yield _sse({"type": "token", "token": reply_text}); accumulated = reply_text
        citations_data = [
            {"citation_index": c["_citation_index"], "vendor_name": c["vendor_name"],
             "vendor_document_id": c["vendor_document_id"], "section_title": c.get("section_title"),
             "page_number": int(c["page_number"]) if c.get("page_number") else None, "text": c["text"][:300]}
            for c in all_chunks if c.get("_citation_index") is not None
        ]
        yield _sse({"type": "citations", "citations": citations_data})
        yield _sse({"type": "done"})
    except Exception as e:
        logger.exception("SSE stream error: %s", e)
        yield _sse({"type": "error", "message": str(e)})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/stream")
async def chat_stream_endpoint(request: MultiVendorChatRequest, indexer: Annotated[ProposalIndexer, Depends(get_proposal_indexer)]):
    return StreamingResponse(_stream_rag(request, indexer), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/health", tags=["Chat"])
async def chat_health():
    return {"status": "ok", "service": "tenderai-chat-v2", "multi_vendor": True, "audit_grounded": True}


@router.post("/test", tags=["Chat"])
async def chat_test_echo(request: MultiVendorChatRequest):
    return {"status": "request_received", "project_id": request.project_id, "message": request.message,
            "history_count": len(request.history), "document_ids": request.document_ids,
            "audit_summary_length": len(request.audit_summary) if request.audit_summary else 0}