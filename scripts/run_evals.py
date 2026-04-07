"""
run_evals.py
------------
Baseline evaluation harness for the Golden Demo project.

This script runs requirement-level compliance predictions for a single
project/vendor pair and scores them against hardcoded ground truth labels.
It is intentionally standalone and does not modify core service code.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from sqlalchemy import select

from backend.database import AsyncSessionLocal, Document, MatchStatus, Requirement
from services.audit_orchestrator import AuditOrchestrator

# Golden Demo targets
PROJECT_ID = 1
VENDOR_DOCUMENT_ID = 2

# Ground truth for core "Gotcha" tests + additional sanity cases (~10 total)
# NOTE: These IDs should map to real requirements in project_id=1.
GROUND_TRUTH: dict[int, str] = {
    1: "PARTIAL",
    2: "PARTIAL",
    3: "FULL",
    4: "PARTIAL",
    5: "FULL",      # gotcha: semantic paraphrase should still pass
    6: "FULL",
    8: "FULL",
    10: "PARTIAL",  # gotcha: under-provisioned financial evidence
    12: "NONE",     # gotcha: omission / negative space
    14: "PARTIAL",
}


@dataclass
class EvalRow:
    requirement_id: int
    expected: str
    actual: str
    latency_s: float
    passed: bool
    note: str = ""


def _fmt_status(value: str) -> str:
    return value.strip().upper()


def _print_report(rows: list[EvalRow], missing_ids: list[int], total_elapsed_s: float) -> None:
    print("\n" + "=" * 88)
    print("TENDER COMPLIANCE EVALUATION REPORT")
    print("=" * 88)
    print(f"Project ID: {PROJECT_ID} | Vendor Document ID: {VENDOR_DOCUMENT_ID}")
    print("-" * 88)
    print(f"{'Req ID':<8} {'Expected':<12} {'Actual':<12} {'Result':<6} {'Latency (s)':<12} Notes")
    print("-" * 88)

    for row in rows:
        icon = "✅" if row.passed else "❌"
        print(
            f"{row.requirement_id:<8} {row.expected:<12} {row.actual:<12} {icon:<6} "
            f"{row.latency_s:<12.3f} {row.note}"
        )

    print("-" * 88)
    evaluated = len(rows)
    passed = sum(1 for r in rows if r.passed)
    accuracy = (passed / evaluated * 100.0) if evaluated else 0.0
    avg_latency = (sum(r.latency_s for r in rows) / evaluated) if evaluated else 0.0

    print(f"Evaluated requirements: {evaluated}")
    print(f"Passed: {passed} | Failed: {evaluated - passed}")
    print(f"Accuracy: {accuracy:.2f}%")
    print(f"Average latency per requirement: {avg_latency:.3f}s")
    print(f"Total runtime: {total_elapsed_s:.3f}s")

    if missing_ids:
        print(f"Missing requirement IDs (not found in DB): {missing_ids}")
    print("=" * 88 + "\n")


async def run_evals() -> None:
    started = time.perf_counter()

    async with AsyncSessionLocal() as db:
        # Validate vendor document exists
        doc_result = await db.execute(select(Document).where(Document.id == VENDOR_DOCUMENT_ID))
        doc = doc_result.scalar_one_or_none()
        if not doc:
            raise RuntimeError(f"Vendor document {VENDOR_DOCUMENT_ID} not found.")
        if doc.project_id != PROJECT_ID:
            raise RuntimeError(
                f"Vendor document {VENDOR_DOCUMENT_ID} belongs to project {doc.project_id}, "
                f"expected project {PROJECT_ID}."
            )

        # Load only requirements in our ground truth map
        req_result = await db.execute(
            select(Requirement).where(
                Requirement.project_id == PROJECT_ID,
                Requirement.id.in_(list(GROUND_TRUTH.keys())),
                Requirement.is_deleted == False,
            )
        )
        requirements = req_result.scalars().all()
        req_by_id = {r.id: r for r in requirements}

        missing_ids = [rid for rid in GROUND_TRUTH if rid not in req_by_id]

        orchestrator = AuditOrchestrator(db)
        classifier = orchestrator.classifier.classifier

        rows: list[EvalRow] = []

        # Run targeted requirement-level evals with the same internal pipeline logic
        for requirement_id, expected_raw in GROUND_TRUTH.items():
            req = req_by_id.get(requirement_id)
            if req is None:
                continue

            req_start = time.perf_counter()
            note = ""
            try:
                print(f"🚀 Processing requirement {requirement_id}")
                prep = await orchestrator._process_requirement_for_vendor(
                    project_id=PROJECT_ID,
                    proposal_id=VENDOR_DOCUMENT_ID,
                    req=req,
                )
                pair = prep["pair"]
                result = await classifier.classify_async(
                    requirement_id=pair["requirement_id"],
                    vendor_document_id=pair["vendor_document_id"],
                    requirement_text=pair["requirement_text"],
                    category=pair["category"],
                    criticality=pair["criticality"],
                    top_passages=pair["top_passages"],
                    top_fused_score=float(pair.get("top_fused_score", 0.0)),
                    rfp_clause_ref=pair.get("rfp_clause_ref"),
                )
                actual = result.status.value
            except Exception as exc:
                actual = "AMBIGUOUS"
                note = f"Pipeline error: {exc}"

            latency_s = time.perf_counter() - req_start
            expected = _fmt_status(expected_raw)
            passed = _fmt_status(actual) == expected

            rows.append(
                EvalRow(
                    requirement_id=requirement_id,
                    expected=expected,
                    actual=_fmt_status(actual),
                    latency_s=latency_s,
                    passed=passed,
                    note=note,
                )
            )

    total_elapsed_s = time.perf_counter() - started
    _print_report(rows=rows, missing_ids=missing_ids, total_elapsed_s=total_elapsed_s)


if __name__ == "__main__":
    asyncio.run(run_evals())
