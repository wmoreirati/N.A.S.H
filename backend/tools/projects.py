"""
N.A.S.H - Gerenciamento de projetos.

Regra importante (seção 7/28 do briefing): excluir um projeto NUNCA apaga
as tarefas relacionadas a ele. As tarefas são preservadas e apenas
desvinculadas (project_id volta a None).
"""
from backend.models import db, Project, Task
from backend.security.validation import (
    require_text, validate_progress, validate_project_status, validate_id,
)


def list_projects(include_tasks: bool = False):
    projects = Project.query.order_by(Project.updated_at.desc()).all()
    return [p.to_dict(include_tasks=include_tasks) for p in projects]


def get_project_or_raise(project_id: int) -> Project:
    project = Project.query.get(validate_id(project_id, "project_id"))
    if not project:
        raise LookupError(f"Projeto {project_id} não encontrado.")
    return project


def get_project(project_id: int, include_tasks: bool = True):
    return get_project_or_raise(project_id).to_dict(include_tasks=include_tasks)


def create_project(name: str, description: str = "", objectives: str = ""):
    name = require_text(name, "name", max_length=255)
    project = Project(
        name=name,
        description=(description or "").strip(),
        objectives=(objectives or "").strip(),
    )
    db.session.add(project)
    db.session.commit()
    return project.to_dict()


def update_project(project_id: int, **fields):
    project = get_project_or_raise(project_id)

    if "name" in fields and fields["name"] is not None:
        project.name = require_text(fields["name"], "name", max_length=255)
    if "description" in fields and fields["description"] is not None:
        project.description = str(fields["description"]).strip()
    if "objectives" in fields and fields["objectives"] is not None:
        project.objectives = str(fields["objectives"]).strip()
    if "notes" in fields and fields["notes"] is not None:
        project.notes = str(fields["notes"]).strip()
    if "progress" in fields and fields["progress"] is not None:
        project.progress = validate_progress(fields["progress"])
    if "status" in fields and fields["status"] is not None:
        project.status = validate_project_status(fields["status"])

    db.session.commit()
    return project.to_dict()


def delete_project(project_id: int):
    project = get_project_or_raise(project_id)

    # Preserva as tarefas: apenas desvincula do projeto excluído.
    linked_tasks = Task.query.filter_by(project_id=project.id).all()
    for t in linked_tasks:
        t.project_id = None

    db.session.delete(project)
    db.session.commit()
    return {"deleted_id": project_id, "tasks_unlinked": len(linked_tasks)}
