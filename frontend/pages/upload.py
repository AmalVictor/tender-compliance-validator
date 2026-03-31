"""
pages/upload.py
---------------
Document upload page — RFP and vendor proposals.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import api_client


def render():
    st.title("📤 Upload Documents")

    active_id = st.session_state.get("active_project_id")
    if not active_id:
        st.warning("Please select a project from the Workspace first.")
        return

    project = api_client.get_project(active_id)
    st.caption(f"Project: **{project['name']}**")
    st.markdown("---")

    docs = api_client.list_documents(active_id)
    rfps = [d for d in docs if d["document_type"] == "RFP"]
    proposals = [d for d in docs if d["document_type"] == "PROPOSAL"]

    col1, col2 = st.columns(2)
    col1.metric("RFPs uploaded", len(rfps))
    col2.metric("Proposals uploaded", len(proposals))

    # ── Upload RFP ────────────────────────────────────────────────────────
    st.subheader("📄 Upload RFP Document")
    st.caption("Requirements will be extracted automatically after upload.")

    if rfps and not st.session_state.get("replace_rfp"):
        r = rfps[0]
        st.success(
            f"RFP uploaded: **{r['filename']}** "
            f"({r.get('page_count', '?')} pages, "
            f"{r.get('word_count', 0):,} words)"
        )
        if r.get("parse_error"):
            st.error(f"Parse warning: {r['parse_error']}")
        if st.button("Replace RFP"):
            st.session_state["replace_rfp"] = True
            st.rerun()
    else:
        rfp_file = st.file_uploader("Upload RFP (PDF only)", type=["pdf"], key="rfp_upload")
        if rfp_file:
            if st.button("Process RFP", type="primary"):
                with st.spinner(f"Parsing '{rfp_file.name}'... may take 30–60s for large docs."):
                    result = api_client.upload_document(
                        project_id=active_id,
                        document_type="RFP",
                        file_bytes=rfp_file.read(),
                        filename=rfp_file.name,
                    )
                if result.get("parse_error"):
                    st.error(f"Parse error: {result['parse_error']}")
                else:
                    st.success(
                        f"RFP processed: {result.get('page_count')} pages, "
                        f"{result.get('word_count', 0):,} words."
                    )
                    st.session_state.pop("replace_rfp", None)
                    st.info("Go to **Review Requirements** to confirm extracted clauses.")
                    st.rerun()

    st.markdown("---")

    # ── Upload Proposals ──────────────────────────────────────────────────
    st.subheader("📁 Upload Vendor Proposals")
    st.caption("Each proposal is parsed, embedded, and admin-checked automatically.")

    if proposals:
        st.markdown("**Already uploaded:**")
        for p in proposals:
            ca, cb, cc = st.columns([3, 1, 1])
            with ca:
                icon = "✅" if p["is_indexed"] else ("❌" if p.get("parse_error") else "⏳")
                st.markdown(f"{icon} **{p.get('vendor_name') or p['filename']}**")
                if p.get("parse_error"):
                    st.caption(f"Error: {p['parse_error']}")
            with cb:
                st.caption(f"{p.get('page_count', '?')} pages")
            with cc:
                if p["is_indexed"]:
                    checks = api_client.get_admin_checks(p["id"])
                    missing = sum(1 for c in checks if c["status"] == "MISSING")
                    st.caption(f"⚠️ {missing} missing" if missing else "✅ Admin OK")

    st.markdown("**Add a vendor:**")
    vendor_name = st.text_input("Vendor name", placeholder="e.g. Accenture / ABC Systems")
    proposal_file = st.file_uploader("Upload proposal (PDF only)", type=["pdf"], key="prop_upload")

    if proposal_file and vendor_name:
        if st.button("Process Proposal", type="primary"):
            with st.spinner(f"Indexing '{proposal_file.name}'... first run downloads ~80MB model."):
                result = api_client.upload_document(
                    project_id=active_id,
                    document_type="PROPOSAL",
                    file_bytes=proposal_file.read(),
                    filename=proposal_file.name,
                    vendor_name=vendor_name.strip(),
                )
            if result.get("parse_error"):
                st.error(f"Parse error: {result['parse_error']}")
            else:
                st.success(
                    f"'{vendor_name}' indexed: {result.get('page_count')} pages, "
                    f"{result.get('word_count', 0):,} words."
                )
                checks = api_client.get_admin_checks(result["id"])
                _render_admin_checks(checks, vendor_name)
                st.rerun()
    elif proposal_file and not vendor_name:
        st.warning("Enter a vendor name before uploading.")


def _render_admin_checks(checks: list[dict], vendor_name: str):
    if not checks:
        return
    missing = [c for c in checks if c["status"] == "MISSING"]
    found = [c for c in checks if c["status"] == "FOUND"]

    st.markdown(f"**Admin eligibility — {vendor_name}:**")
    if missing:
        st.warning(f"⚠️ {len(missing)} required document(s) not found — bid may be disqualified.")
        for item in missing:
            st.markdown(f"- ❌ **{item['item_name']}**")
    for item in found:
        ref = f" — {item['page_reference']}" if item.get("page_reference") else ""
        st.markdown(f"- ✅ **{item['item_name']}**{ref}")