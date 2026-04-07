"""
Smoke-test TenderAI POST /api/chat/ against a running API server.
"""

from __future__ import annotations

import asyncio

import httpx


async def test_chatbot() -> None:
    print("Testing TenderAI chat endpoint...\n")

    url = "http://localhost:8000/api/chat/"

    payload = {
        "project_id": 1,
        "document_id": 2,
        "message": (
            "Does the vendor mention anything about ISO certifications or data residency?"
        ),
        "history": [],
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            print("Reply:")
            print(data.get("reply", ""))
            print("\nCitations:")
            for c in data.get("citations") or []:
                if isinstance(c, dict):
                    idx = c.get("citation_index")
                    title = c.get("section_title")
                    print(f"- [{idx}] {title}: {(c.get('text') or '')[:200]}...")
                else:
                    print(f"- {c}")

        except httpx.HTTPStatusError as e:
            print(f"HTTP error: {e.response.status_code} {e.response.text[:500]}")
        except Exception as e:
            print(f"Request failed: {e}")


if __name__ == "__main__":
    asyncio.run(test_chatbot())
