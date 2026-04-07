#!/usr/bin/env python3
"""Test script to verify the chat endpoint fix."""

import asyncio
import json
import httpx

async def test_chat():
    async with httpx.AsyncClient() as client:
        # Test the chat endpoint
        payload = {
            "project_id": 2,
            "message": "How is peoplesphere's SLA commitment for uptime?",
            "history": [],
            "document_ids": []
        }
        
        print("Testing POST /api/chat/ with payload:")
        print(json.dumps(payload, indent=2))
        print("\n" + "="*60 + "\n")
        
        try:
            response = await client.post(
                "http://localhost:8000/api/chat/",
                json=payload,
                timeout=30.0
            )
            
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"✅ SUCCESS!")
                print(f"Reply: {data['reply'][:200]}...")
                print(f"Citations found: {len(data['citations'])}")
                print(f"Vendors searched: {data['vendors_searched']}")
            else:
                print(f"❌ Error: {response.text}")
                
        except Exception as e:
            print(f"❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_chat())
