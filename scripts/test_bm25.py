import asyncio
from services.proposal_indexer import ProposalIndexer

def test_hybrid_search():
    print("🔍 TESTING HYBRID SEARCH (BM25 + DENSE)...\n")
    indexer = ProposalIndexer()
    
    # A highly specific lexical query
    query = "ISO/IEC 27001:2013"
    print(f"Query: '{query}'")
    
    # Assuming the Golden Demo is project_id=1, document_id=2
    results = indexer.retrieve_hybrid(query_text=query, project_id=1, document_id=2, top_k=3)
    
    for i, res in enumerate(results):
        print(f"\n--- Rank {i+1} ---")
        print(f"RRF Score: {res.get('retrieval_rrf', 'N/A'):.4f}")
        print(f"Text: {res['text']}")

if __name__ == "__main__":
    test_hybrid_search()