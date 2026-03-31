"""
api_client.py
-------------
Thin HTTP client used by all Streamlit pages to talk to the FastAPI backend.
Centralises base URL and error handling so pages stay clean.
"""

from __future__ import annotations

import httpx
import streamlit as st

BASE_URL = "http://localhost:8000/api"
TIMEOUT = 60.0  # seconds — long enough for LLM extraction calls


def _handle_error(response: httpx.Response) -> None:
    """Raise a Streamlit error and stop execution on HTTP errors."""
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        st.error(f"API error {response.status_code}: {detail}")
        st.stop()


# ── Projects ──────────────────────────────────────────────────────────────────

def list_projects() -> list[dict]:
    try:
        r = httpx.get(f"{BASE_URL}/projects", timeout=TIMEOUT)
        _handle_error(r)
        return r.json()
    except httpx.ConnectError:
        st.error("Cannot connect to backend. Is the FastAPI server running on port 8000?")
        st.code("poetry run uvicorn backend.main:app --reload")
        st.stop()


def create_project(name: str, description: str = "") -> dict:
    r = httpx.post(
        f"{BASE_URL}/projects",
        json={"name": name, "description": description},
        timeout=TIMEOUT,
    )
    _handle_error(r)
    return r.json()


def get_project(project_id: int) -> dict:
    r = httpx.get(f"{BASE_URL}/projects/{project_id}", timeout=TIMEOUT)
    _handle_error(r)
    return r.json()


def delete_project(project_id: int) -> dict:
    r = httpx.delete(f"{BASE_URL}/projects/{project_id}", timeout=TIMEOUT)
    _handle_error(r)
    return r.json()


# ── Documents ─────────────────────────────────────────────────────────────────

def list_documents(project_id: int) -> list[dict]:
    r = httpx.get(
        f"{BASE_URL}/documents",
        params={"project_id": project_id},
        timeout=TIMEOUT,
    )
    _handle_error(r)
    return r.json()


def upload_document(
    project_id: int,
    document_type: str,
    file_bytes: bytes,
    filename: str,
    vendor_name: str | None = None,
) -> dict:
    data = {"project_id": str(project_id), "document_type": document_type}
    if vendor_name:
        data["vendor_name"] = vendor_name

    r = httpx.post(
        f"{BASE_URL}/documents/upload",
        data=data,
        files={"file": (filename, file_bytes, "application/pdf")},
        timeout=120.0,  # parsing + extraction can take up to 2 min
    )
    _handle_error(r)
    return r.json()


def get_admin_checks(document_id: int) -> list[dict]:
    r = httpx.get(f"{BASE_URL}/documents/{document_id}/admin-checks", timeout=TIMEOUT)
    _handle_error(r)
    return r.json()


# ── Requirements ──────────────────────────────────────────────────────────────

def get_requirements(project_id: int, confirmed_only: bool = False) -> list[dict]:
    r = httpx.get(
        f"{BASE_URL}/documents/{project_id}/requirements",
        params={"confirmed_only": confirmed_only},
        timeout=TIMEOUT,
    )
    _handle_error(r)
    return r.json()


def update_requirement(requirement_id: int, payload: dict) -> dict:
    r = httpx.patch(
        f"{BASE_URL}/documents/requirements/{requirement_id}",
        json=payload,
        timeout=TIMEOUT,
    )
    _handle_error(r)
    return r.json()


def bulk_confirm(requirement_ids: list[int], confirm: bool = True) -> dict:
    r = httpx.post(
        f"{BASE_URL}/documents/requirements/bulk-confirm",
        json={"requirement_ids": requirement_ids, "confirm": confirm},
        timeout=TIMEOUT,
    )
    _handle_error(r)
    return r.json()


# ── Audit ─────────────────────────────────────────────────────────────────────

def get_audit_status(project_id: int) -> dict:
    r = httpx.get(f"{BASE_URL}/audit/status/{project_id}", timeout=TIMEOUT)
    _handle_error(r)
    return r.json()


def run_audit(project_id: int) -> dict:
    r = httpx.post(f"{BASE_URL}/audit/run/{project_id}", timeout=300.0)
    _handle_error(r)
    return r.json()