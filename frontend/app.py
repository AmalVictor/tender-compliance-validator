"""
app.py
------
Streamlit frontend entry point.
Uses sys.path-based imports to avoid Windows package resolution issues
when Streamlit runs the file as a script rather than a module.
"""

import sys
import os

# Ensure project root is on sys.path so all imports resolve correctly
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st

st.set_page_config(
    page_title="Tender Compliance Validator",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar navigation ────────────────────────────────────────────────────────

st.sidebar.title("📋 Tender Validator")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    [
        "🏠 Workspace",
        "📤 Upload Documents",
        "✅ Review Requirements",
        "📊 Compliance Matrix",
        "🔥 Risk Heatmap",
        "🔍 Deep Dive",
    ],
)

st.sidebar.markdown("---")
st.sidebar.caption("Phase 1 complete: Upload & Extract")
st.sidebar.caption("Phase 2: Audit engine (coming)")

# ── Page routing ──────────────────────────────────────────────────────────────
# Import pages directly by file path to avoid Windows package import issues

import importlib.util

def _load_page(rel_path: str):
    """Load a page module by relative path from project root."""
    abs_path = os.path.join(_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location("page_module", abs_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if page == "🏠 Workspace":
    mod = _load_page("frontend/pages/workspace.py")
    mod.render()

elif page == "📤 Upload Documents":
    mod = _load_page("frontend/pages/upload.py")
    mod.render()

elif page == "✅ Review Requirements":
    mod = _load_page("frontend/pages/requirements.py")
    mod.render()

elif page == "📊 Compliance Matrix":
    st.title("📊 Compliance Matrix")
    st.info("Available after Phase 2 audit engine is complete (Day 10).")

elif page == "🔥 Risk Heatmap":
    st.title("🔥 Risk Heatmap")
    st.info("Available after Phase 2 audit engine is complete (Day 10).")

elif page == "🔍 Deep Dive":
    st.title("🔍 Document Deep Dive")
    st.info("Available after Phase 2 audit engine is complete (Day 10).")