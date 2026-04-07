import asyncio
import csv
import os

from sqlalchemy import select
from database import AsyncSessionLocal, Requirement, Document

from services.proposal_indexer import ProposalIndexer
from services.reranker import Reranker


async def generate_calibration_dataset(
    project_id: int,
    vendor_doc_id: int,
    output_csv: str = "calibration_data.csv",
):
    print(f"🚀 Starting Calibration Data Collection for Project {project_id}...")

    # Init services
    indexer = ProposalIndexer()
    reranker = Reranker()

    async with AsyncSessionLocal() as db:
        # 1. Fetch Requirements
        req_result = await db.execute(
            select(Requirement).where(
                Requirement.project_id == project_id,
                Requirement.is_deleted == False,
            ).limit(15)
        )
        requirements = req_result.scalars().all()

        # 2. Fetch Document
        doc_result = await db.execute(
            select(Document).where(Document.id == vendor_doc_id)
        )
        doc = doc_result.scalar_one_or_none()

        if not doc:
            print("❌ Vendor document not found!")
            return

        csv_data = []

        print(f"📊 Processing {len(requirements)} requirements against {doc.filename}...")

        # 3. Retrieval Pipeline
        for req in requirements:
            query_text = req.normalised_intent or req.raw_text
            print(f"   -> Query: {query_text[:50]}...")

            # Stage 1
            stage_1_results = indexer.retrieve_with_keyword_boost(
                query_text=query_text,
                project_id=project_id,
                document_id=doc.id,
                top_k=10,
            )

            # Stage 2
            stage_2_results = reranker.rerank(
                query=query_text,
                candidates=stage_1_results,
                top_k=10,
            )

            # Collect data
            for result in stage_2_results:
                csv_data.append({
                    "Requirement_ID": req.id,
                    "Requirement_Text": query_text,
                    "Passage_Text": result["text"],
                    "Bi_Encoder_Cosine": round(result["score"], 4),
                    "Cross_Encoder_Logit": round(result["reranker_score"], 4),
                    "LABEL_1_or_0": "",
                })

    # 4. Write CSV
    os.makedirs("scripts/data", exist_ok=True)
    filepath = os.path.join("scripts/data", output_csv)

    if not csv_data:
        print("⚠️ No data generated.")
        return

    with open(filepath, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_data[0].keys())
        writer.writeheader()
        writer.writerows(csv_data)

    print(f"\n✅ Exported {len(csv_data)} rows to {filepath}")
    print("👉 Now label manually: 1 = relevant, 0 = not relevant")


if __name__ == "__main__":
    PROJECT_ID = 1
    VENDOR_DOC_ID = 2

    asyncio.run(generate_calibration_dataset(PROJECT_ID, VENDOR_DOC_ID))