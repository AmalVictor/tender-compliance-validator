"""
pages/requirements.py
---------------------
Human-in-the-loop requirement review and confirmation.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import api_client

CATEGORY_OPTIONS = ["Technical", "Legal", "Financial", "Administrative"]
CRITICALITY_OPTIONS = ["Mandatory", "Recommended", "Informational"]
CRIT_ICON = {"Mandatory": "🔴", "Recommended": "🟡", "Informational": "🟢"}
CAT_ICON = {"Technical": "⚙️", "Legal": "⚖️", "Financial": "💰", "Administrative": "📋"}


def render():
    st.title("✅ Review Requirements")

    active_id = st.session_state.get("active_project_id")
    if not active_id:
        st.warning("Please select a project from the Workspace first.")
        return

    project = api_client.get_project(active_id)
    st.caption(f"Project: **{project['name']}**")

    with st.spinner("Loading requirements..."):
        requirements = api_client.get_requirements(active_id, confirmed_only=False)

    if not requirements:
        st.info("No requirements extracted yet. Upload and process an RFP first.")
        return

    active_reqs = [r for r in requirements if not r["is_deleted"]]
    mandatory = [r for r in active_reqs if r["criticality"] == "Mandatory"]
    confirmed = [r for r in active_reqs if r["is_confirmed"]]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", len(active_reqs))
    c2.metric("Mandatory", len(mandatory))
    c3.metric("Confirmed", len(confirmed))
    c4.metric("Pending", len([r for r in active_reqs if not r["is_confirmed"]]))

    if confirmed and len(confirmed) == len(active_reqs):
        st.success("✅ All requirements confirmed! Ready to run the compliance audit.")
    elif confirmed:
        st.progress(len(confirmed) / max(len(active_reqs), 1),
                    text=f"Confirmation: {len(confirmed)}/{len(active_reqs)}")

    st.markdown("---")

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        filter_cat = st.multiselect("Category", CATEGORY_OPTIONS, default=CATEGORY_OPTIONS)
    with fc2:
        filter_crit = st.multiselect("Criticality", CRITICALITY_OPTIONS, default=CRITICALITY_OPTIONS)
    with fc3:
        show_unconfirmed = st.checkbox("Unconfirmed only")
        show_deleted = st.checkbox("Show deleted")

    display = [
        r for r in requirements
        if r["category"] in filter_cat
        and r["criticality"] in filter_crit
        and (show_deleted or not r["is_deleted"])
        and (not show_unconfirmed or not r["is_confirmed"])
    ]
    st.caption(f"Showing {len(display)} of {len(requirements)}")

    # Bulk actions
    b1, b2 = st.columns(2)
    with b1:
        if st.button("✅ Confirm all mandatory", type="primary"):
            ids = [r["id"] for r in active_reqs if r["criticality"] == "Mandatory"]
            if ids:
                api_client.bulk_confirm(ids, confirm=True)
                st.success(f"Confirmed {len(ids)} mandatory requirements.")
                st.rerun()
    with b2:
        if st.button("✅ Confirm all visible"):
            ids = [r["id"] for r in display if not r["is_deleted"]]
            if ids:
                api_client.bulk_confirm(ids, confirm=True)
                st.success(f"Confirmed {len(ids)} requirements.")
                st.rerun()

    st.markdown("---")

    for req in display:
        _render_card(req)


def _render_card(req: dict):
    req_id = req["id"]
    conf = "✅" if req["is_confirmed"] else "⬜"
    crit = CRIT_ICON.get(req["criticality"], "⬜")
    cat = CAT_ICON.get(req["category"], "📌")
    intent = req.get("normalised_intent", "") or ""
    preview = intent[:100] + ("..." if len(intent) > 100 else "")
    strike = "~~" if req["is_deleted"] else ""

    header = f"{conf} {crit} {cat} {strike}**[{req.get('rfp_clause_ref') or 'No ref'}]** {preview}{strike}"

    with st.expander(header, expanded=False):
        col1, col2 = st.columns([2, 1])

        with col1:
            st.markdown("**Raw clause:**")
            st.markdown(f"> {req['raw_text'][:400]}{'...' if len(req['raw_text']) > 400 else ''}")
            new_intent = st.text_area("Normalised intent", value=intent, height=80, key=f"i_{req_id}")

        with col2:
            new_cat = st.selectbox("Category", CATEGORY_OPTIONS,
                                   index=CATEGORY_OPTIONS.index(req["category"]) if req["category"] in CATEGORY_OPTIONS else 0,
                                   key=f"c_{req_id}")
            new_crit = st.selectbox("Criticality", CRITICALITY_OPTIONS,
                                    index=CRITICALITY_OPTIONS.index(req["criticality"]) if req["criticality"] in CRITICALITY_OPTIONS else 0,
                                    key=f"cr_{req_id}")
            new_ref = st.text_input("Clause ref", value=req.get("rfp_clause_ref") or "", key=f"r_{req_id}")
            if req.get("section_title"):
                st.caption(f"Section: {req['section_title']}")
            if req.get("page_number"):
                st.caption(f"Page: {req['page_number']}")

        ba, bb, bc, bd = st.columns(4)
        with ba:
            if st.button("💾 Save", key=f"s_{req_id}", disabled=req["is_deleted"]):
                api_client.update_requirement(req_id, {
                    "normalised_intent": new_intent, "category": new_cat,
                    "criticality": new_crit, "rfp_clause_ref": new_ref or None,
                })
                st.success("Saved."); st.rerun()
        with bb:
            lbl = "✅ Confirm" if not req["is_confirmed"] else "↩️ Unconfirm"
            if st.button(lbl, key=f"cf_{req_id}", disabled=req["is_deleted"]):
                api_client.update_requirement(req_id, {"is_confirmed": not req["is_confirmed"]})
                st.rerun()
        with bc:
            lbl = "🗑️ Delete" if not req["is_deleted"] else "♻️ Restore"
            if st.button(lbl, key=f"d_{req_id}"):
                api_client.update_requirement(req_id, {"is_deleted": not req["is_deleted"]})
                st.rerun()
        with bd:
            if st.button("✅ Save & Confirm", key=f"sc_{req_id}", type="primary", disabled=req["is_deleted"]):
                api_client.update_requirement(req_id, {
                    "normalised_intent": new_intent, "category": new_cat,
                    "criticality": new_crit, "rfp_clause_ref": new_ref or None,
                    "is_confirmed": True,
                })
                st.rerun()