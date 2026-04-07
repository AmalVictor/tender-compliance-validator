import asyncio
from sqlalchemy.future import select
from database import AsyncSessionLocal, RiskFinding

async def fetch_risk_report():
    print("⚠️ ENTERPRISE RISK REPORT\n")
    print("="*80)
    
    async with AsyncSessionLocal() as db:
        # Assuming Vendor Document ID 2 is the InsightTech proposal
        result = await db.execute(select(RiskFinding).filter(RiskFinding.vendor_document_id == 2))
        risks = result.scalars().all()
        
        if not risks:
            print("✅ No risks found. (Or the risk engine hasn't run on this document yet).")
            return

        for risk in risks:
            # Color coding for terminal output
            color = "\033[91m" if risk.severity in ["CRITICAL", "HIGH"] else "\033[93m"
            reset = "\033[0m"
            
            print(f"{color}[{risk.severity}] {risk.risk_type}{reset}")
            print(f"Matched Phrase: \"{risk.matched_phrase}\"")
            print(f"Impact: {risk.impact_explanation}")
            print("-" * 80)

if __name__ == "__main__":
    asyncio.run(fetch_risk_report())