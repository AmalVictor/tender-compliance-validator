"""
routers/projects.py
-------------------
Project management endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import Document, Project, Requirement, get_db
from backend.schemas import MessageResponse, ProjectCreate, ProjectResponse

router = APIRouter()


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new tender review project."""
    project = Project(name=payload.name, description=payload.description)
    db.add(project)
    await db.flush()
    await db.refresh(project)

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        audit_complete=project.audit_complete,
        document_count=0,
        requirement_count=0,
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List all projects with document and requirement counts."""
    result = await db.execute(
        select(Project).order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()

    response = []
    for p in projects:
        doc_count_result = await db.execute(
            select(func.count(Document.id)).where(Document.project_id == p.id)
        )
        req_count_result = await db.execute(
            select(func.count(Requirement.id)).where(
                Requirement.project_id == p.id,
                Requirement.is_deleted == False,
            )
        )
        response.append(ProjectResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            created_at=p.created_at,
            audit_complete=p.audit_complete,
            document_count=doc_count_result.scalar() or 0,
            requirement_count=req_count_result.scalar() or 0,
        ))

    return response


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single project by ID."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")

    doc_count = await db.execute(
        select(func.count(Document.id)).where(Document.project_id == project_id)
    )
    req_count = await db.execute(
        select(func.count(Requirement.id)).where(
            Requirement.project_id == project_id,
            Requirement.is_deleted == False,
        )
    )
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        audit_complete=project.audit_complete,
        document_count=doc_count.scalar() or 0,
        requirement_count=req_count.scalar() or 0,
    )


@router.delete("/{project_id}", response_model=MessageResponse)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a project and all associated data."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")

    await db.delete(project)
    return MessageResponse(message=f"Project '{project.name}' deleted successfully.")