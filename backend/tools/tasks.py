"""
N.A.S.H - Gerenciamento de tarefas (agenda local).
"""
from datetime import datetime
from backend.models import db, Task
from backend.security.auth import escopar, marcar_dono
from backend.security.validation import (
    require_text, validate_priority, validate_date, validate_time, validate_id,
)


def list_tasks(status: str | None = None, include_deleted: bool = False):
    query = escopar(Task.query, Task)
    if not include_deleted:
        query = query.filter(Task.deleted_at.is_(None))
    if status:
        query = query.filter_by(status=status)
    # Ordena por data/hora; tarefas sem data (NULL) vão para o final.
    # Evita nullslast() por compatibilidade com versões mais antigas do SQLite.
    tasks = query.all()
    tasks.sort(key=lambda t: (t.date is None, t.date or "", t.time is None, t.time or ""))
    return [t.to_dict() for t in tasks]


def get_task(task_id: int) -> Task:
    # Passa pelo escopo do dono: tarefa de outra pessoa responde "não
    # encontrada", e não "acesso negado" -- a segunda resposta confirmaria a
    # existência do registro. Como toda alteração e exclusão passa por aqui,
    # este é o ponto único que impede mexer no que não é seu.
    task = escopar(Task.query, Task).filter(
        Task.id == validate_id(task_id, "task_id")
    ).first()
    if not task:
        raise LookupError(f"Tarefa {task_id} não encontrada.")
    return task


def create_task(title: str, description: str = "", date: str | None = None,
                 time: str | None = None, priority: str = "normal", project_id: int | None = None):
    title = require_text(title, "title", max_length=255)
    priority = validate_priority(priority)
    date = validate_date(date)
    time = validate_time(time)
    if project_id is not None:
        project_id = validate_id(project_id, "project_id")

    task = Task(
        title=title,
        description=(description or "").strip(),
        date=date,
        time=time,
        priority=priority,
        project_id=project_id,
        status="pendente",
    )
    marcar_dono(task)
    db.session.add(task)
    db.session.commit()
    return task.to_dict()


def update_task(task_id: int, **fields):
    task = get_task(task_id)

    if "title" in fields and fields["title"] is not None:
        task.title = require_text(fields["title"], "title", max_length=255)
    if "description" in fields and fields["description"] is not None:
        task.description = str(fields["description"]).strip()
    if "date" in fields:
        task.date = validate_date(fields["date"])
    if "time" in fields:
        task.time = validate_time(fields["time"])
    if "priority" in fields and fields["priority"] is not None:
        task.priority = validate_priority(fields["priority"])
    if "project_id" in fields:
        task.project_id = validate_id(fields["project_id"], "project_id") if fields["project_id"] is not None else None

    db.session.commit()
    return task.to_dict()


def complete_task(task_id: int):
    task = get_task(task_id)
    task.status = "concluida"
    task.completed_at = datetime.utcnow()
    db.session.commit()
    return task.to_dict()


def delete_task(task_id: int, permanent: bool = False):
    task = get_task(task_id)
    if permanent:
        db.session.delete(task)
        db.session.commit()
        return {"deleted_id": task_id, "permanent": True}
    task.status = "excluida"
    task.deleted_at = datetime.utcnow()
    db.session.commit()
    return task.to_dict()


def restore_task(task_id: int):
    task = get_task(task_id)
    task.status = "pendente"
    task.deleted_at = None
    task.completed_at = None
    db.session.commit()
    return task.to_dict()


def delete_all_tasks():
    active_tasks = escopar(Task.query, Task).filter(Task.deleted_at.is_(None)).all()
    count = len(active_tasks)
    now = datetime.utcnow()
    for t in active_tasks:
        t.status = "excluida"
        t.deleted_at = now
    db.session.commit()
    return {"deleted_count": count}


def count_active_tasks() -> int:
    return escopar(Task.query, Task).filter(Task.deleted_at.is_(None)).count()
