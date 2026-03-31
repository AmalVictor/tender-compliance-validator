"""
pages/workspace.py
------------------
Project workspace — landing page showing all projects with stats.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import api_client


def render():
    st.title("🏠 Project Workspace")
    st.caption("Create and manage your tender review projects.")

    with st.expander("➕ Create New Project", expanded=False):
        with st.form("new_project_form"):
            name = st.text_input("Project name", placeholder="e.g. SITA RFP 2025/001")
            description = st.text_area("Description (optional)", height=80)
            submitted = st.form_submit_button("Create Project", type="primary")
            if submitted:
                if not name.strip():
                    st.error("Project name is required.")
                else:
                    with st.spinner("Creating project..."):
                        project = api_client.create_project(name.strip(), description.strip())
                    st.success(f"Project '{project['name']}' created!")
                    st.session_state["active_project_id"] = project["id"]
                    st.rerun()

    st.markdown("---")

    with st.spinner("Loading projects..."):
        projects = api_client.list_projects()

    if not projects:
        st.info("No projects yet. Create one above to get started.")
        return

    st.subheader(f"Your Projects ({len(projects)})")

    for project in projects:
        with st.container():
            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])

            with col1:
                is_active = st.session_state.get("active_project_id") == project["id"]
                label = f"{'✅ ' if is_active else ''}{project['name']}"
                st.markdown(f"**{label}**")
                if project.get("description"):
                    st.caption(project["description"])

            with col2:
                st.metric("Documents", project["document_count"])

            with col3:
                st.metric("Requirements", project["requirement_count"])

            with col4:
                status_txt = "✅ Done" if project["audit_complete"] else "⏳ Pending"
                st.markdown(f"**Audit**<br>{status_txt}", unsafe_allow_html=True)

            with col5:
                if st.button("Select", key=f"sel_{project['id']}", type="primary"):
                    st.session_state["active_project_id"] = project["id"]
                    st.rerun()

            if st.session_state.get("active_project_id") == project["id"]:
                status_data = api_client.get_audit_status(project["id"])
                stages = status_data.get("pipeline_stages", {})
                _render_pipeline_status(stages)

            st.divider()

    active_id = st.session_state.get("active_project_id")
    if active_id:
        active = next((p for p in projects if p["id"] == active_id), None)
        if active:
            st.sidebar.success(f"Active: {active['name']}")


def _render_pipeline_status(stages: dict):
    st.markdown("**Pipeline status:**")
    pipeline = [
        ("RFP uploaded", stages.get("rfp_uploaded")),
        ("RFP parsed", stages.get("rfp_parsed")),
        ("Reqs extracted", stages.get("requirements_extracted")),
        ("Reqs confirmed", stages.get("requirements_confirmed")),
        ("Proposals up", stages.get("proposals_uploaded")),
        ("Proposals indexed", stages.get("proposals_indexed")),
        ("Audit done", stages.get("audit_complete")),
    ]
    cols = st.columns(len(pipeline))
    for col, (label, done) in zip(cols, pipeline):
        with col:
            st.markdown(f"{'✅' if done else '⬜'}<br><small>{label}</small>", unsafe_allow_html=True)